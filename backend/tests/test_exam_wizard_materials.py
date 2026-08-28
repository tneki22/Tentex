import pytest
from conftest import add_page_with_fragments, make_exam_project, make_material
from sqlalchemy.orm import Session

from app.materials import service
from app.materials.schemas import ExamCompositeDraftImportWrite, ExamProgramDraftImportWrite
from app.models import (
    ExamFormat,
    GoalPassport,
    ProjectMaterial,
    ProjectStatus,
    SourceRole,
    WizardDraft,
)
from app.projects import service as projects_service
from app.projects.errors import ProjectConflictError
from app.projects.schemas import ExamImportWrite


def make_ready_exam_draft(session: Session, text: str, *, expected_item_count: int | None = None):
    project = make_exam_project(session, status=ProjectStatus.DRAFT)
    draft = WizardDraft(project_id=project.id, revision=2, state={"exam_format": "questions"})
    passport = GoalPassport(
        project_id=project.id,
        exam_format=ExamFormat.QUESTIONS,
        expected_item_count=expected_item_count,
    )
    material = make_material(session, "e1")
    add_page_with_fragments(session, material, page_number=1, revision=1, fragments=[text])
    link = ProjectMaterial(
        project_id=project.id,
        material_id=material.id,
        source_role=SourceRole.REFERENCE,
        priority=0,
        affects_program=True,
        purposes=["exam_structure"],
    )
    session.add_all([draft, passport, link])
    session.commit()
    return project, draft, material


def test_ready_exam_material_replaces_draft_program(session: Session) -> None:
    project, draft, material = make_ready_exam_draft(
        session, "1. Индексы\n2. Транзакции"
    )

    result = service.import_exam_draft_from_material(
        session,
        project.id,
        material.id,
        ExamProgramDraftImportWrite(
            expected_draft_revision=draft.revision,
            expected_program_revision=project.program_revision,
        ),
    )

    assert [node.title for node in result.program.nodes] == ["Индексы", "Транзакции"]
    assert {node.origin_material_id for node in result.program.nodes} == {material.id}
    assert result.draft_revision == 3


def test_text_exam_import_replaces_draft_program(session: Session) -> None:
    project, draft, _material = make_ready_exam_draft(session, "1. Индексы\n2. Транзакции")

    result = projects_service.import_exam_program(
        session,
        project.id,
        ExamImportWrite(
            expected_revision=draft.revision,
            expected_program_revision=project.program_revision,
            exam_format=ExamFormat.QUESTIONS,
            raw_text="1. Индексы\n2. Транзакции",
        ),
    )

    assert [node.title for node in result.program.nodes] == ["Индексы", "Транзакции"]
    assert result.revision == 3


def test_exam_material_import_rejects_stale_draft_revision(session: Session) -> None:
    project, _draft, material = make_ready_exam_draft(session, "1. Индексы")

    with pytest.raises(ProjectConflictError) as caught:
        service.import_exam_draft_from_material(
            session,
            project.id,
            material.id,
            ExamProgramDraftImportWrite(
                expected_draft_revision=1,
                expected_program_revision=project.program_revision,
            ),
        )

    assert caught.value.code == "stale_draft_revision"


def _slotted_material(
    session: Session, project, seed: str, slot: str, text: str
) -> ProjectMaterial:
    material = make_material(session, seed)
    add_page_with_fragments(session, material, page_number=1, revision=1, fragments=[text])
    link = ProjectMaterial(
        project_id=project.id,
        material_id=material.id,
        source_role=SourceRole.REFERENCE,
        priority=0,
        affects_program=True,
        purposes=["exam_structure"],
        exam_slot=slot,
    )
    session.add(link)
    session.commit()
    return link


def test_composite_import_orders_questions_before_tasks_and_keeps_subpoints(
    session: Session,
) -> None:
    project = make_exam_project(session, status=ProjectStatus.DRAFT)
    draft = WizardDraft(project_id=project.id, revision=1, state={})
    session.add(draft)
    session.commit()
    question_link = _slotted_material(
        session,
        project,
        "a1",
        "question_list",
        "1. Нормальные формы\n1.1. Первая нормальная форма\n2. Транзакции",
    )
    task_link = _slotted_material(
        session, project, "b1", "task_list", "1. Построить график\n2. Решить уравнение"
    )

    result = service.import_composite_exam_draft(
        session,
        project.id,
        ExamCompositeDraftImportWrite(
            expected_draft_revision=draft.revision,
            expected_program_revision=project.program_revision,
            question_material_id=question_link.material_id,
            task_material_id=task_link.material_id,
        ),
    )

    titles_in_order = [node.title for node in result.change.program.nodes]
    assert titles_in_order == [
        "Нормальные формы",
        "Транзакции",
        "Построить график",
        "Решить уравнение",
        "Первая нормальная форма",
    ]
    assert result.counts == {"questions": 2, "tasks": 2, "subpoints": 1}
    assert result.change.draft_revision == 2
    subpoint = next(node for node in result.change.program.nodes if node.exam_kind == "question"
                     and node.title == "Первая нормальная форма")
    parent = next(node for node in result.change.program.nodes if node.title == "Нормальные формы")
    assert subpoint.parent_id == parent.id


def test_composite_import_dedupes_top_level_duplicates_when_requested(session: Session) -> None:
    project = make_exam_project(session, status=ProjectStatus.DRAFT)
    draft = WizardDraft(project_id=project.id, revision=1, state={})
    session.add(draft)
    session.commit()
    question_link = _slotted_material(
        session, project, "a2", "question_list", "1. Индексы\n2. Индексы\n3. Транзакции"
    )

    first = service.import_composite_exam_draft(
        session,
        project.id,
        ExamCompositeDraftImportWrite(
            expected_draft_revision=draft.revision,
            expected_program_revision=project.program_revision,
            question_material_id=question_link.material_id,
        ),
    )
    first_titles = [node.title for node in first.change.program.nodes]
    assert first_titles == ["Индексы", "Индексы", "Транзакции"]
    assert any("повторяется" in warning for warning in first.warnings)

    deduped = service.import_composite_exam_draft(
        session,
        project.id,
        ExamCompositeDraftImportWrite(
            expected_draft_revision=first.change.draft_revision,
            expected_program_revision=first.change.program.revision,
            question_material_id=question_link.material_id,
            dedupe_duplicates=True,
        ),
    )
    assert [node.title for node in deduped.change.program.nodes] == ["Индексы", "Транзакции"]
    assert deduped.counts == {"questions": 2, "tasks": 0, "subpoints": 0}


def test_exam_material_uses_expected_count_to_ignore_title_and_trailing_reset(
    session: Session,
) -> None:
    project, _draft, material = make_ready_exam_draft(
        session,
        "Вопросы для подготовки\n1. Первый\n2. Второй\n3. Третий\n1. Приложение",
        expected_item_count=3,
    )

    preview = service.preview_exam_program(session, project.id, material.id)

    assert preview.counts["questions"] == 3
    assert [node.title for node in preview.nodes] == ["Первый", "Второй", "Третий"]
    assert preview.warnings == [
        "Перед списком пропущено строк: 1",
        "После списка пропущено строк: 1",
    ]
