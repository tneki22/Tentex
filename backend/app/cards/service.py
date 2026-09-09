"""Бизнес-логика карточек без назначения календарных повторений."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from statistics import mean
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.cards.schemas import (
    CardAnalyticsRead,
    CardBulkWrite,
    CardCreate,
    CardListRead,
    CardOverviewRead,
    CardRead,
    CardSessionCreate,
    CardSessionRead,
    CardSessionSummaryRead,
    CardSourceRead,
    CardSourceWrite,
    CardUnitRead,
    CardUpdate,
    ConfidenceBucket,
    FragmentPrefillRead,
    SessionCardRead,
    SessionDeferWrite,
    SessionFinishWrite,
    SessionProgressWrite,
    SessionRetryWrite,
    SessionReviewWrite,
    TodayUnitRead,
)
from app.db import project_write_transaction
from app.models import (
    Activity,
    ActivityKind,
    ActivityOrigin,
    Attempt,
    AttemptOutcome,
    Binding,
    BindingStatus,
    Card,
    CardSession,
    CardSessionPace,
    CardSessionScope,
    CardSessionState,
    CardSourceKind,
    CardState,
    Grade,
    GradeMethod,
    Material,
    MaterialFragment,
    MaterialPage,
    ProjectMaterial,
    ReferenceAnswer,
    utc_now,
)
from app.preparation.calendar import day_bounds, study_date
from app.preparation.data import get_settings, require_project, units
from app.preparation.models import PreparationPlan
from app.preparation.progress import record_unit_opening
from app.projects.errors import ProjectConflictError, ProjectDomainError

ACTIVE_BINDINGS = {BindingStatus.MACHINE, BindingStatus.CONFIRMED, BindingStatus.MANUAL}
CARD_SECONDS_ESTIMATE = 30


def _unit_rows(session: Session, project_id: UUID) -> list[CardUnitRead]:
    references = {
        row.program_node_id: row.revision
        for row in session.scalars(
            select(ReferenceAnswer).where(
                ReferenceAnswer.project_id == project_id,
                ReferenceAnswer.is_active.is_(True),
            )
        )
    }
    return [
        CardUnitRead(
            id=row.id,
            title=row.title,
            path=row.path,
            kind=row.kind,
            topic_ids=row.topic_ids,
            reference_revision=references.get(row.id),
        )
        for row in units(session, project_id)
    ]


def _require_unit(unit_rows: list[CardUnitRead], node_id: UUID | None) -> CardUnitRead | None:
    if node_id is None:
        return None
    unit = next((row for row in unit_rows if row.id == node_id), None)
    if unit is None:
        raise ProjectDomainError(
            "Вопрос или билет не найден", status=404, code="card_unit_not_found"
        )
    return unit


def _require_card(
    session: Session, project_id: UUID, card_id: UUID, *, include_deleted: bool = False
) -> Card:
    card = session.get(Card, card_id)
    if (
        card is None
        or card.project_id != project_id
        or (card.deleted_at is not None and not include_deleted)
    ):
        raise ProjectDomainError("Карточка не найдена", status=404, code="card_not_found")
    return card


def _check_revision(card: Card, expected: int) -> None:
    if card.revision != expected:
        raise ProjectConflictError(
            "Карточка уже изменена в другой вкладке",
            code="stale_card_revision",
            context={"expected": expected, "actual": card.revision},
        )


def _fragment_snapshot(session: Session, project_id: UUID, fragment_id: UUID) -> dict[str, object]:
    row = session.execute(
        select(MaterialFragment, MaterialPage, Material)
        .join(MaterialPage, MaterialPage.id == MaterialFragment.page_id)
        .join(Material, Material.id == MaterialFragment.material_id)
        .join(
            ProjectMaterial,
            (ProjectMaterial.material_id == Material.id)
            & (ProjectMaterial.project_id == project_id),
        )
        .where(MaterialFragment.id == fragment_id)
    ).first()
    if row is None:
        raise ProjectDomainError(
            "Фрагмент недоступен в этом проекте",
            status=404,
            code="card_fragment_not_found",
        )
    fragment, page, material = row
    return {
        "material_name": material.original_name,
        "page_number": page.page_number,
        "bbox": fragment.bbox,
        "text": fragment.text,
    }


def _source_payload(
    session: Session,
    project_id: UUID,
    unit: CardUnitRead | None,
    source: CardSourceWrite,
) -> tuple[CardSourceKind, UUID | None, int | None, dict[str, object]]:
    if source.kind == "none":
        return CardSourceKind.NONE, None, None, {}
    if source.kind == "fragment":
        assert source.fragment_id is not None
        return (
            CardSourceKind.FRAGMENT,
            source.fragment_id,
            None,
            _fragment_snapshot(session, project_id, source.fragment_id),
        )
    if unit is None:
        raise ProjectDomainError(
            "Эталонный ответ можно связать только с вопросом",
            status=422,
            code="card_reference_requires_unit",
        )
    answer = session.get(ReferenceAnswer, (project_id, unit.id))
    if answer is None or not answer.is_active:
        raise ProjectDomainError(
            "У вопроса нет доступного эталонного ответа",
            status=404,
            code="card_reference_not_found",
        )
    if source.reference_revision is not None and source.reference_revision != answer.revision:
        raise ProjectConflictError("Эталонный ответ уже изменён", code="stale_reference_revision")
    return (
        CardSourceKind.REFERENCE,
        None,
        answer.revision,
        {"material_name": "Эталонный ответ", "text": answer.text},
    )


def _source_read(card: Card) -> CardSourceRead:
    snapshot = card.source_snapshot or {}
    lost = card.source_kind == CardSourceKind.FRAGMENT and card.source_fragment_id is None
    label = {
        CardSourceKind.NONE: "Без источника",
        CardSourceKind.FRAGMENT: (
            "Источник удалён"
            if lost
            else (
                f"{snapshot.get('material_name', 'Материал')} · "
                f"стр. {snapshot.get('page_number', '—')}"
            )
        ),
        CardSourceKind.REFERENCE: "Эталонный ответ",
    }[card.source_kind]
    return CardSourceRead(
        kind=card.source_kind.value,
        fragment_id=card.source_fragment_id,
        reference_revision=card.source_reference_revision,
        label=label,
        material_name=str(snapshot["material_name"]) if snapshot.get("material_name") else None,
        page_number=int(snapshot["page_number"]) if snapshot.get("page_number") else None,
        text_snapshot=str(snapshot["text"]) if snapshot.get("text") else None,
        lost=lost,
    )


def _stats(session: Session, card_ids: list[UUID]) -> dict[UUID, list[tuple[datetime, int | None]]]:
    result: dict[UUID, list[tuple[datetime, int | None]]] = defaultdict(list)
    if not card_ids:
        return result
    rows = session.execute(
        select(Card.id, Attempt.created_at, Grade.confidence)
        .join(Activity, Activity.id == Card.activity_id)
        .join(Attempt, Attempt.activity_id == Activity.id)
        .outerjoin(Grade, Grade.attempt_id == Attempt.id)
        .where(Card.id.in_(card_ids))
        .order_by(Attempt.created_at.desc())
    )
    for card_id, created_at, confidence in rows:
        result[card_id].append((created_at, confidence))
    return result


def _card_read(
    card: Card,
    unit_by_id: dict[UUID, CardUnitRead],
    attempts: list[tuple[datetime, int | None]],
) -> CardRead:
    rated = [(at, confidence) for at, confidence in attempts if confidence is not None]
    last_three = [confidence for _, confidence in rated[:3]]
    return CardRead(
        id=card.id,
        project_id=card.project_id,
        program_node_id=card.activity.program_node_id,
        unit=unit_by_id.get(card.activity.program_node_id),
        front=card.front,
        back=card.back,
        hint=card.hint,
        source=_source_read(card),
        state=card.state.value,
        revision=card.revision,
        deleted_at=card.deleted_at,
        last_confidence=rated[0][1] if rated else None,
        attempt_count=len(attempts),
        last_reviewed_at=attempts[0][0] if attempts else None,
        average_last_three=mean(last_three) if last_three else None,
        created_at=card.created_at,
        updated_at=card.updated_at,
    )


def _all_card_reads(
    session: Session, project_id: UUID, *, include_deleted: bool = False
) -> tuple[list[CardRead], list[CardUnitRead]]:
    unit_rows = _unit_rows(session, project_id)
    query = select(Card).where(Card.project_id == project_id)
    if not include_deleted:
        query = query.where(Card.deleted_at.is_(None))
    cards = list(session.scalars(query))
    stats = _stats(session, [card.id for card in cards])
    unit_by_id = {row.id: row for row in unit_rows}
    return [_card_read(card, unit_by_id, stats.get(card.id, [])) for card in cards], unit_rows


def create_card(session: Session, project_id: UUID, command: CardCreate) -> CardRead:
    """Create one manual card and its reusable evidence activity."""
    with project_write_transaction(session, project_id):
        require_project(session, project_id, writable=True)
        unit_rows = _unit_rows(session, project_id)
        unit = _require_unit(unit_rows, command.program_node_id)
        kind, fragment_id, revision, snapshot = _source_payload(
            session, project_id, unit, command.source
        )
        activity = Activity(
            project_id=project_id,
            program_node_id=unit.id if unit else None,
            kind=ActivityKind.CARD,
            evidence_strength=0.5,
            origin=(
                ActivityOrigin.FRAGMENT
                if kind == CardSourceKind.FRAGMENT
                else ActivityOrigin.MANUAL
            ),
        )
        session.add(activity)
        session.flush()
        card = Card(
            project_id=project_id,
            activity_id=activity.id,
            front=command.front.strip(),
            back=command.back.strip(),
            hint=command.hint.strip() if command.hint else None,
            source_kind=kind,
            source_fragment_id=fragment_id,
            source_reference_revision=revision,
            source_snapshot=snapshot,
            state=CardState(command.state),
            revision=1,
        )
        session.add(card)
        session.flush()
        session.refresh(card)
    return _card_read(card, {row.id: row for row in unit_rows}, [])


def list_cards(
    session: Session,
    project_id: UUID,
    *,
    query: str | None = None,
    unit_id: UUID | None = None,
    state: str | None = None,
    source: str | None = None,
    rating: str | None = None,
    include_deleted: bool = False,
) -> CardListRead:
    """Filter the local bank and keep program order with unlinked cards last."""
    require_project(session, project_id)
    cards, unit_rows = _all_card_reads(session, project_id, include_deleted=include_deleted)
    position = {row.id: index for index, row in enumerate(unit_rows)}
    needle = (query or "").strip().casefold()

    def matches(card: CardRead) -> bool:
        haystack = " ".join(
            [
                card.front,
                card.back,
                card.unit.title if card.unit else "",
                *(card.unit.path if card.unit else []),
            ]
        ).casefold()
        return (
            (not needle or needle in haystack)
            and (unit_id is None or card.program_node_id == unit_id)
            and (state is None or card.state == state)
            and (source is None or card.source.kind == source)
            and (
                rating is None
                or rating == "unrated"
                and card.last_confidence is None
                or rating == "hard"
                and card.last_confidence in {1, 2}
                or rating == "recalled"
                and card.last_confidence in {3, 4}
                or rating == "lost"
                and card.source.lost
            )
        )

    filtered = [card for card in cards if matches(card)]
    filtered.sort(
        key=lambda card: (
            position.get(card.program_node_id, len(position)),
            card.created_at,
            card.id,
        )
    )
    return CardListRead(items=filtered, total=len(filtered), units=unit_rows)


def update_card(session: Session, project_id: UUID, card_id: UUID, command: CardUpdate) -> CardRead:
    """Apply an optimistic card edit; omitted fields remain unchanged."""
    with project_write_transaction(session, project_id):
        require_project(session, project_id, writable=True)
        card = _require_card(session, project_id, card_id)
        _check_revision(card, command.expected_revision)
        unit_rows = _unit_rows(session, project_id)
        if "program_node_id" in command.model_fields_set:
            unit = _require_unit(unit_rows, command.program_node_id)
            card.activity.program_node_id = unit.id if unit else None
        else:
            unit = next((row for row in unit_rows if row.id == card.activity.program_node_id), None)
        if command.front is not None:
            card.front = command.front.strip()
        if command.back is not None:
            card.back = command.back.strip()
        if "hint" in command.model_fields_set:
            card.hint = command.hint.strip() if command.hint else None
        if command.state is not None:
            card.state = CardState(command.state)
        if command.source is not None:
            kind, fragment_id, revision, snapshot = _source_payload(
                session, project_id, unit, command.source
            )
            card.source_kind = kind
            card.source_fragment_id = fragment_id
            card.source_reference_revision = revision
            card.source_snapshot = snapshot
        card.revision += 1
        card.updated_at = utc_now()
        session.flush()
        session.refresh(card)
        attempts = _stats(session, [card.id]).get(card.id, [])
    return _card_read(card, {row.id: row for row in unit_rows}, attempts)


def bulk_cards(session: Session, project_id: UUID, command: CardBulkWrite) -> CardListRead:
    """Change card state or soft-delete a checked batch atomically."""
    with project_write_transaction(session, project_id):
        require_project(session, project_id, writable=True)
        now = utc_now()
        for item in command.items:
            card = _require_card(
                session, project_id, item.id, include_deleted=command.action == "restore"
            )
            _check_revision(card, item.expected_revision)
            if command.action == "activate":
                card.state = CardState.ACTIVE
            elif command.action == "suspend":
                card.state = CardState.SUSPENDED
            elif command.action == "delete":
                card.deleted_at = now
            else:
                card.deleted_at = None
            card.revision += 1
            card.updated_at = now
    return list_cards(
        session,
        project_id,
        include_deleted=command.action in {"delete", "restore"},
    )


def fragment_prefill(session: Session, project_id: UUID, fragment_id: UUID) -> FragmentPrefillRead:
    """Return a verified source snapshot and a unit suggested by its binding."""
    require_project(session, project_id)
    snapshot = _fragment_snapshot(session, project_id, fragment_id)
    unit_rows = _unit_rows(session, project_id)
    topic_id = session.scalar(
        select(Binding.program_node_id)
        .where(
            Binding.project_id == project_id,
            Binding.fragment_id == fragment_id,
            Binding.status.in_(ACTIVE_BINDINGS),
        )
        .order_by(Binding.created_at)
        .limit(1)
    )
    proposed = next((unit.id for unit in unit_rows if topic_id in unit.topic_ids), None)
    source = CardSourceRead(
        kind="fragment",
        fragment_id=fragment_id,
        reference_revision=None,
        label=f"{snapshot['material_name']} · стр. {snapshot['page_number']}",
        material_name=str(snapshot["material_name"]),
        page_number=int(snapshot["page_number"]),
        text_snapshot=str(snapshot["text"]),
        lost=False,
    )
    return FragmentPrefillRead(
        fragment_id=fragment_id,
        proposed_program_node_id=proposed,
        back=str(snapshot["text"]),
        source=source,
    )


def _today_units(
    session: Session, project_id: UUID, unit_rows: list[CardUnitRead]
) -> tuple[bool, list[CardUnitRead]]:
    plan = session.get(PreparationPlan, project_id)
    plan_exists = bool(plan and (plan.items or plan.phases))
    if plan is None:
        return False, []
    config = get_settings(session, project_id).config
    today = study_date(datetime.now(UTC), config)
    by_id = {str(row.id): row for row in unit_rows}
    # Автоповтор (repetitions.due_items) не проставляет order — без запасного ключа
    # по позиции в программе вопросы одного дня расходятся по UUID и выглядят как
    # обратный порядок.
    unit_order = {str(row.id): index for index, row in enumerate(unit_rows)}
    items = sorted(
        plan.items,
        key=lambda item: (
            item.get("order", 0),
            unit_order.get(str(item.get("unit_id")), len(unit_rows)),
        ),
    )
    return plan_exists, [
        by_id[str(item["unit_id"])]
        for item in items
        if item.get("kind") == "review"
        and str(item.get("on_date")) == today.isoformat()
        and str(item.get("unit_id")) in by_id
    ]


def _analytics(
    session: Session,
    project_id: UUID,
    period: int,
    cards: list[CardRead],
    unit_rows: list[CardUnitRead],
) -> CardAnalyticsRead:
    config = get_settings(session, project_id).config
    today = study_date(datetime.now(UTC), config)
    cutoff, _ = day_bounds(today - timedelta(days=period - 1), config)
    rows = list(
        session.execute(
            select(Card.id, Activity.program_node_id, Grade.confidence)
            .join(Activity, Activity.id == Card.activity_id)
            .join(Attempt, Attempt.activity_id == Activity.id)
            .join(Grade, Grade.attempt_id == Attempt.id)
            .where(
                Card.project_id == project_id,
                Grade.confidence.is_not(None),
                Attempt.created_at >= cutoff.replace(tzinfo=None),
            )
        )
    )
    distribution = Counter(confidence for _, _, confidence in rows)
    per_unit: dict[UUID, list[int]] = defaultdict(list)
    for _, node_id, confidence in rows:
        if node_id is not None and confidence is not None:
            per_unit[node_id].append(confidence)
    hardest_id = max(
        per_unit,
        key=lambda node_id: (
            sum(value <= 2 for value in per_unit[node_id]) / len(per_unit[node_id]),
            len(per_unit[node_id]),
        ),
        default=None,
    )
    unit_by_id = {row.id: row for row in unit_rows}
    hardest_values = per_unit.get(hardest_id, [])
    return CardAnalyticsRead(
        period=period,
        observation_count=len(rows),
        distribution=[
            ConfidenceBucket(confidence=value, count=distribution[value]) for value in range(1, 5)
        ],
        hard_card_count=sum(card.last_confidence in {1, 2} for card in cards),
        hardest_unit=unit_by_id.get(hardest_id),
        hardest_low_share=(
            sum(value <= 2 for value in hardest_values) / len(hardest_values)
            if hardest_values
            else None
        ),
        hardest_observation_count=len(hardest_values),
    )


def overview(session: Session, project_id: UUID, period: int) -> CardOverviewRead:
    """Compose calendar coverage, fallback selections and honest analytics."""
    require_project(session, project_id)
    cards, unit_rows = _all_card_reads(session, project_id)
    active = [card for card in cards if card.state == "active"]
    plan_exists, today = _today_units(session, project_id, unit_rows)
    count_by_unit = Counter(card.program_node_id for card in active)
    recent = sorted(
        (card for card in cards if card.last_reviewed_at),
        key=lambda card: card.last_reviewed_at or datetime.min,
        reverse=True,
    )[:5]
    hard = sorted(
        (card for card in active if card.last_confidence in {1, 2}),
        key=lambda card: (
            card.average_last_three if card.average_last_three is not None else 5,
            card.last_reviewed_at or datetime.min,
        ),
    )[:5]
    active_session = session.scalar(
        select(CardSession).where(
            CardSession.project_id == project_id,
            CardSession.state == CardSessionState.ACTIVE,
        )
    )
    return CardOverviewRead(
        program_exists=bool(unit_rows),
        plan_exists=plan_exists,
        today_units=[
            TodayUnitRead(
                unit=unit,
                card_count=count_by_unit[unit.id],
                covered=count_by_unit[unit.id] > 0,
                cards=[card for card in active if card.program_node_id == unit.id],
            )
            for unit in today
        ],
        covered_unit_count=sum(count_by_unit[unit.id] > 0 for unit in today),
        active_card_count=len(active),
        estimated_minutes=(
            sum(count_by_unit[unit.id] for unit in today) * CARD_SECONDS_ESTIMATE + 59
        )
        // 60,
        recent_cards=recent,
        hard_cards=hard,
        analytics=_analytics(session, project_id, period, cards, unit_rows),
        active_session=(
            CardSessionSummaryRead(
                id=active_session.id,
                scope=active_session.scope.value,
                pace=active_session.pace.value,
                position=active_session.position,
                card_count=len(active_session.queue),
                revision=active_session.revision,
            )
            if active_session
            else None
        ),
        units=unit_rows,
    )


def _scope_units(
    session: Session,
    project_id: UUID,
    command: CardSessionCreate,
    cards: list[CardRead],
    unit_rows: list[CardUnitRead],
) -> list[UUID | None]:
    if command.scope == "today":
        _, today = _today_units(session, project_id, unit_rows)
        return [row.id for row in today]
    if command.scope == "selected":
        selected = list(dict.fromkeys(command.selected_unit_ids))
        for node_id in selected:
            _require_unit(unit_rows, node_id)
        return selected
    if command.scope == "hard":
        hard = sorted(
            (card for card in cards if card.last_confidence in {1, 2}),
            key=lambda card: card.average_last_three or 5,
        )
        return list(dict.fromkeys(card.program_node_id for card in hard))
    return [row.id for row in unit_rows] + [None]


def _queue_snapshot(
    cards: list[CardRead], scope_units: list[UUID | None]
) -> list[dict[str, object]]:
    rank = {unit_id: index for index, unit_id in enumerate(scope_units)}
    selected = [
        card
        for card in cards
        if card.state == "active" and card.program_node_id in rank
    ]
    selected.sort(key=lambda card: (rank[card.program_node_id], card.created_at, card.id))
    return [_card_snapshot(card) for card in selected]


def _card_snapshot(card: CardRead) -> dict[str, object]:
    return {
        "card_id": str(card.id),
        "unit_id": str(card.program_node_id) if card.program_node_id else None,
        "unit_title": card.unit.title if card.unit else None,
        "front": card.front,
        "back": card.back,
        "hint": card.hint,
        "source": card.source.model_dump(mode="json"),
        "state": "pending",
        "confidence": None,
    }


def _session_read(
    session: Session, row: CardSession, unit_rows: list[CardUnitRead] | None = None
) -> CardSessionRead:
    unit_rows = unit_rows or _unit_rows(session, row.project_id)
    present = {UUID(item["unit_id"]) for item in row.queue if item.get("unit_id")}
    selected = [UUID(value) for value in row.selected_unit_ids]
    missing_ids = [value for value in selected if value not in present]
    unit_by_id = {unit.id: unit for unit in unit_rows}
    return CardSessionRead(
        id=row.id,
        project_id=row.project_id,
        scope=row.scope.value,
        selected_unit_ids=selected,
        pace=row.pace.value,
        limit_minutes=row.limit_minutes,
        queue=[SessionCardRead.model_validate(item) for item in row.queue],
        position=row.position,
        active_seconds=row.active_seconds,
        limit_reached=bool(row.limit_minutes and row.active_seconds >= row.limit_minutes * 60),
        state=row.state.value,
        revision=row.revision,
        missing_units=[unit_by_id[value] for value in missing_ids if value in unit_by_id],
        created_at=row.created_at,
        updated_at=row.updated_at,
        completed_at=row.completed_at,
    )


def create_session(
    session: Session, project_id: UUID, command: CardSessionCreate
) -> CardSessionRead:
    """Freeze a deterministic queue; replacing an active session is explicit."""
    with project_write_transaction(session, project_id):
        require_project(session, project_id, writable=True)
        active = session.scalar(
            select(CardSession).where(
                CardSession.project_id == project_id,
                CardSession.state == CardSessionState.ACTIVE,
            )
        )
        if active and not command.replace_active:
            raise ProjectConflictError(
                "У проекта уже есть незавершённый сеанс",
                code="active_card_session_exists",
                context={"session_id": str(active.id)},
            )
        if active:
            active.state = CardSessionState.CANCELLED
            active.completed_at = utc_now()
            active.revision += 1
        cards, unit_rows = _all_card_reads(session, project_id)
        scope_units = _scope_units(session, project_id, command, cards, unit_rows)
        if command.scope == "hard":
            hard_cards = sorted(
                (
                    card
                    for card in cards
                    if card.state == "active" and card.last_confidence in {1, 2}
                ),
                key=lambda card: (
                    card.average_last_three
                    if card.average_last_three is not None
                    else 5,
                    card.created_at,
                    card.id,
                ),
            )
            queue = [_card_snapshot(card) for card in hard_cards]
        else:
            queue = _queue_snapshot(cards, scope_units)
        if not queue:
            raise ProjectDomainError(
                "В выбранной подборке нет активных карточек",
                status=422,
                code="card_session_empty",
            )
        row = CardSession(
            project_id=project_id,
            scope=CardSessionScope(command.scope),
            selected_unit_ids=[
                str(value)
                for value in (
                    command.selected_unit_ids if command.scope == "selected" else scope_units
                )
                if value is not None
            ],
            pace=CardSessionPace(command.pace),
            limit_minutes=command.limit_minutes,
            queue=queue,
            position=0,
            active_seconds=0,
            state=CardSessionState.ACTIVE,
            revision=1,
        )
        session.add(row)
        session.flush()
        session.refresh(row)
    return _session_read(session, row, unit_rows)


def get_session(
    session: Session, project_id: UUID, session_id: UUID | None = None
) -> CardSessionRead:
    require_project(session, project_id)
    row = (
        session.get(CardSession, session_id)
        if session_id
        else session.scalar(
            select(CardSession).where(
                CardSession.project_id == project_id,
                CardSession.state == CardSessionState.ACTIVE,
            )
        )
    )
    if row is None or row.project_id != project_id:
        raise ProjectDomainError("Сеанс не найден", status=404, code="card_session_not_found")
    return _session_read(session, row)


def _require_session(
    session: Session, project_id: UUID, session_id: UUID, expected_revision: int
) -> CardSession:
    row = session.get(CardSession, session_id)
    if row is None or row.project_id != project_id:
        raise ProjectDomainError("Сеанс не найден", status=404, code="card_session_not_found")
    if row.state != CardSessionState.ACTIVE:
        raise ProjectConflictError("Сеанс уже завершён", code="card_session_finished")
    if row.revision != expected_revision:
        raise ProjectConflictError(
            "Сеанс уже изменён в другой вкладке",
            code="stale_card_session_revision",
            context={"expected": expected_revision, "actual": row.revision},
        )
    return row


def save_progress(
    session: Session,
    project_id: UUID,
    session_id: UUID,
    command: SessionProgressWrite,
) -> CardSessionRead:
    with project_write_transaction(session, project_id):
        row = _require_session(session, project_id, session_id, command.expected_revision)
        row.position = min(command.position, len(row.queue))
        row.active_seconds = max(row.active_seconds, command.active_seconds)
        row.revision += 1
        row.updated_at = utc_now()
    return _session_read(session, row)


def open_current_unit(
    session: Session, project_id: UUID, session_id: UUID, expected_revision: int
) -> CardSessionRead:
    """Opening only records calendar completion; it never edits plan items."""
    with project_write_transaction(session, project_id):
        require_project(session, project_id, writable=True)
        row = session.get(CardSession, session_id)
        if row is None or row.project_id != project_id:
            raise ProjectDomainError("Сеанс не найден", status=404, code="card_session_not_found")
        if row.revision != expected_revision:
            raise ProjectConflictError("Сеанс уже изменён", code="stale_card_session_revision")
        if row.position < len(row.queue):
            unit_id = row.queue[row.position].get("unit_id")
            if unit_id:
                record_unit_opening(session, project_id, UUID(unit_id), in_transaction=True)
    return _session_read(session, row)


def _record_attempt(
    session: Session,
    project_id: UUID,
    card: Card,
    attempt_id: UUID,
    active_seconds: int,
    confidence: int | None,
) -> None:
    if session.get(Attempt, attempt_id) is not None:
        return
    ordinal = (
        session.scalar(
            select(func.count(Attempt.id)).where(Attempt.activity_id == card.activity_id)
        )
        or 0
    ) + 1
    attempt = Attempt(
        id=attempt_id,
        project_id=project_id,
        activity_id=card.activity_id,
        ordinal=ordinal,
        active_seconds=active_seconds,
        text=None,
        persona=None,
        strictness=None,
        context_snapshot={"card_revision": card.revision},
    )
    session.add(attempt)
    if confidence is not None:
        outcome = (
            AttemptOutcome.FAILED
            if confidence == 1
            else AttemptOutcome.PARTIAL
            if confidence == 2
            else AttemptOutcome.PASSED
        )
        session.add(
            Grade(
                attempt_id=attempt_id,
                outcome=outcome,
                method=GradeMethod.SELF_ASSESSMENT,
                self_assessment=outcome,
                confidence=confidence,
                credited_points=[],
                missed_points=[],
                wrong_points=[],
                summary="Самооценка карточки",
            )
        )


def _mark_queue(row: CardSession, card_id: UUID, state: str, confidence: int | None) -> None:
    queue = [dict(item) for item in row.queue]
    item = next((value for value in queue if value["card_id"] == str(card_id)), None)
    if item is None:
        raise ProjectDomainError(
            "Карточки нет в этом сеансе", status=404, code="session_card_not_found"
        )
    item["state"] = state
    item["confidence"] = confidence
    row.queue = queue


def review_card(
    session: Session,
    project_id: UUID,
    session_id: UUID,
    card_id: UUID,
    command: SessionReviewWrite,
) -> CardSessionRead:
    with project_write_transaction(session, project_id):
        card = _require_card(session, project_id, card_id)
        existing = session.get(Attempt, command.id)
        row = session.get(CardSession, session_id)
        if row is None or row.project_id != project_id:
            raise ProjectDomainError(
                "Сеанс не найден", status=404, code="card_session_not_found"
            )
        if existing is not None:
            if (
                existing.project_id != project_id
                or existing.activity_id != card.activity_id
            ):
                raise ProjectConflictError(
                    "Идентификатор оценки уже использован",
                    code="card_review_id_reused",
                )
            return _session_read(session, row)
        row = _require_session(session, project_id, session_id, command.expected_revision)
        _record_attempt(
            session, project_id, card, command.id, command.active_seconds, command.confidence
        )
        _mark_queue(row, card_id, "rated", command.confidence)
        row.position = min(row.position + 1, len(row.queue))
        row.active_seconds += command.active_seconds
        row.revision += 1
        row.updated_at = utc_now()
    return _session_read(session, row)


def defer_card(
    session: Session,
    project_id: UUID,
    session_id: UUID,
    card_id: UUID,
    command: SessionDeferWrite,
) -> CardSessionRead:
    with project_write_transaction(session, project_id):
        card = _require_card(session, project_id, card_id)
        existing = session.get(Attempt, command.id)
        row = session.get(CardSession, session_id)
        if row is None or row.project_id != project_id:
            raise ProjectDomainError(
                "Сеанс не найден", status=404, code="card_session_not_found"
            )
        if existing is not None:
            if (
                existing.project_id != project_id
                or existing.activity_id != card.activity_id
            ):
                raise ProjectConflictError(
                    "Идентификатор действия уже использован",
                    code="card_review_id_reused",
                )
            return _session_read(session, row)
        row = _require_session(session, project_id, session_id, command.expected_revision)
        _record_attempt(session, project_id, card, command.id, command.active_seconds, None)
        _mark_queue(row, card_id, "deferred", None)
        row.position = min(row.position + 1, len(row.queue))
        row.active_seconds += command.active_seconds
        row.revision += 1
        row.updated_at = utc_now()
    return _session_read(session, row)


def finish_session(
    session: Session,
    project_id: UUID,
    session_id: UUID,
    command: SessionFinishWrite,
) -> CardSessionRead:
    with project_write_transaction(session, project_id):
        row = _require_session(session, project_id, session_id, command.expected_revision)
        row.state = (
            CardSessionState.COMPLETED
            if command.action == "complete"
            else CardSessionState.CANCELLED
        )
        row.completed_at = utc_now()
        row.updated_at = row.completed_at
        row.revision += 1
    return _session_read(session, row)


def retry_session(
    session: Session,
    project_id: UUID,
    session_id: UUID,
    command: SessionRetryWrite,
) -> CardSessionRead:
    """Start an exact retry queue from confidence 1–2 and deferred cards."""
    with project_write_transaction(session, project_id):
        row = _require_session(session, project_id, session_id, command.expected_revision)
        queue = [
            {**item, "state": "pending", "confidence": None}
            for item in row.queue
            if item.get("state") == "deferred"
            or item.get("confidence") in {1, 2}
        ]
        if not queue:
            raise ProjectDomainError(
                "В сеансе нет сложных или отложенных карточек",
                status=422,
                code="card_session_retry_empty",
            )
        now = utc_now()
        row.state = CardSessionState.COMPLETED
        row.completed_at = now
        row.updated_at = now
        row.revision += 1
        retry = CardSession(
            project_id=project_id,
            scope=CardSessionScope.HARD,
            selected_unit_ids=list(
                dict.fromkeys(
                    item["unit_id"] for item in queue if item.get("unit_id")
                )
            ),
            pace=row.pace,
            limit_minutes=row.limit_minutes,
            queue=queue,
            position=0,
            active_seconds=0,
            state=CardSessionState.ACTIVE,
            revision=1,
        )
        session.add(retry)
        session.flush()
        session.refresh(retry)
    return _session_read(session, retry)
