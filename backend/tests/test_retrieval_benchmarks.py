"""Метрики поиска не подсказывают выдаче эталонные материалы и переживают новый индекс."""

from __future__ import annotations

from uuid import uuid4

import pytest
from conftest import make_material
from sqlalchemy.orm import Session

from app.models import (
    EmbeddingBackendKind,
    EmbeddingProfile,
    RetrievalBenchmarkCase,
    RetrievalChunk,
    RetrievalChunkKind,
    RetrievalIndex,
    RetrievalIndexState,
    RetrievalPreset,
)
from app.projects.errors import ProjectDomainError
from app.retrieval.benchmarks import _score_case, run_benchmark
from app.retrieval.schemas import (
    RetrievalHitRead,
    RetrievalLocatorRead,
    RetrievalScope,
    RetrievalSearchRead,
    SearchStrategy,
)


def _hit(material_id, *, chunk_id=None, block_id=None) -> RetrievalHitRead:
    return RetrievalHitRead(
        locator=RetrievalLocatorRead(
            chunk_id=chunk_id or uuid4(), material_id=material_id,
            material_name="Материал", block_id=block_id, block_title=None,
            page_from=None, page_to=None, fragment_ids=[],
        ),
        text="Текст", quality=None, score=1, signals=["semantic"],
    )


def _index(session: Session) -> RetrievalIndex:
    profile = EmbeddingProfile(
        label="Тест", backend_kind=EmbeddingBackendKind.LOCAL_HF,
        model_id="test/embedding", installed=True,
    )
    session.add(profile)
    session.flush()
    index = RetrievalIndex(
        profile_id=profile.id, state=RetrievalIndexState.READY,
        preset=RetrievalPreset.BALANCED, chunk_target_tokens=280,
        chunk_max_tokens=360, chunk_overlap_tokens=48,
    )
    session.add(index)
    session.commit()
    return index


def test_case_scores_material_without_restricting_corpus(session: Session) -> None:
    target, distractor = make_material(session, "811"), make_material(session, "812")
    case = RetrievalBenchmarkCase(
        query="Пример", relevant_material_ids=[str(target.id)],
        relevant_locator_ids=[], tags=[],
    )
    score = _score_case(session, case, [_hit(distractor.id), _hit(target.id)])

    assert score["recall_at_10"] == 1
    assert score["mrr_at_10"] == .5
    assert _score_case(session, RetrievalBenchmarkCase(
        query="Нет ответа", relevant_material_ids=[], relevant_locator_ids=[], tags=[],
    ), [_hit(distractor.id)]) == {"negative": True, "correct_empty": False}


def test_case_matches_secondary_block_of_chunk(session: Session) -> None:
    material = make_material(session, "813")
    index = _index(session)
    main, expected = uuid4(), uuid4()
    chunk = RetrievalChunk(
        index_id=index.id, material_id=material.id, revision=1,
        kind=RetrievalChunkKind.TEXT, sort_order=0, block_id=None,
        text="Текст", token_count=1, content_hash="0" * 64,
        fragment_ids=[], locator={"block_ids": [str(expected)]},
    )
    session.add(chunk)
    session.commit()
    case = RetrievalBenchmarkCase(
        query="Пример", relevant_material_ids=[str(material.id)],
        relevant_locator_ids=[str(expected)], tags=[],
    )

    assert _score_case(session, case, [_hit(material.id, chunk_id=chunk.id, block_id=main)])[
        "recall_at_10"
    ] == 1


def test_case_does_not_award_repeated_material_twice(session: Session) -> None:
    material = make_material(session, "816")
    case = RetrievalBenchmarkCase(
        query="Пример", relevant_material_ids=[str(material.id)],
        relevant_locator_ids=[], tags=[],
    )

    score = _score_case(session, case, [_hit(material.id), _hit(material.id)])

    assert score["recall_at_10"] == 1
    assert score["ndcg_at_10"] == 1


@pytest.mark.asyncio
async def test_benchmark_searches_full_library_and_counts_absent_case(session: Session) -> None:
    material = make_material(session, "814")
    index = _index(session)
    session.add_all([
        RetrievalBenchmarkCase(
            query="Есть", relevant_material_ids=[str(material.id)],
            relevant_locator_ids=[], tags=[],
        ),
        RetrievalBenchmarkCase(
            query="Нет", relevant_material_ids=[], relevant_locator_ids=[], tags=[],
        ),
    ])
    session.commit()

    class FakeRetriever:
        commands = []

        async def search(self, _session, command):
            self.commands.append(command)
            return RetrievalSearchRead(
                query=command.query, strategy=SearchStrategy.HYBRID,
                index_id=index.id, degraded=False, degradation_reasons=[],
                results=[_hit(material.id)] if command.query == "Есть" else [],
            )

    retriever = FakeRetriever()
    run = await run_benchmark(session, index.id, retriever)

    assert len(retriever.commands) == 2
    assert all(command.scope == RetrievalScope.LIBRARY for command in retriever.commands)
    assert all(not command.material_ids for command in retriever.commands)
    assert run.metrics["recall_at_10"] == 1
    assert run.metrics["negative_false_positive"] == 0


@pytest.mark.asyncio
async def test_benchmark_requires_cases(session: Session) -> None:
    index = _index(session)
    with pytest.raises(ProjectDomainError) as error:
        await run_benchmark(session, index.id)
    assert error.value.code == "retrieval_benchmark_empty"
