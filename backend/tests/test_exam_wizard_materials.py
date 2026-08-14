import pytest
from conftest import add_page_with_fragments, make_exam_project, make_material
from sqlalchemy.orm import Session

from app.materials import service
from app.materials.schemas import ExamProgramDraftImportWrite
from app.models import (
    ExamFormat,
    GoalPassport,
    ProjectMaterial,
    ProjectStatus,
    SourceRole,
    WizardDraft,
)
from app.projects.errors import ProjectConflictError


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
