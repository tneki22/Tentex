"""Офлайновый календарь: черновики, ревизии и неделимые билеты."""

from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from math import ceil
from uuid import UUID, uuid4

from sqlalchemy import select, update
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session

from app.db import project_write_transaction
from app.models import GoalPassport
from app.preparation.activity import completed_items, time_totals
from app.preparation.calendar import budget_minutes, capacity_minutes, dates_between, study_date
from app.preparation.data import get_settings, require_project, units
from app.preparation.models import (
    PreparationDraft,
    PreparationPlan,
    PreparationSettings,
    PreparationVersion,
)
from app.preparation.progress import record_event
from app.preparation.schemas import (
    ApplyDraftWrite,
    DayLoad,
    DraftRead,
    DraftWrite,
    Phase,
    PlanItem,
    PlanRead,
    RevisionWrite,
    SettingsRead,
    SettingsWrite,
)
from app.projects.errors import ProjectDomainError

MAX_PLAN_DAYS = 730  # Ограничение размера редактируемого локального документа.


def allocation_date(day: date, today: date, deadline: date | None, phases=()) -> bool:
    """Общий фильтр локальной и ИИ-раскладки: будущие дни без экзамена и отдыха."""
    if day <= today or (deadline and day >= deadline):
        return False
    if deadline and (deadline - today).days >= 5 and day == deadline - timedelta(days=1):
        return False
    return not any(p.kind in {"rest", "skip"} and p.start <= day <= p.end for p in phases)


def conflict(detail: str = "План изменился в другом окне. Обновите данные.") -> ProjectDomainError:
    """Все stale-конфликты имеют один устойчивый код для перечитывания интерфейса."""
    return ProjectDomainError(detail, status=409, code="preparation_stale")


def read_plan(session: Session, project_id: UUID) -> PlanRead:
    """GET не создаёт пустые строки; отсутствие плана представлено нулевой ревизией."""
    project = require_project(session, project_id)
    settings = get_settings(session, project_id)
    row = session.get(PreparationPlan, project_id)
    phases = [Phase.model_validate(p) for p in row.phases] if row else []
    items = [PlanItem.model_validate(i) for i in row.items] if row else []
    unit_rows = units(session, project_id)
    done = completed_items(session, project_id, items, unit_rows, settings.config)
    assigned = {i.unit_id for i in items if i.kind in {"learn", "answer"}}
    can_undo = session.scalar(
        select(PreparationVersion.revision)
        .where(PreparationVersion.project_id == project_id, PreparationVersion.undone.is_(False))
        .limit(1)
    )
    return PlanRead(
        revision=row.revision if row else 0,
        program_revision=project.program_revision,
        settings_revision=settings.revision,
        stale=bool(
            row
            and (
                row.program_revision != project.program_revision
                or row.settings_revision != settings.revision
            )
        ),
        phases=phases,
        items=items,
        completed_ids=list(done),
        unassigned_ids=[u.id for u in unit_rows if u.id not in assigned],
        can_undo=can_undo is not None,
    )


def save_settings(session: Session, project_id: UUID, command: SettingsWrite) -> SettingsRead:
    """Compare-and-swap защищает бюджет, влияющий на одновременно созданные черновики."""
    with project_write_transaction(session, project_id):
        require_project(session, project_id, writable=True)
        session.execute(
            insert(PreparationSettings)
            .values(project_id=project_id, revision=0, config={})
            .on_conflict_do_nothing()
        )
        count = session.execute(
            update(PreparationSettings)
            .where(
                PreparationSettings.project_id == project_id,
                PreparationSettings.revision == command.expected_revision,
            )
            .values(
                revision=command.expected_revision + 1,
                config=command.config.model_dump(mode="json"),
            )
        ).rowcount
        if count != 1:
            raise conflict("Настройки изменились в другом окне. Обновите данные.")
    return SettingsRead(revision=command.expected_revision + 1, config=command.config)


