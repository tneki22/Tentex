"""Контрольные запросы к полному корпусу и устойчивые к пересборке индекса метрики."""

from __future__ import annotations

import math
import statistics
import time
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import RetrievalBenchmarkCase, RetrievalBenchmarkRun, RetrievalChunk, RetrievalIndex
from app.projects.errors import ProjectDomainError, ProjectNotFoundError
from app.retrieval.schemas import (
    BenchmarkCaseWrite,
    BenchmarkRunRead,
    RetrievalHitRead,
    RetrievalScope,
    RetrievalSearchWrite,
    SearchStrategy,
)
from app.retrieval.search import HybridRetriever


def add_case(session: Session, command: BenchmarkCaseWrite) -> RetrievalBenchmarkCase:
    """Сохранить эталон: material и block ID переживают смену retrieval-индекса."""
    with session.begin():
        row = RetrievalBenchmarkCase(
            id=uuid4(),
            query=command.query,
            relevant_material_ids=[str(item) for item in command.relevant_material_ids],
            relevant_locator_ids=command.relevant_locator_ids,
            tags=command.tags,
        )
        session.add(row)
    return row


def _hit_targets(
    session: Session, hit: RetrievalHitRead, blocks: set[str], materials: set[str]
) -> set[str]:
    """Учесть все блоки составного куска, а не только его главный блок."""
    if blocks:
        found = {str(hit.locator.block_id)} if hit.locator.block_id else set()
        chunk = session.get(RetrievalChunk, hit.locator.chunk_id)
        if chunk:
            found.update(chunk.locator.get("block_ids", []))
        return found & blocks
    return {str(hit.locator.material_id)} & materials


def _score_case(
    session: Session, case: RetrievalBenchmarkCase, hits: list[RetrievalHitRead]
) -> dict:
    """Отдельно оценить положительный и заведомо отсутствующий запрос."""
    blocks = set(case.relevant_locator_ids)
    materials = set(case.relevant_material_ids)
    expected = blocks or materials
    if not expected:
        return {"negative": True, "correct_empty": not hits}
    matched: set[str] = set()
    relevant_ranks: list[int] = []
    for rank, hit in enumerate(hits[:10], 1):
        targets = _hit_targets(session, hit, blocks, materials) - matched
        if targets:
            relevant_ranks.append(rank)
            matched.update(targets)
    dcg = sum(1 / math.log2(rank + 1) for rank in relevant_ranks)
    ideal = sum(1 / math.log2(rank + 1) for rank in range(1, min(len(expected), 10) + 1))
    return {
        "negative": False,
        "recall_at_10": len(matched) / len(expected),
        "mrr_at_10": 1 / relevant_ranks[0] if relevant_ranks else 0.0,
        "ndcg_at_10": dcg / ideal if ideal else 0.0,
        "miss": not relevant_ranks,
    }


async def run_benchmark(
    session: Session, index_id: UUID, retriever: HybridRetriever | None = None
) -> BenchmarkRunRead:
    """Искать во всей готовой Библиотеке, не подсказывая поиск эталонными материалами."""
    if session.get(RetrievalIndex, index_id) is None:
        raise ProjectNotFoundError("Retrieval-индекс не найден")
    cases = list(session.scalars(select(RetrievalBenchmarkCase)))
    if not cases:
        raise ProjectDomainError(
            "Добавьте контрольные запросы перед запуском benchmark",
            status=422,
            code="retrieval_benchmark_empty",
        )
    retriever = retriever or HybridRetriever(index_id=index_id)
    scores: list[dict] = []
    latencies: list[float] = []
    for case in cases:
        started = time.perf_counter()
        result = await retriever.search(
            session,
            RetrievalSearchWrite(
                query=case.query,
                strategy=SearchStrategy.HYBRID,
                scope=RetrievalScope.LIBRARY,
                limit=10,
            ),
        )
        latencies.append((time.perf_counter() - started) * 1_000)
        scores.append(_score_case(session, case, result.results))
    positive = [score for score in scores if not score["negative"]]
    negative = [score for score in scores if score["negative"]]
    sorted_latency = sorted(latencies)
    metrics = {
        key: statistics.fmean(score[key] for score in positive) if positive else 0.0
        for key in ("recall_at_10", "mrr_at_10", "ndcg_at_10")
    }
    metrics.update({
        "positive_cases": len(positive),
        "negative_cases": len(negative),
        "positive_miss": sum(score["miss"] for score in positive),
        "negative_false_positive": sum(not score["correct_empty"] for score in negative),
        "zero_hit": sum(score["miss"] for score in positive),
        "p50_ms": statistics.median(sorted_latency),
        "p95_ms": sorted_latency[max(0, math.ceil(len(sorted_latency) * 0.95) - 1)],
    })
    run = RetrievalBenchmarkRun(
        id=uuid4(), index_id=index_id, metrics=metrics, case_count=len(cases)
    )
    session.add(run)
    session.commit()
    session.refresh(run)
    return BenchmarkRunRead.model_validate(run)
