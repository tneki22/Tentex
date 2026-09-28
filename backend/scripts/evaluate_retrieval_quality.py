"""Проверить лексический, смысловой и гибридный поиск на ручных привязках.

Запускать в контейнере API с данными приложения только для чтения. Ручная
привязка — слабая положительная метка: она указывает известный подходящий блок,
но не объявляет все остальные блоки нерелевантными. Отрицательные запросы
требуют ручной проверки.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import statistics
import time
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import (
    Binding,
    BindingStatus,
    ProgramNode,
    RetrievalChunk,
    RetrievalIndex,
    RetrievalSettings,
)
from app.retrieval.schemas import RetrievalScope, RetrievalSearchWrite, SearchStrategy
from app.retrieval.search import HybridRetriever


@dataclass(frozen=True)
class Case:
    project_id: UUID
    query: str
    expected_blocks: frozenset[UUID]


def read_cases(path: Path) -> list[Case]:
    """Читать закреплённую разметку; пустой expected_blocks означает отсутствие ответа."""
    return [
        Case(UUID(row["project_id"]), row["query"],
             frozenset(UUID(value) for value in row["expected_blocks"]))
        for row in json.loads(path.read_text(encoding="utf-8"))
    ]


def write_cases(path: Path, cases: list[Case]) -> None:
    """Зафиксировать один и тот же набор для сравнения моделей и индексов."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([
        {"project_id": str(case.project_id), "query": case.query,
         "expected_blocks": sorted(str(value) for value in case.expected_blocks)}
        for case in cases
    ], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def manual_cases(session: Session, index_id: UUID, limit: int) -> list[Case]:
    """Sample short topics with 1–5 manually bound blocks present in this index."""
    indexed: set[UUID] = set()
    for block_id, locator in session.execute(
        select(RetrievalChunk.block_id, RetrievalChunk.locator).where(
            RetrievalChunk.index_id == index_id,
        )
    ):
        if block_id:
            indexed.add(block_id)
        indexed.update(UUID(value) for value in locator.get("block_ids", []))
    grouped: dict[UUID, tuple[UUID, str, set[UUID]]] = {}
    rows = session.execute(
        select(ProgramNode.id, ProgramNode.project_id, ProgramNode.title, Binding.block_id)
        .join(Binding, Binding.program_node_id == ProgramNode.id)
        .where(Binding.status == BindingStatus.MANUAL, Binding.block_id.is_not(None))
    )
    for node_id, project_id, title, block_id in rows:
        if block_id not in indexed:
            continue
        grouped.setdefault(node_id, (project_id, title, set()))[2].add(block_id)
    by_project: dict[UUID, list[Case]] = defaultdict(list)
    for project_id, title, blocks in grouped.values():
        if 12 <= len(title) <= 180 and 1 <= len(blocks) <= 5:
            by_project[project_id].append(Case(project_id, title, frozenset(blocks)))
    for cases in by_project.values():
        cases.sort(key=lambda case: case.query)
    selected: list[Case] = []
    while len(selected) < limit and any(by_project.values()):
        for project_id in sorted(by_project):
            if by_project[project_id] and len(selected) < limit:
                selected.append(by_project[project_id].pop(0))
    return selected


def matched_blocks(session: Session, hits, expected: frozenset[UUID]) -> list[int]:
    """Return ranks that reach an expected block, including multi-block chunks."""
    ranks: list[int] = []
    for rank, hit in enumerate(hits, 1):
        blocks = {hit.locator.block_id} if hit.locator.block_id else set()
        chunk = session.get(RetrievalChunk, hit.locator.chunk_id)
        if chunk:
            blocks.update(UUID(value) for value in chunk.locator.get("block_ids", []))
        if blocks & expected:
            ranks.append(rank)
    return ranks


