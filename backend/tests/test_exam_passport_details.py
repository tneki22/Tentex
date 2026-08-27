from datetime import date, time

from sqlalchemy.orm import Session

from app.models import (
    ExamFormat,
    GoalPurpose,
    GoalScope,
    ModuleKey,
    StartingLevel,
    StudyFormat,
    TargetOutcome,
    TemplateKey,
)
from app.projects import service
from app.projects.schemas import (
    GoalPassportWrite,
    ProjectDraftWrite,
    ProjectSettingsProjectWrite,
    ProjectSettingsWrite,
    WizardDraftCreate,
    WizardDraftWrite,
)


def _passport(*, exam_time: time, exam_procedure: str) -> GoalPassportWrite:
    return GoalPassportWrite(
        subject="ТВиМС",
        purpose=GoalPurpose.EXAM,
        scope=GoalScope.WHOLE,
        starting_level=StartingLevel.FAMILIAR,
        target_outcome=TargetOutcome.APPLICATION,
        study_format=StudyFormat.THEORY_AND_PRACTICE,
        exam_format=ExamFormat.QUESTIONS_TASKS,
        expected_item_count=42,
        minutes_per_day=240,
        exam_time=exam_time,
        exam_procedure=exam_procedure,
    )


def test_exam_time_and_procedure_survive_draft_activation_and_settings(
    session: Session,
) -> None:
    draft = service.create_wizard_draft(
        session,
        WizardDraftCreate(template_key=TemplateKey.EXAM),
    )
    saved = service.save_wizard_draft(
        session,
        draft.project.id,
        WizardDraftWrite(
            expected_revision=draft.draft.revision,
            current_step=5,
            max_completed_step=5,
            schema_version=1,
            project=ProjectDraftWrite(
                name="ТВиМС — экзамен",
                deadline=date(2026, 9, 2),
                enabled_modules=[ModuleKey.PLAN, ModuleKey.CARDS],
            ),
            goal_passport=_passport(
                exam_time=time(9, 30),
                exam_procedure="Сначала письменный билет, затем два вопроса устно.",
            ),
            state={},
        ),
    )

    assert saved.goal_passport is not None
    assert saved.goal_passport.exam_time == time(9, 30)
    assert saved.goal_passport.exam_procedure == (
        "Сначала письменный билет, затем два вопроса устно."
    )

    active = service.activate_wizard_draft(
        session,
        draft.project.id,
        saved.draft.revision,
    )
    assert active.goal_passport is not None
    assert active.goal_passport.exam_time == time(9, 30)

    updated = service.update_project_settings(
        session,
        draft.project.id,
        ProjectSettingsWrite(
            project=ProjectSettingsProjectWrite(
                name="ТВиМС — экзамен",
                deadline=date(2026, 9, 2),
                enabled_modules=[ModuleKey.PLAN, ModuleKey.CARDS],
            ),
            goal_passport=_passport(
                exam_time=time(14, 0),
                exam_procedure="Преподаватель проверяет написанное и задаёт один вопрос.",
            ),
        ),
    )

    assert updated.goal_passport.exam_time == time(14, 0)
    assert updated.goal_passport.exam_procedure == (
        "Преподаватель проверяет написанное и задаёт один вопрос."
    )