def validate_revisions(
    session: Session,
    project_id: UUID,
    plan_revision: int,
    program_revision: int,
    settings_revision: int,
):
    """Проверка программы и настроек обязательна при preview и при apply."""
    project = require_project(session, project_id, writable=True)
    plan = read_plan(session, project_id)
    settings = get_settings(session, project_id)
    if (plan.revision, project.program_revision, settings.revision) != (
        plan_revision,
        program_revision,
        settings_revision,
    ):
        raise conflict()
    return project, plan, settings


def default_phases(start: date, end: date, config, deadline: date | None) -> list[Phase]:
    """Начальный первичный проход занимает примерно 60% учебных дней при длинном сроке."""
    study_days = [d for d in dates_between(start, end) if budget_minutes(d, config, deadline) > 0]
    if not study_days:
        return []
    if len(study_days) < 3:
        return [
            Phase(
                id=uuid4(),
                title="Первичный проход",
                start=study_days[0],
                end=study_days[-1],
                kind="learn",
                origin="local",
            )
        ]
    pass_count = round(len(study_days) * 0.6) if len(study_days) >= 7 else len(study_days) - 1
    phases = [
        Phase(
            id=uuid4(),
            title="Первичный проход",
            start=study_days[0],
            end=study_days[pass_count - 1],
            kind="learn",
            origin="local",
        )
    ]
    if pass_count < len(study_days) - 1:
        phases.append(
            Phase(
                id=uuid4(),
                title="Повторение и пробелы",
                kind="review",
                start=study_days[pass_count],
                end=study_days[-2],
                order=1,
                origin="local",
            )
        )
    phases.append(
        Phase(
            id=uuid4(),
            title="Финальный прогон",
            kind="final",
            start=study_days[-1],
            end=study_days[-1],
            order=2,
            origin="local",
        )
    )
    return phases


def day_loads(
    session: Session,
    project_id: UUID,
    items: list[PlanItem],
    start: date,
    end: date,
    *,
    now: datetime | None = None,
) -> list[DayLoad]:
    """Одна строка на учебную дату вне зависимости от пересекающихся фаз."""
    now = now or datetime.now(UTC)
    project = require_project(session, project_id)
    config = get_settings(session, project_id).config
    passport = session.get(GoalPassport, project_id)
    exam_time = passport.exam_time if passport else None
    today = study_date(now, config)
    done = completed_items(session, project_id, items, units(session, project_id), config)
    grouped = defaultdict(list)
    for item in items:
        grouped[item.on_date].append(item)
    phases = read_plan(session, project_id).phases
    result = []
    for day in dates_between(start, end):
        active = sum(time_totals(session, project_id, day, config)[0].values())
        capacity = capacity_minutes(day, config, project.deadline, exam_time)
        remaining = (
            capacity_minutes(day, config, project.deadline, exam_time, now=now, used_seconds=active)
            if day >= today
            else 0
        )
        if any(p.kind in {"rest", "skip"} and p.start <= day <= p.end for p in phases):
            capacity, remaining = 0, 0
        planned = sum(i.minutes for i in grouped[day])
        result.append(
            DayLoad(
                date=day,
                capacity_minutes=capacity,
                remaining_minutes=remaining,
                planned_minutes=planned,
                active_seconds=active,
                planned_count=len(grouped[day]),
                completed_count=sum(i.id in done for i in grouped[day]),
                overload_minutes=max(0, planned - capacity),
                is_rest=capacity == 0,
                new_count=sum(i.kind in {"learn", "answer"} for i in grouped[day]),
                review_count=sum(i.kind in {"review", "gaps", "final"} for i in grouped[day]),
            )
        )
    return result