async def evaluate(
    session: Session, cases: list[Case], strategy: SearchStrategy, index_id: UUID
) -> dict:
    """Measure known-block rank and duplicate rate without writing to the database."""
    retriever = HybridRetriever(index_id=index_id)
    ranks: list[int | None] = []
    latencies: list[float] = []
    duplicate_rates: list[float] = []
    failures: list[dict[str, str | int | None]] = []
    false_positives = 0
    for case in cases:
        started = time.perf_counter()
        result = await retriever.search(session, RetrievalSearchWrite(
            query=case.query, strategy=strategy, scope=RetrievalScope.PROJECT,
            project_id=case.project_id, limit=20,
        ))
        latencies.append((time.perf_counter() - started) * 1000)
        if not case.expected_blocks:
            false_positives += bool(result.results)
            if result.results:
                failures.append({"query": case.query, "rank": None})
            continue
        found = matched_blocks(session, result.results, case.expected_blocks)
        rank = found[0] if found else None
        ranks.append(rank)
        texts = {" ".join(hit.text.split()) for hit in result.results}
        duplicate_rates.append(
            1 - len(texts) / len(result.results) if result.results else 0.0
        )
        if rank is None or rank > 5:
            failures.append({"query": case.query, "rank": rank})
    positive_count = len(ranks)
    return {
        "positive_cases": positive_count,
        "negative_cases": len(cases) - positive_count,
        "negative_false_positive": false_positives,
        "hit_at_5": (
            sum(rank is not None and rank <= 5 for rank in ranks) / positive_count
            if ranks else 0
        ),
        "hit_at_10": (
            sum(rank is not None and rank <= 10 for rank in ranks) / positive_count
            if ranks else 0
        ),
        "mrr_at_10": statistics.fmean(
            1 / rank if rank and rank <= 10 else 0 for rank in ranks
        ) if ranks else 0,
        "duplicate_rate": statistics.fmean(duplicate_rates) if duplicate_rates else 0,
        "p50_ms": statistics.median(latencies),
        "p95_ms": sorted(latencies)[math.ceil(len(latencies) * .95) - 1],
        "failures": failures[:10],
    }


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=30)
    parser.add_argument("--index-id", type=UUID, help="Candidate index; defaults to active")
    parser.add_argument("--cases", type=Path, help="JSON with fixed positive and negative cases")
    parser.add_argument("--export-cases", type=Path, help="Write sampled manual cases to JSON")
    parser.add_argument("--export-only", action="store_true")
    parser.add_argument("--only-negative", action="store_true")
    parser.add_argument("--semantic-weight", type=float, default=1.0)
    parser.add_argument("--rrf-k", type=int, default=60)
    parser.add_argument("--strategies", nargs="+", choices=list(SearchStrategy),
                        default=["lexical", "semantic", "hybrid"])
    args = parser.parse_args()
    if args.limit < 1:
        parser.error("--limit must be positive")
    with SessionLocal() as session:
        session.execute(text("PRAGMA query_only = ON"))
        session.autoflush = False
        settings = session.get(RetrievalSettings, 1)
        index_id = args.index_id or (settings.active_index_id if settings else None)
        if index_id is None:
            parser.error("No active retrieval index")
        if session.get(RetrievalIndex, index_id) is None:
            parser.error("Retrieval index does not exist")
        cases = read_cases(args.cases) if args.cases else manual_cases(
            session, index_id, args.limit,
        )
        if args.only_negative:
            cases = [case for case in cases if not case.expected_blocks]
        if not cases:
            parser.error("No eligible manual bindings in active index")
        if args.export_cases:
            write_cases(args.export_cases, cases)
        if args.export_only:
            print(json.dumps({"cases": len(cases), "path": str(args.export_cases)}))
            return
        if settings:
            settings.expert_parameters = {
                **settings.expert_parameters,
                "semantic_weight": args.semantic_weight,
                "rrf_k": args.rrf_k,
            }
        output = {
            "index_id": str(index_id), "cases": len(cases),
            "semantic_weight": args.semantic_weight,
            "rrf_k": args.rrf_k,
        }
        for strategy in args.strategies:
            output[str(strategy)] = await evaluate(
                session, cases, SearchStrategy(strategy), index_id,
            )
        print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
