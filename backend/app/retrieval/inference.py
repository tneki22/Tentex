"""Локальный inference: веса и нативные библиотеки живут только в дочернем процессе."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.retrieval.local_models import model_path, validate_model_id


class EmbeddingWrite(BaseModel):
    """OpenAI-совместимый запрос embedding-модели."""
    model_config = ConfigDict(extra="forbid")
    model: str = Field(min_length=3, max_length=300)
    input: str | list[str]
    encoding_format: Literal["float"] = "float"


class RerankWrite(BaseModel):
    """Кандидаты одного запроса для reranker."""
    model_config = ConfigDict(extra="forbid")
    model: str = Field(min_length=3, max_length=300)
    query: str
    documents: list[str] = Field(min_length=1, max_length=100)


class InternalEmbeddingWrite(BaseModel):
    """Transformers-запрос с явным pooling."""
    model_config = ConfigDict(extra="forbid")
    model: str = Field(min_length=3, max_length=300)
    input: list[str] = Field(min_length=1, max_length=512)
    pooling: Literal["mean", "cls", "last_token"] = "mean"
    normalize: bool = True


@lru_cache(maxsize=2)
def _embedding_model(model_id: str):
    path = model_path(validate_model_id(model_id))
    if not path.is_dir():
        raise FileNotFoundError(f"Модель {model_id} не установлена")
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(
        str(path), trust_remote_code=False, local_files_only=True, device="cpu"
    )


@lru_cache(maxsize=1)
def _reranker(model_id: str):
    """Прогретый CrossEncoder без загрузок из сети и без выполнения remote code."""
    path = model_path(validate_model_id(model_id))
    if not path.is_dir():
        raise FileNotFoundError(f"Модель {model_id} не установлена")
    import torch
    from sentence_transformers import CrossEncoder

    # Qwen3 Reranker хранится в bfloat16; на CPU без аппаратного bf16 это в 4 раза
    # медленнее float32 (≈ 5 с против 1,2 с на кусок).
    return CrossEncoder(
        str(path), trust_remote_code=False, local_files_only=True, device="cpu",
        model_kwargs={"dtype": torch.float32},
    )


@lru_cache(maxsize=2)
def _transformer_model(model_id: str):
    path = model_path(validate_model_id(model_id))
    if not path.is_dir():
        raise FileNotFoundError(f"Модель {model_id} не установлена")
    from transformers import AutoModel, AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(
        str(path), trust_remote_code=False, local_files_only=True
    )
    model = AutoModel.from_pretrained(
        str(path), trust_remote_code=False, local_files_only=True
    ).eval()
    return tokenizer, model


def model_cache_state() -> dict[str, object]:
    """Число весов в текущем дочернем процессе, без изменения кэшей."""
    return {
        "status": "ok",
        "service": "tentex-retrieval-model",
        "loaded_embedding_models": _embedding_model.cache_info().currsize,
        "loaded_transformer_models": _transformer_model.cache_info().currsize,
        "loaded_rerankers": _reranker.cache_info().currsize,
    }


def embeddings(command: EmbeddingWrite) -> dict[str, object]:
    """Те же нормализованные SentenceTransformer-векторы, что до изоляции."""
    texts = [command.input] if isinstance(command.input, str) else command.input
    try:
        vectors = _embedding_model(command.model).encode(
            texts,
            batch_size=min(64, max(1, len(texts))),
            normalize_embeddings=True,
            convert_to_numpy=True,
        )
    except (FileNotFoundError, ValueError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return {
        "object": "list",
        "model": command.model,
        "data": [
            {"object": "embedding", "index": index, "embedding": vector.tolist()}
            for index, vector in enumerate(vectors)
        ],
        "usage": {
            "prompt_tokens": sum(len(text.split()) for text in texts),
            "total_tokens": 0,
        },
    }


def internal_embeddings(command: InternalEmbeddingWrite) -> dict[str, object]:
    """Безопасный Transformers runtime для ручных HF-профилей без remote code."""
    try:
        tokenizer, model = _transformer_model(command.model)
        import torch
        from torch.nn import functional

        encoded = tokenizer(
            command.input,
            padding=True,
            truncation=True,
            max_length=min(int(getattr(tokenizer, "model_max_length", 512)), 8192),
            return_tensors="pt",
        )
        with torch.no_grad():
            hidden = model(**encoded).last_hidden_state
        mask = encoded["attention_mask"]
        if command.pooling == "cls":
            pooled = hidden[:, 0]
        elif command.pooling == "last_token" and bool(mask[:, -1].all()):
            # Токенизатор Qwen3 дополняет слева: последний токен у всех на месте -1.
            pooled = hidden[:, -1]
        elif command.pooling == "last_token":
            indices = mask.sum(dim=1).sub(1).clamp_min(0)
            pooled = hidden[torch.arange(hidden.shape[0]), indices]
        else:
            weights = mask.unsqueeze(-1).to(hidden.dtype)
            pooled = (hidden * weights).sum(dim=1) / weights.sum(dim=1).clamp_min(1)
        if command.normalize:
            pooled = functional.normalize(pooled, p=2, dim=1)
    except (FileNotFoundError, OSError, RuntimeError, ValueError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    vectors = pooled.cpu().tolist()
    return {"model": command.model, "dimension": len(vectors[0]), "vectors": vectors}


def rerank(command: RerankWrite) -> dict[str, object]:
    """Оценки — вероятность «документ отвечает на запрос» у любого reranker.

    Классификатор (BGE) по умолчанию отдаёт сигмоиду, Qwen3 Reranker — разность
    логитов «yes» и «no». Общая сигмоида приводит обе шкалы к вероятности, и
    порог отказа 0,5 не зависит от модели.
    """
    try:
        model = _reranker(command.model)
        from torch import nn

        scores = model.predict(
            [(command.query, document) for document in command.documents],
            activation_fn=nn.Sigmoid(),
        )
    except (FileNotFoundError, ValueError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return {
        "model": command.model,
        "results": [
            {"index": index, "score": float(score)}
            for index, score in sorted(
                enumerate(scores), key=lambda item: float(item[1]), reverse=True
            )
        ],
    }


def run_inference(operation: str, command: BaseModel) -> tuple[dict, dict]:
    """Возвращать ошибки HTTP как данные: HTTPException не сериализуется через spawn."""
    handlers = {"embeddings": embeddings, "embed": internal_embeddings, "rerank": rerank}
    try:
        result = handlers[operation](command)
    except HTTPException as error:
        result = {"error_status": error.status_code, "error_detail": error.detail}
    return result, model_cache_state()
