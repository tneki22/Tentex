"""Проверить, разделяет ли cosine наличие ответа на закреплённых запросах."""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
from pathlib import Path

from evaluate_retrieval_quality import read_cases
from sqlalchemy import text

from app.db import SessionLocal
from app.materials.lexicon import index_text, query_terms
from app.models import EmbeddingProfile, RetrievalIndex, RetrievalSettings
from app.retrieval.embeddings import backend_for_profile
from app.retrieval.schemas import RetrievalScope, RetrievalSearchWrite
from app.retrieval.search import _lexical_candidates, resolve_scope
from app.retrieval.vector import SqliteVecIndex


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("cases", type=Path)
    args = parser.parse_args()
    cases = read_cases(args.cases)
    with SessionLocal() as session:
        session.execute(text("PRAGMA query_only = ON"))
        settings = session.get(RetrievalSettings, 1)
        index = session.get(RetrievalIndex, settings.active_index_id)
        profile = session.get(EmbeddingProfile, index.profile_id)
        backend = backend_for_profile(session, profile)
        vectors = SqliteVecIndex()
        rows = []
        for case in cases:
            scope = resolve_scope(session, RetrievalSearchWrite(
                query=case.query, scope=RetrievalScope.PROJECT,
                project_id=case.project_id,
            ))
            embedding = await backend.embed_query(case.query)
            found = vectors.search(
                session, index_id=index.id, material_ids=scope.material_ids,
                query_vector=embedding, limit=1,
            )
            if not found:
                continue
            from app.models import RetrievalChunk
            chunk = session.get(RetrievalChunk, found[0].chunk_id)
            terms = set(query_terms(case.query))
            overlap = len(terms & set(index_text(chunk.text + " " + (chunk.title or "")).split()))
            lexical = _lexical_candidates(session, scope, case.query, 1)
            lexical_text = lexical[0].text + " " + (lexical[0].block_title or "") if lexical else ""
            lexical_overlap = len(terms & set(index_text(lexical_text).split()))
            rows.append({
                "query": case.query, "positive": bool(case.expected_blocks),
                "cosine": round(1 - found[0].distance, 4),
                "overlap": round(overlap / len(terms), 3) if terms else 0,
                "lexical_overlap": round(lexical_overlap / len(terms), 3) if terms else 0,
            })
    summary = {}
    for label in (True, False):
        group = [row for row in rows if row["positive"] == label]
        similarity = sorted(row["cosine"] for row in group)
        overlap = sorted(row["overlap"] for row in group)
        summary["positive" if label else "negative"] = {
            "count": len(group), "cosine_min": similarity[0],
            "cosine_p10": similarity[int((len(group) - 1) * .1)],
            "cosine_median": statistics.median(similarity),
            "cosine_p90": similarity[int((len(group) - 1) * .9)],
            "cosine_max": similarity[-1],
            "overlap_median": statistics.median(overlap),
        }
    summary["thresholds"] = [
        {"cosine": round(threshold / 100, 2),
         "positive_kept": sum(row["cosine"] >= threshold / 100 for row in rows
                              if row["positive"]),
         "negative_kept": sum(row["cosine"] >= threshold / 100 for row in rows
                              if not row["positive"])}
        for threshold in range(76, 91, 2)
    ]
    summary["combined_thresholds"] = [
        {"cosine": threshold / 100, "lexical_overlap": lexical / 100,
         "positive_kept": sum(
             row["cosine"] >= threshold / 100 or row["lexical_overlap"] >= lexical / 100
             for row in rows if row["positive"]
         ),
         "negative_kept": sum(
             row["cosine"] >= threshold / 100 or row["lexical_overlap"] >= lexical / 100
             for row in rows if not row["positive"]
         )}
        for threshold, lexical in ((82, 75), (83, 75), (84, 75), (83, 100))
    ]
    summary["lexical_thresholds"] = [
        {"coverage": threshold / 100,
         "positive_kept": sum(row["lexical_overlap"] >= threshold / 100 for row in rows
                              if row["positive"]),
         "negative_kept": sum(row["lexical_overlap"] >= threshold / 100 for row in rows
                              if not row["positive"])}
        for threshold in (50, 60, 75, 100)
    ]
    summary["borderline"] = sorted(rows, key=lambda row: abs(row["cosine"] - .84))[:15]
    summary["lowest_positive"] = sorted(
        (row for row in rows if row["positive"]), key=lambda row: row["cosine"]
    )[:12]
    summary["highest_negative"] = sorted(
        (row for row in rows if not row["positive"]),
        key=lambda row: row["cosine"], reverse=True,
    )[:12]
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
