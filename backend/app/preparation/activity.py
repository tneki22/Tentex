"""Доставка времени и история занятий: один факт ответа, независимо от числа проверок."""

from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from uuid import UUID, uuid5

from sqlalchemy import select, update
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session

from app.db import project_write_transaction
from app.models import Attempt, ChatMessage, Grade
from app.preparation.calendar import day_bounds, naive_utc, study_date, utc
from app.preparation.data import get_settings, node_path, program_nodes, require_project, units
from app.preparation.models import ReviewQuality, StudyActivity, StudyInterval
from app.preparation.schemas import (
    ActivityRead,
    HistoryRead,
    ManualActivityWrite,
    TimeBatchRead,
    TimeBatchWrite,
    UnderstoodWrite,
)
from app.projects.errors import ProjectDomainError

MIN_VIEW_SECONDS = 10  # Короткий переход по дереву не является просмотром вопроса.
FUTURE_TOLERANCE_SECONDS = 60  # Допуск небольшого расхождения часов клиента и сервера.


def add_intervals(session: Session, project_id: UUID, command: TimeBatchWrite) -> TimeBatchRead:
    """Конфликт UUID отклоняется, повторная доставка того же пакета безопасна."""
    with project_write_transaction(session, project_id):
        require_project(session, project_id, writable=True)
        nodes = {n.id: n for n in program_nodes(session, project_id)}
        accepted = []
        latest = datetime.now(UTC) + timedelta(seconds=FUTURE_TOLERANCE_SECONDS)
        for interval in command.intervals:
            node = nodes.get(interval.node_id)
            if node is None or interval.ended_at > latest:
                raise ProjectDomainError(
                    "Неизвестный вопрос или время в будущем",
                    status=422,
                    code="study_interval_invalid",
                )
            values = interval.model_dump()
            values.update(
                project_id=project_id,
                started_at=naive_utc(interval.started_at),
                ended_at=naive_utc(interval.ended_at),
            )
            existing = session.get(StudyInterval, interval.id)
            if existing and any(getattr(existing, k) != v for k, v in values.items()):
                raise ProjectDomainError(
                    "Идентификатор интервала уже использован",
                    status=409,
                    code="study_interval_conflict",
                )
            session.execute(insert(StudyInterval).values(**values).on_conflict_do_nothing())
            accepted.append(interval.id)
            seconds = (interval.ended_at - interval.started_at).total_seconds()
            if seconds >= MIN_VIEW_SECONDS:
                _record_view(session, project_id, interval, node, nodes)
    return TimeBatchRead(accepted_ids=accepted)


def _record_view(session: Session, project_id: UUID, interval, node, nodes) -> None:
    key = uuid5(interval.session_id, f"view:{node.id}")
    session.execute(
        insert(StudyActivity)
        .values(
            id=key,
            project_id=project_id,
            node_id=node.id,
            title=node.title,
            path=node_path(node, nodes),
            kind="view",
            seconds=0,
            note="Вопрос открыт",
            occurred_at=naive_utc(interval.started_at),
            understood=False,
        )
        .on_conflict_do_nothing()
    )


def time_segments(session: Session, project_id: UUID, start: datetime, end: datetime):
    """Пересечения всех вкладок вырезаются до группировки по вопросу и виду работы."""
    rows = session.scalars(
        select(StudyInterval)
        .where(
            StudyInterval.project_id == project_id,
            StudyInterval.ended_at > naive_utc(start),
            StudyInterval.started_at < naive_utc(end),
        )
        .order_by(StudyInterval.started_at, StudyInterval.id)
    )
    cursor = utc(start)
    segments = []
    for row in rows:
        left, right = max(cursor, utc(row.started_at)), min(utc(end), utc(row.ended_at))
        if right > left:
            segments.append((row, left, right))
            cursor = right
    return segments


def time_totals(session: Session, project_id: UUID, day: date, config):
    """Один и тот же расчёт используется календарём, счётчиком и диаграммой."""
    start, end = day_bounds(day, config)
    by_kind, by_node = defaultdict(int), defaultdict(int)
    for row, left, right in time_segments(session, project_id, start, end):
        seconds = int((right - left).total_seconds())
        by_kind[row.kind] += seconds
        by_node[row.node_id] += seconds
    for row in session.scalars(
        select(StudyActivity).where(
            StudyActivity.project_id == project_id,
            StudyActivity.occurred_at >= naive_utc(start),
            StudyActivity.occurred_at < naive_utc(end),
            StudyActivity.kind == "manual",
        )
    ):
        by_kind["manual"] += row.seconds
        by_node[row.node_id] += row.seconds
    return dict(by_kind), dict(by_node)


