from __future__ import annotations

from typing import Protocol

import httpx
from sqlalchemy.orm import Session

from app.ai.catalog import production_transport
from app.config import settings
from app.models import EmbeddingBackendKind, EmbeddingProfile
from app.projects.errors import ProjectDomainError


class EmbeddingBackend(Protocol):
    async def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    async def embed_query(self, text: str) -> list[float]: ...


class OpenAIEmbeddingBackend:
    def __init__(self, profile: EmbeddingProfile, transport) -> None:
        self.profile = profile
        self.transport = transport

    def _render(self, template: str, text: str) -> str:
        return template.replace("{text}", text)

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        rendered = [self._render(self.profile.document_template, text) for text in texts]
        result = await self.transport.embed(model=self.profile.model_id, texts=rendered)
        _validate_vectors(result.vectors, len(texts), self.profile.dimension)
        return result.vectors

    async def embed_query(self, text: str) -> list[float]:
        rendered = self._render(self.profile.query_template, text)
        result = await self.transport.embed(model=self.profile.model_id, texts=[rendered])
        _validate_vectors(result.vectors, 1, self.profile.dimension)
        return result.vectors[0]


class LocalEmbeddingBackend:
    """Внутренний endpoint передаёт pooling/normalize, которых нет в OpenAI API."""

    def __init__(self, profile: EmbeddingProfile) -> None:
        self.profile = profile

    async def _embed(self, texts: list[str], template: str) -> list[list[float]]:
        payload = {
            "model": self.profile.model_id,
            "input": [template.replace("{text}", text) for text in texts],
            "pooling": self.profile.pooling,
            "normalize": self.profile.normalize,
        }
        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.post(f"{settings.retrieval_model_url}/embed", json=payload)
        try:
            response.raise_for_status()
            vectors = response.json()["vectors"]
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as error:
            raise ProjectDomainError(
                "Локальный model service не вернул embeddings",
                status=503,
                code="retrieval_local_model_unavailable",
            ) from error
        _validate_vectors(vectors, len(texts), self.profile.dimension)
        return vectors

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return await self._embed(texts, self.profile.document_template)

    async def embed_query(self, text: str) -> list[float]:
        return (await self._embed([text], self.profile.query_template))[0]


def backend_for_profile(session: Session, profile: EmbeddingProfile) -> EmbeddingBackend:
    """Собрать adapter без протекания провайдера в retrieval-сервис."""
    if profile.backend_kind == EmbeddingBackendKind.LOCAL_HF:
        return LocalEmbeddingBackend(profile)
    elif profile.provider_id is not None:
        transport = production_transport(session, profile.provider_id)
    else:
        raise ProjectDomainError(
            "У embedding-профиля не настроен провайдер",
            status=422,
            code="retrieval_provider_missing",
        )
    return OpenAIEmbeddingBackend(profile, transport)


def _validate_vectors(
    vectors: list[list[float]], expected_count: int, expected_dimension: int | None
) -> None:
    if len(vectors) != expected_count or not vectors:
        raise ProjectDomainError(
            "Embedding endpoint вернул неполный batch",
            status=502,
            code="retrieval_embedding_batch_mismatch",
        )
    dimensions = {len(vector) for vector in vectors}
    if len(dimensions) != 1 or 0 in dimensions:
        raise ProjectDomainError(
            "Embedding endpoint вернул векторы разной размерности",
            status=502,
            code="retrieval_dimension_mismatch",
        )
    actual = next(iter(dimensions))
    if expected_dimension is not None and actual != expected_dimension:
        raise ProjectDomainError(
            f"Размерность embedding изменилась: ожидалось {expected_dimension}, получено {actual}",
            status=409,
            code="retrieval_dimension_mismatch",
        )
