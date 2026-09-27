"""Полный обзор «По всем источникам»: область с привязками, снимок запуска, проверка ссылок."""

from __future__ import annotations

import json
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from conftest import (
    add_page_with_fragments,
    link_material,
    make_exam_project,
    make_material,
    make_topic_node,
)
from sqlalchemy.orm import Session

from app.ai.provider import FakeTransport, ProviderCompletion, ProviderUsage
from app.exam import chat as chat_service
from app.models import (
    BackgroundJob,
    BackgroundJobState,
    Binding,
    BindingMechanism,
    BindingStatus,
    ChatMessage,
    MaterialBlock,
    RetrievalExhaustiveRun,
)
from app.retrieval.exhaustive import process_exhaustive_job, start_run
from app.retrieval.schemas import ExhaustiveRunWrite, RetrievalScope

OUTSIDE = "Индексы ускоряют выборку строк по ключу."
BOUND = "Вторая нормальная форма запрещает частичные зависимости от ключа."


def _completion(payload: dict) -> ProviderCompletion:
    return ProviderCompletion(
        content=json.dumps(payload, ensure_ascii=False),
        actual_model_id="test/structured-model",
        usage=ProviderUsage(input_tokens=100, output_tokens=20, cost_usd=Decimal("0.001")),
    )


def _finding(*ids: str) -> ProviderCompletion:
    return _completion({"findings": [{"statement": "2НФ", "source_ids": list(ids)}]})


def _answer(text: str) -> ProviderCompletion:
    return _completion({"answer": text, "limitations": []})


@pytest.fixture
def topic_run(session: Session, ai_config: str, monkeypatch: pytest.MonkeyPatch):
    """Материал из трёх блоков, к теме привязан только средний."""
    del ai_config
    project = make_exam_project(session)
    node = make_topic_node(session, project, title="Нормальные формы")
    material = make_material(session, uuid4().hex[:12])
    link_material(session, project, material)
    blocks: list[tuple[UUID, list[UUID]]] = []
    for page, text in enumerate([OUTSIDE, BOUND, OUTSIDE], start=1):
        added = add_page_with_fragments(
            session, material, page_number=page, revision=1, fragments=[text],
            block_title=f"Глава {page}",
        )
        session.get(MaterialBlock, added.block_id).sort_order = page
        session.commit()
        blocks.append((added.block_id, added.fragment_ids))
    session.add(
        Binding(
            project_id=project.id, program_node_id=node.id, fragment_id=blocks[1][1][0],
            material_id=material.id, block_id=blocks[1][0],
            status=BindingStatus.MANUAL, mechanism=BindingMechanism.MANUAL,
        )
    )
    session.commit()
    chat = chat_service.create_session(session, project.id, node.id)
    fake = FakeTransport()
    monkeypatch.setattr("app.ai.gateway.production_transport", lambda db, modality: fake)

    def start(policy: str = "sources_only") -> RetrievalExhaustiveRun:
        read = start_run(
            session, project.id, chat.id,
            ExhaustiveRunWrite(
                query="Что такое 2НФ?", scope=RetrievalScope.LINKED_TOPIC,
                node_id=node.id, knowledge_policy=policy, confirmed=True,
            ),
        )
        return session.get(RetrievalExhaustiveRun, read.id)

    return start, fake, blocks


def _process(session: Session, run: RetrievalExhaustiveRun) -> BackgroundJob:
    process_exhaustive_job(session, session.get(BackgroundJob, run.job_id))
    session.expire_all()
    return session.get(BackgroundJob, run.job_id)


def test_linked_topic_reads_only_bound_blocks_and_snapshots_the_run(
    session: Session, topic_run
) -> None:
    """Раньше обзор резал все блоки материала, и ограничение привязками терялось."""
    start, fake, blocks = topic_run
    fake.completions.extend([_finding("S1"), _answer("Итог [S1]")])

    run = start("allow_model")
    assert run.settings == {
        "block_ids": [str(blocks[1][0])],
        "model_override": None,
        "parameters": {},
        "knowledge_policy": "allow_model",
    }
    job = _process(session, run)

    assert job.state == BackgroundJobState.COMPLETED, job.error
    mapped = fake.complete_requests[0]["messages"][-1]["content"]
    assert BOUND in mapped and OUTSIDE not in mapped
    reduce_system = fake.complete_requests[1]["messages"][0]["content"]
    assert "Дополнение модели" in reduce_system
    final = session.get(ChatMessage, session.get(RetrievalExhaustiveRun, run.id).final_message_id)
    assert [entry["id"] for entry in final.context_snapshot["retrieval_sources"]] == ["S1"]


def test_reduce_with_unknown_citation_is_asked_once_more(session: Session, topic_run) -> None:
    start, fake, _ = topic_run
    fake.completions.extend([_finding("S1"), _answer("Итог [S1, S7]"), _answer("Итог [S1]")])

    run = start()
    job = _process(session, run)

    assert job.state == BackgroundJobState.COMPLETED, job.error
    retry = fake.complete_requests[2]["messages"][-1]["content"]
    assert "S7" in retry
    final = session.get(ChatMessage, session.get(RetrievalExhaustiveRun, run.id).final_message_id)
    assert final.text == "Итог [S1]"


def test_reduce_without_citations_twice_fails_the_run(session: Session, topic_run) -> None:
    start, fake, _ = topic_run
    fake.completions.extend([_finding("S1"), _answer("Итог"), _answer("Итог снова")])

    job = _process(session, start())

    assert job.state == BackgroundJobState.FAILED
    assert "цитат" in (job.error or "")
