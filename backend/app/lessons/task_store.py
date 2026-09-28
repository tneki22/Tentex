"""Задания урока в документе: живы ли они и как читаются вместе с попытками.

Отдельно от `tasks`, чтобы `service` и `editing` читали и сверяли задания, не
завися от модулей модели и проверки ответа.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.lessons import task_check
from app.lessons.task_schemas import StudyTaskAttemptRead, StudyTaskRead, StudyTaskSourceRead
from app.models import (
    Attempt,
    Grade,
    LessonBlock,
    StudyTask,
    StudyTaskForm,
    utc_now,
)

PENDING_REASON = "Проверка недоступна без внешней модели — ответ сохранён, проверьте позже"


def sync_lesson_tasks(session: Session, lesson_id: UUID) -> None:
    """Задание живо, пока его держит блок урока: удаление и отмена правят `deleted_at`."""
    held = set(session.scalars(select(LessonBlock.activity_id).where(
        LessonBlock.lesson_id == lesson_id, LessonBlock.activity_id.is_not(None),
    )))
    for task in session.scalars(select(StudyTask).where(StudyTask.lesson_id == lesson_id)):
        alive = task.activity_id in held
        if alive and task.deleted_at is not None:
            task.deleted_at = None
        elif not alive and task.deleted_at is None:
            task.deleted_at = utc_now()


def retire_lesson_tasks(session: Session, lesson_id: UUID) -> None:
    """Урок удаляется — его задания уходят в историю вместе с попытками."""
    session.execute(update(StudyTask).where(
        StudyTask.lesson_id == lesson_id, StudyTask.deleted_at.is_(None),
    ).values(deleted_at=utc_now()))


# --- чтение -----------------------------------------------------------------------------------


def attempt_read(task: StudyTask, attempt: Attempt, grade: Grade | None
                  ) -> StudyTaskAttemptRead:
    answer = attempt.context_snapshot.get("answer")
    items: list[bool] = []
    score: float | None = None
    if grade is not None and task.form != StudyTaskForm.OPEN_ANSWER and answer is not None:
        try:
            result = task_check.check(task.form, task.payload, task.answer_key, answer)
        except task_check.AnswerShapeError:
            result = None
        if result is not None:
            items, score = result.items, result.score

    def points(values: list[Any] | None) -> list[str]:
        return [str(item.get("point", "")) if isinstance(item, dict) else str(item)
                for item in values or []]

    return StudyTaskAttemptRead(
        id=attempt.id, activity_id=attempt.activity_id, ordinal=attempt.ordinal,
        answer=answer, text=attempt.text,
        outcome=grade.outcome if grade else None, method=grade.method if grade else None,
        score=score, items=items, summary=grade.summary if grade else "",
        credited=points(grade.credited_points if grade else None),
        missed=points(grade.missed_points if grade else None),
        wrong=points(grade.wrong_points if grade else None),
        pending_reason=None if grade else PENDING_REASON,
        created_at=attempt.created_at,
    )


def task_reads(session: Session, activity_ids: list[UUID]) -> dict[UUID, StudyTaskRead]:
    """Задания блоков урока с числом попыток и последней попыткой."""
    if not activity_ids:
        return {}
    tasks = {task.activity_id: task for task in session.scalars(
        select(StudyTask).where(StudyTask.activity_id.in_(activity_ids))
    )}
    counts = dict(session.execute(
        select(Attempt.activity_id, func.count()).where(Attempt.activity_id.in_(activity_ids))
        .group_by(Attempt.activity_id)
    ).tuples().all())
    last: dict[UUID, tuple[Attempt, Grade | None]] = {}
    for attempt, grade in session.execute(
        select(Attempt, Grade).outerjoin(Grade, Grade.attempt_id == Attempt.id)
        .where(Attempt.activity_id.in_(activity_ids)).order_by(Attempt.ordinal)
    ).tuples():
        last[attempt.activity_id] = (attempt, grade)
    result: dict[UUID, StudyTaskRead] = {}
    for activity_id, task in tasks.items():
        latest = last.get(activity_id)
        result[activity_id] = StudyTaskRead(
            activity_id=activity_id, form=task.form, prompt_md=task.prompt_md,
            payload=task.payload, answer_key=task.answer_key, reference_md=task.reference_md,
            explanation_md=task.explanation_md, hint_md=task.hint_md,
            difficulty=task.difficulty, basis=task.basis,
            sources=[
                StudyTaskSourceRead(source_name=item["material_name"],
                                    page_from=item["page_from"], page_to=item["page_to"])
                for item in (task.source_snapshot or {}).get("sources", [])
            ],
            attempts=int(counts.get(activity_id, 0)),
            last_attempt=attempt_read(task, *latest) if latest else None,
        )
    return result


