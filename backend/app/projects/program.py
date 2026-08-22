from collections import defaultdict
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.bindings.service import apply_undo as apply_binding_undo
from app.models import (
    ExamKind,
    GoalPassport,
    GoalRole,
    NodeType,
    OriginKind,
    ProgramNode,
    Project,
    ProjectActionLog,
    ProjectStatus,
    TargetOutcome,
    WizardDraft,
    WorkspaceVariant,
    utc_now,
)
from app.projects.errors import (
    ProjectConflictError,
    ProjectInvariantError,
    ProjectNotFoundError,
)
from app.projects.importer import ParsedExamProgram
from app.projects.schemas import (
    ActionUndoResult,
    LatestUndoableAction,
    ProgramChangeResult,
    ProgramMove,
    ProgramNodeCreate,
    ProgramNodeRead,
    ProgramNodeUpdate,
    ProgramRevisionCommand,
    ProgramState,
    ProgramSwap,
    ProgramTargetLevel,
)


def _nodes(session: Session, project_id: UUID) -> list[ProgramNode]:
    return list(
        session.scalars(
            select(ProgramNode)
            .where(ProgramNode.project_id == project_id)
            .order_by(
                ProgramNode.parent_id.is_not(None),
                ProgramNode.parent_id,
                ProgramNode.sort_order,
                ProgramNode.id,
            )
        )
    )


def _phase(project: Project) -> str:
    return "draft" if project.status == ProjectStatus.DRAFT else "active"


def _require_project(session: Session, project_id: UUID) -> Project:
    project = session.get(Project, project_id)
    if project is None:
        raise ProjectNotFoundError()
    return project


def _require_writable_project(session: Session, project_id: UUID) -> Project:
    project = _require_project(session, project_id)
    if project.status not in {ProjectStatus.DRAFT, ProjectStatus.ACTIVE}:
        raise ProjectConflictError(
            "Архивный или завершённый проект нельзя изменять",
            code="project_read_only",
            context={"current_status": project.status.value},
        )
    return project


def _latest_action_row(session: Session, project_id: UUID, phase: str) -> ProjectActionLog | None:
    return session.scalar(
        select(ProjectActionLog)
        .where(
            ProjectActionLog.project_id == project_id,
            ProjectActionLog.phase == phase,
            ProjectActionLog.undone_at.is_(None),
        )
        .order_by(ProjectActionLog.sequence.desc())
        .limit(1)
    )


def latest_undoable_action(
    session: Session, project_id: UUID, phase: str
) -> LatestUndoableAction | None:
    row = _latest_action_row(session, project_id, phase)
    return LatestUndoableAction.model_validate(row) if row is not None else None


def read_program(session: Session, project_id: UUID) -> ProgramState:
    project = _require_project(session, project_id)
    return ProgramState(
        nodes=[ProgramNodeRead.model_validate(node) for node in _nodes(session, project_id)],
        revision=project.program_revision,
    )


def _validate_tree(parent_by_id: dict[UUID, UUID | None]) -> None:
    depths: dict[UUID, int] = {}
    for node_id in parent_by_id:
        path: list[UUID] = []
        seen: set[UUID] = set()
        current = node_id
        while current not in depths:
            if current in seen:
                raise ProjectInvariantError("В программе обнаружен цикл")
            seen.add(current)
            path.append(current)
            parent_id = parent_by_id.get(current)
            if parent_id is None:
                base_depth = 0
                break
            if parent_id not in parent_by_id:
                raise ProjectInvariantError("Родитель узла отсутствует в этом проекте")
            current = parent_id
        else:
            base_depth = depths[current]

        for path_node_id in reversed(path):
            base_depth += 1
            if base_depth > 4:
                raise ProjectInvariantError("Глубина программы не может превышать четыре уровня")
            depths[path_node_id] = base_depth


def _validate_variant(
    variant: WorkspaceVariant, node_type: NodeType, exam_kind: ExamKind | None
) -> None:
    if variant == WorkspaceVariant.TEXTBOOK:
        if exam_kind is not None:
            raise ProjectInvariantError("В учебниковой программе exam_kind должен быть null")
        return
    if node_type == NodeType.SECTION:
        if exam_kind not in {None, ExamKind.TICKET}:
            raise ProjectInvariantError("Раздел экзамена может быть группой или билетом")
    elif exam_kind not in {ExamKind.QUESTION, ExamKind.TASK}:
        raise ProjectInvariantError("Тема экзамена должна быть вопросом или задачей")


