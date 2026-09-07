"""Согласованные сводки времени, попыток, статусов и причин назначения."""

from collections import Counter, defaultdict
from datetime import UTC, date, datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import GoalPassport, NodeType, ProjectStatus
from app.preparation.activity import counted_time_segments, history, time_totals
from app.preparation.calendar import budget_minutes, study_date
from app.preparation.data import (
    answer_presence,
    get_settings,
    node_path,
    program_nodes,
    require_project,
    target_level,
    units,
)
from app.preparation.evidence import TARGET_SUCCESSES, project_attempts, replay
from app.preparation.forecast import memory_forecast
from app.preparation.models import PreparationCoach, PreparationQueue, StudyActivity
from app.preparation.planner import day_loads, read_plan
from app.preparation.progress import milestones, openings, remaining_budget
from app.preparation.schemas import (
    CoachRead,
    DailyIntervalRead,
    OverviewRead,
    PreparationSummary,
    TopicProgress,
)


def topic_progress(session, project_id, config, unit_rows, *, before=None, rows=None):
    """Статус отражает учебные свидетельства; источник показывается отдельным признаком."""
    nodes = {n.id: n for n in program_nodes(session, project_id)}
    passport = session.get(GoalPassport, project_id)
    rows = project_attempts(session, project_id, before) if rows is None else rows
    evidence = replay(rows, config)
    references = answer_presence(session, project_id)
    query = select(StudyActivity).where(
        StudyActivity.project_id == project_id, StudyActivity.understood.is_(True)
    )
    if before:
        from app.preparation.calendar import naive_utc

        query = query.where(StudyActivity.occurred_at <= naive_utc(before))
    understood = {a.node_id for a in session.scalars(query)}
    topic_units = {t: u.id for u in unit_rows for t in u.topic_ids}
    latest_grade = {a.program_node_id: g for a, g, _ in rows if g is not None}
    independent_outcomes = {
        a.program_node_id: g.outcome.value
        for a, g, _ in rows
        if g and a.answer_mode == "memory" and a.parent_attempt_id is None
    }
    omissions = defaultdict(Counter)
    for attempt, grade, _ in rows:
        if grade:
            # Одна попытка даёт одно наблюдение пункта, даже если судья повторил его в разборе.
            points = {str(p.get("point", "")).strip() for p in grade.missed_points}
            omissions[attempt.program_node_id].update(point for point in points if point)
    result = []
    for node in nodes.values():
        if node.node_type != NodeType.TOPIC:
            continue
        ev = evidence.get(node.id)
        target = target_level(node, nodes, passport)
        count = ev.success_count if ev else 0
        required = TARGET_SUCCESSES[target]
        latest = ev.latest_outcome if ev else None
        status = "understood" if node.id in understood or count or latest == "passed" else "unseen"
        if count >= required:
            status = "practiced"
        if (
            status == "practiced"
            and independent_outcomes.get(node.id) == "passed"
            and ev.delayed_successes
        ):
            status = "mastered"
        due = (
            study_date(ev.last_at, config) + timedelta(days=ev.state.interval)
            if ev and ev.last_at
            else None
        )
        grade = latest_grade.get(node.id)
        missing = (
            [p.get("point", "") for p in grade.missed_points + grade.wrong_points] if grade else []
        )
        reason = f"Успешных самостоятельных ответов: {count}; для цели нужно {required}. " + (
            "Пройдено отложенное повторение."
            if ev and ev.delayed_successes
            else "Для освоения нужно успешное отложенное повторение."
        )
        result.append(
            TopicProgress(
                node_id=node.id,
                title=node.title,
                path=node_path(node, nodes),
                unit_id=topic_units.get(node.id, node.id),
                target_level=target,
                status=status,
                has_material=node.id in references,
                successful_attempts=count,
                required_successes=required,
                latest_outcome=latest,
                due=due,
                interval_days=ev.state.interval if ev else 0,
                reason=reason,
                missed_points=missing,
                recurring_omissions={
                    point: count for point, count in omissions[node.id].items() if count >= 2
                },
                active_seconds=0,
            )
        )
    return result, evidence


