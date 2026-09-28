"""«Обычный» и «Подробный»: план-предложение, шаги с чекпоинтом, рецензент, продолжение."""

import asyncio
import json
from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.gateway import ModelGateway
from app.ai.jobs import process_ai_job
from app.ai.provider import FakeTransport, ProviderCompletion, ProviderError, ProviderUsage
from app.background import registry
from app.lessons import ai_build
from app.lessons.ai_schemas import (
    LessonAiBuildWrite,
    LessonAiPlanWrite,
    LessonAiResumeWrite,
    LessonAiRunWrite,
)
from app.lessons.service import _lesson_read
from app.models import AiRun, BackgroundJob, BackgroundJobState, Lesson, LessonBlockKind
from tests.test_lessons import Book, add_node, make_lessons_project


@pytest.fixture
def project(session: Session, ai_config: str):
    del ai_config
    return make_lessons_project(session)


def _reply(payload: dict) -> ProviderCompletion:
    return ProviderCompletion(
        content=json.dumps(payload, ensure_ascii=False),
        actual_model_id="test/structured-model",
        usage=ProviderUsage(input_tokens=500, output_tokens=200, cost_usd=Decimal("0.001")),
    )


def _step(title, sources=(), kind="concept", introduces=()):
    return {"kind": kind, "title": title, "intent": f"объяснить {title}",
            "sources": list(sources), "collapsed": None, "introduces": list(introduces)}


def _plan(*steps):
    return {"title": "Ethernet", "goal": "Понять общую среду",
            "concepts": ["общая среда", "коллизия"], "steps": list(steps)}


def _text(body, variant="explanation"):
    return {"variant": variant, "body_md": body, "summary": f"итог: {body[:20]}"}


def _topic(session, project):
    book = Book(session, project, "Олифер")
    book.page(10, "h:2.3 Ethernet", "p:Станции делят общую среду.")
    book.page(11, "h:Коллизия", "p:Коллизия — одновременная передача.")
    return add_node(session, project, "Ethernet", 0, ranges=[(book, 10, 11)])


def _process(session, job_id, *replies):
    transport = FakeTransport(completions=list(replies))
    job = session.get(BackgroundJob, job_id)
    process_ai_job(session, job, ModelGateway(session, transport, retry_backoff=()))
    session.expire_all()
    return session.get(BackgroundJob, job_id), transport


def _plan_job(session, project, node, payload, level="standard"):
    started = asyncio.run(ai_build.start_plan(session, project.id, LessonAiRunWrite(
        program_node_id=node.id, level=level,
    )))
    job, _ = _process(session, started.job_id, _reply(payload))
    return job


def _notes(session, job):
    lesson = session.get(Lesson, UUID(job.checkpoint["result"]["lesson_id"]))
    return [
        block.body_md for block in _lesson_read(session, lesson).blocks
        if block.kind == LessonBlockKind.NOTE and block.variant != "heading"
    ]


def test_plan_is_a_proposal_waiting_for_review(session, project):
    node = _topic(session, project)

    job = _plan_job(session, project, node, _plan(
        _step("Общая среда", ["C1", "C9"], introduces=["общая среда"]),
        _step("Коллизия", ["C2"], introduces=["коллизия"]),
    ))

    assert job.state == BackgroundJobState.COMPLETED, job.error
    result = job.checkpoint["result"]
    assert [step["sources"] for step in result["steps"]] == [["C1"], ["C2"]]
    assert result["dropped"] == ["Шаг 1: опоры C9 не было в карте"]
    assert [item["label"] for item in result["candidates"]] == ["C1", "C2"]
    assert Decimal(result["step_cost_usd"]) > 0 and result["fixed_calls"] == 0
    assert registry.get_job(session, job.id).needs_review
    run = session.scalars(select(AiRun).where(AiRun.job_id == job.id)).one()
    assert run.context_manifest[0] == {"kind": "stage", "stage": "plan"}


