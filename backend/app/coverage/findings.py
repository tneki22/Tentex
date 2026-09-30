"""Проверяемые находки о новой теме: предпросмотр, решение и общий undo."""

from collections import defaultdict
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.coverage.interaction import (
    _binding_snapshot,
    _decision,
    _decision_snapshot,
    _put_reject_decision,
    _restore_binding,
    _restore_decision,
    _target_fingerprint,
)
from app.coverage.schemas import FindingApply, FindingPreviewRequest, FindingReject
from app.coverage.snapshots import fingerprint, require_project
from app.coverage.validation import normalize_title
from app.db import project_write_transaction
from app.materials.naming import project_material_display_name
from app.models import (
    Binding,
    BindingMechanism,
    BindingStatus,
    CoverageFinding,
    Material,
    MaterialBlock,
    MaterialFragment,
    MaterialPage,
    NodeType,
    ProgramNode,
    ProjectActionLog,
    ProjectMaterial,
    utc_now,
)
from app.projects import program
from app.projects.errors import ProjectConflictError, ProjectDomainError, ProjectNotFoundError
from app.projects.schemas import ProgramNodeCreate


def _proposal_fields(row: CoverageFinding) -> tuple[str, UUID | None, list[UUID]]:
    operations = row.payload.get("operations") or []
    operation = next((item for item in operations if item.get("op") == "create"), {})
    title = " ".join(str(operation.get("title", "")).split())
    parent = operation.get("parent")
    refs = []
    for evidence in row.payload.get("evidence") or []:
        try:
            refs.append(UUID(evidence["ref"]))
        except (KeyError, TypeError, ValueError):
            continue
    return title, UUID(parent) if parent else None, refs


def _rows(session: Session, project_id: UUID, finding_ids: list[UUID]) -> list[CoverageFinding]:
    ids = list(dict.fromkeys(finding_ids))
    rows = list(session.scalars(select(CoverageFinding).where(CoverageFinding.id.in_(ids))))
    if len(rows) != len(ids) or any(
        row.project_id != project_id or row.kind != "new_topic" or row.state != "proposed"
        for row in rows
    ):
        raise ProjectNotFoundError("Предложение больше не доступно")
    titles = {normalize_title(_proposal_fields(row)[0]) for row in rows}
    if len(titles) != 1:
        raise ProjectDomainError(
            "Выберите находки с одним названием", status=422, code="coverage_finding_group"
        )
    return sorted(rows, key=lambda row: str(row.id))


def _fragment(session: Session, project_id: UUID, fragment_id: UUID) -> MaterialFragment:
    fragment = session.get(MaterialFragment, fragment_id)
    block = session.get(MaterialBlock, fragment.block_id) if fragment else None
    material = session.get(Material, fragment.material_id) if fragment else None
    link = session.get(ProjectMaterial, (project_id, fragment.material_id)) if fragment else None
    if (
        not fragment
        or not block
        or not material
        or not link
        or block.revision != material.active_parse_revision
    ):
        raise ProjectConflictError("Опора уже устарела", code="coverage_finding_stale")
    return fragment


def _block_fragments(session: Session, project_id: UUID, block_ids: list[UUID]) -> list[UUID]:
    ids: list[UUID] = []
    for block_id in dict.fromkeys(block_ids):
        block = session.get(MaterialBlock, block_id)
        if not block or not session.get(ProjectMaterial, (project_id, block.material_id)):
            raise ProjectNotFoundError("Блок материала не найден")
        material = session.get(Material, block.material_id)
        if not material or block.revision != material.active_parse_revision:
            raise ProjectConflictError("Блок уже устарел", code="coverage_finding_stale")
        ids.extend(
            session.scalars(
                select(MaterialFragment.id).where(MaterialFragment.block_id == block_id)
            )
        )
    return ids


