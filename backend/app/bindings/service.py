from collections import defaultdict
from dataclasses import dataclass
from uuid import UUID, uuid4

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.bindings import search as search_module
from app.bindings.schemas import (
    AffectedProjectPreview,
    BindingChangeResult,
    BindingCreateWrite,
    BindingFragmentRead,
    NodeBindingSummary,
    ReindexResult,
    SearchHighlightRead,
    SearchResultRead,
)
from app.materials.schemas import MaterialPurpose
from app.models import (
    Binding,
    BindingStatus,
    Material,
    MaterialBlock,
    MaterialFragment,
    MaterialPage,
    NodeType,
    PageQuality,
    ProgramNode,
    Project,
    ProjectActionLog,
    ProjectMaterial,
    ProjectStatus,
    WorkspaceVariant,
    utc_now,
)
from app.projects.errors import ProjectConflictError, ProjectDomainError, ProjectNotFoundError
from app.projects.schemas import LatestUndoableAction

STUDY_NODE_TYPES = {NodeType.TOPIC, NodeType.SUBPOINT}
ACTIVE_STATUSES = {BindingStatus.MANUAL, BindingStatus.CONFIRMED, BindingStatus.MACHINE}
QUALITY_RANK = {PageQuality.NATIVE: 0, PageQuality.OCR: 1, PageQuality.OCR_LOW: 2}


def _require_project(session: Session, project_id: UUID, *, writable: bool) -> Project:
    project = session.get(Project, project_id)
    if project is None or project.status == ProjectStatus.DRAFT:
        raise ProjectNotFoundError()
    if project.workspace_variant != WorkspaceVariant.EXAM:
        raise ProjectConflictError(
            "Привязки доступны только экзаменационным проектам",
            code="bindings_require_exam_project",
        )
    if writable and project.status != ProjectStatus.ACTIVE:
        raise ProjectConflictError(
            "Архивный или завершённый проект нельзя изменять",
            code="project_read_only",
            context={"current_status": project.status.value},
        )
    return project


def _require_study_node(session: Session, project_id: UUID, node_id: UUID) -> ProgramNode:
    node = session.get(ProgramNode, node_id)
    if node is None or node.project_id != project_id or node.is_archived:
        raise ProjectNotFoundError("Тема программы не найдена")
    if node.node_type not in STUDY_NODE_TYPES:
        raise ProjectDomainError(
            "Привязать материал можно только к изучаемому узлу",
            status=422,
            code="binding_requires_study_node",
        )
    return node


def _require_project_material(session: Session, project_id: UUID, material_id: UUID) -> Material:
    link = session.get(ProjectMaterial, (project_id, material_id))
    if link is None:
        raise ProjectConflictError(
            "Материал не подключён к этому проекту", code="material_not_in_project"
        )
    material = session.get(Material, material_id)
    if material is None:
        raise ProjectNotFoundError("Материал не найден")
    return material


def _record_action(
    session: Session, project: Project, action_type: str, target_title: str, inverse_data: dict
) -> None:
    session.add(
        ProjectActionLog(
            project_id=project.id,
            action_type=action_type,
            phase="active",
            payload_version=1,
            target_title=target_title,
            inverse_data=inverse_data,
        )
    )


def _latest_undoable_action(session: Session, project_id: UUID) -> LatestUndoableAction | None:
    row = session.scalar(
        select(ProjectActionLog)
        .where(
            ProjectActionLog.project_id == project_id,
            ProjectActionLog.phase == "active",
            ProjectActionLog.undone_at.is_(None),
        )
        .order_by(ProjectActionLog.sequence.desc())
        .limit(1)
    )
    return LatestUndoableAction.model_validate(row) if row is not None else None


def _fragment_read(
    session: Session, binding: Binding, node: ProgramNode | None = None
) -> BindingFragmentRead:
    fragment = session.get(MaterialFragment, binding.fragment_id)
    page = session.get(MaterialPage, fragment.page_id)
    material = session.get(Material, binding.material_id)
    if node is None:
        node = session.get(ProgramNode, binding.program_node_id)
    return BindingFragmentRead(
        id=binding.id,
        project_id=binding.project_id,
        program_node_id=binding.program_node_id,
        node_title=node.title if node is not None else "",
        fragment_id=fragment.id,
        material_id=material.id,
        material_name=material.original_name,
        block_id=binding.block_id,
        page_number=page.page_number,
        text=fragment.text,
        bbox=fragment.bbox,
        quality=fragment.quality,
        status=binding.status,
        mechanism=binding.mechanism,
        created_at=binding.created_at,
        updated_at=binding.updated_at,
    )


