from __future__ import annotations

from functools import lru_cache
from typing import Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.retrieval.local_models import model_path, validate_model_id

app = FastAPI(title="Tentex retrieval model service", version="0.1.0")


class EmbeddingWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model: str = Field(min_length=3, max_length=300)
    input: str | list[str]
    encoding_format: Literal["float"] = "float"


class RerankWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model: str = Field(min_length=3, max_length=300)
    query: str
    documents: list[str] = Field(min_length=1, max_length=100)


class InternalEmbeddingWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model: str = Field(min_length=3, max_length=300)
    input: list[str] = Field(min_length=1, max_length=512)
    pooling: Literal["mean", "cls", "last_token"] = "mean"
    normalize: bool = True


@lru_cache(maxsize=2)
def _embedding_model(model_id: str):
    from sentence_transformers import SentenceTransformer

    path = model_path(validate_model_id(model_id))
    if not path.is_dir():
        raise FileNotFoundError(f"Модель {model_id} не установлена")
    return SentenceTransformer(
        str(path), trust_remote_code=False, local_files_only=True, device="cpu"
    )


@lru_cache(maxsize=1)
def _reranker(model_id: str):
    from sentence_transformers import CrossEncoder

    path = model_path(validate_model_id(model_id))
    if not path.is_dir():
        raise FileNotFoundError(f"Модель {model_id} не установлена")
    return CrossEncoder(str(path), trust_remote_code=False, local_files_only=True, device="cpu")


@lru_cache(maxsize=2)
def _transformer_model(model_id: str):
    from transformers import AutoModel, AutoTokenizer

    path = model_path(validate_model_id(model_id))
    if not path.is_dir():
        raise FileNotFoundError(f"Модель {model_id} не установлена")
    tokenizer = AutoTokenizer.from_pretrained(
        str(path), trust_remote_code=False, local_files_only=True
    )
    model = AutoModel.from_pretrained(
        str(path), trust_remote_code=False, local_files_only=True
    ).eval()
    return tokenizer, model


@app.get("/health")
def health() -> dict[str, object]:
    return {
        "status": "ok",
        "service": "tentex-retrieval-model",
        "loaded_embedding_models": _embedding_model.cache_info().currsize,
        "loaded_transformer_models": _transformer_model.cache_info().currsize,
        "loaded_rerankers": _reranker.cache_info().currsize,
    }


@app.post("/v1/embeddings")
def embeddings(command: EmbeddingWrite) -> dict[str, object]:
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


@app.post("/embed")
def internal_embeddings(command: InternalEmbeddingWrite) -> dict[str, object]:
    """Безопасный Transformers runtime для ручных HF-профилей без remote code."""
    try:
        import torch
        from torch.nn import functional

        tokenizer, model = _transformer_model(command.model)
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


@app.post("/rerank")
def rerank(command: RerankWrite) -> dict[str, object]:
    try:
        scores = _reranker(command.model).predict(
            [(command.query, document) for document in command.documents]
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
