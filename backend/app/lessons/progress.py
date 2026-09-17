"""Прохождение урока: где остановились и отметка «Урок пройден» (записка «Уроки» §4.6).

Пользователь один, поэтому позиция чтения и факт прохождения лежат прямо в `lessons`, а
не в отдельной таблице сессий. Просмотр урока не меняет прогресс по теме (FR-L9): в
«Историю» уходит запись занятия без времени и без оценки — прогресс двигают только задания.
"""

from datetime import UTC, datetime
from uuid import UUID, uuid5

from sqlalchemy import delete, select
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session

from app.db import project_write_transaction
from app.lessons.schemas import (
    LessonChangeResult,
    LessonCompletionWrite,
    LessonProgressWrite,
)
from app.lessons.service import (
    _change_result,
    _require_lesson,
    _require_lessons_project,
)
from app.models import Lesson, LessonBlock, LessonTopic, ProgramNode, utc_now
from app.preparation.calendar import naive_utc
from app.preparation.data import node_path, program_nodes
from app.preparation.models import StudyActivity
from app.projects.errors import ProjectDomainError

ACTIVITY_KIND = "lesson"


def save_position(
    session: Session, project_id: UUID, lesson_id: UUID, command: LessonProgressWrite
) -> LessonChangeResult:
    """Позиция чтения меняется часто и молча: ни ревизии, ни записи в журнал."""
    with project_write_transaction(session, project_id):
        _require_lessons_project(session, project_id, writable=True)
        lesson = _require_lesson(session, project_id, lesson_id)
        if command.last_block_id is not None:
            block = session.get(LessonBlock, command.last_block_id)
            if block is None or block.lesson_id != lesson.id:
                raise ProjectDomainError(
                    "Блок не принадлежит уроку", status=422, code="lesson_block_foreign"
                )
        lesson.last_block_id = command.last_block_id
        session.flush()
        return _change_result(session, lesson)


def set_completed(
    session: Session, project_id: UUID, lesson_id: UUID, command: LessonCompletionWrite
) -> LessonChangeResult:
    """«Урок пройден» — отметка и запись занятия в «Историю»; снятие убирает обе."""
    with project_write_transaction(session, project_id):
        _require_lessons_project(session, project_id, writable=True)
        lesson = _require_lesson(session, project_id, lesson_id)
        now = datetime.now(UTC)
        activity_id = uuid5(project_id, f"lesson:{lesson.id}")
        if not command.completed:
            lesson.completed_at = None
            session.execute(delete(StudyActivity).where(StudyActivity.id == activity_id))
            session.flush()
            return _change_result(session, lesson)
        lesson.completed_at = utc_now()
        _record_activity(session, project_id, lesson, activity_id, now)
        session.flush()
        return _change_result(session, lesson)


def _record_activity(
    session: Session, project_id: UUID, lesson: Lesson, activity_id: UUID, now: datetime
) -> None:
    """Запись «Истории»: тема первого занятия урока, без времени — его считает таймер."""
    topic_id = session.scalar(
        select(LessonTopic.program_node_id)
        .where(LessonTopic.lesson_id == lesson.id)
        .order_by(LessonTopic.sort_order)
        .limit(1)
    )
    nodes = {node.id: node for node in program_nodes(session, project_id, active=False)}
    node: ProgramNode | None = nodes.get(topic_id) if topic_id else None
    values = dict(
        id=activity_id,
        project_id=project_id,
        node_id=node.id if node else None,
        title=lesson.title,
        path=node_path(node, nodes) if node else [],
        kind=ACTIVITY_KIND,
        seconds=0,
        occurred_at=naive_utc(now),
        note="Урок пройден",
        understood=False,
    )
    session.execute(
        insert(StudyActivity)
        .values(**values)
        .on_conflict_do_update(index_elements=[StudyActivity.id], set_=values)
    )