def _resolve_fragments(
    session: Session, project_id: UUID, command: BindingCreateWrite
) -> list[MaterialFragment]:
    if command.block_id is not None:
        block = session.get(MaterialBlock, command.block_id)
        if block is None:
            raise ProjectNotFoundError("Блок материала не найден")
        material = _require_project_material(session, project_id, block.material_id)
        if block.revision != material.active_parse_revision:
            raise ProjectConflictError(
                "Блок относится к устаревшей ревизии материала", code="block_revision_stale"
            )
        return list(
            session.scalars(
                select(MaterialFragment)
                .where(MaterialFragment.block_id == block.id)
                .order_by(MaterialFragment.sort_order)
            )
        )

    fragments: list[MaterialFragment] = []
    for fragment_id in dict.fromkeys(command.fragment_ids):
        fragment = session.get(MaterialFragment, fragment_id)
        if fragment is None:
            raise ProjectNotFoundError("Фрагмент материала не найден")
        material = _require_project_material(session, project_id, fragment.material_id)
        page = session.get(MaterialPage, fragment.page_id)
        if page.revision != material.active_parse_revision:
            raise ProjectConflictError(
                "Фрагмент относится к устаревшей ревизии материала",
                code="fragment_revision_stale",
            )
        fragments.append(fragment)
    return fragments


def create_bindings(
    session: Session, project_id: UUID, command: BindingCreateWrite
) -> BindingChangeResult:
    with session.begin():
        project = _require_project(session, project_id, writable=True)
        node = _require_study_node(session, project_id, command.program_node_id)
        fragments = _resolve_fragments(session, project_id, command)
        if not fragments:
            raise ProjectDomainError(
                "У блока нет содержательных фрагментов для привязки",
                status=422,
                code="binding_no_fragments",
            )

        now = utc_now()
        results: list[Binding] = []
        touched_ids: list[UUID] = []
        for fragment in fragments:
            existing = session.scalar(
                select(Binding).where(
                    Binding.project_id == project_id,
                    Binding.program_node_id == node.id,
                    Binding.fragment_id == fragment.id,
                )
            )
            if existing is None:
                binding = Binding(
                    id=uuid4(),
                    project_id=project_id,
                    program_node_id=node.id,
                    fragment_id=fragment.id,
                    material_id=fragment.material_id,
                    block_id=command.block_id,
                    status=BindingStatus.MANUAL,
                    mechanism=command.mechanism,
                    created_at=now,
                    updated_at=now,
                )
                session.add(binding)
                session.flush()
                results.append(binding)
                touched_ids.append(binding.id)
            elif existing.status == BindingStatus.REMOVED:
                existing.status = BindingStatus.MANUAL
                existing.mechanism = command.mechanism
                existing.updated_at = now
                results.append(existing)
                touched_ids.append(existing.id)
            else:
                results.append(existing)

        if touched_ids:
            _record_action(
                session,
                project,
                "binding_create",
                node.title,
                {"binding_ids": [str(binding_id) for binding_id in touched_ids]},
            )
        session.flush()
        return BindingChangeResult(
            bindings=[_fragment_read(session, binding, node) for binding in results],
            latest_undoable_action=_latest_undoable_action(session, project_id),
        )


def remove_binding(session: Session, project_id: UUID, binding_id: UUID) -> BindingChangeResult:
    with session.begin():
        project = _require_project(session, project_id, writable=True)
        binding = session.get(Binding, binding_id)
        if binding is None or binding.project_id != project_id:
            raise ProjectNotFoundError("Привязка не найдена")
        if binding.status == BindingStatus.REMOVED:
            raise ProjectConflictError("Привязка уже снята", code="binding_already_removed")
        node = session.get(ProgramNode, binding.program_node_id)
        binding.status = BindingStatus.REMOVED
        binding.updated_at = utc_now()
        _record_action(
            session,
            project,
            "binding_remove",
            node.title if node else "",
            {"binding_ids": [str(binding.id)]},
        )
        session.flush()
        return BindingChangeResult(
            bindings=[_fragment_read(session, binding, node)],
            latest_undoable_action=_latest_undoable_action(session, project_id),
        )


