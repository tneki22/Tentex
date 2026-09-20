from __future__ import annotations

import hashlib
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import RetrievalChunk
from app.retrieval.chunking import count_tokens
from app.retrieval.schemas import RetrievalHitRead, RetrievalSearchRead
from app.retrieval.search import chunk_read


@dataclass(frozen=True)
class AssembledContext:
    sources: list[RetrievalHitRead]
    token_count: int
    truncated: bool


class ContextAssembler:
    """Дедупликация, соседние куски и единый бюджет контекста ответа."""

    def assemble(
        self,
        session: Session,
        result: RetrievalSearchRead,
        *,
        token_budget: int = 6_000,
        neighbor_window: int = 1,
    ) -> AssembledContext:
        candidates: list[RetrievalHitRead] = []
        for hit in result.results:
            candidates.append(hit)
            if result.index_id is None or neighbor_window <= 0:
                continue
            chunk = session.get(RetrievalChunk, hit.locator.chunk_id)
            if chunk is None:
                continue
            neighbors = list(
                session.scalars(
                    select(RetrievalChunk)
                    .where(
                        RetrievalChunk.index_id == result.index_id,
                        RetrievalChunk.material_id == chunk.material_id,
                        RetrievalChunk.block_id == chunk.block_id,
                        RetrievalChunk.sort_order.between(
                            chunk.sort_order - neighbor_window,
                            chunk.sort_order + neighbor_window,
                        ),
                        RetrievalChunk.id != chunk.id,
                    )
                    .order_by(RetrievalChunk.sort_order)
                )
            )
            candidates.extend(
                chunk_read(session, neighbor, hit.score * 0.9, hit.signals)
                for neighbor in neighbors
            )
        sources: list[RetrievalHitRead] = []
        seen_chunks = set()
        seen_text = set()
        used = 0
        truncated = False
        for hit in candidates:
            digest = hashlib.sha256(" ".join(hit.text.split()).encode()).digest()
            if hit.locator.chunk_id in seen_chunks or digest in seen_text:
                continue
            size = count_tokens(hit.text)
            if sources and used + size > token_budget:
                truncated = True
                continue
            sources.append(hit)
            seen_chunks.add(hit.locator.chunk_id)
            seen_text.add(digest)
            used += size
        return AssembledContext(sources=sources, token_count=used, truncated=truncated)
