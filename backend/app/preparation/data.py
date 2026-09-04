"""Чтение проекта и атомарные единицы плана без зависимости от поверхностей чата."""

from collections import defaultdict
from statistics import median
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Attempt,
    Binding,
    BindingStatus,
    ExamKind,
    GoalPassport,
    NodeType,
    ProgramNode,
    Project,
    ProjectStatus,
    ReferenceAnswer,
    WorkspaceVariant,
)
from app.preparation.models import PreparationPlan, PreparationSettings
from app.preparation.schemas import PreparationConfig, SettingsRead, UnitRead
from app.projects.errors import ProjectDomainError, ProjectNotFoundError

TARGET_MULTIPLIERS = {"awareness": 0.6, "understanding": 0.8, "application": 1, "mastery": 1.25}
START_MULTIPLIERS = {"beginner": 1.35, "familiar": 1, "refreshing": 0.75}
MIN_TIME_OBSERVATIONS = 3


def require_project(session: Session, project_id: UUID, *, writable: bool = False) -> Project:
    """Проект подготовки всегда экзаменационный; архив разрешает только чтение."""
    project = session.get(Project, project_id)
    if project is None:
        raise ProjectNotFoundError()
    if project.workspace_variant != WorkspaceVariant.EXAM:
        raise ProjectDomainError(
            "Подготовка доступна для экзамена", status=422, code="preparation_exam_only"
        )
    if writable and project.status not in {ProjectStatus.DRAFT, ProjectStatus.ACTIVE}:
        raise ProjectDomainError(
            "Проект доступен только для чтения", status=409, code="project_read_only"
        )
    return project


def get_settings(session: Session, project_id: UUID) -> SettingsRead:
    """Без отдельной настройки бюджет наследуется из паспорта, запись не создаётся."""
    row = session.get(PreparationSettings, project_id)
    if row:
        return SettingsRead(
            revision=row.revision, config=PreparationConfig.model_validate(row.config)
        )
    passport = session.get(GoalPassport, project_id)
    return SettingsRead(
        revision=0,
        config=PreparationConfig(
            daily_minutes=passport.minutes_per_day if passport else None,
            weekday_minutes={day: 0 for day in range(passport.days_per_week, 7)}
            if passport and passport.days_per_week else {},
        ),
    )


def program_nodes(session: Session, project_id: UUID, *, active: bool = True) -> list[ProgramNode]:
    """Иерархию изучаем целиком, не сортируя детей разных разделов вперемешку."""
    query = select(ProgramNode).where(ProgramNode.project_id == project_id)
    if active:
        query = query.where(
            ProgramNode.is_archived.is_(False), ProgramNode.is_in_current_program.is_(True)
        )
    rows = list(session.scalars(query.order_by(ProgramNode.sort_order, ProgramNode.id)))
    parents = {node.id for node in rows}
    children = defaultdict(list)
    for node in rows:
        children[node.parent_id if node.parent_id in parents else None].append(node)
    ordered = []
    stack = list(reversed(children[None]))
    while stack:
        node = stack.pop()
        ordered.append(node)
        stack.extend(reversed(children[node.id]))
    return ordered


def node_path(node: ProgramNode, nodes: dict[UUID, ProgramNode]) -> list[str]:
    """Путь сохраняет смысл одинаково названных вопросов разных разделов."""
    path = []
    parent = nodes.get(node.parent_id)
    seen = {node.id}
    while parent and parent.id not in seen:
        seen.add(parent.id)
        path.append(parent.title)
        parent = nodes.get(parent.parent_id)
    return list(reversed(path))


def target_level(node: ProgramNode, nodes: dict, passport: GoalPassport | None) -> str:
    """Наследование цели идёт от вопроса к разделам и паспорту."""
    current = node
    while current:
        if current.target_level:
            return current.target_level.value
        current = nodes.get(current.parent_id)
    return (
        passport.target_outcome.value if passport and passport.target_outcome else "understanding"
    )


def _initial_minutes(node: ProgramNode, nodes: dict, passport: GoalPassport | None) -> int:
    base = (
        50 if node.exam_kind == ExamKind.TICKET else 36 if node.exam_kind == ExamKind.TASK else 30
    )
    start = passport.starting_level.value if passport and passport.starting_level else "familiar"
    practice = 1.1 if passport and str(passport.study_format) == "practice" else 1
    return max(
        1,
        round(
            base
            * START_MULTIPLIERS[start]
            * TARGET_MULTIPLIERS[target_level(node, nodes, passport)]
            * practice
        ),
    )


def _unit_topics(nodes: list[ProgramNode]) -> dict[UUID, list[ProgramNode]]:
    by_id = {n.id: n for n in nodes}
    grouped = defaultdict(list)
    for node in nodes:
        if node.node_type != NodeType.TOPIC:
            continue
        parent = by_id.get(node.parent_id)
        unit_id = node.id
        while parent:
            if parent.exam_kind == ExamKind.TICKET:
                unit_id = parent.id
                break
            parent = by_id.get(parent.parent_id)
        grouped[unit_id].append(node)
    return grouped


def units(session: Session, project_id: UUID) -> list[UnitRead]:
    """Каждая тема принадлежит ровно одной единице; билет не раздробить подбором id."""
    nodes = program_nodes(session, project_id)
    by_id = {n.id: n for n in nodes}
    passport = session.get(GoalPassport, project_id)
    observations = defaultdict(list)
    for attempt in session.scalars(
        select(Attempt).where(Attempt.project_id == project_id, Attempt.active_seconds > 0)
    ):
        observations[attempt.program_node_id].append(attempt.active_seconds / 60)
    plan = session.get(PreparationPlan, project_id)
    estimates = {}
    for item in plan.items if plan else []:
        if item.get("estimate_source") in {"Ручная оценка", "Оценка ИИ"}:
            estimates[item["unit_id"]] = (item["minutes"], item["estimate_source"])
    result = []
    for unit_id, topics in _unit_topics(nodes).items():
        node = by_id[unit_id]
        observed = [observations[t.id] for t in topics]
        estimate, source = _initial_minutes(node, by_id, passport), "Начальная оценка"
        stored = estimates.get(str(unit_id))
        if stored and stored[1] == "Ручная оценка":
            estimate, source = stored
        elif all(len(values) >= MIN_TIME_OBSERVATIONS for values in observed):
            estimate = max(1, round(sum(median(values) for values in observed)))
            source = "Фактическое время"
        elif stored:
            estimate, source = stored
        kind = (
            "ticket"
            if node.exam_kind == ExamKind.TICKET
            else ("task" if node.exam_kind == ExamKind.TASK else "question")
        )
        result.append(
            UnitRead(
                id=unit_id,
                title=node.title,
                path=node_path(node, by_id),
                kind=kind,
                topic_ids=[t.id for t in topics],
                topic_titles=[t.title for t in topics],
                target_level=target_level(node, by_id, passport),
                minutes=estimate,
                estimate_source=source,
            )
        )
    return result


def answer_presence(session: Session, project_id: UUID) -> set[UUID]:
    """Сам ответ тоже источник подготовки, даже если учебной привязки нет."""
    references = set(
        session.scalars(
            select(ReferenceAnswer.program_node_id).where(
                ReferenceAnswer.project_id == project_id, ReferenceAnswer.is_active.is_(True)
            )
        )
    )
    bound = set(
        session.scalars(
            select(Binding.program_node_id).where(
                Binding.project_id == project_id,
                Binding.status.in_(
                    [BindingStatus.MANUAL, BindingStatus.CONFIRMED, BindingStatus.MACHINE]
                ),
            )
        )
    )
    return references | bound
