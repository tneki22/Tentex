"""Факты открытий, начала дня и достижений отдельно от отменяемого плана."""

from contextlib import nullcontext
from datetime import UTC, datetime
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert

from app.models import Activity, ActivityKind, Attempt
from app.preparation.calendar import study_date, utc
from app.preparation.models import StudyActivity, StudyInterval
from app.preparation.schemas import BudgetRead, MilestoneRead


def event_id(project_id, key):
    """Одинаковое предметное действие получает один UUID при повторной доставке."""
    return uuid5(NAMESPACE_URL, f"tentex:{project_id}:{key}")


def openings(session, project_id, config):
    """Открытия из журнала и старых занятий; один вопрос считается раз за учебный день."""
    from app.preparation.queue import day_start_at

    result = {}
    automatic_rows = [
        (a.node_id, a.occurred_at)
        for a in session.scalars(
            select(StudyActivity).where(
                StudyActivity.project_id == project_id, StudyActivity.node_id.is_not(None)
            )
        )
    ]
    automatic_rows.extend(
        (a.node_id, a.started_at)
        for a in session.scalars(
            select(StudyInterval).where(StudyInterval.project_id == project_id)
        )
    )
    for node_id, at in automatic_rows:
        day = study_date(at, config)
        started_at = day_start_at(session, project_id, day)
        if started_at is not None and utc(at) >= started_at:
            result.setdefault(day, set()).add(node_id)

    answer_rows = (
        (node_id, created_at)
        for node_id, created_at in session.execute(
            select(Activity.program_node_id, Attempt.created_at)
            .join(Attempt, Attempt.activity_id == Activity.id)
            .where(
                Attempt.project_id == project_id,
                Activity.kind == ActivityKind.FREE_ANSWER,
                Activity.program_node_id.is_not(None),
            )
        )
    )
    for node_id, at in answer_rows:
        day = study_date(at, config)
        result.setdefault(day, set()).add(node_id)
    return result


def record_event(session, project_id, kind, title, *, key, note="", at=None, node_id=None):
    """Уникальный ключ действия защищает достижения при повторной доставке."""
    session.execute(
        insert(StudyActivity)
        .values(
            id=event_id(project_id, key),
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
    """Просмотр закрывает назначение только после явного начала учебного дня."""
    from app.db import project_write_transaction
    from app.preparation.data import get_settings, require_project, units
    from app.preparation.queue import day_start_at
    from app.projects.errors import ProjectDomainError

    with project_write_transaction(session, project_id):
        require_project(session, project_id, writable=True)
        topic = next((u for u in units(session, project_id) if node_id in u.topic_ids), None)
        if topic is None:
            raise ProjectDomainError(
                "Вопрос не найден", status=404, code="preparation_unit_invalid"
            )
        moment = datetime.now(UTC)
        today = study_date(moment, get_settings(session, project_id).config)
        if day_start_at(session, project_id, today) is None:
            return False
        record_event(
            session,
            project_id,
            "view",
            topic.title,
            key=f"opened:{today}:{node_id}",
            node_id=node_id,
            at=moment,
        )
    return True


def record_unit_opening(session, project_id, unit_id, *, at=None, in_transaction=False):
    """Вопрос или билет засчитываются одной транзакцией только в начатый день."""
    from app.db import project_write_transaction
    from app.preparation.data import get_settings, require_project, units
    from app.preparation.queue import day_start_at
    from app.projects.errors import ProjectDomainError

    transaction = (
        nullcontext()
        if in_transaction
        else project_write_transaction(session, project_id)
    )
    with transaction:
        require_project(session, project_id, writable=True)
        unit = next((item for item in units(session, project_id) if item.id == unit_id), None)
        if unit is None:
            raise ProjectDomainError(
                "Единица программы не найдена",
                status=404,
                code="preparation_unit_invalid",
            )
        moment = at or datetime.now(UTC)
        today = study_date(moment, get_settings(session, project_id).config)
        if day_start_at(session, project_id, today) is None:
            return False
        for node_id in unit.topic_ids:
            record_event(
                session,
                project_id,
                "view",
                unit.title,
                key=f"opened:{today}:{node_id}",
                node_id=node_id,
                at=moment,
            )
    return True
