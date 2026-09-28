"""План по урокам и учёт времени на общих хранилищах подготовки."""

from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import select, update
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session

from app.db import project_write_transaction
from app.lesson_planning.schemas import (
    DistributionRead,
    DistributionWrite,
    LessonCandidate,
    LessonPlanItem,
    LessonPlanningRead,
    LessonTimeBatch,
    LessonTimeResult,
    LessonTimeRow,
    PlanWrite,
)
from app.models import (
    GoalPassport,
    Lesson,
    LessonBlock,
    LessonBlockKind,
    LessonSourceRef,
    LessonStatus,
    LessonTopic,
    ModuleKey,
    NodeType,
    Project,
    ProjectStatus,
    WorkspaceVariant,
)
from app.preparation.activity import time_segments
from app.preparation.calendar import day_bounds, naive_utc, study_date, utc
from app.preparation.data import get_settings, program_nodes
from app.preparation.models import PreparationPlan, StudyInterval
from app.projects.errors import ProjectDomainError, ProjectNotFoundError

MAX_DAYS = 730
FUTURE_TOLERANCE = timedelta(seconds=60)


def _project(
    session: Session, project_id: UUID, *, writable: bool = False, allow_disabled: bool = False
) -> Project:
    """Для времени после выключения остаётся доступна доставка накопленного буфера."""
    project = session.get(Project, project_id)
    if project is None or project.status == ProjectStatus.DRAFT:
        raise ProjectNotFoundError()
    if project.workspace_variant != WorkspaceVariant.TEXTBOOK:
        raise ProjectDomainError(
            "Планирование доступно в учебниковом проекте",
            status=422,
            code="lesson_planning_textbook_only",
        )
    if (
        not allow_disabled
        and ModuleKey.LESSON_PLANNING.value not in (project.enabled_modules or [])
    ):
        raise ProjectDomainError(
            "Включите планирование занятий в настройках проекта",
            status=409,
            code="lesson_planning_disabled",
        )
    if writable and project.status != ProjectStatus.ACTIVE:
        raise ProjectDomainError(
            "Проект доступен только для чтения", status=409, code="project_read_only"
        )
    return project


def _catalog(session: Session, project_id: UUID) -> list[LessonCandidate]:
    """Один урок с несколькими темами остаётся одной единицей календаря."""
    nodes = program_nodes(session, project_id)
    positions = {
        node.id: index
        for index, node in enumerate(nodes)
        if node.node_type in {NodeType.TOPIC, NodeType.SUBPOINT}
    }
    lessons = list(
        session.scalars(
            select(Lesson)
            .where(Lesson.project_id == project_id)
            .order_by(Lesson.created_at, Lesson.id)
        )
    )
    ids = [lesson.id for lesson in lessons]
    if not ids:
        return []
    topics: dict[UUID, list[UUID]] = defaultdict(list)
    for row in session.scalars(select(LessonTopic).where(LessonTopic.lesson_id.in_(ids))):
        topics[row.lesson_id].append(row.program_node_id)
    blocks = list(session.scalars(select(LessonBlock).where(LessonBlock.lesson_id.in_(ids))))
    source_ids = [block.id for block in blocks if block.kind == LessonBlockKind.SOURCE]
    referenced = (
        set(
            session.scalars(
                select(LessonSourceRef.block_id).where(LessonSourceRef.block_id.in_(source_ids))
            )
        )
        if source_ids
        else set()
    )
    content: set[UUID] = set()
    for block in blocks:
        if (
            (block.kind == LessonBlockKind.SOURCE and block.id in referenced)
            or (block.kind == LessonBlockKind.NOTE and bool((block.body_md or "").strip()))
            or (block.kind == LessonBlockKind.MEDIA and bool(block.media_path))
            or (block.kind == LessonBlockKind.ACTIVITY and block.activity_id is not None)
        ):
            content.add(block.lesson_id)
    passport = session.get(GoalPassport, project_id)
    fallback = (passport.session_minutes if passport else None) or 30
    ordered = sorted(
        lessons,
        key=lambda lesson: (
            min((positions[id] for id in topics[lesson.id] if id in positions), default=10**9),
            lesson.created_at,
            str(lesson.id),
        ),
    )
    return [
        LessonCandidate(
            id=lesson.id,
            title=lesson.title,
            minutes=lesson.duration_minutes or fallback,
            completed_at=lesson.completed_at,
            eligible=(
                lesson.status == LessonStatus.READY
                and lesson.id in content
                and any(node_id in positions for node_id in topics[lesson.id])
            ),
        )
        for lesson in ordered
    ]


