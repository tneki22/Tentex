from __future__ import annotations

import math
import sqlite3
from array import array
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.orm import Session

from app.retrieval.snapshot import current_revisions, index_snapshot


class VectorUnavailableError(RuntimeError):
    pass


@dataclass(frozen=True)
class VectorHit:
    chunk_id: UUID
    distance: float


def vector_blob(values: list[float]) -> bytes:
    if not values or not all(math.isfinite(value) for value in values):
        raise ValueError("Вектор должен содержать конечные числа")
    return array("f", values).tobytes()


class SqliteVecIndex:
    """Точный cosine search по кускам текущих ревизий материалов области."""

    def search(
        self,
        session: Session,
        *,
        index_id: UUID,
        material_ids: list[UUID],
        query_vector: list[float],
        limit: int,
        block_ids: list[UUID] | None = None,
    ) -> list[VectorHit]:
        if not material_ids or (block_ids is not None and not block_ids):
            return []
        query = vector_blob(query_vector)
        try:
            # Кусок из нескольких блоков хранит их в `locator.block_ids`: снимок
            # относит его к теме, если к ней привязан любой из его блоков.
            hits = index_snapshot(session, index_id).nearest(
                query,
                current_revisions(session, material_ids),
                limit=limit,
                block_ids=block_ids,
            )
        except (ImportError, OSError, sqlite3.Error) as error:
            raise VectorUnavailableError("sqlite-vec не выполнил cosine search") from error
        return [VectorHit(chunk_id, distance) for chunk_id, distance in hits]


def reciprocal_rank_fusion(
    lexical_ids: list[UUID],
    semantic_ids: list[UUID],
    *,
    k: int = 60,
    lexical_weight: float = 1.0,
    semantic_weight: float = 1.0,
) -> list[tuple[UUID, float, list[str]]]:
    """Слить независимые ранги без сравнения несопоставимых score."""
    scores: dict[UUID, float] = {}
    signals: dict[UUID, list[str]] = {}
    for signal, ranked, weight in (
        ("lexical", lexical_ids, lexical_weight),
        ("semantic", semantic_ids, semantic_weight),
    ):
        for rank, item_id in enumerate(ranked, start=1):
            scores[item_id] = scores.get(item_id, 0.0) + weight / (k + rank)
            signals.setdefault(item_id, []).append(signal)
    return sorted(
        ((item_id, score, signals[item_id]) for item_id, score in scores.items()),
        key=lambda item: item[1],
        reverse=True,
    )
