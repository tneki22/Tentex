from __future__ import annotations

import math
import statistics
import time
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import RetrievalBenchmarkCase, RetrievalBenchmarkRun, RetrievalIndex
from app.projects.errors import ProjectNotFoundError
from app.retrieval.schemas import (
    BenchmarkCaseWrite,
    BenchmarkRunRead,
    RetrievalScope,
    RetrievalSearchWrite,
    SearchStrategy,
)
from app.retrieval.search import HybridRetriever


def add_case(session: Session, command: BenchmarkCaseWrite) -> RetrievalBenchmarkCase:
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


async def run_benchmark(
    session: Session, index_id: UUID, retriever: HybridRetriever | None = None
) -> BenchmarkRunRead:
    if session.get(RetrievalIndex, index_id) is None:
        raise ProjectNotFoundError("Retrieval-индекс не найден")
    cases = list(session.scalars(select(RetrievalBenchmarkCase)))
    if not cases:
        metrics = {
            "recall_at_10": 0.0,
            "mrr_at_10": 0.0,
            "ndcg_at_10": 0.0,
            "zero_hit": 0,
            "p50_ms": 0.0,
            "p95_ms": 0.0,
        }
    else:
        recalls: list[float] = []
        reciprocal_ranks: list[float] = []
        ndcgs: list[float] = []
        latencies: list[float] = []
        zero_hit = 0
        retriever = retriever or HybridRetriever(index_id=index_id)
        for case in cases:
            started = time.perf_counter()
            result = await retriever.search(
                session,
                RetrievalSearchWrite(
                    query=case.query,
                    strategy=SearchStrategy.HYBRID,
                    scope=RetrievalScope.SELECTED_MATERIALS,
                    material_ids=[UUID(item) for item in case.relevant_material_ids],
                    limit=10,
                ),
            )
            latencies.append((time.perf_counter() - started) * 1_000)
            expected = set(case.relevant_locator_ids)
            ranked = [str(hit.locator.chunk_id) for hit in result.results]
            relevant_ranks = [rank for rank, item in enumerate(ranked, 1) if item in expected]
            if not relevant_ranks:
                zero_hit += 1
            recalls.append(len(relevant_ranks) / len(expected) if expected else 1.0)
            reciprocal_ranks.append(1.0 / relevant_ranks[0] if relevant_ranks else 0.0)
            dcg = sum(1.0 / math.log2(rank + 1) for rank in relevant_ranks)
            ideal = sum(1.0 / math.log2(rank + 1) for rank in range(1, min(len(expected), 10) + 1))
            ndcgs.append(dcg / ideal if ideal else 1.0)
        sorted_latency = sorted(latencies)
        metrics = {
            "recall_at_10": statistics.fmean(recalls),
            "mrr_at_10": statistics.fmean(reciprocal_ranks),
            "ndcg_at_10": statistics.fmean(ndcgs),
            "zero_hit": zero_hit,
            "p50_ms": statistics.median(sorted_latency),
            "p95_ms": sorted_latency[max(0, math.ceil(len(sorted_latency) * 0.95) - 1)],
        }
    run = RetrievalBenchmarkRun(
        id=uuid4(), index_id=index_id, metrics=metrics, case_count=len(cases)
    )
    session.add(run)
    session.commit()
    session.refresh(run)
    return BenchmarkRunRead.model_validate(run)