def preview(session: Session, project_id: UUID, command: FindingPreviewRequest) -> dict:
    """Снимок предложения: только действующие опоры и снимаемые связи родителя."""
    project = require_project(session, project_id)
    if not command.finding_ids and not command.block_ids:
        raise ProjectDomainError(
            "Выберите находку или блок", status=422, code="coverage_finding_empty"
        )
    rows = _rows(session, project_id, command.finding_ids) if command.finding_ids else []
    display_row = (
        min(
            rows,
            key=lambda row: (
                not _proposal_fields(row)[0][:1].isupper(),
                _proposal_fields(row)[0].casefold(),
                _proposal_fields(row)[0],
            ),
        )
        if rows
        else None
    )
    title, parent_id, _ = _proposal_fields(display_row) if display_row else ("", None, [])
    refs = [ref for row in rows for ref in _proposal_fields(row)[2]]
    refs.extend(_block_fragments(session, project_id, command.block_ids))
    fragments = [_fragment(session, project_id, fragment_id) for fragment_id in dict.fromkeys(refs)]
    if not fragments:
        raise ProjectDomainError(
            "У предложения нет доступных фрагментов", status=422, code="coverage_finding_empty"
        )
    parents = list(session.scalars(select(ProgramNode).where(ProgramNode.project_id == project_id)))
    if parent_id and not any(
        node.id == parent_id and node.is_in_current_program and not node.is_archived
        for node in parents
    ):
        parent_id = None
    parent_bindings = (
        list(
            session.scalars(
                select(Binding).where(
                    Binding.project_id == project_id,
                    Binding.program_node_id == parent_id,
                    Binding.fragment_id.in_([item.id for item in fragments]),
                    Binding.status.in_(
                        [BindingStatus.MANUAL, BindingStatus.CONFIRMED, BindingStatus.MACHINE]
                    ),
                )
            )
        )
        if parent_id
        else []
    )
    payload = [(str(row.id), row.proposal_version, row.evidence_refs, row.payload) for row in rows]
    version = fingerprint(
        {
            "findings": payload,
            "fragments": [(str(item.id), item.text) for item in fragments],
            "blocks": sorted(map(str, command.block_ids)),
        }
    )
    items = []
    for fragment in fragments:
        page = session.get(MaterialPage, fragment.page_id)
        material = session.get(Material, fragment.material_id)
        link = session.get(ProjectMaterial, (project_id, fragment.material_id))
        items.append(
            {
                "id": str(fragment.id),
                "block_id": str(fragment.block_id),
                "material_id": str(fragment.material_id),
                "material_name": project_material_display_name(material, link),
                "page": page.page_number,
                "text": fragment.text,
                "role": "definition" if fragment.structure_level is not None else "explanation",
            }
        )
    return {
        "finding_ids": [str(row.id) for row in rows],
        "block_ids": sorted(map(str, command.block_ids)),
        "source_block_ids": sorted({str(item.block_id) for item in fragments}),
        "title": title,
        "parent_id": str(parent_id) if parent_id else None,
        "fragments": items,
        "remove_parent_binding_ids": [str(item.id) for item in parent_bindings],
        "parent_bindings": [
            {"id": str(item.id), "fragment_id": str(item.fragment_id)} for item in parent_bindings
        ],
        "proposal_version": version,
        "program_revision": project.program_revision,
        "coverage_revision": project.coverage_revision,
    }


def list_proposed(session: Session, project_id: UUID) -> dict:
    """Группировать живые `new_topic` по названию, учитывая ё и пробелы."""
    require_project(session, project_id)
    groups: dict[str, list[UUID]] = defaultdict(list)
    for row in session.scalars(
        select(CoverageFinding).where(
            CoverageFinding.project_id == project_id,
            CoverageFinding.kind == "new_topic",
            CoverageFinding.state == "proposed",
        )
    ):
        title, _, refs = _proposal_fields(row)
        if title and refs:
            groups[normalize_title(title)].append(row.id)
    items = []
    for ids in groups.values():
        try:
            items.append(preview(session, project_id, FindingPreviewRequest(finding_ids=ids)))
        except ProjectConflictError:
            continue
    return {"items": sorted(items, key=lambda item: item["title"].casefold())}


def _check_snapshot(current: dict, expected_version: str, expected_coverage: int) -> None:
    if current["proposal_version"] != expected_version:
        raise ProjectConflictError("Предложение обновилось", code="stale_finding_proposal")
    if current["coverage_revision"] != expected_coverage:
        raise ProjectConflictError("Покрытие уже изменилось", code="stale_coverage_revision")


def _application_choices(session, project_id, current, command):
    """Все выбранные строки должны принадлежать текущему предпросмотру."""
    if current["program_revision"] != command.expected_program_revision:
        raise ProjectConflictError("Программа уже изменена", code="stale_program_revision")
    title = " ".join(command.title.split())
    if not title:
        raise ProjectDomainError(
            "Введите название темы", status=422, code="coverage_topic_title_required"
        )
    existing = session.scalars(
        select(ProgramNode).where(
            ProgramNode.project_id == project_id,
            ProgramNode.is_in_current_program.is_(True),
            ProgramNode.is_archived.is_(False),
        )
    )
    if any(normalize_title(node.title) == normalize_title(title) for node in existing):
        raise ProjectConflictError("Тема с таким названием уже есть", code="coverage_topic_exists")
    available = {item["id"]: item for item in current["fragments"]}
    chosen = list(dict.fromkeys(map(str, command.fragment_ids)))
    if not chosen or any(item not in available for item in chosen):
        raise ProjectDomainError(
            "Выберите фрагменты предложения", status=422, code="coverage_finding_fragments"
        )
    removable = (
        set(current["remove_parent_binding_ids"])
        if str(command.parent_id) == current["parent_id"]
        else set()
    )
    removed = list(dict.fromkeys(map(str, command.remove_parent_binding_ids)))
    if any(item not in removable for item in removed):
        raise ProjectConflictError("Связи родителя обновились", code="stale_finding_proposal")
    if removed:
        selected_old = session.scalars(
            select(Binding).where(Binding.id.in_([UUID(item) for item in removed]))
        )
        if any(str(item.fragment_id) not in chosen for item in selected_old):
            raise ProjectDomainError(
                "Связь снятого фрагмента нельзя удалить отдельно",
                status=422,
                code="coverage_finding_parent_selection",
            )
    parent = session.get(ProgramNode, command.parent_id) if command.parent_id else None
    if command.parent_id and (
        not parent
        or parent.project_id != project_id
        or parent.is_archived
        or not parent.is_in_current_program
        or parent.node_type == NodeType.SECTION
    ):
        raise ProjectNotFoundError("Родительская тема не найдена")
    return title, available, chosen, removed