def _validate_document(
    phases: list[Phase], items: list[PlanItem], unit_rows, *, previous=()
) -> None:
    phase_map, unit_map = {p.id: p for p in phases}, {u.id: u for u in unit_rows}
    if len(phase_map) != len(phases) or len({i.id for i in items}) != len(items):
        raise ProjectDomainError(
            "Повторяющиеся идентификаторы в плане", status=422, code="preparation_duplicate"
        )
    ordered = sorted(phases, key=lambda phase: phase.start)
    for left, right in zip(ordered, ordered[1:], strict=False):
        if left.end >= right.start:
            raise ProjectDomainError(
                f"Блоки «{left.title}» и «{right.title}» пересекаются",
                status=422,
                code="preparation_phase_overlap",
            )
    seen = set()
    archived = {i.id: i for i in previous if i.unit_id not in unit_map}
    for item in items:
        key = (item.unit_id, item.on_date, item.kind)
        if key in seen or (item.unit_id not in unit_map and archived.get(item.id) != item):
            raise ProjectDomainError(
                "Дубль назначения или часть неделимого билета",
                status=422,
                code="preparation_unit_invalid",
            )
        seen.add(key)
        # Старые phase_id читаются для совместимости; блок больше не владеет назначением.


def _protect_existing(plan: PlanRead, proposed: list[PlanItem], today: date, *, manual: bool):
    by_id = {i.id: i for i in proposed}
    for old in plan.items:
        protected = (
            old.on_date < today or old.id in plan.completed_ids or (old.pinned and not manual)
        )
        proposed_item = by_id.get(old.id)
        unchanged = proposed_item == old or (
            manual
            and proposed_item is not None
            and proposed_item.model_copy(update={"phase_id": old.phase_id}) == old
        )
        if protected and not unchanged:
            raise ProjectDomainError(
                "Прошлые, выполненные и закреплённые задания сохраняются",
                status=409,
                code="preparation_protected_item",
            )


def _distribute(session, project_id, command, project, plan, settings, now):
    """Локальная раскладка сохраняет порядок дерева и не делит тяжёлые билеты."""
    config = settings.config
    today = study_date(now, config)
    start = max(today, command.start or today)
    end = command.end or project.deadline or start + timedelta(days=13)
    if (end - start).days > MAX_PLAN_DAYS or end < start:
        raise ProjectDomainError(
            "Выберите срок до двух лет, заканчивающийся не раньше начала",
            status=422,
            code="preparation_range_invalid",
        )
    phases = command.phases if command.phases is not None else plan.phases
    retained = list(plan.items)
    # Долг — отдельная операция: прошлую запись оставляем, перенос создаёт новое назначение.
    if command.mode in {"spread", "catch_up", "dismiss"}:
        return _recovery(session, project_id, command, plan, phases, start, end, now)
    capacities = {
        d.date: d.remaining_minutes for d in day_loads(session, project_id, [], start, end, now=now)
    }
    load, counts = defaultdict(int), defaultdict(int)
    for item in retained:
        if item.id not in plan.completed_ids:
            load[item.on_date] += item.minutes
            counts[item.on_date] += 1
    assigned = {i.unit_id for i in retained if i.kind in {"learn", "answer"}}
    unit_rows = units(session, project_id)
    if command.unit_ids is not None:
        selected = set(command.unit_ids)
        if selected - {u.id for u in unit_rows}:
            raise ProjectDomainError(
                "В списке есть часть билета или неизвестный вопрос",
                status=422,
                code="preparation_unit_invalid",
            )
        unit_rows = [u for u in unit_rows if u.id in selected]
    occupied = {i.on_date for i in retained}
    candidates = [
        d
        for d in capacities
        if d not in occupied
        and capacities[d] > 0
        and allocation_date(d, today, project.deadline, phases)
    ]
    items = list(retained)
    pending_count = sum(unit.id not in assigned for unit in unit_rows)
    daily_target = max(1, ceil(pending_count / max(1, len(candidates))))
    cursor = candidates[0] if candidates else end
    for unit in unit_rows:
        if unit.id in assigned:
            continue
        available = [d for d in candidates if d >= cursor]
        if command.mode == "count":
            available = [d for d in available if counts[d] < daily_target]
        # Соседние вопросы остаются рядом; следующий день начинается после дневной квоты.
        possible = [
            d
            for d in available
            if load[d] + unit.minutes <= capacities[d] and counts[d] < config.max_new_per_day
        ]
        chosen = min(possible) if possible else None
        if chosen is None:
            continue
        cursor = chosen
        items.append(
            PlanItem(
                id=uuid4(),
                unit_id=unit.id,
                on_date=chosen,
                minutes=unit.minutes,
                phase_id=None,
                order=counts[chosen],
                origin="local",
                estimate_source=unit.estimate_source,
                reason="Равномерно по количеству"
                if command.mode == "count"
                else "По свободному бюджету и ожидаемому времени",
            )
        )
        load[chosen] += unit.minutes
        counts[chosen] += 1
    return phases, items


