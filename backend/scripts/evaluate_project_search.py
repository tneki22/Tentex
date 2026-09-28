"""Read-only, source-grounded retrieval check for project case sets.

Run in the API container with this branch mounted at /app and /data mounted read-only.
Holdout cases must stay out of tuning.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import statistics
import time
from pathlib import Path
from uuid import UUID

from sqlalchemy import text

from app.db import SessionLocal
from app.models import RetrievalSettings
from app.retrieval.schemas import RetrievalScope, RetrievalSearchWrite, SearchStrategy
from app.retrieval.search import HybridRetriever

PROJECT_ID = UUID("e65453f3-bff9-43ba-a353-acc018622b53")
CASES_PATH = Path(__file__).with_name("fixtures") / "matlogika_search_quality.json"


def _matches(hit, case: dict) -> bool:
    """Require both the original page and answer-bearing text, not just a bound block."""
    locator = hit.locator
    return (
        locator.material_name == case["material"]
        and locator.page_from is not None
        and locator.page_to is not None
        and locator.page_from <= case["page"] <= locator.page_to
        and case["evidence"] in hit.text
    )


async def evaluate(
    split: str, cases_path: Path = CASES_PATH, semantic_weight: float = 1.0
) -> dict:
    """Execute each public search strategy while forbidding database writes."""
    cases = json.loads(cases_path.read_text(encoding="utf-8"))
    cases = [case for case in cases if split == "all" or case["split"] == split]
    output: dict = {"split": split, "cases": len(cases), "strategies": {}}
    with SessionLocal() as session:
        session.execute(text("PRAGMA query_only = ON"))
        session.autoflush = False
        settings = session.get(RetrievalSettings, 1)
        if settings is not None:
            settings.expert_parameters = {
                **settings.expert_parameters, "semantic_weight": semantic_weight
            }
        for strategy in SearchStrategy:
            retriever = HybridRetriever()
            rows = []
            for case in cases:
                started = time.perf_counter()
                result = await retriever.search(session, RetrievalSearchWrite(
                    query=case["query"], strategy=strategy, scope=RetrievalScope.PROJECT,
                    project_id=UUID(case.get("project_id", str(PROJECT_ID))), limit=10,
                ))
                elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
                rank = next(
                    (i for i, hit in enumerate(result.results, 1) if _matches(hit, case)),
                    None,
                ) if case["material"] else None
                rows.append({
                    "id": case["id"], "query": case["query"], "expected_material": case["material"],
                    "expected_page": case["page"], "expected_excerpt": case["evidence"],
                    "rank": rank, "empty": not result.results,
                    "no_relevant_match": result.no_relevant_match,
                    "degradation_reasons": result.degradation_reasons,
                    "latency_ms": elapsed_ms,
                    "top5": [{
                        "material": hit.locator.material_name,
                        "page_from": hit.locator.page_from,
                        "page_to": hit.locator.page_to,
                        "section": hit.locator.block_title,
                        "chunk_id": str(hit.locator.chunk_id),
                        "signals": hit.signals,
                        "excerpt": " ".join(hit.text.split())[:250],
                        "answer_excerpt_present": bool(case["material"] and _matches(hit, case)),
                    } for hit in result.results[:5]],
                })
            positive = [row for row in rows if row["expected_material"]]
            negative = [row for row in rows if not row["expected_material"]]
            latency = sorted(row["latency_ms"] for row in rows)
            output["strategies"][strategy.value] = {
                "hit_at_5": sum(row["rank"] is not None and row["rank"] <= 5 for row in positive)
                / len(positive),
                "hit_at_10": sum(row["rank"] is not None for row in positive) / len(positive),
                "mrr_at_10": statistics.fmean(
                    1 / row["rank"] if row["rank"] is not None else 0 for row in positive
                ),
                "negative_false_results": sum(not row["empty"] for row in negative),
                "negative_count": len(negative),
                "latency_p50_ms": statistics.median(latency),
                "latency_p95_ms": latency[math.ceil(len(latency) * 0.95) - 1],
                "rows": rows,
            }
    return output


def main() -> None:
    """Print machine-readable evidence for review; do not persist to the user database."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split", choices=("development", "holdout", "all"), default="all")
    parser.add_argument("--cases", type=Path, default=CASES_PATH)
    parser.add_argument("--semantic-weight", type=float, default=1.0)
    args = parser.parse_args()
    print(json.dumps(
        asyncio.run(evaluate(args.split, args.cases, args.semantic_weight)),
        ensure_ascii=False, indent=2,
    ))


if __name__ == "__main__":
    main()