def test_build_follows_edited_plan_and_resolves_it(session, project):
    node = _topic(session, project)
    plan_job = _plan_job(session, project, node, _plan(
        _step("Лишний шаг", kind="intro"),
        _step("Общая среда", ["C1"]),
        _step("Коллизия", ["C2"]),
    ))
    proposed = plan_job.checkpoint["result"]
    steps = proposed["steps"][1:]
    steps[1]["sources"] = ["C1"]  # ⇄: опора второго шага заменена

    started = asyncio.run(ai_build.start(session, project.id, LessonAiBuildWrite(
        program_node_id=node.id, level="standard",
        plan=LessonAiPlanWrite(job_id=plan_job.id, title=proposed["title"],
                               goal=proposed["goal"], concepts=proposed["concepts"],
                               steps=steps),
    )))
    job, transport = _process(
        session, started.job_id,
        _reply(_text("Станции делят одну среду [S1].")),
        _reply(_text("Одновременная передача — коллизия [S1] [S3].", "definition")),
    )

    assert job.state == BackgroundJobState.COMPLETED, job.error
    assert transport.complete_calls == 2
    lesson = session.get(Lesson, UUID(job.checkpoint["result"]["lesson_id"]))
    blocks = _lesson_read(session, lesson).blocks
    assert [(block.kind, block.variant) for block in blocks] == [
        (LessonBlockKind.NOTE, "heading"), (LessonBlockKind.NOTE, "explanation"),
        (LessonBlockKind.SOURCE, None),
        (LessonBlockKind.NOTE, "heading"), (LessonBlockKind.NOTE, "definition"),
    ]
    assert blocks[0].body_md == "## Общая среда"
    assert blocks[4].body_md == "Одновременная передача — коллизия [S1]."
    assert any("S3" in reason for reason in job.checkpoint["result"]["dropped"])
    assert lesson.build_meta["level"] == "standard"
    session.refresh(plan_job)
    assert plan_job.reviewed_at is not None


def test_failed_step_resumes_without_repeating_done_steps(session, project):
    node = _topic(session, project)
    started = asyncio.run(ai_build.start(session, project.id, LessonAiBuildWrite(
        program_node_id=node.id, level="standard",
    )))
    job, _ = _process(
        session, started.job_id,
        _reply(_plan(_step("Общая среда", ["C1"]), _step("Коллизия", ["C2"]))),
        _reply(_text("Первый шаг [S1].")),
        ProviderError("ai_provider_unavailable", "провайдер молчит"),
    )
    assert job.state == BackgroundJobState.FAILED
    assert list(job.checkpoint["steps"]) == ["0"]

    ai_build.resume(session, project.id, job.id, LessonAiResumeWrite())
    job, transport = _process(session, job.id, _reply(_text("Второй шаг [S1].")))

    assert job.state == BackgroundJobState.COMPLETED, job.error
    assert transport.complete_calls == 1
    assert _notes(session, job) == ["Первый шаг [S1].", "Второй шаг [S2]."]


def test_detailed_review_rewrites_flagged_step(session, project):
    node = _topic(session, project)
    started = asyncio.run(ai_build.start(session, project.id, LessonAiBuildWrite(
        program_node_id=node.id, level="detailed",
    )))
    review = {"issues": [{"step": 2, "problem": "term_before_definition",
                          "comment": "«коллизия» до определения"}]}

    job, transport = _process(
        session, started.job_id,
        _reply(_plan(_step("Общая среда", ["C1"]), _step("Коллизия", ["C2"]))),
        _reply(_text("Среда общая [S1].")),
        _reply(_text("Черновой текст [S1].")),
        _reply(review),
        _reply(_text("Исправленный текст [S1].", "definition")),
    )

    assert job.state == BackgroundJobState.COMPLETED, job.error
    assert job.checkpoint["rewritten"] == [1]
    rewrite = transport.complete_requests[-1]["messages"][-1]["content"]
    assert "термин не объяснён до использования" in rewrite
    assert _notes(session, job) == ["Среда общая [S1].", "Исправленный текст [S2]."]
    stages = [run.context_manifest[0]["stage"] for run in session.scalars(
        select(AiRun).where(AiRun.job_id == job.id).order_by(AiRun.created_at))]
    assert stages == ["plan", "step", "step", "review", "rewrite"]


def test_cancel_between_steps_creates_no_lesson(session, project):
    node = _topic(session, project)
    started = asyncio.run(ai_build.start(session, project.id, LessonAiBuildWrite(
        program_node_id=node.id, level="standard",
    )))
    job = session.get(BackgroundJob, started.job_id)
    job.pause_requested = True
    session.commit()

    job, _ = _process(session, started.job_id, _reply(_plan(_step("Общая среда", ["C1"]))))

    assert job.state == BackgroundJobState.CANCELLED
    assert not session.scalars(select(Lesson)).all()
