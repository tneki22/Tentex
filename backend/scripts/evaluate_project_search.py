"""Read-only, source-grounded retrieval check for project case sets.

Run in the API container with this branch mounted at /app and /data mounted read-only.
Holdout cases must stay out of tuning.

A positive case is a hit only when one result has the labelled material, page and
answer text (`evidence`, or one of `alternatives`). A negative case must come back
empty with `no_relevant_match`. Refusing a positive case is counted separately as a
false refusal: it is worse than a low rank because the user gets no source at all.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import statistics
import time
from collections import defaultdict
from pathlib import Path
from uuid import UUID

from sqlalchemy import text

from app.db import SessionLocal
from app.models import RetrievalPreset, RetrievalSettings
from app.retrieval.schemas import RetrievalScope, RetrievalSearchWrite, SearchStrategy
from app.retrieval.search import HybridRetriever

PROJECT_ID = UUID("e65453f3-bff9-43ba-a353-acc018622b53")
FIXTURES = Path(__file__).with_name("fixtures")
CASES_PATH = FIXTURES / "matlogika_search_quality.json"


def _norm(value: str) -> str:
    """Compare text regardless of line breaks the chunker kept or dropped."""
    return " ".join(value.split())


def _answers(case: dict) -> list[dict]:
    """The labelled answer place plus any other verified place with the same answer."""
    if not case["material"]:
        return []
    main = {key: case[key] for key in ("material", "page", "evidence")}
    return [main, *case.get("alternatives", [])]


def _matches(hit, case: dict) -> bool:
    """Require both the original page and answer-bearing text, not just a bound block."""
    locator = hit.locator
    return any(
        _norm(locator.material_name) == _norm(answer["material"])
        and locator.page_from is not None
        and locator.page_to is not None
        and locator.page_from <= answer["page"] <= locator.page_to
        and _norm(answer["evidence"]) in _norm(hit.text)
        for answer in _answers(case)
    )


def _share(count: int, total: int) -> float | None:
    return round(count / total, 3) if total else None


def _summary(rows: list[dict]) -> dict:
    """Ranking and abstention metrics for one group of cases."""
    positive = [row for row in rows if row["expected_material"]]
    negative = [row for row in rows if not row["expected_material"]]
    latency = sorted(row["latency_ms"] for row in rows)
    return {
        "positive_count": len(positive),
        "negative_count": len(negative),
        "hit_at_5": _share(sum(row["rank"] is not None and row["rank"] <= 5 for row in positive),
                          len(positive)),
        "hit_at_10": _share(sum(row["rank"] is not None for row in positive), len(positive)),
        "mrr_at_10": round(statistics.fmean(
            1 / row["rank"] if row["rank"] is not None else 0 for row in positive
        ), 3) if positive else None,
        "false_refusals": sum(row["empty"] for row in positive),
        "negative_false_results": sum(not row["empty"] for row in negative),
        "latency_p50_ms": statistics.median(latency) if latency else None,
        "latency_p95_ms": latency[math.ceil(len(latency) * 0.95) - 1] if latency else None,
    }


async def evaluate(
    split: str,
    cases_paths: list[Path] | Path = CASES_PATH,
    semantic_weight: float = 1.0,
    *,
    strategies: list[SearchStrategy] | None = None,
    preset: RetrievalPreset | None = None,
) -> dict:
    """Execute the requested search strategies while forbidding database writes."""
    paths = [cases_paths] if isinstance(cases_paths, Path) else cases_paths
    cases = [case for path in paths for case in json.loads(path.read_text(encoding="utf-8"))]
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
            if preset is not None:
                settings.preset = preset
        output["preset"] = settings.preset.value if settings else None
        for strategy in strategies or list(SearchStrategy):
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
                    "id": case["id"], "project_id": case.get("project_id", str(PROJECT_ID)),
                    "query": case["query"], "expected_material": case["material"],
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
                        "score": round(hit.score, 4),
                        "signals": hit.signals,
                        "excerpt": " ".join(hit.text.split())[:250],
                        "answer_excerpt_present": bool(case["material"] and _matches(hit, case)),
                    } for hit in result.results[:5]],
                })
            by_project: dict[str, list[dict]] = defaultdict(list)
            for row in rows:
                by_project[row["project_id"]].append(row)
            output["strategies"][strategy.value] = {
                **_summary(rows),
                "by_project": {key: _summary(value) for key, value in by_project.items()},
                "rows": rows,
            }
    return output


def main() -> None:
    """Print machine-readable evidence for review; do not persist to the user database."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split", choices=("development", "holdout", "all"), default="all")
    parser.add_argument("--cases", type=Path, nargs="+", default=[CASES_PATH])
    parser.add_argument("--semantic-weight", type=float, default=1.0)
    parser.add_argument("--strategies", nargs="+", choices=[item.value for item in SearchStrategy])
    parser.add_argument("--preset", choices=[item.value for item in RetrievalPreset])
    parser.add_argument("--summary", action="store_true", help="Omit per-case rows")
    args = parser.parse_args()
    output = asyncio.run(evaluate(
        args.split, args.cases, args.semantic_weight,
        strategies=[SearchStrategy(item) for item in args.strategies] if args.strategies else None,
        preset=RetrievalPreset(args.preset) if args.preset else None,
    ))
    if args.summary:
        for result in output["strategies"].values():
            result.pop("rows")
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