def _recovery(session, project_id, command, plan, phases, start, end, now):
    """Прошлый факт не переписывается; черновик переносит только выбранный остаток."""
    items = list(plan.items)
    today = study_date(now, get_settings(session, project_id).config)
    debt = [
        i
        for i in items
        if i.on_date < today
        and i.id not in plan.completed_ids
        and (not i.pinned or command.include_pinned)
    ]
    if command.unit_ids is not None:
        debt = [i for i in debt if i.unit_id in command.unit_ids]
    if command.mode == "dismiss":
        # Явное снятие долга разрешено только этой командой, не обычным пересчётом.
        return phases, [i for i in items if i not in debt]
    loads = day_loads(session, project_id, items, start, end, now=now)
    config = get_settings(session, project_id).config
    deadline = require_project(session, project_id).deadline
    new_counts = {d.date: d.new_count for d in loads}
    review_counts = {d.date: d.review_count for d in loads}
    remaining = {d.date: max(0, d.remaining_minutes - d.planned_minutes) for d in loads}
    occupied = {i.on_date for i in plan.items}
    for old in debt:
        if old.pinned and not command.include_pinned:
            continue
        is_new = old.kind in {"learn", "answer"}
        candidates = [
            d
            for d in remaining
            if remaining[d] >= old.minutes
            and d not in occupied
            and allocation_date(d, today, deadline, phases)
            and (
                new_counts[d] < config.max_new_per_day
                if is_new
                else review_counts[d] < config.max_reviews_per_day
            )
        ]
        if not candidates:
            continue
        chosen = (
            min(candidates)
            if command.mode == "catch_up"
            else max(candidates, key=lambda d: (remaining[d], -d.toordinal()))
        )
        items.remove(old)
        items.append(
            old.model_copy(
                update={
                    "on_date": chosen,
                    "phase_id": None,
                    "origin": "local",
                    "reason": "Перенесено после пропуска",
                }
            )
        )
        remaining[chosen] -= old.minutes
        (new_counts if is_new else review_counts)[chosen] += 1
    return phases, items


def create_draft(
    session: Session,
    project_id: UUID,
    command: DraftWrite,
    *,
    origin="local",
    now: datetime | None = None,
) -> DraftRead:
    """Сначала серверный preview; никакой алгоритм не меняет календарь непосредственно."""
    now = now or datetime.now(UTC)
    with project_write_transaction(session, project_id):
        project, plan, settings = validate_revisions(
            session,
            project_id,
            command.expected_plan_revision,
            command.expected_program_revision,
            command.expected_settings_revision,
        )
        if command.mode == "manual":
            phases = command.phases if command.phases is not None else plan.phases
            items = command.items if command.items is not None else plan.items
        else:
            if settings.config.daily_minutes is None and command.mode != "dismiss":
                raise ProjectDomainError(
                    "Сначала задайте дневной бюджет занятий",
                    status=422,
                    code="preparation_budget_missing",
                )
            phases, items = _distribute(session, project_id, command, project, plan, settings, now)
        unit_rows = units(session, project_id)
        _validate_document(phases, items, unit_rows, previous=plan.items)
        if command.mode not in {"spread", "catch_up", "dismiss"}:
            _protect_existing(
                plan, items, study_date(now, settings.config), manual=command.mode == "manual"
            )
        else:
            for old in plan.items:
                if (
                    old.id in plan.completed_ids or (old.pinned and not command.include_pinned)
                ) and next((i for i in items if i.id == old.id), None) != old:
                    raise ProjectDomainError(
                        "Выполнение и закрепления сохраняются при переносе долга",
                        status=409,
                        code="preparation_protected_item",
                    )
        return persist_draft(
            session,
            project_id,
            plan,
            settings.revision,
            project.program_revision,
            phases,
            items,
            origin,
            now,
            recovery=command.mode in {"spread", "catch_up", "dismiss"},
            allow_pinned=command.include_pinned,
        )


