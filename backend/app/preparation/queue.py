"""Очередь рабочего дня сохраняется отдельно от плана и фактов занятий."""

from datetime import UTC, date, datetime
from uuid import UUID

from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session

from app.db import project_write_transaction
from app.preparation.calendar import day_bounds, study_date, utc
from app.preparation.data import get_settings, require_project, units
from app.preparation.models import PreparationQueue, StudyActivity
from app.preparation.planner import read_plan
from app.preparation.progress import event_id, record_event
from app.preparation.schemas import QueueItem, QueuePositionWrite, QueueRead
from app.projects.errors import ProjectDomainError


def day_start_at(session: Session, project_id: UUID, day: date) -> datetime | None:
    """Момент первого старта — граница автоматических метрик учебного дня."""
    if session.get(PreparationQueue, (project_id, day)) is None:
        return None
    event = session.get(StudyActivity, event_id(project_id, f"day-start:{day}"))
    if event is not None:
        return utc(event.occurred_at)
    return day_bounds(day, get_settings(session, project_id).config)[0]


def _read(
    row: PreparationQueue | None,
    day: date,
    *,
    started_at: datetime | None = None,
    seconds_by_node: dict | None = None,
) -> QueueRead:
    items = [QueueItem.model_validate(i) for i in row.items] if row else []
    position = row.position if row else 0
    return QueueRead(
        date=day,
        items=items,
        position=position,
        topic_position=row.topic_position if row else 0,
        completed=bool(row and position >= len(items)),
        started=row is not None,
        started_at=started_at,
        seconds_by_node=seconds_by_node or {},
    )


def get_queue(session: Session, project_id: UUID, day: date | None = None) -> QueueRead:
    """Чтение не создаёт очередь и не сдвигает курсор."""
    require_project(session, project_id)
    config = get_settings(session, project_id).config
    day = day or study_date(datetime.now(UTC), config)
    row = session.get(PreparationQueue, (project_id, day))
    from app.preparation.activity import time_totals

    _, seconds_by_node = time_totals(session, project_id, day, config)
    result = _read(
        row,
        day,
        started_at=day_start_at(session, project_id, day),
        seconds_by_node=seconds_by_node,
    )
    plan = read_plan(session, project_id)
    result.has_plan = any(i.on_date == day and i.id not in plan.completed_ids for i in plan.items)
    return result


def _build(session, project_id, day, now):
    require_project(session, project_id, writable=True)
    config = get_settings(session, project_id).config
    unit_rows = units(session, project_id)
    unit_map = {u.id: u for u in unit_rows}
    plan = read_plan(session, project_id)
    candidates = [i for i in plan.items if i.on_date == day]
    candidates.sort(key=lambda i: (i.order, str(i.id)))
    result, seen = [], set()
    new_count, review_count = 0, 0
    for item in candidates:
        unit = unit_map.get(item.unit_id)
        if unit is None or unit.id in seen:
            continue
        is_new = item.kind in {"learn", "answer"}
        if (is_new and new_count >= config.max_new_per_day) or (
            not is_new and review_count >= config.max_reviews_per_day
        ):
            continue
        new_count += int(is_new)
        review_count += int(not is_new)
        seen.add(unit.id)
        reason = (
            "Просроченное повторение"
            if item.kind == "review" and item.on_date < day
            else item.reason
        )
        result.append(
            QueueItem(
                unit_id=unit.id,
                title=unit.title,
                topic_ids=unit.topic_ids,
                kind=item.kind,
                minutes=item.minutes,
                reason=reason,
            )
        )
    return result


def start_queue(
    session: Session,
    project_id: UUID,
    day: date | None = None,
    *,
    now: datetime | None = None,
) -> QueueRead:
    """Повторный запуск возвращает тот же порядок; две вкладки не создают две очереди."""
    now = now or datetime.now(UTC)
    with project_write_transaction(session, project_id):
        require_project(session, project_id, writable=True)
        today = study_date(now, get_settings(session, project_id).config)
        day = day or today
        if day != today:
            raise ProjectDomainError(
                "Можно начать только текущий учебный день",
                status=422,
                code="preparation_day_invalid",
            )
        row = session.get(PreparationQueue, (project_id, day))
        if row is None:
            items = _build(session, project_id, day, now)
            session.execute(
                insert(PreparationQueue)
                .values(
                    project_id=project_id,
                    study_date=day,
                    items=[i.model_dump(mode="json") for i in items],
                    position=0,
                    topic_position=0,
                )
                .on_conflict_do_nothing()
            )
            row = session.get(PreparationQueue, (project_id, day))
        record_event(
            session,
            project_id,
            "day_start",
            "Начат учебный день",
            key=f"day-start:{day}",
            at=now,
        )
        result = get_queue(session, project_id, day)
    return result


def move_queue(
    session: Session, project_id: UUID, command: QueuePositionWrite, day: date | None = None
) -> QueueRead:
    """Навигация в очереди не объявляет задание выполненным — это делает журнал."""
    with project_write_transaction(session, project_id):
        require_project(session, project_id, writable=True)
        day = day or study_date(datetime.now(UTC), get_settings(session, project_id).config)
        row = session.get(PreparationQueue, (project_id, day))
        if row is None:
            raise ProjectDomainError(
                "Сначала начните день", status=404, code="preparation_queue_missing"
            )
        if command.position > len(row.items) or (
            command.position < len(row.items)
            and command.topic_position >= len(row.items[command.position]["topic_ids"])
        ):
            raise ProjectDomainError(
                "Позиция за пределами очереди", status=422, code="preparation_queue_position"
            )
        row.position, row.topic_position = command.position, command.topic_position
        result = get_queue(session, project_id, day)
    return result
