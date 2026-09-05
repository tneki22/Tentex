"""Факты открытий, начала дня и достижений отдельно от отменяемого плана."""

from datetime import UTC, datetime
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert

from app.models import Attempt
from app.preparation.calendar import study_date
from app.preparation.models import StudyActivity, StudyInterval
from app.preparation.schemas import BudgetRead, MilestoneRead


def openings(session, project_id, config):
    """Открытия из журнала и старых занятий; один вопрос считается раз за учебный день."""
    result = {}
    rows = [
        (a.node_id, a.occurred_at)
        for a in session.scalars(
            select(StudyActivity).where(
                StudyActivity.project_id == project_id, StudyActivity.node_id.is_not(None)
            )
        )
    ]
    rows.extend(
        (a.node_id, a.started_at)
        for a in session.scalars(
            select(StudyInterval).where(StudyInterval.project_id == project_id)
        )
    )
    rows.extend(
        (a.program_node_id, a.created_at)
        for a in session.scalars(select(Attempt).where(Attempt.project_id == project_id))
    )
    for node_id, at in rows:
        day = study_date(at, config)
        result.setdefault(day, set()).add(node_id)
    return result


def record_event(session, project_id, kind, title, *, key, note="", at=None, node_id=None):
    """Уникальный ключ действия защищает достижения при повторной доставке."""
    session.execute(
        insert(StudyActivity)
        .values(
            id=uuid5(NAMESPACE_URL, f"tentex:{project_id}:{key}"),
            project_id=project_id,
            node_id=node_id,
            kind=kind,
            title=title,
            note=note,
            seconds=0,
            path=[],
            understood=False,
            occurred_at=(at or datetime.now(UTC)).replace(tzinfo=None),
        )
        .on_conflict_do_nothing()
    )


def milestones(events):
    """Пять первых шагов по настоящему журналу, без выдуманных дат задним числом."""
    definitions = [
        (
            "plan",
            "Первый план",
            "🗓️",
            lambda e: e.kind == "plan_change" and e.note == "distribution",
        ),
        ("start", "Начало положено", "☀️", lambda e: e.kind == "day_start"),
        ("study", "Первое занятие", "📖", lambda e: (e.seconds or 0) > 0),
        ("answer", "Первый сданный ответ", "✍️", lambda e: e.kind == "answer"),
        ("passed", "Первый зачёт", "🎯", lambda e: e.kind == "answer" and e.outcome == "passed"),
    ]
    result = []
    for key, title, emoji, matches in definitions:
        first = min((e for e in events if matches(e)), key=lambda e: e.occurred_at, default=None)
        if first:
            result.append(
                MilestoneRead(key=key, title=title, emoji=emoji, occurred_at=first.occurred_at)
            )
    return sorted(result, key=lambda m: m.occurred_at)


def remaining_budget(days, config, today, deadline):
    """Бюджет дня ограничен свободными часами; сон не вычитается второй раз из лимита."""
    future = [d for d in days if d.date >= today and (not deadline or d.date < deadline)]
    base = sum(config.daily_minutes or 0 for _ in future)
    rest = sum(config.daily_minutes or 0 for d in future if d.is_rest)
    effective = sum(
        config.date_minutes.get(
            d.date, config.weekday_minutes.get(d.date.weekday(), config.daily_minutes or 0)
        )
        for d in future
        if not d.is_rest
    )
    remaining = sum(d.remaining_minutes for d in future)
    used = sum(min(d.capacity_minutes, (d.active_seconds + 59) // 60) for d in future)
    return BudgetRead(
        base_minutes=base,
        rest_minutes=rest,
        exception_minutes=base - rest - effective,
        used_minutes=used,
        unavailable_minutes=effective - remaining - used,
        remaining_minutes=remaining,
        study_days=sum(d.remaining_minutes > 0 for d in future),
    )


def record_opening(session, project_id, node_id):
    """Открытие сохраняется сразу, независимо от таймера и начала дня."""
    from app.db import project_write_transaction
    from app.preparation.data import get_settings, require_project, units
    from app.projects.errors import ProjectDomainError

    with project_write_transaction(session, project_id):
        require_project(session, project_id, writable=True)
        topic = next((u for u in units(session, project_id) if node_id in u.topic_ids), None)
        if topic is None:
            raise ProjectDomainError(
                "Вопрос не найден", status=404, code="preparation_unit_invalid"
            )
        today = study_date(datetime.now(UTC), get_settings(session, project_id).config)
        record_event(
            session,
            project_id,
            "view",
            topic.title,
            key=f"opened:{today}:{node_id}",
            node_id=node_id,
        )