def restore_binding(session: Session, project_id: UUID, binding_id: UUID) -> BindingChangeResult:
    with session.begin():
        project = _require_project(session, project_id, writable=True)
        binding = session.get(Binding, binding_id)
        if binding is None or binding.project_id != project_id:
            raise ProjectNotFoundError("Привязка не найдена")
        if binding.status != BindingStatus.REMOVED:
            raise ProjectConflictError("Привязка не снята", code="binding_not_removed")
        node = session.get(ProgramNode, binding.program_node_id)
        binding.status = BindingStatus.MANUAL
        binding.updated_at = utc_now()
        _record_action(
            session,
            project,
            "binding_create",
            node.title if node else "",
            {"binding_ids": [str(binding.id)]},
        )
        session.flush()
        return BindingChangeResult(
            bindings=[_fragment_read(session, binding, node)],
            latest_undoable_action=_latest_undoable_action(session, project_id),
        )


def apply_undo(session: Session, project_id: UUID, action_type: str, data: dict) -> None:
    """Вызывается из projects.program.undo_last_project_action (Р1, journal reuse)."""
    target_status = (
        BindingStatus.REMOVED if action_type == "binding_create" else BindingStatus.MANUAL
    )
    now = utc_now()
    for raw_id in data["binding_ids"]:
        binding = session.get(Binding, UUID(raw_id))
        if binding is None or binding.project_id != project_id:
            raise ProjectDomainError(
                "Привязка для отмены не найдена", status=422, code="binding_undo_missing"
            )
        binding.status = target_status
        binding.updated_at = now


def list_bindings(
    session: Session,
    project_id: UUID,
    *,
    node_id: UUID | None = None,
    material_id: UUID | None = None,
    page_number: int | None = None,
    status: BindingStatus | None = None,
) -> list[BindingFragmentRead]:
    _require_project(session, project_id, writable=False)
    query = (
        select(Binding, MaterialPage.page_number)
        .join(MaterialFragment, MaterialFragment.id == Binding.fragment_id)
        .join(MaterialPage, MaterialPage.id == MaterialFragment.page_id)
        .where(Binding.project_id == project_id)
    )
    if node_id is not None:
        query = query.where(Binding.program_node_id == node_id)
    if material_id is not None:
        query = query.where(Binding.material_id == material_id)
    if page_number is not None:
        query = query.where(MaterialPage.page_number == page_number)
    if status is not None:
        query = query.where(Binding.status == status)
    else:
        query = query.where(Binding.status.in_(ACTIVE_STATUSES))
    query = query.order_by(MaterialPage.page_number, MaterialFragment.sort_order)

    nodes_by_id: dict[UUID, ProgramNode] = {}
    results: list[BindingFragmentRead] = []
    for binding, _page_number in session.execute(query).all():
        node = nodes_by_id.get(binding.program_node_id)
        if node is None:
            node = session.get(ProgramNode, binding.program_node_id)
            if node is not None:
                nodes_by_id[binding.program_node_id] = node
        results.append(_fragment_read(session, binding, node))
    return results


def get_summary(session: Session, project_id: UUID) -> list[NodeBindingSummary]:
    _require_project(session, project_id, writable=False)
    rows = session.execute(
        select(Binding.program_node_id, Binding.material_id, MaterialFragment.quality)
        .join(MaterialFragment, MaterialFragment.id == Binding.fragment_id)
        .where(Binding.project_id == project_id, Binding.status.in_(ACTIVE_STATUSES))
    ).all()
    aggregates: dict[UUID, dict] = {}
    for node_id, material_id, quality in rows:
        entry = aggregates.setdefault(
            node_id, {"fragment_count": 0, "materials": set(), "worst_quality": None}
        )
        entry["fragment_count"] += 1
        entry["materials"].add(material_id)
        worst = entry["worst_quality"]
        if worst is None or QUALITY_RANK[quality] > QUALITY_RANK[worst]:
            entry["worst_quality"] = quality
    return [
        NodeBindingSummary(
            program_node_id=node_id,
            fragment_count=entry["fragment_count"],
            material_count=len(entry["materials"]),
            worst_quality=entry["worst_quality"],
        )
        for node_id, entry in aggregates.items()
    ]


