"""HTTP-сервис моделей: healthcheck не загружает веса и не мешает их выгрузке."""

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException

from app.config import settings
from app.process_pool import IdleProcessPool
from app.retrieval.inference import (
    EmbeddingWrite,
    InternalEmbeddingWrite,
    RerankWrite,
    run_inference,
)

_pool = IdleProcessPool(idle_seconds=settings.retrieval_model_idle_seconds)
_loaded: dict[str, object] = {}


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Остановка сервера закрывает inference-процесс вместе с его кэшами."""
    _pool.start()
    try:
        yield
    finally:
        _pool.close()


app = FastAPI(title="Tentex retrieval model service", version="0.1.0", lifespan=lifespan)


@app.get("/health")
def health() -> dict[str, object]:
    """Показывать загруженные модели без обращения к inference-процессу."""
    loaded = _loaded if settings.retrieval_model_idle_seconds == 0 or _pool.loaded else {}
    return {
        "status": "ok", "service": "tentex-retrieval-model",
        "loaded_embedding_models": loaded.get("loaded_embedding_models", 0),
        "loaded_transformer_models": loaded.get("loaded_transformer_models", 0),
        "loaded_rerankers": loaded.get("loaded_rerankers", 0),
    }


def _infer(operation: str, command: EmbeddingWrite | InternalEmbeddingWrite | RerankWrite) -> dict:
    """Держать прогретые модели на протяжении серии запросов, включая индексирование."""
    global _loaded
    if settings.retrieval_model_idle_seconds == 0:
        result, _loaded = run_inference(operation, command)
    else:
        result, _loaded = _pool.submit(run_inference, operation, command).result()
    if "error_status" in result:
        raise HTTPException(status_code=result["error_status"], detail=result["error_detail"])
    return result


@app.post("/v1/embeddings")
def embeddings(command: EmbeddingWrite) -> dict:
    """OpenAI-совместимые embeddings с прежним форматом ответа."""
    return _infer("embeddings", command)


@app.post("/embed")
def internal_embeddings(command: InternalEmbeddingWrite) -> dict:
    """Transformers-профили с прежними pooling и нормализацией."""
    return _infer("embed", command)


@app.post("/rerank")
def rerank(command: RerankWrite) -> dict:
    """Ранжировать той же моделью и сигмоидой в отдельном процессе."""
    return _infer("rerank", command)
