"""«Собрать урок с ИИ», уровень «Черновик»: паспорт, задача, проверка ссылок и отмена."""

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
from app.lessons import ai_build, ai_context, editing
from app.lessons.ai_schemas import LessonAiBuildWrite, LessonAiOrder
from app.lessons.schemas import LessonBlockWrite
from app.models import (
    AiRun,
    BackgroundJob,
    BackgroundJobState,
    Binding,
    BindingMechanism,
    BindingStatus,
    Conspect,
    GoalPassport,
    GoalPurpose,
    GoalRole,
    Lesson,
    LessonBasis,
    LessonBlockKind,
    LessonBlockOrigin,
    LessonRefRole,
    ProgramNode,
    ProjectActionLog,
    ProjectMaterial,
    StartingLevel,
    StudyFormat,
    TargetOutcome,
)
from app.projects.errors import ProjectDomainError
from app.projects.program import undo_last_project_action
from tests.test_lessons import Book, add_node, make_lessons_project


@pytest.fixture
def project(session: Session, ai_config: str):
    del ai_config
    return make_lessons_project(session)


def _completion(payload: dict) -> ProviderCompletion:
    return ProviderCompletion(
        content=json.dumps(payload, ensure_ascii=False),
        actual_model_id="test/structured-model",
        usage=ProviderUsage(input_tokens=900, output_tokens=300, cost_usd=Decimal("0.002")),
    )


def _note(body, variant="explanation"):
    return {"kind": "note", "variant": variant, "body_md": body, "source": None,
            "collapsed": None}


def _source(label, collapsed=None):
    return {"kind": "source", "variant": None, "body_md": None, "source": label,
            "collapsed": collapsed}


def _draft(*steps, concepts=("общая среда", "коллизия")):
    return {"title": "Ethernet", "goal": "Понять, как станции делят среду",
            "concepts": list(concepts), "steps": list(steps)}


def _ethernet(session, project):
    book = Book(session, project, "Олифер")
    book.page(10, "h:2.3 Ethernet", "p:Станции делят общую среду.")
    book.page(11, "h:Коллизия", "p:Коллизия — одновременная передача двух станций.")
    node = add_node(session, project, "Ethernet", 0, ranges=[(book, 10, 11)])
    return book, node


def _build(session, project, node, payload, **order):
    started = asyncio.run(ai_build.start(
        session, project.id, LessonAiBuildWrite(program_node_id=node.id, **order)
    ))
    job = session.get(BackgroundJob, started.job_id)
    gateway = ModelGateway(session, FakeTransport(completions=[_completion(payload)]))
    process_ai_job(session, job, gateway)
    session.expire_all()
    return session.get(BackgroundJob, started.job_id)


def _undo(session, project):
    sequence = session.scalar(
        select(ProjectActionLog.sequence)
        .where(ProjectActionLog.project_id == project.id)
        .order_by(ProjectActionLog.sequence.desc())
        .limit(1)
    )
    undo_last_project_action(session, project.id, sequence)


def _blocks(session, lesson_id):
    lesson = session.get(Lesson, lesson_id)
    from app.lessons.service import _lesson_read

    return lesson, _lesson_read(session, lesson).blocks


def test_brief_carries_every_filled_field(session, project):
    book, node = _ethernet(session, project)
    section = add_node(session, project, "Канальный уровень", 0)
    node.parent_id = section.id
    node.section_purpose = "Как кадры доходят до соседа"
    node.goal_role = GoalRole.PREREQUISITE
    node.target_level = TargetOutcome.APPLICATION
    node.origin_note = "Без Ethernet не понять коммутацию"
    node.material_search_queries = ["CSMA/CD Олифер"]
    node.material_kind = "учебник"
    add_node(session, project, "Формат кадра", 0, parent=node)
    session.add(GoalPassport(
        project_id=project.id, subject="Компьютерные сети",
        starting_level=StartingLevel.BEGINNER, current_knowledge="знаю модель OSI",
        target_outcome=TargetOutcome.UNDERSTANDING, goal="сдать зачёт по сетям",
        success_criterion="объяснить CSMA/CD", purpose=GoalPurpose.EXAM,
        study_format=StudyFormat.THEORY_AND_PRACTICE, important="примеры из жизни",
        excluded="история протокола", session_minutes=25,
    ))
    session.get(ProjectMaterial, (project.id, book.material.id)).instruction = (
        "отсюда теорию, из методички — примеры"
    )
    session.add(Conspect(project_id=project.id, program_node_id=node.id,
                         content_markdown="Моя заметка про преамбулу"))
    session.commit()

    preflight = asyncio.run(ai_build.preflight(session, project.id, LessonAiOrder(
        program_node_id=node.id, wishes="больше примеров из жизни",
    )))

    text = preflight.brief_text
    for value in (
        "Учебник", "изучение по учебнику", "Компьютерные сети", "начинает с нуля",
        "знаю модель OSI", "понимать", "сдать зачёт по сетям", "объяснить CSMA/CD", "экзамен",
        "теория и задачи", "примеры из жизни", "история протокола", "Ethernet", "Канальный уровень",
        "Как кадры доходят до соседа", "предпосылка", "уверенно отвечать",
        "Без Ethernet не понять коммутацию", "CSMA/CD Олифер", "учебник", "Формат кадра",
        "Олифер", "основной", "отсюда теорию, из методички — примеры", "стр. 10–11",
        "есть диапазон темы по оглавлению", "Моя заметка про преамбулу", "Объяснение с нуля",
        "Черновик", "материалы проекта и знания модели", "≈25 мин", "больше примеров из жизни",
    ):
        assert value in text, value
    assert preflight.use_conspect and preflight.default_minutes == 25


