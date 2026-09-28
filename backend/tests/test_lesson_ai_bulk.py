"""Массовая сборка с ИИ: порядок программы, «уже известно» по цепочке, продолжение."""

import asyncio
from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy.orm import Session

from app.ai.gateway import ModelGateway
from app.ai.jobs import process_ai_job
from app.ai.provider import FakeTransport, ProviderError
from app.background import registry
from app.lessons import ai_build, ai_bulk
from app.lessons.ai_schemas import LessonAiBulkOrder, LessonAiBulkWrite, LessonAiResumeWrite
from app.models import BackgroundJob, BackgroundJobState, Lesson, LessonBasis
from tests.test_lesson_ai_build import _completion, _draft, _note, _source
from tests.test_lessons import Book, add_node, make_lessons_project


@pytest.fixture
def project(session: Session, ai_config: str):
    del ai_config
    return make_lessons_project(session)


def _topics(session, project):
    book = Book(session, project, "Олифер")
    book.page(10, "h:2.3 Ethernet", "p:Станции делят общую среду.")
    book.page(12, "h:2.4 Коммутаторы", "p:Коммутатор разделяет домены коллизий.")
    first = add_node(session, project, "Ethernet", 0, ranges=[(book, 10, 10)])
    second = add_node(session, project, "Коммутаторы", 1, ranges=[(book, 12, 12)])
    bare = add_node(session, project, "История сетей", 2)
    return first, second, bare


def _process(session, job_id, *completions):
    job = session.get(BackgroundJob, job_id)
    transport = FakeTransport(completions=list(completions))
    process_ai_job(session, job, ModelGateway(session, transport, retry_backoff=()))
    session.expire_all()
    return session.get(BackgroundJob, job_id), transport


def test_bulk_builds_topics_in_program_order_with_known_concepts(session, project):
    first, second, bare = _topics(session, project)

    estimate = asyncio.run(ai_bulk.preflight(session, project.id, LessonAiBulkOrder(
        program_node_ids=[second.id, bare.id, first.id], basis=LessonBasis.SOURCES,
    )))
    assert [item.title for item in estimate.topics] == ["Ethernet", "Коммутаторы",
                                                        "История сетей"]
    assert [item.sources_available for item in estimate.topics] == [True, True, False]
    assert estimate.calls == 2 and estimate.cost_usd > 0

    started = asyncio.run(ai_bulk.start(session, project.id, LessonAiBulkWrite(
        program_node_ids=[second.id, bare.id, first.id], basis=LessonBasis.SOURCES,
    )))
    job, transport = _process(
        session, started.job_id,
        _completion(_draft(_note("Станции делят среду [S1]."), _source("S1"),
                           concepts=("общая среда",))),
        _completion(_draft(_note("Коммутатор делит домены [S1]."), _source("S1"),
                           concepts=("коммутатор",))),
    )

    assert job.state == BackgroundJobState.COMPLETED, job.error
    result = job.checkpoint["result"]
    assert [item["topic_title"] for item in result["lessons"]] == [
        "Ethernet", "Коммутаторы", "История сетей",
    ]
    assert result["lessons"][2]["lesson_id"] is None and result["lessons"][2]["skipped"]
    # Вторая тема видит понятие урока первой в «уже известно».
    second_prompt = transport.complete_requests[1]["messages"][-1]["content"]
    assert "общая среда" in second_prompt
    lessons = [session.get(Lesson, UUID(item["lesson_id"])) for item in result["lessons"][:2]]
    assert [lesson.build_meta["concepts"] for lesson in lessons] == [["общая среда"],
                                                                     ["коммутатор"]]
    assert registry.get_job(session, job.id).subject == "Уроки с ИИ · 3 тем"


def test_bulk_resumes_without_rebuilding_done_topics(session, project):
    first, second, _ = _topics(session, project)
    started = asyncio.run(ai_bulk.start(session, project.id, LessonAiBulkWrite(
        program_node_ids=[first.id, second.id],
    )))
    job, _ = _process(
        session, started.job_id,
        _completion(_draft(_note("Первая [S1]."), _source("S1"))),
        ProviderError("ai_provider_unavailable", "провайдер молчит"),
    )
    assert job.state == BackgroundJobState.FAILED
    assert list(job.checkpoint["topics"]) == [str(first.id)]

    # Упавший вызов предел засчитывает резервом — продолжение идёт с новым пределом.
    ai_build.resume(session, project.id, job.id, LessonAiResumeWrite(max_cost_usd=Decimal("0.1")))
    job, transport = _process(session, job.id,
                              _completion(_draft(_note("Вторая [S1]."), _source("S1"))))

    assert job.state == BackgroundJobState.COMPLETED, job.error
    assert transport.complete_calls == 1
    assert len(session.query(Lesson).all()) == 2