def _apply_binding_changes(session, project_id, node_id, available, chosen, removed):
    """Снимки и запреты родителя пишутся рядом с подтверждёнными опорами новой темы."""
    before, decision_keys, before_decisions = {}, [], {}
    for binding_id in removed:
        old = session.get(Binding, UUID(binding_id))
        before[binding_id] = _binding_snapshot(old)
        key = ("reject_link", f"{old.program_node_id}:{old.fragment_id}")
        decision_keys.append(key)
        before_decisions[f"{key[0]}:{key[1]}"] = _decision_snapshot(
            _decision(session, project_id, *key)
        )
        old.status = BindingStatus.REMOVED
        old.updated_at = utc_now()
        _put_reject_decision(session, project_id, old, True)
    for fragment_id in chosen:
        item = available[fragment_id]
        fragment = session.get(MaterialFragment, UUID(fragment_id))
        binding = Binding(
            project_id=project_id,
            program_node_id=node_id,
            fragment_id=fragment.id,
            material_id=fragment.material_id,
            block_id=fragment.block_id,
            status=BindingStatus.CONFIRMED,
            mechanism=BindingMechanism.MANUAL,
            semantic_kind="content",
            roles=[item["role"]],
            semantic_revision=1,
        )
        session.add(binding)
        session.flush()
        before[str(binding.id)] = None
    return before, decision_keys, before_decisions


def _record_application(
    session, project_id, title, node_id, finding_ids, before, decision_keys, before_decisions
):
    """Один журнал хранит снимки всех затронутых строк и отпечаток для undo."""
    rows = _rows(session, project_id, finding_ids) if finding_ids else []
    old_states = {str(row.id): [row.state, row.feedback, row.applied_action_id] for row in rows}
    action = ProjectActionLog(
        project_id=project_id,
        action_type="coverage_finding_apply",
        phase="active",
        payload_version=1,
        target_title=f"Создать тему «{title}»",
        inverse_data={},
    )
    session.add(action)
    session.flush()
    for kind, key in decision_keys:
        _decision(session, project_id, kind, key).action_id = action.sequence
    for row in rows:
        row.state = "applied"
        row.applied_action_id = action.sequence
    project = require_project(session, project_id)
    project.coverage_revision += 1
    binding_ids = sorted(before)
    action.inverse_data = {
        "node_id": str(node_id),
        "bindings": before,
        "binding_ids": binding_ids,
        "after_fingerprint": _target_fingerprint(session, project_id, binding_ids, decision_keys),
        "decisions": before_decisions,
        "decision_keys": [list(item) for item in decision_keys],
        "findings": old_states,
    }
    return action.sequence, project.program_revision, project.coverage_revision


def _parent_content_blocks(session, project_id, parent_id):
    """Предложение повторной проверки ограничено оставшимися опорами родителя."""
    if not parent_id:
        return []
    rows = session.scalars(
        select(Binding.block_id)
        .join(MaterialBlock, MaterialBlock.id == Binding.block_id)
        .join(Material, Material.id == MaterialBlock.material_id)
        .where(
            Binding.project_id == project_id,
            Binding.program_node_id == parent_id,
            Binding.semantic_kind == "content",
            Binding.status.in_(
                [BindingStatus.MANUAL, BindingStatus.CONFIRMED, BindingStatus.MACHINE]
            ),
            MaterialBlock.revision == Material.active_parse_revision,
        )
    )
    return sorted({str(item) for item in rows})