def local_coach(today, days, plan, summary) -> CoachRead:
    """Факты вычисляет сервер; офлайн-текст не обвиняет пользователя в неизвестных действиях."""
    current = next((d for d in days if d.date == today), None)
    yesterday = next((d for d in days if d.date == today - timedelta(days=1)), None)
    if not plan.items:
        return CoachRead(
            date=today,
            text="Задайте доступное время и распределите вопросы по дням.",
            origin="local",
            action="create",
        )
    minutes = current.remaining_minutes if current else 0
    if yesterday and yesterday.planned_count > yesterday.completed_count:
        remaining = yesterday.planned_count - yesterday.completed_count
        text = (
            f"Вчера завершены {yesterday.completed_count} из {yesterday.planned_count} заданий. "
            f"Осталось {remaining}. Сегодня доступно {minutes} минут — пересмотрите остаток."
        )
        return CoachRead(date=today, text=text, origin="local", action="redistribute")
    if current and current.is_rest:
        text = "Сегодня запланирован отдых. Следующее занятие можно открыть в календаре."
    elif summary.available_minutes >= summary.remaining_work_minutes:
        text = f"План укладывается в доступное время. Сегодня осталось {minutes} минут для занятий."
    else:
        text = (
            f"Работы больше, чем свободного времени. Сегодня доступно {minutes} минут; "
            "начните с повторений."
        )
    return CoachRead(date=today, text=text, origin="local", action="start")


def _streak(days, today, config, deadline):
    lookup = {d.date: d for d in days}
    streak = 0
    cursor = today
    if not lookup.get(cursor) or lookup[cursor].active_seconds == 0:
        cursor -= timedelta(days=1)
    for _ in range(len(days)):
        row = lookup.get(cursor)
        if row is None:
            break
        if row.active_seconds > 0:
            streak += 1
        elif budget_minutes(cursor, config, deadline) > 0:
            break
        cursor -= timedelta(days=1)
    return streak


def _summary(topics, rows, days, plan, unit_rows, today, config, deadline, by_kind):
    outcomes = Counter(g.outcome.value for _, g, _ in rows if g)
    pairs = [g for _, g, _ in rows if g and g.self_assessment and g.outcome.value != "unscored"]
    disagreement = sum(g.self_assessment != g.outcome for g in pairs)
    by_mode = defaultdict(Counter)
    for attempt, grade, _ in rows:
        by_mode[attempt.answer_mode or "unknown"][grade.outcome.value if grade else "pending"] += 1
    future = [d for d in days if d.date >= today]
    done = set(plan.completed_ids)
    remaining = sum(i.minutes for i in plan.items if i.id not in done)
    unit_map = {u.id: u for u in unit_rows}
    remaining += sum(unit_map[i].minutes for i in plan.unassigned_ids if i in unit_map)
    first_record = min((d.date for d in days if d.active_seconds > 0), default=None)
    observed = [
        d
        for d in days
        if first_record
        and first_record <= d.date
        and today - timedelta(days=7) <= d.date < today
        and not d.is_rest
    ]
    pace = sum(d.active_seconds for d in observed) / 60 / len(observed) if observed else None
    projected = None
    if pace and len(observed) >= 3:
        left = remaining
        for day in future:
            left -= min(pace, day.remaining_minutes)
            if left <= 0:
                projected = day.date
                break
    explanation = "Нужны минимум три учебных дня наблюдений"
    if len(observed) >= 3:
        explanation = "По среднему темпу последних семи дней, включая пропуски"
        if projected is None:
            explanation += "; текущего темпа недостаточно в выбранном сроке"
    return PreparationSummary(
        total_topics=len(topics),
        passed_topics=sum(t.status != "unseen" for t in topics),
        confirmed_topics=sum(t.status in {"practiced", "mastered"} for t in topics),
        mastered_topics=sum(t.status == "mastered" for t in topics),
        today_seconds=sum(d.active_seconds for d in days if d.date == today),
        week_seconds=sum(
            d.active_seconds for d in days if today - timedelta(days=6) <= d.date <= today
        ),
        streak_days=_streak(days, today, config, deadline),
        attempts_count=len(rows),
        passed_attempts=outcomes["passed"],
        partial_attempts=outcomes["partial"],
        failed_attempts=outcomes["failed"],
        pending_attempts=sum(g is None for _, g, _ in rows),
        disputed_attempts=disagreement,
        assessment_pairs=len(pairs),
        disagreement_percent=round(100 * disagreement / len(pairs), 1) if pairs else None,
        results_by_mode={mode: dict(counts) for mode, counts in by_mode.items()},
        memory_attempts=sum(a.answer_mode == "memory" for a, _, _ in rows),
        supported_attempts=sum(a.answer_mode == "supported" for a, _, _ in rows),
        available_minutes=sum(d.remaining_minutes for d in future),
        remaining_work_minutes=remaining,
        projected_finish=projected,
        pace_minutes_per_day=round(pace, 1) if pace is not None else None,
        pace_explanation=explanation,
        seconds_by_kind=dict(by_kind),
    )