def _items(row: PreparationPlan | None) -> list[LessonPlanItem]:
    return [LessonPlanItem.model_validate(item) for item in (row.items if row else [])]


def _rhythm(session: Session, project_id: UUID) -> tuple[int, int]:
    passport = session.get(GoalPassport, project_id)
    return (
        (passport.minutes_per_day if passport else None) or 60,
        (passport.days_per_week if passport else None) or 5,
    )


def _allocate(
    candidates: list[LessonCandidate],
    retained: list[LessonPlanItem],
    today: date,
    daily_minutes: int,
    days_per_week: int,
    deadline: date | None,
) -> list[LessonPlanItem]:
    """Раскладывает оставшееся в порядке программы, не дробя урок."""
    assigned = {item.lesson_id for item in retained}
    pending = [
        lesson for lesson in candidates
        if lesson.eligible and not lesson.completed_at and lesson.id not in assigned
    ]
    load = defaultdict(int)
    for item in retained:
        load[item.on_date] += item.minutes
    result = list(retained)
    cursor = 0
    for offset in range(MAX_DAYS):
        if cursor >= len(pending):
            break
        day = today + timedelta(days=offset)
        if deadline and day > deadline:
            break
        if day.weekday() >= days_per_week:
            continue
        while cursor < len(pending):
            lesson = pending[cursor]
            if load[day] and load[day] + lesson.minutes > daily_minutes:
                break
            result.append(
                LessonPlanItem(
                    id=uuid4(),
                    lesson_id=lesson.id,
                    title=lesson.title,
                    on_date=day,
                    minutes=lesson.minutes,
                    origin="local",
                )
            )
            load[day] += lesson.minutes
            cursor += 1
            if load[day] >= daily_minutes:
                break
    return sorted(result, key=lambda item: (item.on_date, str(item.id)))


def _forecast(
    candidates: list[LessonCandidate],
    items: list[LessonPlanItem],
    today: date,
    daily_minutes: int,
    days_per_week: int,
) -> date | None:
    """Оценка завершения продолжает текущий план за дедлайн, если нужно."""
    remaining = [lesson for lesson in candidates if lesson.eligible and not lesson.completed_at]
    if not remaining:
        return None
    # Просроченное назначение остаётся фактом плана, но незавершённый урок
    # снова участвует только в прогнозе будущей даты.
    future_items = [item for item in items if item.on_date >= today]
    future = _allocate(candidates, future_items, today, daily_minutes, days_per_week, None)
    remaining_ids = {lesson.id for lesson in remaining}
    scheduled = [item.on_date for item in future if item.lesson_id in remaining_ids]
    return max(scheduled, default=None)


def _today_time(
    session: Session, project_id: UUID, today: date
) -> tuple[int, list[LessonTimeRow]]:
    start, end = day_bounds(today, get_settings(session, project_id).config)
    grouped: dict[UUID | None, int] = defaultdict(int)
    titles: dict[UUID | None, str] = {}
    for row, left, right in time_segments(session, project_id, start, end):
        if row.kind == "lesson":
            grouped[row.lesson_id] += int((right - left).total_seconds())
            titles[row.lesson_id] = row.lesson_title or "Удалённый урок"
    title_rows = session.execute(
        select(Lesson.id, Lesson.title).where(Lesson.project_id == project_id)
    ).all()
    current_titles = dict(title_rows)
    rows = [
        LessonTimeRow(
            lesson_id=lesson_id,
            title=current_titles.get(lesson_id, titles[lesson_id]),
            seconds=seconds,
        )
        for lesson_id, seconds in grouped.items()
    ]
    rows.sort(key=lambda item: (-item.seconds, item.title))
    return sum(item.seconds for item in rows), rows