def _visible_parent(nodes_by_id: dict[UUID, ProgramNode], parent_id: UUID | None) -> None:
    if parent_id is None:
        return
    parent = nodes_by_id.get(parent_id)
    if parent is None:
        raise ProjectInvariantError("Родитель узла должен находиться в этом проекте")
    if not parent.is_in_current_program or parent.is_archived:
        raise ProjectInvariantError("Нельзя поместить узел в скрытый или архивный раздел")


def _subtree_ids(nodes: list[ProgramNode], root_id: UUID) -> list[UUID]:
    children: dict[UUID, list[UUID]] = defaultdict(list)
    for node in nodes:
        if node.parent_id is not None:
            children[node.parent_id].append(node.id)
    result: list[UUID] = []
    stack = [root_id]
    while stack:
        current = stack.pop()
        result.append(current)
        stack.extend(reversed(children.get(current, [])))
    return result


def _normalize_group(nodes: list[ProgramNode], parent_id: UUID | None) -> None:
    siblings = sorted(
        (node for node in nodes if node.parent_id == parent_id),
        key=lambda node: (node.sort_order, str(node.id)),
    )
    for index, sibling in enumerate(siblings):
        sibling.sort_order = index


def _place_node(
    nodes: list[ProgramNode], node: ProgramNode, parent_id: UUID | None, position: int | None
) -> None:
    siblings = sorted(
        (sibling for sibling in nodes if sibling.parent_id == parent_id and sibling.id != node.id),
        key=lambda sibling: (sibling.sort_order, str(sibling.id)),
    )
    visible = [
        sibling for sibling in siblings if sibling.is_in_current_program and not sibling.is_archived
    ]
    target_position = len(visible) if position is None else position
    if target_position > len(visible):
        raise ProjectInvariantError("Позиция выходит за границы списка соседей")
    if target_position < len(visible):
        full_index = siblings.index(visible[target_position])
    elif visible:
        full_index = siblings.index(visible[-1]) + 1
    else:
        full_index = len(siblings)
    node.parent_id = parent_id
    siblings.insert(full_index, node)
    for index, sibling in enumerate(siblings):
        sibling.sort_order = index