def overview(
    session: Session,
    project_id: UUID,
    start: date | None = None,
    end: date | None = None,
    *,
    now: datetime | None = None,
) -> OverviewRead:
    """Единое серверное время предотвращает расхождение дня, бюджета и рекомендации."""
    now = now or datetime.now(UTC)
    project = require_project(session, project_id)
    settings = get_settings(session, project_id)
    config = settings.config
    today = study_date(now, config)
    start = min(start or study_date(project.created_at, config), today - timedelta(days=13))
    end = max(end or project.deadline or today + timedelta(days=30), today)
    if (end - start).days > 730:
        from app.projects.errors import ProjectDomainError

        raise ProjectDomainError(
            "Выберите диапазон календаря до двух лет", status=422, code="preparation_range_invalid"
        )
    unit_rows = units(session, project_id)
    plan = read_plan(session, project_id)
    rows = project_attempts(session, project_id, now)
    topics, evidence = topic_progress(session, project_id, config, unit_rows, rows=rows)
    days = day_loads(session, project_id, plan.items, start, end, now=now)
    opened = openings(session, project_id, config)
    first_opened = {}
    for day, node_ids in sorted(opened.items()):
        for node_id in node_ids:
            first_opened.setdefault(node_id, day)
    done = set(plan.completed_ids)
    by_kind, by_node = defaultdict(int), defaultdict(int)
    for day in days:
        kinds, nodes = time_totals(session, project_id, day.date, config)
        for k, seconds in kinds.items():
            by_kind[k] += seconds
        for k, seconds in nodes.items():
            by_node[k] += seconds
        day.opened_topic_ids = list(opened.get(day.date, set()))
        day.passed_count = sum(
            at <= day.date
            for node, at in first_opened.items()
            if node in {t.node_id for t in topics}
        )
        completed = [i for i in plan.items if i.on_date == day.date and i.id in done]
        day.opened_new_count = len({i.unit_id for i in completed if i.kind != "review"})
        day.opened_review_count = len({i.unit_id for i in completed if i.kind == "review"})
    for topic in topics:
        topic.active_seconds = by_node[topic.node_id]
    summary = _summary(
        topics, rows, days, plan, unit_rows, today, config, project.deadline, by_kind
    )
    passport = session.get(GoalPassport, project_id)
    exam_time = passport.exam_time if passport else None
    memory = memory_forecast(
        topics, evidence, unit_rows, plan.items, config, project.deadline, exam_time, now=now
    )
    coach = local_coach(today, days, plan, summary)
    saved = session.get(PreparationCoach, (project_id, today))
    if saved:
        coach = CoachRead(
            date=today,
            text=saved.text if saved.origin == "ai" and saved.text else coach.text,
            origin=saved.origin,
            action=saved.action if saved.origin == "ai" else coach.action,
            job_id=saved.job_id,
            reason=saved.reason,
        )
    intervals = []
    topic_names = {t.node_id: t.title for t in topics}
    for row, left, right in counted_time_segments(session, project_id, today, config):
        if (
            intervals
            and intervals[-1].node_id == row.node_id
            and intervals[-1].kind == row.kind
            and (left - intervals[-1].ended_at).total_seconds() <= 2
        ):
            intervals[-1].ended_at = right
            intervals[-1].seconds += int((right - left).total_seconds())
        else:
            intervals.append(
                DailyIntervalRead(
                    node_id=row.node_id,
                    title=topic_names.get(row.node_id, "Занятие"),
                    kind=row.kind,
                    started_at=left,
                    ended_at=right,
                    seconds=int((right - left).total_seconds()),
                )
            )
    events = history(session, project_id, limit=100000).items
    return OverviewRead(
        project_id=project_id,
        project_name=project.name or "Экзамен",
        now=now,
        readonly=project.status not in {ProjectStatus.ACTIVE, ProjectStatus.DRAFT},
        today=today,
        deadline=project.deadline,
        exam_time=exam_time,
        exam_at=datetime.combine(project.deadline, exam_time, ZoneInfo(config.timezone))
        if project.deadline and exam_time
        else None,
        settings=settings,
        plan=plan,
        units=unit_rows,
        days=days,
        topics=topics,
        summary=summary,
        memory=memory,
        coach=coach,
        today_intervals=intervals,
        day_started=session.get(PreparationQueue, (project_id, today)) is not None,
        budget=remaining_budget(days, config, today, project.deadline),
        milestones=milestones(events),
        recent_events=events[:3],
    )