def persist_draft(
    session,
    project_id,
    plan,
    settings_revision,
    program_revision,
    phases,
    items,
    origin,
    now,
    *,
    recovery=False,
    allow_pinned=False,
    unassigned_reasons=None,
) -> DraftRead:
    """Общее сохранение для алгоритма и проверенного предложения модели, внутри транзакции."""
    before = {i.id: i for i in plan.items}
    after = {i.id: i for i in items}
    removed = list(before.keys() - after.keys())
    unit_rows = units(session, project_id)
    assigned = {i.unit_id for i in items if i.kind in {"learn", "answer"}}
    changed = [i for i in items if before.get(i.id) != i]
    changes = [f"Изменено назначений: {len(changed)}", f"Снято назначений: {len(removed)}"]
    if phases != plan.phases:
        changes.append(f"Блоков в новом плане: {len(phases)}")
    dates = [i.on_date for i in items] + [study_date(now, get_settings(session, project_id).config)]
    start, end = min(dates), max(dates)
    result = DraftRead(
        id=uuid4(),
        base_revision=plan.revision,
        program_revision=program_revision,
        settings_revision=settings_revision,
        phases=phases,
        items=items,
        removed_ids=removed,
        unassigned_ids=[u.id for u in unit_rows if u.id not in assigned],
        unassigned_reasons=unassigned_reasons or {},
        changes=changes,
        days=day_loads(session, project_id, items, start, end, now=now),
        origin=origin,
    )
    session.add(
        PreparationDraft(
            id=result.id,
            project_id=project_id,
            base_revision=plan.revision,
            program_revision=program_revision,
            settings_revision=settings_revision,
            payload={
                **result.model_dump(mode="json"),
                "recovery": recovery,
                "allow_pinned": allow_pinned,
            },
            origin=origin,
        )
    )
    return result


def get_draft(session: Session, project_id: UUID, draft_id: UUID) -> DraftRead:
    """Черновик чужого проекта не выдаётся даже при знании UUID."""
    require_project(session, project_id)
    row = session.get(PreparationDraft, draft_id)
    if row is None or row.project_id != project_id:
        raise ProjectDomainError(
            "Черновик не найден", status=404, code="preparation_draft_not_found"
        )
    return DraftRead.model_validate(
        {k: v for k, v in row.payload.items() if k not in {"recovery", "allow_pinned"}}
    )


def _write_version(session, project_id, plan, phases, items, program_revision, settings_revision):
    session.execute(
        insert(PreparationPlan)
        .values(
            project_id=project_id,
            revision=0,
            program_revision=program_revision,
            settings_revision=settings_revision,
            phases=[],
            items=[],
        )
        .on_conflict_do_nothing()
    )
    count = session.execute(
        update(PreparationPlan)
        .where(
            PreparationPlan.project_id == project_id,
            PreparationPlan.revision == plan.revision,
        )
        .values(
            revision=plan.revision + 1,
            program_revision=program_revision,
            settings_revision=settings_revision,
            phases=[p.model_dump(mode="json") for p in phases],
            items=[i.model_dump(mode="json") for i in items],
        )
    ).rowcount
    if count != 1:
        raise conflict()
    session.add(
        PreparationVersion(
            project_id=project_id, revision=plan.revision + 1, snapshot=plan.model_dump(mode="json")
        )
    )