def overview(session: Session, project_id: UUID) -> LessonPlanningRead:
    """Снимок плана и небольшая фактическая сводка за учебные сутки."""
    project = _project(session, project_id)
    today = study_date(datetime.now(UTC), get_settings(session, project_id).config)
    candidates = _catalog(session, project_id)
    by_id = {lesson.id: lesson for lesson in candidates}
    row = session.get(PreparationPlan, project_id)
    items = _items(row)
    assigned = {item.lesson_id for item in items}
    daily_minutes, days_per_week = _rhythm(session, project_id)
    seconds, breakdown = _today_time(session, project_id, today)
    return LessonPlanningRead(
        revision=row.revision if row else 0,
        today=today,
        deadline=project.deadline,
        daily_minutes=daily_minutes,
        days_per_week=days_per_week,
        readonly=project.status != ProjectStatus.ACTIVE,
        lessons=candidates,
        items=items,
        unassigned_ids=[
            lesson.id for lesson in candidates
            if lesson.eligible and not lesson.completed_at and lesson.id not in assigned
        ],
        unavailable_ids=[
            item.id for item in items
            if item.lesson_id not in by_id or not by_id[item.lesson_id].eligible
        ],
        estimated_finish=_forecast(candidates, items, today, daily_minutes, days_per_week),
        outside_deadline_count=sum(
            project.deadline is not None and item.on_date > project.deadline for item in items
        ),
        today_seconds=seconds,
        today_by_lesson=breakdown,
    )


def preview(
    session: Session, project_id: UUID, command: DistributionWrite
) -> DistributionRead:
    """Предпросмотр не пишет БД и сохраняет ручные, прошлые и завершённые назначения."""
    _project(session, project_id, writable=True)
    current = overview(session, project_id)
    by_id = {lesson.id: lesson for lesson in current.lessons}
    retained = [
        item for item in current.items
        if command.mode == "append"
        or item.origin == "manual"
        or item.on_date < current.today
        or item.lesson_id not in by_id
        or not by_id[item.lesson_id].eligible
        or bool(by_id[item.lesson_id].completed_at)
    ]
    items = _allocate(
        current.lessons, retained, current.today, current.daily_minutes,
        current.days_per_week, current.deadline,
    )
    assigned = {item.lesson_id for item in items}
    return DistributionRead(
        base_revision=current.revision,
        items=items,
        unassigned_ids=[
            lesson.id for lesson in current.lessons
            if lesson.eligible and not lesson.completed_at and lesson.id not in assigned
        ],
        estimated_finish=_forecast(
            current.lessons, items, current.today, current.daily_minutes, current.days_per_week
        ),
    )