def _activity_read(row: StudyActivity) -> ActivityRead:
    return ActivityRead(
        id=row.id,
        node_id=row.node_id,
        title=row.title,
        path=row.path,
        kind=row.kind,
        occurred_at=utc(row.occurred_at),
        seconds=row.seconds,
        note=row.note,
        understood=row.understood,
    )


def save_manual(session: Session, project_id: UUID, command: ManualActivityWrite) -> ActivityRead:
    """Изменение вручную сохраняет происхождение и не создаёт Оценку."""
    with project_write_transaction(session, project_id):
        require_project(session, project_id, writable=True)
        nodes = {n.id: n for n in program_nodes(session, project_id)}
        node = nodes.get(command.node_id)
        if command.node_id is not None and node is None:
            raise ProjectDomainError("Вопрос не найден", status=404, code="study_node_not_found")
        if utc(command.occurred_at) > datetime.now(UTC) + timedelta(minutes=1):
            raise ProjectDomainError(
                "Занятие не может быть в будущем", status=422, code="study_activity_future"
            )
        row = session.get(StudyActivity, command.id)
        if row and (row.project_id != project_id or row.kind != "manual"):
            raise ProjectDomainError(
                "Это занятие нельзя изменить", status=409, code="study_activity_conflict"
            )
        if row is None:
            row = StudyActivity(id=command.id, project_id=project_id, kind="manual")
            session.add(row)
        row.node_id = command.node_id
        row.title = node.title if node else "Самостоятельное занятие"
        row.path = node_path(node, nodes) if node else []
        row.occurred_at = naive_utc(command.occurred_at)
        row.seconds, row.note, row.understood = command.seconds, command.note, command.understood
        session.flush()
        result = _activity_read(row)
    return result


def delete_manual(session: Session, project_id: UUID, activity_id: UUID) -> None:
    """Удаляются только ручные записи, не реальные попытки из чата."""
    with project_write_transaction(session, project_id):
        require_project(session, project_id, writable=True)
        row = session.get(StudyActivity, activity_id)
        if row is None or row.project_id != project_id or row.kind != "manual":
            raise ProjectDomainError(
                "Ручное занятие не найдено", status=404, code="study_activity_not_found"
            )
        session.delete(row)


def mark_understood(session: Session, project_id: UUID, command: UnderstoodWrite) -> None:
    """Чтение можно отметить по вопросу; назначение билета завершается всеми его вопросами."""
    with project_write_transaction(session, project_id):
        require_project(session, project_id, writable=True)
        unit = next((u for u in units(session, project_id) if u.id == command.unit_id), None)
        nodes = {n.id: n for n in program_nodes(session, project_id)}
        topic_ids = (
            unit.topic_ids
            if unit
            else (
                [command.unit_id]
                if any(command.unit_id in u.topic_ids for u in units(session, project_id))
                else []
            )
        )
        if not topic_ids:
            raise ProjectDomainError(
                "Вопрос или билет не найден", status=404, code="study_unit_not_found"
            )
        config = get_settings(session, project_id).config
        today = study_date(datetime.now(UTC), config)
        for topic_id in topic_ids:
            if not command.understood:
                session.execute(
                    update(StudyActivity)
                    .where(
                        StudyActivity.project_id == project_id,
                        StudyActivity.node_id == topic_id,
                        StudyActivity.kind == "reading",
                    )
                    .values(understood=False)
                )
                continue
            key = uuid5(project_id, f"understood:{topic_id}:{today.isoformat()}")
            node = nodes[topic_id]
            values = dict(
                id=key,
                project_id=project_id,
                node_id=topic_id,
                title=node.title,
                path=node_path(node, nodes),
                kind="reading",
                seconds=0,
                occurred_at=naive_utc(datetime.now(UTC)),
                note="Отметка «Разобрался»",
                understood=command.understood,
            )
            session.execute(
                insert(StudyActivity)
                .values(**values)
                .on_conflict_do_update(index_elements=[StudyActivity.id], set_=values)
            )


def completed_items(session: Session, project_id: UUID, items, unit_rows, config) -> set[UUID]:
    """Открытие закрывает оба назначения только своего учебного дня; билет неделим."""
    from app.preparation.progress import openings

    by_day = openings(session, project_id, config)
    unit_map = {u.id: u for u in unit_rows}
    return {
        item.id
        for item in items
        if item.unit_id in unit_map
        and set(unit_map[item.unit_id].topic_ids)
        and set(unit_map[item.unit_id].topic_ids) <= by_day.get(item.on_date, set())
    }


