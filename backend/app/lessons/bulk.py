"""Массовая подготовка уроков без модели: один проход по темам, одна отмена.

Правила и умолчания таблицы — записка «Уроки» §4.5; контракт —
`docs/architecture/lessons.md`. «Пропустить» до сервера не доходит: клиент присылает
только те темы, по которым урок действительно создаётся.
"""

from uuid import UUID

from sqlalchemy.orm import Session

from app.db import project_write_transaction
from app.lessons.schemas import LessonBulkResult, LessonBulkWrite
from app.lessons.service import (
    ACTION_LESSON_BULK,
    _latest_action,
    _load_program,
    _require_lessons_project,
    _require_study_node,
    fill_quick_lesson,
    lessons_overview,
    new_lesson,
    quick_sources,
)
from app.models import ProjectActionLog, utc_now
from app.projects.errors import ProjectDomainError
from app.projects.schemas import LatestUndoableAction


def create_bulk_lessons(
    session: Session, project_id: UUID, command: LessonBulkWrite
) -> LessonBulkResult:
    """Черновики по списку тем одной транзакцией: падение на любой теме не создаёт ничего."""
    seen: set[UUID] = set()
    for item in command.items:
        if item.program_node_id in seen:
            raise ProjectDomainError(
                "Тема встречается в списке дважды",
                status=422,
                code="lesson_bulk_duplicate",
                context={"program_node_id": str(item.program_node_id)},
            )
        seen.add(item.program_node_id)

    with project_write_transaction(session, project_id):
        project = _require_lessons_project(session, project_id, writable=True)
        program = _load_program(session, project_id)
        now = utc_now()
        lesson_ids: list[UUID] = []
        binding_ids: list[UUID] = []
        for item in command.items:
            node = _require_study_node(session, project_id, item.program_node_id)
            lesson = new_lesson(session, project_id, node, now)
            lesson_ids.append(lesson.id)
            if item.action == "quick":
                sources = quick_sources(session, program, node, None)
                binding_ids += fill_quick_lesson(session, program, node, sources, lesson, now)
        session.add(
            ProjectActionLog(
                project_id=project.id,
                action_type=ACTION_LESSON_BULK,
                phase="active",
                payload_version=1,
                target_title=f"Уроков: {len(lesson_ids)}",
                inverse_data={
                    "lesson_ids": [str(lesson_id) for lesson_id in lesson_ids],
                    "binding_ids": [str(binding_id) for binding_id in binding_ids],
                },
            )
        )
        session.flush()
        created = set(lesson_ids)
        action = _latest_action(session, project_id)
        return LessonBulkResult(
            lessons=[
                summary
                for summary in lessons_overview(session, project_id).lessons
                if summary.id in created
            ],
            latest_undoable_action=(
                LatestUndoableAction.model_validate(action) if action is not None else None
            ),
        )
