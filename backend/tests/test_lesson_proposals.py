"""«Дополнить урок»: проверка операций, частичное применение, конфликт и одна отмена."""

import asyncio
import json
from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.gateway import ModelGateway
from app.ai.jobs import process_ai_job
from app.ai.provider import FakeTransport, ProviderCompletion, ProviderUsage
from app.background import registry
from app.lessons import ai_enrich, editing, proposals, service
from app.lessons.ai_schemas import LessonEnrichWrite, LessonProposalApplyWrite
from app.lessons.schemas import LessonBlockWrite, LessonNoteWrite, LessonQuickWrite
from app.models import (
    BackgroundJob,
    BackgroundJobState,
    LessonBasis,
    LessonBlockKind,
    LessonBlockOrigin,
    ProjectActionLog,
)
from app.projects.errors import ProjectConflictError
from app.projects.program import undo_last_project_action
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


def _op(op, block=None, **fields):
    base = {"op": op, "block": block, "cut_after": None, "variant": None, "body_md": None,
            "collapsed": None, "text": None, "reason": "нужно читателю"}
    return {**base, **fields}


def _lesson(session, project):
    """Быстрый урок из одного куска в три абзаца и ручное пояснение за ним."""
    book = Book(session, project, "Олифер")
    book.page(10, "h:2.3 Ethernet", "p:Станции делят среду.", "p:Кадр идёт всем станциям.",
              "p:Коллизия — одновременная передача.")
    node = add_node(session, project, "Ethernet", 0, ranges=[(book, 10, 10)])
    result = service.create_quick_lesson(
        session, project.id, LessonQuickWrite(program_node_id=node.id)
    )
    lesson = result.lesson
    result = editing.edit_lesson_blocks(session, project.id, lesson.id, LessonBlockWrite(
        expected_revision=lesson.revision, operation="add_note", variant="explanation",
    ))
    note = result.lesson.blocks[-1]
    result = editing.update_lesson_note(session, project.id, lesson.id, note.id, LessonNoteWrite(
        expected_revision=result.lesson.revision, body_md="Моё пояснение",
    ))
    return result.lesson


def _enrich(session, project, lesson, payload, **order):
    started = asyncio.run(ai_enrich.start(session, project.id, lesson.id, LessonEnrichWrite(
        expected_revision=lesson.revision, **order,
    )))
    job = session.get(BackgroundJob, started.job_id)
    process_ai_job(session, job, ModelGateway(session, FakeTransport(completions=[
        _reply(payload),
    ]), retry_backoff=()))
    session.expire_all()
    return session.get(BackgroundJob, started.job_id)


def _undo(session, project):
    sequence = session.scalar(
        select(ProjectActionLog.sequence).where(ProjectActionLog.project_id == project.id)
        .order_by(ProjectActionLog.sequence.desc()).limit(1)
    )
    undo_last_project_action(session, project.id, sequence)


def test_proposal_keeps_valid_ops_and_names_the_rest(session, project):
    lesson = _lesson(session, project)
    # B1 — заголовок быстрого урока, B2 — кусок S1, B3 — ручное пояснение.
    job = _enrich(session, project, lesson, {"summary": "добавил пояснения", "operations": [
        _op("insert_note", "B2", cut_after="¶2", variant="example", body_md="Пример [S1] [S9]"),
        _op("rewrite_note", "B3", body_md="Проще [S1]"),
        _op("rewrite_note", "B2", body_md="кусок переписать нельзя"),
        _op("set_collapsed", "B2", collapsed=True),
        _op("insert_note", "B7", body_md="куда-то"),
        _op("rename_lesson", text="Ethernet: общая среда"),
    ]})

    assert job.state == BackgroundJobState.COMPLETED, job.error
    result = job.checkpoint["result"]
    assert [op["op"] for op in result["ops"]] == [
        "insert_note", "rewrite_note", "set_collapsed", "rename_lesson",
    ]
    insert = result["ops"][0]
    assert insert["body_md"] == "Пример [S1]" and insert["supports"] == ["S1"]
    assert insert["after_fragment_id"] is not None
    assert len(result["dropped"]) == 3
    assert registry.get_job(session, job.id).needs_review


