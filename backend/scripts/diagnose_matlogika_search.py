"""Trace fixed Matlogika cases through BM25, E5 candidates and RRF, read-only."""

from __future__ import annotations

import argparse
import asyncio
import json

from evaluate_project_search import CASES_PATH, PROJECT_ID
from sqlalchemy import select, text

from app.db import SessionLocal
from app.models import EmbeddingProfile, Material, RetrievalChunk, RetrievalIndex, RetrievalSettings
from app.retrieval.embeddings import backend_for_profile
from app.retrieval.presets import PRESETS
from app.retrieval.schemas import RetrievalScope, RetrievalSearchWrite, SearchStrategy
from app.retrieval.search import (
    _lexical_candidates,
    _lexical_coverage,
    _lexical_ids,
    _ranking,
    resolve_scope,
)
from app.retrieval.vector import SqliteVecIndex


async def diagnose(ids: set[str]) -> list[dict]:
    """Show the rank of the exact answer chunk at every selection boundary."""
    cases = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    rows = []
    with SessionLocal() as session:
        session.execute(text("PRAGMA query_only = ON"))
        session.autoflush = False
        settings = session.get(RetrievalSettings, 1)
        index = session.get(RetrievalIndex, settings.active_index_id)
        profile = session.get(EmbeddingProfile, index.profile_id)
        preset = PRESETS[settings.preset]
        for case in cases:
            if case["id"] not in ids or case["material"] is None:
                continue
            material = session.scalar(
                select(Material).where(Material.original_name == case["material"])
            )
            expected = next(
                chunk for chunk in session.scalars(
                    select(RetrievalChunk).where(
                        RetrievalChunk.index_id == index.id,
                        RetrievalChunk.material_id == material.id,
                        RetrievalChunk.page_from <= case["page"],
                        RetrievalChunk.page_to >= case["page"],
                    )
                ) if case["evidence"] in chunk.text
            )
            scope = resolve_scope(session, RetrievalSearchWrite(
                query=case["query"], scope=RetrievalScope.PROJECT, project_id=PROJECT_ID,
            ))
            lexical_hits = _lexical_candidates(
                session, scope, case["query"], preset.lexical_candidates
            )
            plain_query = case["query"].translate(str.maketrans("∀∃¬∧∨→↔", "       "))
            plain_hits = _lexical_candidates(
                session, scope, plain_query, preset.lexical_candidates
            )
            pseudo = {}
            lexical_ids = _lexical_ids(session, index, lexical_hits, pseudo)
            vector = await backend_for_profile(session, profile).embed_query(case["query"])
            semantic_hits = SqliteVecIndex().search(
                session, index_id=index.id, material_ids=scope.material_ids,
                query_vector=vector, limit=preset.semantic_candidates,
            )
            semantic_ids = [hit.chunk_id for hit in semantic_hits]
            ranking = _ranking(
                SearchStrategy.HYBRID,
                lexical_ids, semantic_ids, preset, settings.expert_parameters,
            )
            def rank(ids_or_tuples, needle):
                ids = [value[0] if isinstance(value, tuple) else value for value in ids_or_tuples]
                return ids.index(needle) + 1 if needle in ids else None
            rows.append({
                "id": case["id"], "query": case["query"], "expected_chunk": str(expected.id),
                "lexical_coverage": _lexical_coverage(case["query"], lexical_hits),
                "plain_coverage": _lexical_coverage(plain_query, plain_hits),
                "lexical_fragment_count": len(lexical_hits),
                "lexical_rank": rank(lexical_ids, expected.id),
                "semantic_rank": rank(semantic_ids, expected.id),
                "rrf_rank": rank(ranking, expected.id),
                "best_cosine": round(1 - semantic_hits[0].distance, 4) if semantic_hits else None,
                "top5": [{
                    "rank": i,
                    "chunk_id": str(item_id),
                    "signals": signals,
                    "page": (
                        chunk.page_from
                        if (chunk := session.get(RetrievalChunk, item_id)) else None
                    ),
                    "title": chunk.title if chunk else None,
                    "excerpt": " ".join(chunk.text.split())[:180] if chunk else None,
                } for i, (item_id, _, signals) in enumerate(ranking[:5], 1)],
            })
    return rows


def main() -> None:
    """Trace named development cases without touching holdout queries."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ids", nargs="+")
    args = parser.parse_args()
    print(json.dumps(asyncio.run(diagnose(set(args.ids))), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