def _attempt_history(session: Session, project_id: UUID, nodes) -> list[ActivityRead]:
    messages = {
        m.attempt_id: m.session_id
        for m in session.scalars(
            select(ChatMessage)
            .join(Attempt, ChatMessage.attempt_id == Attempt.id)
            .where(Attempt.project_id == project_id)
        )
    }
    rows = session.execute(
        select(Attempt, Grade, ReviewQuality.quality)
        .outerjoin(Grade, Grade.attempt_id == Attempt.id)
        .outerjoin(ReviewQuality, ReviewQuality.attempt_id == Attempt.id)
        .where(Attempt.project_id == project_id)
    )
    result = []
    for attempt, grade, quality in rows:
        node = nodes.get(attempt.program_node_id)
        result.append(
            ActivityRead(
                id=attempt.id,
                node_id=attempt.program_node_id,
                title=str(
                    attempt.context_snapshot.get("question") or (node.title if node else "Вопрос")
                ),
                path=node_path(node, nodes) if node else [],
                kind="answer",
                occurred_at=utc(attempt.created_at),
                seconds=attempt.active_seconds,
                note=grade.summary if grade else "Ожидает проверки",
                attempt_id=attempt.id,
                chat_id=messages.get(attempt.id),
                outcome=grade.outcome.value if grade else None,
                method=grade.method.value if grade and grade.method else None,
                self_assessment=grade.self_assessment.value
                if grade and grade.self_assessment
                else None,
                answer_mode=attempt.answer_mode,
                quality=quality,
            )
        )
    return result


def history(
    session: Session,
    project_id: UUID,
    *,
    date_from: date | None = None,
    date_to: date | None = None,
    node_id: UUID | None = None,
    section_id: UUID | None = None,
    kind: str | None = None,
    outcome: str | None = None,
    method: str | None = None,
    answer_mode: str | None = None,
    disputed: bool = False,
    q: str = "",
    offset: int = 0,
    limit: int = 50,
) -> HistoryRead:
    """Проекция всех видов занятий с фильтрацией до пагинации."""
    require_project(session, project_id)
    config = get_settings(session, project_id).config
    nodes = {n.id: n for n in program_nodes(session, project_id, active=False)}
    activities = [
        _activity_read(a)
        for a in session.scalars(
            select(StudyActivity).where(StudyActivity.project_id == project_id)
        )
    ]
    attempts = _attempt_history(session, project_id, nodes)
    activities.extend(attempts)
    interval_rows = list(
        session.scalars(select(StudyInterval).where(StudyInterval.project_id == project_id))
    )
    if interval_rows:
        start = min(i.started_at for i in interval_rows)
        end = max(i.ended_at for i in interval_rows)
        grouped = {}
        for row, left, right in time_segments(session, project_id, utc(start), utc(end)):
            while left < right:
                day = study_date(left, config)
                boundary = min(right, day_bounds(day, config)[1])
                key = (row.session_id, row.node_id, row.kind, day)
                entry = grouped.setdefault(key, [row, left, 0, boundary])
                entry[2] += int((boundary - left).total_seconds())
                entry[3] = boundary
                left = boundary
        for key, (row, at, seconds, until) in grouped.items():
            if row.kind == "answer" and any(
                a.node_id == row.node_id and at <= a.occurred_at <= until + timedelta(minutes=2)
                for a in attempts
            ):
                continue
            node = nodes.get(row.node_id)
            activities.append(
                ActivityRead(
                    id=uuid5(row.session_id, str(key[1:])),
                    node_id=row.node_id,
                    title=node.title if node else "Занятие",
                    path=node_path(node, nodes) if node else [],
                    kind=row.kind,
                    occurred_at=at,
                    seconds=seconds,
                    note="Время в рабочей области",
                )
            )
    selected = [
        a
        for a in activities
        if _matches(
            a, config, nodes, date_from, date_to, node_id, section_id, kind, outcome, method, q
        )
        and (answer_mode is None or a.answer_mode == answer_mode)
        and (
            not disputed
            or (
                a.outcome not in {None, "unscored"}
                and a.self_assessment is not None
                and a.self_assessment != a.outcome
            )
        )
    ]
    selected.sort(key=lambda a: (a.occurred_at, str(a.id)), reverse=True)
    return HistoryRead(
        items=selected[offset : offset + limit], total=len(selected), offset=offset, limit=limit
    )


def _matches(a, config, nodes, start, end, node_id, section_id, kind, outcome, method, q):
    day = study_date(a.occurred_at, config)
    if (start and day < start) or (end and day > end) or (node_id and a.node_id != node_id):
        return False
    if kind and a.kind != kind:
        return False
    if outcome == "pending" and (a.attempt_id is None or a.outcome is not None):
        return False
    if outcome and outcome != "pending" and a.outcome != outcome:
        return False
    if (method and a.method != method) or q.casefold() not in (a.title + " " + a.note).casefold():
        return False
    if section_id:
        node = nodes.get(a.node_id)
        while node and node.id != section_id:
            node = nodes.get(node.parent_id)
        return node is not None
    return True