def _project_material_ids(
    session: Session, project_id: UUID, material_id: UUID | None
) -> list[UUID]:
    """Материалы, по которым имеет смысл искать формулировку вопроса.

    Файл со списком вопросов (`exam_structure`) исключается: искать вопрос
    по файлу вопросов бессмысленно — он вытесняет из выдачи ответы и учебники.
    Явный `material_id` — это поиск внутри открытого файла, там фильтр не нужен.
    """
    if material_id is not None:
        link = session.get(ProjectMaterial, (project_id, material_id))
        if link is None:
            raise ProjectNotFoundError("Материал проекта не найден")
        return [material_id]
    links = session.scalars(
        select(ProjectMaterial).where(ProjectMaterial.project_id == project_id)
    )
    return [
        link.material_id
        for link in links
        if MaterialPurpose.EXAM_STRUCTURE.value not in (link.purposes or [])
    ]


def search_project_materials(
    session: Session,
    project_id: UUID,
    query: str,
    *,
    material_id: UUID | None = None,
    node_id: UUID | None = None,
    limit: int = search_module.RESULT_LIMIT,
) -> list[SearchResultRead]:
    project = session.get(Project, project_id)
    if project is None:
        raise ProjectNotFoundError()
    material_ids = _project_material_ids(session, project_id, material_id)
    hits = search_module.search_fragments(session, material_ids, query, limit=limit)

    bound_fragment_ids: set[UUID] = set()
    if node_id is not None:
        bound_fragment_ids = set(
            session.scalars(
                select(Binding.fragment_id).where(
                    Binding.project_id == project_id,
                    Binding.program_node_id == node_id,
                    Binding.status.in_(ACTIVE_STATUSES),
                )
            )
        )

    return [
        SearchResultRead(
            fragment_ids=hit.fragment_ids,
            material_id=hit.material_id,
            material_name=hit.material_name,
            block_id=hit.block_id,
            block_title=hit.block_title,
            page_from=hit.page_from,
            page_to=hit.page_to,
            quality=hit.quality,
            text=hit.text,
            highlights=[
                SearchHighlightRead(start=highlight.start, end=highlight.end)
                for highlight in hit.highlights
            ],
            already_bound=bool(bound_fragment_ids)
            and any(fragment_id in bound_fragment_ids for fragment_id in hit.fragment_ids),
        )
        for hit in hits
    ]


def reindex_material(session: Session, project_id: UUID, material_id: UUID) -> ReindexResult:
    with session.begin():
        project = session.get(Project, project_id)
        if project is None:
            raise ProjectNotFoundError()
        _require_project_material(session, project_id, material_id)
        indexed = search_module.reindex_material(session, material_id)
    return ReindexResult(material_id=material_id, indexed_fragments=indexed)


def _normalize_for_match(text: str) -> str:
    return " ".join(text.split())


def _match_fragments_on_page(
    old_fragments: list[MaterialFragment], new_fragments: list[MaterialFragment]
) -> dict[UUID, MaterialFragment]:
    """Р6: сначала точный текст, затем порядковый номер при неизменившемся счёте."""
    mapping: dict[UUID, MaterialFragment] = {}
    old_by_text: dict[str, list[MaterialFragment]] = defaultdict(list)
    for fragment in old_fragments:
        old_by_text[_normalize_for_match(fragment.text)].append(fragment)
    new_by_text: dict[str, list[MaterialFragment]] = defaultdict(list)
    for fragment in new_fragments:
        new_by_text[_normalize_for_match(fragment.text)].append(fragment)

    matched_old_ids: set[UUID] = set()
    matched_new_ids: set[UUID] = set()
    for text_key, olds in old_by_text.items():
        news = new_by_text.get(text_key, [])
        for old_fragment, new_fragment in zip(olds, news, strict=False):
            mapping[old_fragment.id] = new_fragment
            matched_old_ids.add(old_fragment.id)
            matched_new_ids.add(new_fragment.id)

    if len(old_fragments) == len(new_fragments):
        remaining_old = [f for f in old_fragments if f.id not in matched_old_ids]
        remaining_new = [f for f in new_fragments if f.id not in matched_new_ids]
        for old_fragment, new_fragment in zip(remaining_old, remaining_new, strict=True):
            mapping[old_fragment.id] = new_fragment
    return mapping