def save_plan(session: Session, project_id: UUID, command: PlanWrite) -> LessonPlanningRead:
    """Одна ревизия защищает и ручной перенос, и применение предпросмотра."""
    with project_write_transaction(session, project_id):
        project = _project(session, project_id, writable=True)
        old = session.get(PreparationPlan, project_id)
        old_items = _items(old)
        if (old.revision if old else 0) != command.expected_revision:
            raise ProjectDomainError(
                "План изменился в другом окне. Обновите данные.",
                status=409,
                code="lesson_plan_stale",
            )
        today = study_date(datetime.now(UTC), get_settings(session, project_id).config)
        candidates = {lesson.id: lesson for lesson in _catalog(session, project_id)}
        previous = {item.id: item for item in old_items}
        incoming = {item.id: item for item in command.items}
        lesson_ids = [item.lesson_id for item in command.items]
        if len(incoming) != len(command.items) or len(set(lesson_ids)) != len(lesson_ids):
            raise ProjectDomainError(
                "Урок не может быть назначен дважды", status=422, code="lesson_plan_duplicate"
            )
        for item in old_items:
            lesson = candidates.get(item.lesson_id)
            protected = item.on_date < today or bool(lesson and lesson.completed_at)
            if protected and incoming.get(item.id) != item:
                raise ProjectDomainError(
                    "Прошедшие и завершённые назначения сохраняются",
                    status=409,
                    code="lesson_plan_protected",
                )
        for item in command.items:
            if previous.get(item.id) == item:
                continue
            lesson = candidates.get(item.lesson_id)
            if not lesson or not lesson.eligible or lesson.completed_at:
                raise ProjectDomainError(
                    "Урок недоступен для планирования",
                    status=422,
                    code="lesson_plan_unavailable",
                )
            if (
                item.on_date < today
                or (item.on_date - today).days >= MAX_DAYS
                or (project.deadline and item.on_date > project.deadline)
            ):
                raise ProjectDomainError(
                    "Дата урока вне доступного срока", status=422, code="lesson_plan_date"
                )
        if command.items != old_items:
            session.execute(
                insert(PreparationPlan)
                .values(
                    project_id=project_id, revision=0, program_revision=project.program_revision,
                    settings_revision=0, phases=[], items=[],
                )
                .on_conflict_do_nothing()
            )
            count = session.execute(
                update(PreparationPlan)
                .where(
                    PreparationPlan.project_id == project_id,
                    PreparationPlan.revision == command.expected_revision,
                )
                .values(
                    revision=command.expected_revision + 1,
                    program_revision=project.program_revision,
                    items=[item.model_dump(mode="json") for item in command.items],
                )
            ).rowcount
            if count != 1:
                raise ProjectDomainError(
                    "План изменился в другом окне. Обновите данные.",
                    status=409,
                    code="lesson_plan_stale",
                )
    return overview(session, project_id)


def add_intervals(
    session: Session, project_id: UUID, command: LessonTimeBatch
) -> LessonTimeResult:
    """Доставляет интервалы идемпотентно; после выключения обрезает хвост."""
    with project_write_transaction(session, project_id):
        project = _project(session, project_id, allow_disabled=True, writable=True)
        enabled = ModuleKey.LESSON_PLANNING.value in (project.enabled_modules or [])
        catalog = {lesson.id: lesson for lesson in _catalog(session, project_id)}
        accepted, ignored = [], []
        latest = datetime.now(UTC) + FUTURE_TOLERANCE
        for interval in command.intervals:
            existing = session.get(StudyInterval, interval.id)
            if existing:
                if (
                    existing.project_id != project_id
                    or existing.session_id != interval.session_id
                    or existing.lesson_id != interval.lesson_id
                    or existing.kind != "lesson"
                    or existing.started_at != naive_utc(interval.started_at)
                    or existing.ended_at > naive_utc(interval.ended_at)
                ):
                    raise ProjectDomainError(
                        "Идентификатор интервала уже использован",
                        status=409,
                        code="study_interval_conflict",
                    )
                accepted.append(interval.id)
                continue
            lesson = catalog.get(interval.lesson_id)
            end = interval.ended_at
            if not enabled:
                cutoff = project.lesson_planning_disabled_at
                if cutoff is None:
                    ignored.append(interval.id)
                    continue
                end = min(end, utc(cutoff))
            if (
                lesson is None or not lesson.eligible
                or interval.ended_at > latest
                or end <= interval.started_at
            ):
                ignored.append(interval.id)
                continue
            session.add(
                StudyInterval(
                    id=interval.id,
                    project_id=project_id,
                    node_id=None,
                    lesson_id=interval.lesson_id,
                    lesson_title=lesson.title,
                    session_id=interval.session_id,
                    kind="lesson",
                    started_at=naive_utc(interval.started_at),
                    ended_at=naive_utc(end),
                )
            )
            accepted.append(interval.id)
    return LessonTimeResult(accepted_ids=accepted, ignored_ids=ignored)
