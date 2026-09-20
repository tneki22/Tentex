from __future__ import annotations

import math
from array import array
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session


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
    """Точный cosine search после SQL-фильтра по индексу и материалам."""

    def _load(self, session: Session) -> None:
        try:
            import sqlite_vec

            raw = session.connection().connection.driver_connection
            raw.enable_load_extension(True)
            try:
                sqlite_vec.load(raw)
            finally:
                raw.enable_load_extension(False)
        except (ImportError, AttributeError, OSError) as error:
            raise VectorUnavailableError("sqlite-vec недоступен") from error

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
        if not material_ids:
            return []
        self._load(session)
        placeholders = ", ".join(f":m{number}" for number in range(len(material_ids)))
        params: dict[str, object] = {
            "index_id": index_id.hex,
            "query": vector_blob(query_vector),
            "limit": limit,
        }
        params.update({f"m{number}": item.hex for number, item in enumerate(material_ids)})
        block_filter = ""
        if block_ids is not None:
            if not block_ids:
                return []
            block_placeholders = ", ".join(f":b{number}" for number in range(len(block_ids)))
            params.update({f"b{number}": item.hex for number, item in enumerate(block_ids)})
            block_filter = f"AND block_id IN ({block_placeholders}) "
        try:
            rows = session.execute(
                text(
                    "SELECT id, vec_distance_cosine(embedding, :query) AS distance "
                    "FROM retrieval_chunks WHERE index_id = :index_id "
                    f"AND material_id IN ({placeholders}) {block_filter}AND embedding IS NOT NULL "
                    "AND revision = (SELECT active_parse_revision FROM materials "
                    "WHERE materials.id = retrieval_chunks.material_id) "
                    "ORDER BY distance LIMIT :limit"
                ),
                params,
            ).all()
        except Exception as error:
            raise VectorUnavailableError("sqlite-vec не выполнил cosine search") from error
        return [VectorHit(UUID(hex=row[0]), float(row[1])) for row in rows]


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