def test_empty_passport_fields_are_named_not_invented(session, project):
    _, node = _ethernet(session, project)

    text = asyncio.run(ai_build.preflight(
        session, project.id, LessonAiOrder(program_node_id=node.id)
    )).brief_text

    assert "- Цель: не указано" in text
    assert "- Стартовый уровень: не указано" in text
    assert "## Мой конспект темы\n- не передаётся" in text


def test_preflight_estimates_draft_and_lists_candidates(session, project):
    _, node = _ethernet(session, project)

    result = asyncio.run(ai_build.preflight(
        session, project.id, LessonAiOrder(program_node_id=node.id)
    ))

    assert result.models_available and result.model_id == "test/structured-model"
    assert result.candidates == 2 and result.sources_available
    draft, standard, detailed = result.levels
    assert draft.available and draft.calls == 1 and draft.cost_usd > 0
    assert not standard.available and standard.calls == 8
    assert detailed.calls > standard.calls
    assert [item.selected for item in result.materials] == [True]


def test_draft_becomes_lesson_with_checked_citations(session, project):
    book, node = _ethernet(session, project)
    payload = _draft(
        _note("Ethernet", variant="heading"),
        _note("Станции делят одну среду [S1]. Об этом же пишет [S7]."),
        _source("S1"),
        _note("Коллизия возникает, когда две станции передают сразу [S2, S1]."),
        _source("S2", collapsed=False),
        _note("Итог: без правил доступа среда бы не работала."),
        _source("S9"),
    )

    job = _build(session, project, node, payload)

    assert job.state == BackgroundJobState.COMPLETED, job.error
    result = job.checkpoint["result"]
    lesson, blocks = _blocks(session, UUID(result["lesson_id"]))
    kinds = [(block.kind, block.variant) for block in blocks]
    assert [kind for kind, _ in kinds] == [
        LessonBlockKind.NOTE, LessonBlockKind.NOTE, LessonBlockKind.SOURCE,
        LessonBlockKind.NOTE, LessonBlockKind.SOURCE, LessonBlockKind.NOTE,
    ]
    heading, first, piece, second, second_piece, summary = blocks
    assert heading.body_md == "## Ethernet" and heading.basis is None
    # Неизвестная [S7] убрана вместе с пробелом, известные — сквозные номера урока.
    assert first.body_md == "Станции делят одну среду [S1]. Об этом же пишет."
    assert second.body_md == "Коллизия возникает, когда две станции передают сразу [S2, S1]."
    assert first.basis == LessonBasis.SOURCES_AND_MODEL
    assert summary.basis == LessonBasis.MODEL_ONLY
    assert [(ref.role, ref.citation_label) for ref in second.refs] == [
        (LessonRefRole.SUPPORT, "S1"), (LessonRefRole.SUPPORT, "S2"),
    ]
    assert piece.origin == LessonBlockOrigin.MODEL and piece.collapsed
    assert not second_piece.collapsed
    # Кусок начинается с края страницы — граница хранится краем, а не фрагментом.
    assert (piece.refs[0].page_from, piece.refs[0].page_to) == (10, 10)
    assert piece.refs[0].material_id == book.material.id
    assert any("S9" in reason for reason in result["dropped"])
    assert any("S7" in reason for reason in result["dropped"])
    meta = lesson.build_meta
    assert meta["template"] == "explain" and meta["concepts"] == ["общая среда", "коллизия"]
    bindings = session.scalars(select(Binding).where(Binding.program_node_id == node.id)).all()
    assert bindings and all(
        (item.status, item.mechanism) == (BindingStatus.MACHINE, BindingMechanism.LESSON)
        for item in bindings
    )
    run = session.scalars(select(AiRun).where(AiRun.job_id == job.id)).one()
    assert run.context_manifest[0] == {"kind": "stage", "stage": "draft"}
    assert run.role == "lesson_builder"


def test_undo_removes_built_lesson_and_its_bindings(session, project):
    _, node = _ethernet(session, project)
    job = _build(session, project, node, _draft(_note("Текст [S1]"), _source("S1")))
    lesson_id = UUID(job.checkpoint["result"]["lesson_id"])

    _undo(session, project)

    session.expire_all()
    assert session.get(Lesson, lesson_id) is None
    assert not session.scalars(select(Binding).where(Binding.program_node_id == node.id)).all()