@dataclass(frozen=True, slots=True)
class TransferResult:
    transferred: int
    orphaned: list[UUID]


def transfer_bindings_on_revision(
    session: Session,
    material_id: UUID,
    fragments_by_page_old: dict[int, list[MaterialFragment]],
    fragments_by_page_new: dict[int, list[MaterialFragment]],
) -> TransferResult:
    """Р6: вызывается из materials.service.update_page_text в той же транзакции."""
    bindings = list(
        session.scalars(
            select(Binding).where(
                Binding.material_id == material_id, Binding.status.in_(ACTIVE_STATUSES)
            )
        )
    )
    if not bindings:
        return TransferResult(transferred=0, orphaned=[])

    old_fragment_by_id = {
        fragment.id: fragment
        for fragments in fragments_by_page_old.values()
        for fragment in fragments
    }
    mapping: dict[UUID, MaterialFragment] = {}
    for page_number, olds in fragments_by_page_old.items():
        news = fragments_by_page_new.get(page_number, [])
        mapping.update(_match_fragments_on_page(olds, news))

    now = utc_now()
    transferred = 0
    orphaned: list[UUID] = []
    for binding in bindings:
        if binding.fragment_id not in old_fragment_by_id:
            continue
        new_fragment = mapping.get(binding.fragment_id)
        if new_fragment is not None:
            binding.fragment_id = new_fragment.id
            if binding.block_id is not None:
                binding.block_id = new_fragment.block_id
            binding.updated_at = now
            transferred += 1
        else:
            binding.status = BindingStatus.ORPHANED
            binding.updated_at = now
            orphaned.append(binding.id)
    return TransferResult(transferred=transferred, orphaned=orphaned)


def delete_project_material_bindings(
    session: Session, project_id: UUID, material_id: UUID
) -> None:
    """Материал уходит из проекта (не из библиотеки) — привязки этого проекта теряют смысл."""
    session.execute(
        delete(Binding).where(Binding.project_id == project_id, Binding.material_id == material_id)
    )


def binding_count_for_material(session: Session, material_id: UUID) -> int:
    return (
        session.scalar(
            select(func.count())
            .select_from(Binding)
            .where(Binding.material_id == material_id, Binding.status.in_(ACTIVE_STATUSES))
        )
        or 0
    )


def affected_projects_preview(
    session: Session, material_id: UUID
) -> list[AffectedProjectPreview]:
    """Р7: для каждого проекта — узлы, которые останутся без материала после удаления."""
    pairs = session.execute(
        select(Binding.project_id, Binding.program_node_id)
        .where(Binding.material_id == material_id, Binding.status.in_(ACTIVE_STATUSES))
        .distinct()
    ).all()
    if not pairs:
        return []

    node_ids_by_project: dict[UUID, set[UUID]] = defaultdict(set)
    for project_id, node_id in pairs:
        node_ids_by_project[project_id].add(node_id)

    results: list[AffectedProjectPreview] = []
    for project_id, node_ids in node_ids_by_project.items():
        other_material_nodes = set(
            session.scalars(
                select(Binding.program_node_id).where(
                    Binding.project_id == project_id,
                    Binding.program_node_id.in_(node_ids),
                    Binding.material_id != material_id,
                    Binding.status.in_(ACTIVE_STATUSES),
                )
            )
        )
        losing_node_ids = node_ids - other_material_nodes
        if not losing_node_ids:
            continue
        project = session.get(Project, project_id)
        nodes = session.scalars(
            select(ProgramNode).where(ProgramNode.id.in_(losing_node_ids))
        )
        results.append(
            AffectedProjectPreview(
                project_id=project_id,
                project_name=project.name if project is not None else "",
                nodes_losing_material=sorted(node.title for node in nodes),
            )
        )
    return results
