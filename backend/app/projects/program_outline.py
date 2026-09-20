"""Атомарный офлайновый импорт оглавлений в учебниковую программу."""

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import project_write_transaction
from app.materials.naming import project_material_display_name
from app.materials.outline_titles import GENERAL_TITLE_RE, TOPIC_TITLE_RE
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


def _section_indices(items: list[PreparedOutlineItem]) -> set[int]:
    """Найти только общие контейнеры, которые не должны изучаться как темы.

    Явные «Часть»/«Раздел» однозначны. Безымянный верхний пункт также считается
    разделом, если непосредственно содержит главы, лекции или темы; это покрывает
    оглавления вида «Микроэкономика → Тема 1» без превращения всех корней в
    служебные разделы.
    """
    result = {
        index
        for index, item in enumerate(items)
        if GENERAL_TITLE_RE.match(item.value.title)
    }
    for item in items:
        if item.parent_index is not None and TOPIC_TITLE_RE.match(item.value.title):
            result.add(item.parent_index)
    return result


def _node_type(
    index: int,
    item: PreparedOutlineItem,
    imported_by_index: dict[int, ProgramNode],
    sections: set[int],
) -> NodeType:
    """Назначить предметный тип независимо от технического уровня оглавления."""
    if index in sections:
        return NodeType.SECTION
    parent = (
        imported_by_index.get(item.parent_index) if item.parent_index is not None else None
    )
    if parent is None or parent.node_type == NodeType.SECTION:
        return NodeType.TOPIC
    return NodeType.SUBPOINT


def _outline_key_anchor(key: str) -> str:
    """Убрать уровень из сгенерированного ключа, сохранив произвольные ключи."""
    prefix, separator, level = key.rpartition(":")
    return prefix if separator and level.isdigit() else key


def _existing_inverse(
    node: ProgramNode, source_range: ProgramNodeSourcePageRange
) -> dict[str, object]:
    """Снимок полей, которые повторный импорт может синхронизировать."""
    return {
        "id": str(node.id),
        "is_in_current_program": node.is_in_current_program,
        "is_archived": node.is_archived,
        "parent_id": str(node.parent_id) if node.parent_id else None,
        "node_type": node.node_type.value,
        "sort_order": node.sort_order,
        "title": node.title,
        "origin_kind": node.origin_kind.value,
        "basis_kind": node.basis_kind.value,
        "range": {
            "id": str(source_range.id),
            "outline_item_key": source_range.outline_item_key,
            "page_from": source_range.page_from,
            "page_to": source_range.page_to,
        },
    }


def _sync_existing_node(
    node: ProgramNode,
    source_range: ProgramNodeSourcePageRange,
    item: PreparedOutlineItem,
    *,
    parent: ProgramNode | None,
    node_type: NodeType,
    sort_order: int,
    now: datetime,
) -> bool:
    """Обновить импортированный узел после исправления текста или уровней."""
    desired = {
        "parent_id": parent.id if parent is not None else None,
        "node_type": node_type,
        "sort_order": sort_order,
        "title": item.value.title,
        "origin_kind": OriginKind.IMPORT,
        "basis_kind": ProgramBasisKind.OUTLINE,
        "is_in_current_program": True,
        "is_archived": False,
    }
    changed = any(getattr(node, field) != value for field, value in desired.items())
    range_changed = (
        source_range.outline_item_key != item.value.outline_item_key
        or source_range.page_from != item.value.page
        or source_range.page_to != item.page_to
    )
    if not changed and not range_changed:
        return False
    for field, value in desired.items():
        setattr(node, field, value)
    node.updated_at = now
    source_range.outline_item_key = item.value.outline_item_key
    source_range.page_from = item.value.page
    source_range.page_to = item.page_to
    return True


def import_outlines(
    session: Session, project_id: UUID, command: ProgramOutlinesImportWrite
) -> ProgramChangeResult:
    """Импортировать выбранные ветви источников одной ревизией и одной записью undo."""
    with project_write_transaction(session, project_id):
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
        range_by_key = {
            (source_range.material_id, source_range.outline_item_key): source_range
            for source_range in ranges
        }
        range_by_anchor = {
            (
                source_range.material_id,
                _outline_key_anchor(source_range.outline_item_key),
            ): source_range
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
            section_indices = _section_indices(prepared)
            imported_by_index: dict[int, ProgramNode] = {}
            source_name = project_material_display_name(material, link)
            for index, item in enumerate(prepared):
                if not item.value.selected:
                    continue
                parent = (
                    imported_by_index.get(item.parent_index)
                    if item.parent_index is not None
                    else None
                )
                source_range = range_by_key.get((material.id, item.value.outline_item_key))
                if source_range is None:
                    source_range = range_by_anchor.get(
                        (material.id, _outline_key_anchor(item.value.outline_item_key))
                    )
                node = (
                    nodes_by_id.get(source_range.program_node_id)
                    if source_range is not None
                    else None
                )
                if node is not None:
                    imported_by_index[index] = node
                    desired_type = _node_type(
                        index, item, imported_by_index, section_indices
                    )
                    desired_position = node.sort_order
                    desired_parent_id = parent.id if parent is not None else None
                    if node.parent_id != desired_parent_id:
                        desired_position = next_position[desired_parent_id]
                        next_position[desired_parent_id] += 1
                    snapshot = _existing_inverse(node, source_range)
                    if _sync_existing_node(
                        node,
                        source_range,
                        item,
                        parent=parent,
                        node_type=desired_type,
                        sort_order=desired_position,
                        now=now,
                    ):
                        inverse.append(snapshot)
                        changed_node_id = changed_node_id or node.id
                    range_by_key[(material.id, item.value.outline_item_key)] = source_range
                    range_by_anchor[
                        (material.id, _outline_key_anchor(item.value.outline_item_key))
                    ] = source_range
                    continue
                node = ProgramNode(
                    id=uuid4(),
                    project_id=project_id,
                    parent_id=parent.id if parent is not None else None,
                    node_type=_node_type(index, item, imported_by_index, section_indices),
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
                source_range = ProgramNodeSourcePageRange(
                    project_id=project_id,
                    program_node_id=node.id,
                    material_id=material.id,
                    source_name_snapshot=source_name,
                    outline_item_key=item.value.outline_item_key,
                    page_from=item.value.page,
                    page_to=item.page_to,
                )
                session.add(source_range)
                nodes_by_id[node.id] = node
                imported_by_index[index] = node
                range_by_key[(material.id, item.value.outline_item_key)] = source_range
                range_by_anchor[
                    (material.id, _outline_key_anchor(item.value.outline_item_key))
                ] = source_range
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