def test_model_only_lesson_for_topic_without_outline(session, project):
    node = add_node(session, project, "Трансформеры", 0)
    payload = _draft(_note("Внимание взвешивает слова [S1]."), _source("S1"))

    job = _build(session, project, node, payload, basis=LessonBasis.MODEL_ONLY)

    assert job.state == BackgroundJobState.COMPLETED, job.error
    _, blocks = _blocks(session, UUID(job.checkpoint["result"]["lesson_id"]))
    assert [block.kind for block in blocks] == [LessonBlockKind.NOTE]
    assert blocks[0].body_md == "Внимание взвешивает слова."
    assert blocks[0].basis == LessonBasis.MODEL_ONLY and not blocks[0].refs


def test_sources_only_without_material_is_refused(session, project):
    node = add_node(session, project, "Трансформеры", 0)

    with pytest.raises(ProjectDomainError) as error:
        asyncio.run(ai_build.start(session, project.id, LessonAiBuildWrite(
            program_node_id=node.id, basis=LessonBasis.SOURCES,
        )))

    assert error.value.code == "lesson_ai_no_material"


def test_levels_beyond_draft_are_not_started_yet(session, project):
    _, node = _ethernet(session, project)

    with pytest.raises(ProjectDomainError) as error:
        asyncio.run(ai_build.start(session, project.id, LessonAiBuildWrite(
            program_node_id=node.id, level="standard",
        )))

    assert error.value.code == "lesson_ai_level_unavailable"


def test_cancel_during_call_creates_no_lesson(session, project):
    _, node = _ethernet(session, project)
    started = asyncio.run(ai_build.start(
        session, project.id, LessonAiBuildWrite(program_node_id=node.id)
    ))
    job = session.get(BackgroundJob, started.job_id)
    job.pause_requested = True
    session.commit()
    gateway = ModelGateway(session, FakeTransport(completions=[_completion(_draft(_note("x")))]))

    process_ai_job(session, job, gateway)

    session.expire_all()
    job = session.get(BackgroundJob, started.job_id)
    assert job.state == BackgroundJobState.CANCELLED
    assert job.checkpoint["result"]["lesson_id"] is None
    assert not session.scalars(select(Lesson)).all()


def test_collapsed_flag_is_an_undoable_block_operation(session, project):
    _, node = _ethernet(session, project)
    job = _build(session, project, node, _draft(_note("Текст [S1]"), _source("S1")))
    lesson, blocks = _blocks(session, UUID(job.checkpoint["result"]["lesson_id"]))
    piece = next(block for block in blocks if block.kind == LessonBlockKind.SOURCE)

    changed = editing.edit_lesson_blocks(session, project.id, lesson.id, LessonBlockWrite(
        expected_revision=lesson.revision, operation="set_collapsed", block_id=piece.id,
        collapsed=False,
    ))
    assert not next(b for b in changed.lesson.blocks if b.id == piece.id).collapsed

    _undo(session, project)

    session.expire_all()
    _, blocks = _blocks(session, lesson.id)
    assert next(b for b in blocks if b.id == piece.id).collapsed
    note = next(b for b in blocks if b.kind == LessonBlockKind.NOTE)
    assert [ref.citation_label for ref in note.refs] == ["S1"]


def test_known_concepts_come_from_earlier_lessons(session, project):
    book, first = _ethernet(session, project)
    _build(session, project, first, _draft(_note("x [S1]"), concepts=("MAC-адрес", "кадр")))
    second = add_node(session, project, "Коммутация", 1)
    session.commit()

    text = asyncio.run(ai_build.preflight(
        session, project.id, LessonAiOrder(program_node_id=second.id)
    )).brief_text

    assert "- Понятия из уроков предыдущих тем: MAC-адрес; кадр" in text
    assert session.get(ProgramNode, second.id) is not None
    del book


def test_brief_render_compact_keeps_reader_topic_and_order():
    brief = {
        "project": {"name": "P", "kind": "k", "subject": None},
        "reader": {key: None for key in (
            "starting_level", "current_knowledge", "target_outcome", "goal",
            "success_criterion", "purpose", "study_format", "important", "excluded")},
        "topic": {"number": "1", "title": "T", "type": "тема", "path": [],
                  "section_purpose": None, "goal_role": None, "target_level": None,
                  "origin_note": None, "search_hint": [], "material_kind": None},
        "subpoints": [], "place": {"position": 1, "total": 1, "previous": [], "next": [],
                                   "siblings": []},
        "known": {"concepts": [], "other_lessons": []}, "materials": [],
        "material_state": {"label": "l", "notes": []}, "conspect": None,
        "order": {"template": "guide", "level": "draft", "basis": "sources",
                  "minutes": None, "wishes": ""},
    }

    compact = ai_context.render_brief(brief, compact=True)

    assert "## Читатель" in compact and "## Заказ" in compact
    assert "## Материалы" not in compact and "Путеводитель по материалу" in compact
