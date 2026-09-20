from uuid import UUID

import pytest
from conftest import link_material, make_material
from sqlalchemy.orm import Session

from app.models import (
    GoalPurpose,
    GoalScope,
    Project,
    StartingLevel,
    TargetOutcome,
    TemplateKey,
)
from app.projects import service
from app.projects.errors import ProjectConflictError
from app.projects.schemas import (
    GoalPassportWrite,
    ProjectDraftWrite,
    WizardDraftCreate,
    WizardDraftWrite,
)


def _save_draft(
    session: Session, template_key: TemplateKey, passport: GoalPassportWrite
) -> tuple[UUID, int]:
    draft = service.create_wizard_draft(session, WizardDraftCreate(template_key=template_key))
    saved = service.save_wizard_draft(
        session,
        draft.project.id,
        WizardDraftWrite(
            expected_revision=draft.draft.revision,
            current_step=5,
            max_completed_step=5,
            schema_version=1,
            project=ProjectDraftWrite(name="Проверка активации"),
            goal_passport=passport,
            state={},
        ),
    )
    return draft.project.id, saved.draft.revision


def _passport(**changes: object) -> GoalPassportWrite:
    values: dict[str, object] = {
        "subject": "Компьютерные сети",
        "purpose": GoalPurpose.INTEREST,
        "scope": GoalScope.GOAL,
        "starting_level": StartingLevel.FAMILIAR,
        "target_outcome": TargetOutcome.UNDERSTANDING,
        "goal": "Понять коммутацию трафика",
    }
    values.update(changes)
    return GoalPassportWrite(**values)


def test_textbook_activation_does_not_require_absent_study_format(session: Session) -> None:
    project_id, revision = _save_draft(session, TemplateKey.TEXTBOOK, _passport())

    active = service.activate_wizard_draft(session, project_id, revision)

    assert active.project.status.value == "active"
    assert active.goal_passport is not None
    assert active.goal_passport.study_format is None


def test_exam_activation_still_requires_study_format(session: Session) -> None:
    project_id, revision = _save_draft(session, TemplateKey.EXAM, _passport())

    with pytest.raises(ProjectConflictError, match="заполните паспорт цели"):
        service.activate_wizard_draft(session, project_id, revision)


def test_goal_scope_requires_a_goal_before_activation(session: Session) -> None:
    project_id, revision = _save_draft(
        session, TemplateKey.TEXTBOOK, _passport(goal=None)
    )

    with pytest.raises(ProjectConflictError, match="заполните паспорт цели"):
        service.activate_wizard_draft(session, project_id, revision)


def test_free_draft_uses_textbook_workspace_and_allows_empty_subject(
    session: Session,
) -> None:
    draft = service.create_wizard_draft(
        session, WizardDraftCreate(template_key=TemplateKey.FREE)
    )

    assert draft.project.workspace_variant.value == "textbook"

    saved = service.save_wizard_draft(
        session,
        draft.project.id,
        WizardDraftWrite(
            expected_revision=draft.draft.revision,
            current_step=3,
            max_completed_step=3,
            schema_version=1,
            project=ProjectDraftWrite(name="Нейросети"),
            goal_passport=_passport(subject=None),
            state={},
        ),
    )
    active = service.activate_wizard_draft(
        session, draft.project.id, saved.draft.revision
    )

    assert active.project.status.value == "active"
    assert active.project.template_key == TemplateKey.FREE
    assert active.project.workspace_variant.value == "textbook"

    project = session.get(Project, draft.project.id)
    assert project is not None
    link_material(session, project, make_material(session, "e01"))
    stats = next(
        item for item in service.list_project_stats(session) if item.project_id == project.id
    )
    assert stats.program_nodes == 0
    assert stats.materials == 1
    assert stats.material_pages == 1


def test_free_activation_requires_goal_even_with_hidden_goal_scope(
    session: Session,
) -> None:
    project_id, revision = _save_draft(
        session, TemplateKey.FREE, _passport(subject=None, goal=None)
    )

    with pytest.raises(ProjectConflictError, match="заполните паспорт цели"):
        service.activate_wizard_draft(session, project_id, revision)