def apply(session: Session, project_id: UUID, command: FindingApply) -> dict:
    """Узел, подтверждённые опоры, снятие родителя и находки — одна транзакция."""
    with project_write_transaction(session, project_id):
        current = preview(session, project_id, command)
        _check_snapshot(current, command.proposal_version, command.expected_coverage_revision)
        title, available, chosen, removed = _application_choices(
            session, project_id, current, command
        )
        _, node, _ = program.create_node_in_transaction(
            session,
            project_id,
            ProgramNodeCreate(
                expected_program_revision=command.expected_program_revision,
                parent_id=command.parent_id,
                node_type=NodeType.TOPIC,
                title=title,
            ),
        )
        before, decision_keys, before_decisions = _apply_binding_changes(
            session, project_id, node.id, available, chosen, removed
        )
        action_sequence, program_revision, coverage_revision = _record_application(
            session,
            project_id,
            title,
            node.id,
            command.finding_ids,
            before,
            decision_keys,
            before_decisions,
        )
        parent_blocks = _parent_content_blocks(session, project_id, command.parent_id)
        parent_materials = (
            session.scalars(
                select(MaterialBlock.material_id).where(
                    MaterialBlock.id.in_([UUID(item) for item in parent_blocks])
                )
            )
            if parent_blocks
            else []
        )
        return {
            "node_id": str(node.id),
            "action_sequence": action_sequence,
            "program_revision": program_revision,
            "coverage_revision": coverage_revision,
            "parent_block_ids": parent_blocks,
            "material_ids": sorted(
                {
                    *(available[item]["material_id"] for item in chosen),
                    *(str(item) for item in parent_materials),
                }
            ),
        }


def reject(session: Session, project_id: UUID, command: FindingReject) -> dict:
    """Отклонить группу на тех же опорах с одним обратимым действием."""
    if not command.finding_ids:
        raise ProjectDomainError("Выберите находку", status=422, code="coverage_finding_empty")
    with project_write_transaction(session, project_id):
        current = preview(session, project_id, command)
        _check_snapshot(current, command.proposal_version, command.expected_coverage_revision)
        rows = _rows(session, project_id, command.finding_ids)
        old_states = {str(row.id): [row.state, row.feedback, row.applied_action_id] for row in rows}
        anchors = sorted((item["id"], fingerprint(item["text"])) for item in current["fragments"])
        action = ProjectActionLog(
            project_id=project_id,
            action_type="coverage_finding_reject",
            phase="active",
            payload_version=1,
            target_title=f"Не нужно: {current['title']}",
            inverse_data={"findings": old_states},
        )
        session.add(action)
        session.flush()
        for row in rows:
            row.state = "rejected"
            row.feedback = {
                "reason": command.feedback,
                "title": normalize_title(current["title"]),
                "anchors": anchors,
            }
        project = require_project(session, project_id)
        project.coverage_revision += 1
        return {"action_sequence": action.sequence, "coverage_revision": project.coverage_revision}


def undo(session: Session, project_id: UUID, action_type: str, data: dict) -> None:
    """Восстановить все части действия после проверки общего стека undo."""
    if action_type == "coverage_finding_apply":
        decision_keys = [tuple(item) for item in data["decision_keys"]]
        current = _target_fingerprint(session, project_id, data["binding_ids"], decision_keys)
        if current != data["after_fingerprint"]:
            raise ProjectConflictError("Связи уже изменились", code="coverage_undo_conflict")
        for binding_id, snapshot in data["bindings"].items():
            _restore_binding(session, snapshot, binding_id)
        for kind, key in decision_keys:
            _restore_decision(
                session, project_id, kind, key, data["decisions"].get(f"{kind}:{key}")
            )
        node = session.get(ProgramNode, UUID(data["node_id"]))
        if node is None:
            raise ProjectNotFoundError("Созданная тема не найдена")
        node.is_in_current_program = False
        node.is_archived = True
    for finding_id, (state, feedback, action_id) in data["findings"].items():
        row = session.get(CoverageFinding, UUID(finding_id))
        if row is not None:
            row.state, row.feedback, row.applied_action_id = state, feedback, action_id
    require_project(session, project_id).coverage_revision += 1


def was_rejected(session: Session, project_id: UUID, finding: dict) -> bool:
    """Та же тема на тех же точных текстах не возникает повторно после отказа."""
    operation = next(
        (item for item in finding.get("operations", []) if item.get("op") == "create"), {}
    )
    title = normalize_title(operation.get("title", ""))
    refs = []
    for item in finding.get("evidence", []):
        try:
            fragment = session.get(MaterialFragment, UUID(item["ref"]))
        except (KeyError, TypeError, ValueError):
            return False
        if fragment is None:
            return False
        refs.append((str(fragment.id), fingerprint(fragment.text)))
    if not title or not refs:
        return False
    for row in session.scalars(
        select(CoverageFinding).where(
            CoverageFinding.project_id == project_id,
            CoverageFinding.kind == "new_topic",
            CoverageFinding.state == "rejected",
        )
    ):
        feedback = row.feedback or {}
        if feedback.get("title") == title and set(map(tuple, refs)) <= set(
            map(tuple, feedback.get("anchors", []))
        ):
            return True
    return False
