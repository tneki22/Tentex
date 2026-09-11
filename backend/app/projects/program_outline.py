"""Атомарный офлайновый импорт оглавлений в учебниковую программу."""

from collections import defaultdict
from dataclasses import dataclass
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    GoalPassport,
    GoalRole,
    Material,
    NodeType,
    OriginKind,
    ProgramBasisKind,
    ProgramNode,
    ProgramNodeSourcePageRange,
    ProjectMaterial,
    WorkspaceVariant,
    utc_now,
)
from app.projects import program
from app.projects.errors import ProjectConflictError, ProjectInvariantError
from app.projects.schemas import (
    ProgramChangeResult,
    ProgramOutlineItemWrite,
    ProgramOutlinesImportWrite,
)


@dataclass(frozen=True, slots=True)
class PreparedOutlineItem:
    """Пункт оглавления с вычисленными родителем и диапазоном страниц."""

    value: ProgramOutlineItemWrite
    parent_index: int | None
    page_to: int


def _prepare_items(
    items: list[ProgramOutlineItemWrite], page_count: int | None
) -> list[PreparedOutlineItem]:
    """Собрать плоское оглавление без искусственных узлов при пропусках уровней."""
    keys: set[str] = set()
    parents: list[int | None] = []
    stack: list[int] = []
    for index, item in enumerate(items):
        if item.outline_item_key in keys:
            raise ProjectInvariantError("Ключи пунктов одного оглавления должны быть уникальны")
        keys.add(item.outline_item_key)
        while stack and items[stack[-1]].level >= item.level:
            stack.pop()
        parents.append(stack[-1] if stack else None)
        stack.append(index)

    # ponytail: квадратичный поиск ограничен схемой в 2 000 строк;
    # при росте лимита нужен обратный стек.
    prepared = []
    for index, item in enumerate(items):
        boundary = next(
            (candidate.page for candidate in items[index + 1 :] if candidate.level <= item.level),
            None,
        )
        last_page = page_count or item.page
        page_to = max(item.page, boundary - 1 if boundary is not None else last_page)
        if page_count is not None and item.page > page_count:
            raise ProjectInvariantError("Страница пункта оглавления выходит за границы материала")
        parent_index = parents[index]
        if item.selected and parent_index is not None and not items[parent_index].selected:
            raise ProjectInvariantError("Нельзя импортировать ветвь без выбранного родителя")
        prepared.append(PreparedOutlineItem(item, parent_index, page_to))
    return prepared


def _node_type(level: int) -> NodeType:
    if level == 1:
        return NodeType.SECTION
    if level == 2:
        return NodeType.TOPIC
    return NodeType.SUBPOINT


def import_outlines(
    session: Session, project_id: UUID, command: ProgramOutlinesImportWrite
) -> ProgramChangeResult:
    """Импортировать выбранные ветви источников одной ревизией и одной записью undo."""
    with session.begin():
        project = program._require_writable_project(session, project_id)
        if project.workspace_variant != WorkspaceVariant.TEXTBOOK:
            raise ProjectConflictError(
                "Импорт оглавлений доступен только в учебниковом проекте",
                code="textbook_program_only",
            )
        if project.program_revision != command.expected_program_revision:
            raise ProjectConflictError(
                "Программа уже изменена в другой вкладке",
                code="stale_program_revision",
                context={"current_program_revision": project.program_revision},
            )
        source_ids = [source.material_id for source in command.sources]
        if len(source_ids) != len(set(source_ids)):
            raise ProjectInvariantError("Один источник нельзя импортировать дважды за запрос")
        links = list(
            session.scalars(
                select(ProjectMaterial)
                .where(
                    ProjectMaterial.project_id == project_id,
                    ProjectMaterial.material_id.in_(source_ids),
                )
                .order_by(ProjectMaterial.priority, ProjectMaterial.created_at)
            )
        )
        if {link.material_id for link in links} != set(source_ids):
            raise ProjectInvariantError("Один из материалов не принадлежит проекту")
        source_by_id = {source.material_id: source for source in command.sources}
        nodes = program._nodes(session, project_id)
        nodes_by_id = {node.id: node for node in nodes}
        ranges = list(
            session.scalars(
                select(ProgramNodeSourcePageRange).where(
                    ProgramNodeSourcePageRange.project_id == project_id,
                    ProgramNodeSourcePageRange.material_id.in_(source_ids),
                )
            )
        )
        existing = {
            (source_range.material_id, source_range.outline_item_key): source_range.program_node_id
            for source_range in ranges
        }
        next_position: dict[UUID | None, int] = defaultdict(int)
        for node in nodes:
            next_position[node.parent_id] = max(next_position[node.parent_id], node.sort_order + 1)
        passport = session.get(GoalPassport, project_id)
        target_level = passport.target_outcome if passport is not None else None
        inverse: list[dict[str, object]] = []
        changed_node_id: UUID | None = None
        now = utc_now()

        for link in links:
            material = session.get(Material, link.material_id)
            if material is None:
                raise ProjectInvariantError("Материал источника не найден")
            source = source_by_id[link.material_id]
            prepared = _prepare_items(source.items, material.page_count)
            imported_by_index: dict[int, ProgramNode] = {}
            source_name = link.display_name or material.original_name
            for index, item in enumerate(prepared):
                if not item.value.selected:
                    continue
                parent = (
                    imported_by_index.get(item.parent_index)
                    if item.parent_index is not None
                    else None
                )
                node_id = existing.get((material.id, item.value.outline_item_key))
                node = nodes_by_id.get(node_id) if node_id is not None else None
                if node is not None:
                    imported_by_index[index] = node
                    if not node.is_in_current_program:
                        inverse.append({"id": str(node.id), "is_in_current_program": False})
                        node.is_in_current_program = True
                        node.is_archived = False
                        node.updated_at = now
                        changed_node_id = changed_node_id or node.id
                    continue
                node = ProgramNode(
                    id=uuid4(),
                    project_id=project_id,
                    parent_id=parent.id if parent is not None else None,
                    node_type=_node_type(item.value.level),
                    exam_kind=None,
                    sort_order=next_position[parent.id if parent is not None else None],
                    title=item.value.title,
                    goal_role=GoalRole.TARGET,
                    target_level=target_level,
                    is_in_current_program=True,
                    needs_material=False,
                    is_archived=False,
                    origin_kind=OriginKind.IMPORT,
                    basis_kind=ProgramBasisKind.OUTLINE,
                    origin_note=f"Оглавление: {source_name}",
                    origin_material_id=material.id,
                    created_at=now,
                    updated_at=now,
                )
                next_position[node.parent_id] += 1
                session.add(node)
                session.flush()
                session.add(
                    ProgramNodeSourcePageRange(
                        project_id=project_id,
                        program_node_id=node.id,
                        material_id=material.id,
                        source_name_snapshot=source_name,
                        outline_item_key=item.value.outline_item_key,
                        page_from=item.value.page,
                        page_to=item.page_to,
                    )
                )
                nodes_by_id[node.id] = node
                imported_by_index[index] = node
                existing[(material.id, item.value.outline_item_key)] = node.id
                inverse.append({"id": str(node.id), "is_in_current_program": False})
                changed_node_id = changed_node_id or node.id

        if not inverse:
            return program._change_result(session, project, None, None)
        draft_revision = program._begin_program_change(
            session, project, command.expected_program_revision
        )
        program._record_action(
            session,
            project,
            "outline_import",
            "Импорт оглавлений",
            {"values": inverse},
        )
        return program._change_result(session, project, changed_node_id, draft_revision)