def apply_draft(
    session: Session, project_id: UUID, draft_id: UUID, command: ApplyDraftWrite
) -> PlanRead:
    """Выборочное применение снова проверяет документ и ревизии в транзакции."""
    with project_write_transaction(session, project_id):
        draft = get_draft(session, project_id, draft_id)
        row = session.get(PreparationDraft, draft_id)
        if row.applied_revision is not None:
            return read_plan(session, project_id)
        project, plan, settings = validate_revisions(
            session,
            project_id,
            draft.base_revision,
            draft.program_revision,
            draft.settings_revision,
        )
        phases = draft.phases if command.apply_phases else plan.phases
        selected = set(command.selected_item_ids) if command.selected_item_ids is not None else None
        if selected is None:
            items = draft.items
        else:
            items = [i for i in plan.items if i.id not in selected]
            items.extend(i for i in draft.items if i.id in selected)
        _validate_document(phases, items, units(session, project_id), previous=plan.items)
        if not row.payload.get("recovery"):
            _protect_existing(
                plan,
                items,
                study_date(datetime.now(UTC), settings.config),
                manual=draft.origin != "ai",
            )
        else:
            for old in plan.items:
                if (
                    old.id in plan.completed_ids
                    or (old.pinned and not row.payload.get("allow_pinned"))
                ) and next((i for i in items if i.id == old.id), None) != old:
                    raise conflict("Задание выполнено или закреплено после создания черновика")
        if items == plan.items and phases == plan.phases:
            row.applied_revision = plan.revision
            return plan
        _write_version(
            session, project_id, plan, phases, items, project.program_revision, settings.revision
        )
        if items != plan.items or phases != plan.phases:
            distribution = bool(
                [i for i in items if i not in plan.items and i.origin in {"local", "ai"}]
            )
            record_event(
                session,
                project_id,
                "plan_change",
                "Распределены вопросы" if distribution else "Обновлён план подготовки",
                key=f"plan:{plan.revision + 1}",
                note="distribution" if distribution else "edit",
            )
        row.applied_revision = plan.revision + 1
        session.flush()
        result = read_plan(session, project_id)
    return result


def undo(session: Session, project_id: UUID, command: RevisionWrite) -> PlanRead:
    """Отменяем последнюю неотменённую редакцию, сохраняя монотонность ревизий."""
    with project_write_transaction(session, project_id):
        require_project(session, project_id, writable=True)
        plan = read_plan(session, project_id)
        if plan.revision != command.expected_revision:
            raise conflict()
        version = session.scalar(
            select(PreparationVersion)
            .where(
                PreparationVersion.project_id == project_id, PreparationVersion.undone.is_(False)
            )
            .order_by(PreparationVersion.revision.desc())
            .limit(1)
        )
        if version is None:
            raise ProjectDomainError(
                "Нет изменения для отмены", status=409, code="preparation_nothing_to_undo"
            )
        snapshot = PlanRead.model_validate(version.snapshot)
        count = session.execute(
            update(PreparationPlan)
            .where(
                PreparationPlan.project_id == project_id, PreparationPlan.revision == plan.revision
            )
            .values(
                revision=plan.revision + 1,
                phases=[p.model_dump(mode="json") for p in snapshot.phases],
                items=[i.model_dump(mode="json") for i in snapshot.items],
                program_revision=snapshot.program_revision,
                settings_revision=snapshot.settings_revision,
            )
        ).rowcount
        if count != 1:
            raise conflict()
        version.undone = True
        session.flush()
        result = read_plan(session, project_id)
    return result