def _begin_program_change(session: Session, project: Project, expected_revision: int) -> int | None:
    now = utc_now()
    result = session.execute(
        update(Project)
        .where(Project.id == project.id, Project.program_revision == expected_revision)
        .values(
            program_revision=Project.program_revision + 1,
            updated_at=now,
        )
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        current = session.scalar(select(Project.program_revision).where(Project.id == project.id))
        raise ProjectConflictError(
            "Программа уже изменена в другой вкладке",
            code="stale_program_revision",
            context={"current_program_revision": current},
        )
    draft_revision: int | None = None
    if project.status == ProjectStatus.DRAFT:
        draft_result = session.execute(
            update(WizardDraft)
            .where(WizardDraft.project_id == project.id)
            .values(revision=WizardDraft.revision + 1, updated_at=now)
            .execution_options(synchronize_session=False)
        )
        if draft_result.rowcount != 1:
            raise ProjectInvariantError("У draft-проекта отсутствует WizardDraft")
        draft_revision = session.scalar(
            select(WizardDraft.revision).where(WizardDraft.project_id == project.id)
        )
    session.expire(project)
    return draft_revision


def _record_action(
    session: Session,
    project: Project,
    action_type: str,
    target_title: str,
    inverse_data: dict[str, Any],
) -> None:
    session.add(
        ProjectActionLog(
            project_id=project.id,
            action_type=action_type,
            phase=_phase(project),
            payload_version=1,
            target_title=target_title,
            inverse_data=inverse_data,
        )
    )


def _change_result(
    session: Session,
    project: Project,
    changed_node_id: UUID | None,
    draft_revision: int | None,
) -> ProgramChangeResult:
    session.flush()
    changed_node = (
        session.scalar(
            select(ProgramNode).where(
                ProgramNode.project_id == project.id, ProgramNode.id == changed_node_id
            )
        )
        if changed_node_id is not None
        else None
    )
    return ProgramChangeResult(
        changed_node=(
            ProgramNodeRead.model_validate(changed_node) if changed_node is not None else None
        ),
        program=read_program(session, project.id),
        latest_undoable_action=latest_undoable_action(session, project.id, _phase(project)),
        draft_revision=draft_revision,
    )


def _node_snapshot(node: ProgramNode) -> dict[str, Any]:
    return {
        "id": str(node.id),
        "project_id": str(node.project_id),
        "parent_id": str(node.parent_id) if node.parent_id else None,
        "node_type": node.node_type.value,
        "exam_kind": node.exam_kind.value if node.exam_kind else None,
        "sort_order": node.sort_order,
        "title": node.title,
        "section_purpose": node.section_purpose,
        "goal_role": node.goal_role.value if node.goal_role else None,
        "target_level": node.target_level.value if node.target_level else None,
        "is_in_current_program": node.is_in_current_program,
        "needs_material": node.needs_material,
        "is_archived": node.is_archived,
        "origin_kind": node.origin_kind.value,
        "origin_note": node.origin_note,
        "origin_material_id": str(node.origin_material_id) if node.origin_material_id else None,
        "created_at": node.created_at.isoformat(),
        "updated_at": node.updated_at.isoformat(),
    }


def create_program_node(
    session: Session, project_id: UUID, command: ProgramNodeCreate
) -> ProgramChangeResult:
    with session.begin():
        project = _require_writable_project(session, project_id)
        nodes = _nodes(session, project_id)
        nodes_by_id = {node.id: node for node in nodes}
        _visible_parent(nodes_by_id, command.parent_id)
        _validate_variant(project.workspace_variant, command.node_type, command.exam_kind)
        node_id = uuid4()
        parent_map = {node.id: node.parent_id for node in nodes}
        parent_map[node_id] = command.parent_id
        _validate_tree(parent_map)
        passport = session.get(GoalPassport, project_id)
        target_level = command.target_level or (
            passport.target_outcome if passport is not None else None
        )
        node = ProgramNode(
            id=node_id,
            project_id=project_id,
            parent_id=command.parent_id,
            node_type=command.node_type,
            exam_kind=command.exam_kind,
            sort_order=0,
            title=command.title,
            section_purpose=command.section_purpose,
            goal_role=command.goal_role,
            target_level=target_level,
            is_in_current_program=True,
            needs_material=command.needs_material,
            is_archived=False,
            origin_kind=OriginKind.MANUAL,
            origin_note=None,
        )
        nodes.append(node)
        _place_node(nodes, node, command.parent_id, command.position)
        session.add(node)
        draft_revision = _begin_program_change(session, project, command.expected_program_revision)
        _record_action(
            session,
            project,
            "node_create",
            node.title,
            {"node_id": str(node.id)},
        )
        return _change_result(session, project, node.id, draft_revision)


def update_program_node(
    session: Session,
    project_id: UUID,
    node_id: UUID,
    command: ProgramNodeUpdate,
) -> ProgramChangeResult:
    with session.begin():
        project = _require_writable_project(session, project_id)
        node = session.scalar(
            select(ProgramNode).where(
                ProgramNode.project_id == project_id, ProgramNode.id == node_id
            )
        )
        if node is None:
            raise ProjectNotFoundError("Узел программы не найден")
        data = command.model_dump(
            mode="python", exclude_unset=True, exclude={"expected_program_revision"}
        )
        for field in {"title", "node_type", "needs_material"}:
            if field in data and data[field] is None:
                raise ProjectInvariantError("Обязательное поле узла нельзя очистить")
        inverse: dict[str, Any] = {}
        for field, value in data.items():
            old_value = getattr(node, field)
            inverse[field] = old_value.value if hasattr(old_value, "value") else old_value
            setattr(node, field, value)
        _validate_variant(project.workspace_variant, node.node_type, node.exam_kind)
        draft_revision = _begin_program_change(session, project, command.expected_program_revision)
        node.updated_at = utc_now()
        _record_action(
            session,
            project,
            "node_update",
            node.title,
            {"node_id": str(node.id), "fields": inverse},
        )
        return _change_result(session, project, node.id, draft_revision)


def move_program_node(
    session: Session, project_id: UUID, node_id: UUID, command: ProgramMove
) -> ProgramChangeResult:
    with session.begin():
        project = _require_writable_project(session, project_id)
        nodes = _nodes(session, project_id)
        nodes_by_id = {node.id: node for node in nodes}
        node = nodes_by_id.get(node_id)
        if node is None:
            raise ProjectNotFoundError("Узел программы не найден")
        if not node.is_in_current_program or node.is_archived:
            raise ProjectInvariantError("Скрытый или архивный узел нельзя перемещать")
        _visible_parent(nodes_by_id, command.parent_id)
        positions = [
            {
                "id": str(item.id),
                "parent_id": str(item.parent_id) if item.parent_id else None,
                "sort_order": item.sort_order,
            }
            for item in nodes
        ]
        old_parent = node.parent_id
        parent_map = {item.id: item.parent_id for item in nodes}
        parent_map[node.id] = command.parent_id
        _validate_tree(parent_map)
        _place_node(nodes, node, command.parent_id, command.position)
        if old_parent != command.parent_id:
            _normalize_group(nodes, old_parent)
        draft_revision = _begin_program_change(session, project, command.expected_program_revision)
        now = utc_now()
        for item in nodes:
            item.updated_at = now
        _record_action(
            session,
            project,
            "node_move",
            node.title,
            {"positions": positions},
        )
        return _change_result(session, project, node.id, draft_revision)


def swap_program_nodes(
    session: Session, project_id: UUID, node_id: UUID, command: ProgramSwap
) -> ProgramChangeResult:
    with session.begin():
        project = _require_writable_project(session, project_id)
        nodes = _nodes(session, project_id)
        nodes_by_id = {node.id: node for node in nodes}
        node = nodes_by_id.get(node_id)
        target = nodes_by_id.get(command.target_node_id)
        if node is None or target is None:
            raise ProjectNotFoundError("Узел программы не найден")
        if node.id == target.id:
            raise ProjectInvariantError("Нельзя поменять узел местами с самим собой")
        if not node.is_in_current_program or node.is_archived:
            raise ProjectInvariantError("Скрытый или архивный узел нельзя перемещать")
        if not target.is_in_current_program or target.is_archived:
            raise ProjectInvariantError("Скрытый или архивный узел нельзя перемещать")
        if target.id in _subtree_ids(nodes, node.id) or node.id in _subtree_ids(nodes, target.id):
            raise ProjectInvariantError("Нельзя поменять местами родительский и дочерний узлы")

        positions = [
            {
                "id": str(item.id),
                "parent_id": str(item.parent_id) if item.parent_id else None,
                "sort_order": item.sort_order,
            }
            for item in nodes
        ]
        node_parent_id, node_sort_order = node.parent_id, node.sort_order
        parent_map = {item.id: item.parent_id for item in nodes}
        parent_map[node.id] = target.parent_id
        parent_map[target.id] = node_parent_id
        _validate_tree(parent_map)
        node.parent_id, node.sort_order = target.parent_id, target.sort_order
        target.parent_id, target.sort_order = node_parent_id, node_sort_order

        draft_revision = _begin_program_change(session, project, command.expected_program_revision)
        now = utc_now()
        for item in nodes:
            item.updated_at = now
        _record_action(
            session,
            project,
            "node_swap",
            f"{node.title} ↔ {target.title}",
            {"positions": positions},
        )
        return _change_result(session, project, node.id, draft_revision)


def set_target_level(
    session: Session, project_id: UUID, node_id: UUID, command: ProgramTargetLevel
) -> ProgramChangeResult:
    with session.begin():
        project = _require_writable_project(session, project_id)
        nodes = _nodes(session, project_id)
        nodes_by_id = {node.id: node for node in nodes}
        node = nodes_by_id.get(node_id)
        if node is None:
            raise ProjectNotFoundError("Узел программы не найден")
        ids = _subtree_ids(nodes, node_id) if command.include_descendants else [node_id]
        inverse = [
            {
                "id": str(item_id),
                "target_level": (
                    nodes_by_id[item_id].target_level.value
                    if nodes_by_id[item_id].target_level
                    else None
                ),
            }
            for item_id in ids
        ]
        draft_revision = _begin_program_change(session, project, command.expected_program_revision)
        now = utc_now()
        for item_id in ids:
            nodes_by_id[item_id].target_level = command.target_level
            nodes_by_id[item_id].updated_at = now
        _record_action(
            session,
            project,
            "target_level_subtree",
            node.title,
            {"values": inverse},
        )
        return _change_result(session, project, node.id, draft_revision)


def _set_subtree_visibility(
    session: Session,
    project_id: UUID,
    node_id: UUID,
    command: ProgramRevisionCommand,
    *,
    restore: bool,
) -> ProgramChangeResult:
    with session.begin():
        project = _require_writable_project(session, project_id)
        nodes = _nodes(session, project_id)
        nodes_by_id = {node.id: node for node in nodes}
        node = nodes_by_id.get(node_id)
        if node is None:
            raise ProjectNotFoundError("Узел программы не найден")
        if restore:
            if node.is_in_current_program:
                raise ProjectInvariantError("Узел уже входит в текущую программу")
            parent = nodes_by_id.get(node.parent_id) if node.parent_id else None
            if parent is not None and not parent.is_in_current_program:
                raise ProjectInvariantError("Сначала верните верхний скрытый раздел")
        elif not node.is_in_current_program:
            raise ProjectInvariantError("Узел уже убран из текущей программы")
        ids = _subtree_ids(nodes, node_id)
        inverse = [
            {
                "id": str(item_id),
                "is_in_current_program": nodes_by_id[item_id].is_in_current_program,
            }
            for item_id in ids
        ]
        draft_revision = _begin_program_change(session, project, command.expected_program_revision)
        now = utc_now()
        for item_id in ids:
            nodes_by_id[item_id].is_in_current_program = restore
            nodes_by_id[item_id].updated_at = now
        _record_action(
            session,
            project,
            "node_restore" if restore else "node_remove",
            node.title,
            {"values": inverse},
        )
        return _change_result(session, project, node.id, draft_revision)


def remove_program_node(
    session: Session, project_id: UUID, node_id: UUID, command: ProgramRevisionCommand
) -> ProgramChangeResult:
    return _set_subtree_visibility(session, project_id, node_id, command, restore=False)


def restore_program_node(
    session: Session, project_id: UUID, node_id: UUID, command: ProgramRevisionCommand
) -> ProgramChangeResult:
    return _set_subtree_visibility(session, project_id, node_id, command, restore=True)


def _delete_nodes_leaves_first(session: Session, nodes: list[ProgramNode]) -> None:
    parent_map = {node.id: node.parent_id for node in nodes}
    depths: dict[UUID, int] = {}

    def depth(node_id: UUID) -> int:
        if node_id not in depths:
            parent_id = parent_map[node_id]
            depths[node_id] = 1 if parent_id is None else depth(parent_id) + 1
        return depths[node_id]

    by_depth: dict[int, list[UUID]] = defaultdict(list)
    for node in nodes:
        by_depth[depth(node.id)].append(node.id)
    for item_depth in sorted(by_depth, reverse=True):
        session.execute(delete(ProgramNode).where(ProgramNode.id.in_(by_depth[item_depth])))
        session.flush()


def replace_draft_program(
    session: Session,
    project_id: UUID,
    *,
    expected_draft_revision: int,
    expected_program_revision: int,
    parsed: ParsedExamProgram,
    material_id: UUID | None = None,
    material_name: str | None = None,
) -> ProgramChangeResult:
    with session.begin():
        project = _require_writable_project(session, project_id)
        if project.status != ProjectStatus.DRAFT:
            raise ProjectConflictError("Импорт доступен только в черновике")
        draft = session.get(WizardDraft, project_id)
        if draft is None:
            raise ProjectNotFoundError("Черновик проекта не найден")
        if draft.revision != expected_draft_revision:
            raise ProjectConflictError(
                "Черновик уже изменён в другой вкладке",
                code="stale_draft_revision",
                context={"current_draft_revision": draft.revision},
            )
        old_nodes = _nodes(session, project_id)
        snapshot = [_node_snapshot(node) for node in old_nodes]
        draft_revision = _begin_program_change(session, project, expected_program_revision)
        _delete_nodes_leaves_first(session, old_nodes)
        passport = session.get(GoalPassport, project_id)
        target_level = passport.target_outcome if passport is not None else None
        created_ids: list[UUID] = []
        for parsed_node in parsed.nodes:
            node_id = uuid4()
            parent_id = (
                created_ids[parsed_node.parent_index]
                if parsed_node.parent_index is not None
                else None
            )
            node = ProgramNode(
                id=node_id,
                project_id=project_id,
                parent_id=parent_id,
                node_type=parsed_node.node_type,
                exam_kind=parsed_node.exam_kind,
                sort_order=parsed_node.position,
                title=parsed_node.title,
                section_purpose=None,
                goal_role=GoalRole.TARGET,
                target_level=target_level,
                is_in_current_program=True,
                needs_material=False,
                is_archived=False,
                origin_kind=OriginKind.IMPORT,
                origin_note=(
                    f"Материал: {material_name}" if material_name else "Вставленный текст"
                ),
                origin_material_id=material_id,
            )
            session.add(node)
            session.flush()
            created_ids.append(node_id)
        _record_action(
            session,
            project,
            "exam_import",
            "Импорт списка экзамена",
            {"nodes": snapshot},
        )
        return _change_result(session, project, None, draft_revision)


def replace_active_exam_program(
    session: Session,
    project_id: UUID,
    *,
    expected_program_revision: int,
    parsed: ParsedExamProgram,
    material_id: UUID,
    material_name: str,
) -> ProgramChangeResult:
    with session.begin():
        project = _require_writable_project(session, project_id)
        if (
            project.status != ProjectStatus.ACTIVE
            or project.workspace_variant != WorkspaceVariant.EXAM
        ):
            raise ProjectConflictError("Импорт доступен только в активном экзаменационном проекте")
        old_nodes = _nodes(session, project_id)
        snapshot = [_node_snapshot(node) for node in old_nodes]
        draft_revision = _begin_program_change(session, project, expected_program_revision)
        passport = session.get(GoalPassport, project_id)
        target_level = passport.target_outcome if passport is not None else None

        candidates: dict[tuple[str, str | None, str], list[ProgramNode]] = defaultdict(list)
        for node in old_nodes:
            if node.is_in_current_program and not node.is_archived:
                key = (
                    node.node_type.value,
                    node.exam_kind.value if node.exam_kind else None,
                    node.title.casefold(),
                )
                candidates[key].append(node)

        imported: list[ProgramNode] = []
        reused: set[UUID] = set()
        created: list[UUID] = []
        for parsed_node in parsed.nodes:
            key = (
                parsed_node.node_type.value,
                parsed_node.exam_kind.value,
                parsed_node.title.casefold(),
            )
            matches = [node for node in candidates.get(key, []) if node.id not in reused]
            if len(matches) == 1:
                node = matches[0]
                reused.add(node.id)
            else:
                node = ProgramNode(id=uuid4(), project_id=project_id)
                session.add(node)
                created.append(node.id)
            parent_id = (
                imported[parsed_node.parent_index].id
                if parsed_node.parent_index is not None
                else None
            )
            node.parent_id = parent_id
            node.node_type = parsed_node.node_type
            node.exam_kind = parsed_node.exam_kind
            node.sort_order = parsed_node.position
            node.title = parsed_node.title
            node.section_purpose = None
            node.goal_role = GoalRole.TARGET
            node.target_level = node.target_level or target_level
            node.is_in_current_program = True
            node.needs_material = False
            node.is_archived = False
            node.origin_kind = OriginKind.IMPORT
            node.origin_note = f"Материал: {material_name}"
            node.origin_material_id = material_id
            session.flush()
            imported.append(node)

        imported_ids = {node.id for node in imported}
        for node in old_nodes:
            if node.id not in imported_ids:
                node.is_in_current_program = False
                node.is_archived = True

        _record_action(
            session,
            project,
            "active_exam_import",
            f"Импорт из {material_name}",
            {"nodes": snapshot, "created_ids": [str(node_id) for node_id in created]},
        )
        return _change_result(
            session, project, imported[0].id if imported else None, draft_revision
        )


def _restore_snapshot(session: Session, project_id: UUID, snapshots: list[dict[str, Any]]) -> None:
    current = _nodes(session, project_id)
    _delete_nodes_leaves_first(session, current)
    remaining = list(snapshots)
    created: set[UUID] = set()
    while remaining:
        progress = False
        for snapshot in list(remaining):
            parent_id = UUID(snapshot["parent_id"]) if snapshot["parent_id"] else None
            if parent_id is not None and parent_id not in created:
                continue
            node = ProgramNode(
                id=UUID(snapshot["id"]),
                project_id=project_id,
                parent_id=parent_id,
                node_type=NodeType(snapshot["node_type"]),
                exam_kind=ExamKind(snapshot["exam_kind"]) if snapshot["exam_kind"] else None,
                sort_order=snapshot["sort_order"],
                title=snapshot["title"],
                section_purpose=snapshot["section_purpose"],
                goal_role=GoalRole(snapshot["goal_role"]) if snapshot["goal_role"] else None,
                target_level=(
                    TargetOutcome(snapshot["target_level"]) if snapshot["target_level"] else None
                ),
                is_in_current_program=snapshot["is_in_current_program"],
                needs_material=snapshot["needs_material"],
                is_archived=snapshot["is_archived"],
                origin_kind=OriginKind(snapshot["origin_kind"]),
                origin_note=snapshot["origin_note"],
                created_at=datetime.fromisoformat(snapshot["created_at"]),
                updated_at=datetime.fromisoformat(snapshot["updated_at"]),
            )
            session.add(node)
            session.flush()
            created.add(node.id)
            remaining.remove(snapshot)
            progress = True
        if not progress:
            raise ProjectInvariantError("Снимок импорта содержит разорванное дерево")


def _increment_for_undo(session: Session, project: Project) -> int | None:
    now = utc_now()
    project.program_revision += 1
    project.updated_at = now
    if project.status != ProjectStatus.DRAFT:
        return None
    draft = session.get(WizardDraft, project.id)
    if draft is None:
        raise ProjectInvariantError("У draft-проекта отсутствует WizardDraft")
    draft.revision += 1
    draft.updated_at = now
    return draft.revision


def undo_last_project_action(
    session: Session, project_id: UUID, expected_action_sequence: int
) -> ActionUndoResult:
    with session.begin():
        project = _require_writable_project(session, project_id)
        phase = _phase(project)
        action = _latest_action_row(session, project_id, phase)
        current_sequence = action.sequence if action is not None else None
        if action is None or current_sequence != expected_action_sequence:
            raise ProjectConflictError(
                "Последнее действие уже изменилось",
                code="stale_action_sequence",
                context={"current_action_sequence": current_sequence},
            )
        if action.payload_version != 1:
            raise ProjectInvariantError("Версия отменяемого действия не поддерживается")

        nodes = _nodes(session, project_id)
        nodes_by_id = {node.id: node for node in nodes}
        data = action.inverse_data
        match action.action_type:
            case "exam_import":
                _restore_snapshot(session, project_id, data["nodes"])
            case "node_create":
                node_id = UUID(data["node_id"])
                node = nodes_by_id.get(node_id)
                if node is None:
                    raise ProjectInvariantError("Созданный узел для undo не найден")
                for item_id in _subtree_ids(nodes, node_id):
                    nodes_by_id[item_id].is_in_current_program = False
            case "node_update":
                node = nodes_by_id.get(UUID(data["node_id"]))
                if node is None:
                    raise ProjectInvariantError("Изменённый узел для undo не найден")
                enum_fields = {
                    "node_type": NodeType,
                    "exam_kind": ExamKind,
                    "goal_role": GoalRole,
                }
                for field, value in data["fields"].items():
                    enum_class = enum_fields.get(field)
                    setattr(node, field, enum_class(value) if enum_class and value else value)
            case "node_move" | "node_swap":
                for position in data["positions"]:
                    node = nodes_by_id.get(UUID(position["id"]))
                    if node is None:
                        raise ProjectInvariantError("Узел порядка для undo не найден")
                    node.parent_id = UUID(position["parent_id"]) if position["parent_id"] else None
                    node.sort_order = position["sort_order"]
            case "target_level_subtree":
                for value in data["values"]:
                    node = nodes_by_id.get(UUID(value["id"]))
                    if node is None:
                        raise ProjectInvariantError("Узел уровня для undo не найден")
                    node.target_level = (
                        TargetOutcome(value["target_level"]) if value["target_level"] else None
                    )
            case "node_remove" | "node_restore":
                for value in data["values"]:
                    node = nodes_by_id.get(UUID(value["id"]))
                    if node is None:
                        raise ProjectInvariantError("Скрытый узел для undo не найден")
                    node.is_in_current_program = value["is_in_current_program"]
            case "binding_create" | "binding_remove":
                apply_binding_undo(session, project_id, action.action_type, data)
            case "active_exam_import" | "ai_import_repair":
                old_ids = {UUID(item["id"]) for item in data["nodes"]}
                for item in data["nodes"]:
                    node = nodes_by_id.get(UUID(item["id"]))
                    if node is None:
                        raise ProjectInvariantError("Узел до импорта для undo не найден")
                    node.parent_id = UUID(item["parent_id"]) if item["parent_id"] else None
                    node.node_type = NodeType(item["node_type"])
                    node.exam_kind = ExamKind(item["exam_kind"]) if item["exam_kind"] else None
                    node.sort_order = item["sort_order"]
                    node.title = item["title"]
                    node.section_purpose = item["section_purpose"]
                    node.goal_role = GoalRole(item["goal_role"]) if item["goal_role"] else None
                    node.target_level = (
                        TargetOutcome(item["target_level"]) if item["target_level"] else None
                    )
                    node.is_in_current_program = item["is_in_current_program"]
                    node.needs_material = item["needs_material"]
                    node.is_archived = item["is_archived"]
                    node.origin_kind = OriginKind(item["origin_kind"])
                    node.origin_note = item["origin_note"]
                    node.origin_material_id = (
                        UUID(item["origin_material_id"]) if item.get("origin_material_id") else None
                    )
                for node_id in map(UUID, data["created_ids"]):
                    node = nodes_by_id.get(node_id)
                    if node is not None and node.id not in old_ids:
                        node.is_in_current_program = False
                        node.is_archived = True
            case "ai_program_grouping":
                section_ids = {UUID(item["id"]) for item in data["sections"]}
                sections_by_id = {
                    section_id: nodes_by_id.get(section_id) for section_id in section_ids
                }
                if any(section is None for section in sections_by_id.values()):
                    raise ProjectInvariantError("Раздел группировки для undo не найден")
                for item in data["sections"]:
                    section = sections_by_id[UUID(item["id"])]
                    assert section is not None
                    if section.title != item["title"] or section.origin_note != item["origin_note"]:
                        raise ProjectConflictError(
                            "Разделы уже отредактированы; автоматическая отмена небезопасна",
                            code="ai_grouping_undo_conflict",
                        )
                for position in data["positions"]:
                    node = nodes_by_id.get(UUID(position["id"]))
                    if node is None or node.parent_id not in section_ids:
                        raise ProjectConflictError(
                            "Состав разделов уже изменён; автоматическая отмена небезопасна",
                            code="ai_grouping_undo_conflict",
                        )
                    node.parent_id = None
                    node.sort_order = position["sort_order"]
                session.flush()
                for section in sections_by_id.values():
                    assert section is not None
                    session.delete(section)
            case _:
                raise ProjectInvariantError(f"Тип действия {action.action_type!r} нельзя отменить")

        action.undone_at = utc_now()
        draft_revision = _increment_for_undo(session, project)
        session.flush()
        return ActionUndoResult(
            undone_action_type=action.action_type,
            program=read_program(session, project_id),
            draft_revision=draft_revision,
            latest_undoable_action=latest_undoable_action(session, project_id, phase),
        )


def prepare_for_activation(
    session: Session, project_id: UUID, default_target_level: TargetOutcome
) -> ProgramState:
    project = _require_project(session, project_id)
    nodes = _nodes(session, project_id)
    changed = False
    now = utc_now()
    for node in nodes:
        if node.target_level is None:
            node.target_level = default_target_level
            node.updated_at = now
            changed = True
    if changed:
        project.program_revision += 1
        project.updated_at = now
        session.flush()
    return read_program(session, project_id)


def delete_program_tree(session: Session, project_id: UUID) -> None:
    _delete_nodes_leaves_first(session, _nodes(session, project_id))
