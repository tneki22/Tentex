from uuid import UUID

import pytest
from sqlalchemy.orm import Session

from app.models import (
    GoalPurpose,
    GoalScope,
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