def test_apply_part_of_proposal_is_one_undo(session, project):
    lesson = _lesson(session, project)
    job = _enrich(session, project, lesson, {"summary": "", "operations": [
        _op("insert_note", "B2", cut_after="¶2", variant="example", body_md="Пример [S1]"),
        _op("rewrite_note", "B3", body_md="Проще [S1]"),
        _op("set_collapsed", "B2", collapsed=True),
        _op("rename_lesson", text="Ethernet: общая среда"),
    ]})
    ops = job.checkpoint["result"]["ops"]
    chosen = [ops[0]["id"], ops[1]["id"], ops[3]["id"]]

    applied = proposals.apply_proposal(
        session, project.id, lesson.id, job.id,
        LessonProposalApplyWrite(op_ids=chosen, expected_revision=lesson.revision),
    )

    assert applied.conflicts == []
    blocks = applied.lesson.blocks
    kinds = [block.kind for block in blocks]
    assert kinds == [LessonBlockKind.NOTE, LessonBlockKind.SOURCE, LessonBlockKind.NOTE,
                     LessonBlockKind.SOURCE, LessonBlockKind.NOTE]
    inserted, rewritten = blocks[2], blocks[4]
    assert inserted.origin == LessonBlockOrigin.MODEL and inserted.variant == "example"
    assert [ref.citation_label for ref in inserted.refs] == ["S1"]
    assert rewritten.body_md == "Проще [S1]" and rewritten.origin == LessonBlockOrigin.MIXED
    assert applied.lesson.title == "Ethernet: общая среда"
    assert not blocks[1].collapsed
    session.expire_all()
    stored = session.get(BackgroundJob, job.id)
    assert stored.reviewed_at is not None and stored.checkpoint["applied_op_ids"] == chosen

    _undo(session, project)

    session.expire_all()
    restored = service.get_lesson(session, project.id, lesson.id)
    assert [block.kind for block in restored.blocks] == [
        LessonBlockKind.NOTE, LessonBlockKind.SOURCE, LessonBlockKind.NOTE,
    ]
    assert restored.blocks[2].body_md == "Моё пояснение"
    assert restored.blocks[2].origin == LessonBlockOrigin.MANUAL
    assert restored.title == "Ethernet"


def test_vanished_block_becomes_conflict(session, project):
    lesson = _lesson(session, project)
    job = _enrich(session, project, lesson, {"summary": "", "operations": [
        _op("rewrite_note", "B3", body_md="Проще"),
        _op("set_collapsed", "B2", collapsed=True),
    ]})
    ops = job.checkpoint["result"]["ops"]
    current = service.get_lesson(session, project.id, lesson.id)
    changed = editing.edit_lesson_blocks(session, project.id, lesson.id, LessonBlockWrite(
        expected_revision=current.revision, operation="delete", block_id=current.blocks[2].id,
    ))

    applied = proposals.apply_proposal(
        session, project.id, lesson.id, job.id,
        LessonProposalApplyWrite(op_ids=[op["id"] for op in ops],
                                 expected_revision=changed.lesson.revision),
    )

    assert applied.conflicts == [ops[0]["id"]]
    assert applied.lesson.blocks[1].collapsed


def test_stale_revision_is_refused(session, project):
    lesson = _lesson(session, project)
    job = _enrich(session, project, lesson, {"summary": "", "operations": [
        _op("set_goal", text="Понять общую среду"),
    ]})

    with pytest.raises(ProjectConflictError) as error:
        proposals.apply_proposal(
            session, project.id, lesson.id, job.id,
            LessonProposalApplyWrite(op_ids=[job.checkpoint["result"]["ops"][0]["id"]],
                                     expected_revision=lesson.revision - 1),
        )

    assert error.value.code == "stale_lesson_revision"


def test_focus_block_limits_context_and_model_only_strips_citations(session, project):
    lesson = _lesson(session, project)
    note_id = service.get_lesson(session, project.id, lesson.id).blocks[2].id

    job = _enrich(session, project, lesson, {"summary": "", "operations": [
        _op("rewrite_note", "B3", body_md="Проще [S1]"),
    ]}, block_id=note_id, basis=LessonBasis.MODEL_ONLY)

    op = job.checkpoint["result"]["ops"][0]
    assert op["body_md"] == "Проще" and op["basis"] == "model_only"
    assert job.checkpoint["portions"] == [[0, 1, 2]]
    assert UUID(op["block_id"]) == note_id
