"""Ручной редактор урока: блоки, разрезы, медиа, темы, привязки и отмена.

Каждое структурное действие — снимок урока до правки и одна запись журнала
`lesson_blocks`; текст пояснения сохраняется без журнала. Правила — записка
«Уроки» §3.2, §3.6, §3.7, §4.3, §4.4; контракт — `docs/architecture/lessons.md`.
"""

import mimetypes
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import UploadFile
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.bindings.service import ACTIVE_STATUSES
from app.db import project_write_transaction
from app.lessons import boundaries
from app.lessons import refs as refs_module
from app.lessons.refs import Bounds
from app.lessons.schemas import (
    LessonBlockWrite,
    LessonChangeResult,
    LessonConfirmWrite,
    LessonNoteWrite,
    LessonUnbindOffer,
    LessonUnbindWrite,
)
from app.lessons.service import (
    ACTION_LESSON_BLOCKS,
    ACTION_LESSON_UNBIND,
    _bind_segment_fragments,
    _change_result,
    _load_program,
    _plan_source,
    _require_lesson,
    _require_lessons_project,
    _require_revision,
    _require_study_node,
    _source_name,
    media_kind,
)
from app.materials.storage import material_path, store_namespaced_upload
from app.models import (
    Binding,
    BindingMechanism,
    BindingStatus,
    Lesson,
    LessonBlock,
    LessonBlockKind,
    LessonBlockOrigin,
    LessonNoteVariant,
    LessonRefRole,
    LessonSourceRef,
    LessonTopic,
    Material,
    MaterialBlock,
    MaterialFragment,
    MaterialPage,
    ProgramNode,
    ProjectActionLog,
    ProjectMaterial,
    utc_now,
)
from app.projects.errors import ProjectDomainError, ProjectNotFoundError

# Снять из урока можно только то, что урок и создал: чужие ручные привязки не предлагаются.
LESSON_MECHANISMS = {BindingMechanism.LESSON, BindingMechanism.OUTLINE}
# Те же форматы и предел, что у изображений конспекта (`conspects.service`): фото доски
# с телефона укладывается в 20 МБ, а форматы показывает любой браузер без конвертации.
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
IMAGE_MAX_BYTES = 20 * 1024 * 1024


def _invalid(detail: str, code: str) -> ProjectDomainError:
    return ProjectDomainError(detail, status=422, code=code)


# --- контекст правки -------------------------------------------------------------------


@dataclass(slots=True)
class _Edit:
    session: Session
    lesson: Lesson
    blocks: list[LessonBlock]
    command: LessonBlockWrite
    binding_ids: list[UUID] = field(default_factory=list)
    offer: LessonUnbindOffer | None = None

    def insert(self, block: LessonBlock, after: UUID | None) -> None:
        self.session.add(block)
        before = self.command.before_block_id
        if before is not None:
            index = next(
                (i for i, item in enumerate(self.blocks) if item.id == before), len(self.blocks)
            )
        else:
            index = next(
                (i + 1 for i, item in enumerate(self.blocks) if item.id == after), len(self.blocks)
            )
        self.blocks.insert(index, block)

    def block(self, kind: LessonBlockKind | None = None) -> LessonBlock:
        block = next((item for item in self.blocks if item.id == self.command.block_id), None)
        if block is None:
            raise ProjectNotFoundError("Блок урока не найден")
        if kind is not None and block.kind != kind:
            raise _invalid("Действие доступно только для куска материала", "lesson_not_source")
        return block

    def new_block(self, kind: LessonBlockKind, **fields: object) -> LessonBlock:
        now = utc_now()
        fields.setdefault("origin", LessonBlockOrigin.MANUAL)
        return LessonBlock(
            id=uuid4(), lesson_id=self.lesson.id, sort_order=0, kind=kind,
            created_at=now, updated_at=now, **fields,
        )

    def topic_ids(self) -> list[UUID]:
        return list(self.session.scalars(
            select(LessonTopic.program_node_id)
            .where(LessonTopic.lesson_id == self.lesson.id)
            .order_by(LessonTopic.sort_order)
        ))


def _ordered_blocks(session: Session, lesson_id: UUID) -> list[LessonBlock]:
    return list(session.scalars(
        select(LessonBlock).where(LessonBlock.lesson_id == lesson_id)
        .order_by(LessonBlock.sort_order, LessonBlock.id)
    ))


def _content_ref(session: Session, block: LessonBlock) -> LessonSourceRef:
    ref = session.scalar(select(LessonSourceRef).where(
        LessonSourceRef.block_id == block.id, LessonSourceRef.role == LessonRefRole.CONTENT
    ))
    if ref is None:
        raise _invalid("У куска нет ссылки на материал", "lesson_not_source")
    return ref


def _ref_material(session: Session, project_id: UUID, ref: LessonSourceRef) -> Material:
    material = session.get(Material, ref.material_id) if ref.material_id else None
    if material is None or session.get(ProjectMaterial, (project_id, material.id)) is None:
        raise _invalid(
            "Источник недоступен: материал убран из проекта", "lesson_source_unavailable"
        )
    return material


# --- снимок и отмена -------------------------------------------------------------------


def _ref_data(ref: LessonSourceRef) -> dict:
    return {
        "id": str(ref.id), "role": ref.role.value,
        "material_id": str(ref.material_id) if ref.material_id else None,
        "source_name_snapshot": ref.source_name_snapshot,
        "material_revision": ref.material_revision, "page_from": ref.page_from,
        "page_to": ref.page_to,
        "from_fragment_id": str(ref.from_fragment_id) if ref.from_fragment_id else None,
        "to_fragment_id": str(ref.to_fragment_id) if ref.to_fragment_id else None,
        "region_bbox": ref.region_bbox, "always_pages": ref.always_pages,
        "boundary_shifted": ref.boundary_shifted,
    }


def _block_data(session: Session, block: LessonBlock) -> dict:
    return {
        "id": str(block.id), "sort_order": block.sort_order, "kind": block.kind.value,
        "variant": block.variant.value if block.variant else None,
        "body_md": block.body_md, "origin": block.origin.value,
        "basis": block.basis.value if block.basis else None,
        "ai_run_id": str(block.ai_run_id) if block.ai_run_id else None,
        "activity_id": str(block.activity_id) if block.activity_id else None,
        "media_path": block.media_path,
        "bound_program_node_id": str(block.bound_program_node_id)
        if block.bound_program_node_id else None,
        "refs": [_ref_data(ref) for ref in session.scalars(
            select(LessonSourceRef).where(LessonSourceRef.block_id == block.id)
        )],
    }


def _topics_data(session: Session, lesson_id: UUID) -> list[dict]:
    return [
        {"program_node_id": str(topic.program_node_id), "sort_order": topic.sort_order,
         "title_snapshot": topic.topic_title_snapshot}
        for topic in session.scalars(select(LessonTopic).where(LessonTopic.lesson_id == lesson_id))
    ]


def _uuid(raw: str | None) -> UUID | None:
    return UUID(raw) if raw else None


def _restore_refs(session: Session, block_id: UUID, refs: list[dict]) -> None:
    """Ссылки правятся на месте: удалённая и заново добавленная строка с тем же id
    столкнулась бы с объектом, который ещё помнит сессия."""
    current = {
        ref.id: ref
        for ref in session.scalars(
            select(LessonSourceRef).where(LessonSourceRef.block_id == block_id)
        )
    }
    wanted = {UUID(ref["id"]) for ref in refs}
    for ref_id, ref in current.items():
        if ref_id not in wanted:
            session.delete(ref)
    for data in refs:
        ref = current.get(UUID(data["id"]))
        if ref is None:
            ref = LessonSourceRef(id=UUID(data["id"]), block_id=block_id)
            session.add(ref)
        ref.role = LessonRefRole(data["role"])
        ref.material_id = _uuid(data["material_id"])
        ref.source_name_snapshot = data["source_name_snapshot"]
        ref.material_revision = data["material_revision"]
        ref.page_from, ref.page_to = data["page_from"], data["page_to"]
        ref.from_fragment_id = _uuid(data["from_fragment_id"])
        ref.to_fragment_id = _uuid(data["to_fragment_id"])
        ref.region_bbox = data["region_bbox"]
        ref.always_pages = data["always_pages"]
        ref.boundary_shifted = data.get("boundary_shifted", False)


def _restore_topics(session: Session, lesson: Lesson, topics: list[dict]) -> None:
    current = {
        topic.program_node_id: topic
        for topic in session.scalars(select(LessonTopic).where(LessonTopic.lesson_id == lesson.id))
    }
    wanted = {UUID(item["program_node_id"]): item for item in topics}
    for node_id, topic in current.items():
        if node_id not in wanted:
            session.delete(topic)
    for node_id, item in wanted.items():
        topic = current.get(node_id)
        if topic is None:
            topic = LessonTopic(lesson_id=lesson.id, program_node_id=node_id,
                                project_id=lesson.project_id)
            session.add(topic)
        topic.sort_order = item["sort_order"]
        topic.topic_title_snapshot = item["title_snapshot"]


def _drop_block(session: Session, block: LessonBlock) -> None:
    for ref in session.scalars(select(LessonSourceRef).where(LessonSourceRef.block_id == block.id)):
        session.delete(ref)
    session.delete(block)


def apply_blocks_undo(session: Session, project_id: UUID, data: dict) -> None:
    """Возвращает структуру урока и убирает лишь привязки этого действия.

    Текст существующих пояснений и подписей не откатывается: он сохранялся
    отдельно и мог быть набран уже после структурной правки.
    """
    lesson = session.get(Lesson, UUID(data["lesson_id"]))
    if lesson is None or lesson.project_id != project_id:
        raise ProjectNotFoundError("Урок для отмены не найден")
    binding_ids = [UUID(item) for item in data["binding_ids"]]
    if binding_ids:
        session.execute(delete(Binding).where(Binding.project_id == project_id,
                                             Binding.id.in_(binding_ids)))
    if "topics" in data:
        _restore_topics(session, lesson, data["topics"])
    current = {block.id: block for block in _ordered_blocks(session, lesson.id)}
    previous_ids = {UUID(item["id"]) for item in data["blocks"]}
    added_ids = set(current) - previous_ids
    if added_ids:
        session.execute(delete(LessonSourceRef).where(LessonSourceRef.block_id.in_(added_ids)))
        session.execute(delete(LessonBlock).where(LessonBlock.id.in_(added_ids)))
        for block_id in added_ids:
            session.expunge(current[block_id])
    for item in data["blocks"]:
        existing = current.get(UUID(item["id"]))
        if existing is None:
            existing = LessonBlock(
                id=UUID(item["id"]), lesson_id=lesson.id, sort_order=item["sort_order"],
                kind=LessonBlockKind(item["kind"]),
                variant=LessonNoteVariant(item["variant"]) if item["variant"] else None,
                body_md=item["body_md"], origin=LessonBlockOrigin(item["origin"]),
                basis=item["basis"], ai_run_id=_uuid(item["ai_run_id"]),
                activity_id=_uuid(item["activity_id"]), media_path=item["media_path"],
            )
            session.add(existing)
            session.flush()
        existing.sort_order = item["sort_order"]
        existing.bound_program_node_id = _uuid(item["bound_program_node_id"])
        _restore_refs(session, existing.id, item["refs"])
    lesson.revision += 1
    lesson.updated_at = utc_now()


def apply_unbind_undo(session: Session, project_id: UUID, data: dict) -> None:
    """Снятые из урока привязки возвращаются в прежний статус, машинные — машинными."""
    now = utc_now()
    for item in data["bindings"]:
        binding = session.get(Binding, UUID(item["id"]))
        if binding is not None and binding.project_id == project_id:
            binding.status = BindingStatus(item["status"])
            binding.updated_at = now


# --- привязки --------------------------------------------------------------------------


def _bind_fragments(
    session: Session, project_id: UUID, node_id: UUID, material_id: UUID,
    fragment_ids: list[UUID], *, manual: bool,
) -> list[UUID]:
    """Существующая пара (тема, фрагмент) не меняется в любом статусе (§4.4)."""
    if not fragment_ids:
        return []
    existing = set(session.scalars(select(Binding.fragment_id).where(
        Binding.project_id == project_id, Binding.program_node_id == node_id,
        Binding.fragment_id.in_(fragment_ids),
    )))
    block_of = dict(session.execute(
        select(MaterialFragment.id, MaterialFragment.block_id)
        .where(MaterialFragment.id.in_(fragment_ids))
    ).tuples().all())
    now = utc_now()
    created: list[UUID] = []
    for fragment_id in fragment_ids:
        if fragment_id in existing:
            continue
        binding = Binding(
            id=uuid4(), project_id=project_id, program_node_id=node_id,
            fragment_id=fragment_id, material_id=material_id, block_id=block_of.get(fragment_id),
            status=BindingStatus.MANUAL if manual else BindingStatus.MACHINE,
            mechanism=BindingMechanism.LESSON if manual else BindingMechanism.OUTLINE,
            created_at=now, updated_at=now,
        )
        session.add(binding)
        existing.add(fragment_id)
        created.append(binding.id)
    return created


def _block_fragments(session: Session, project_id: UUID, block: LessonBlock) -> set[UUID]:
    result: set[UUID] = set()
    for ref in session.scalars(select(LessonSourceRef).where(
        LessonSourceRef.block_id == block.id, LessonSourceRef.role == LessonRefRole.CONTENT
    )):
        material = session.get(Material, ref.material_id) if ref.material_id else None
        if material is None or session.get(ProjectMaterial, (project_id, material.id)) is None:
            continue
        order = refs_module.load_order(session, material, ref.page_from, ref.page_to)
        result.update(refs_module.content_fragment_ids(order, refs_module.bounds_of(ref)))
    return result


def _unbind_offer(
    edit: _Edit, block: LessonBlock, node_id: UUID | None
) -> LessonUnbindOffer | None:
    """Привязки куска к теме, которые больше не держит ни один другой кусок урока."""
    if block.kind != LessonBlockKind.SOURCE or node_id is None:
        return None
    project_id = edit.lesson.project_id
    fragments = _block_fragments(edit.session, project_id, block)
    for other in edit.blocks:
        if other.id != block.id and other.bound_program_node_id == node_id:
            fragments -= _block_fragments(edit.session, project_id, other)
    if not fragments:
        return None
    binding_ids = list(edit.session.scalars(select(Binding.id).where(
        Binding.project_id == project_id, Binding.program_node_id == node_id,
        Binding.fragment_id.in_(fragments), Binding.status.in_(ACTIVE_STATUSES),
        Binding.mechanism.in_(LESSON_MECHANISMS),
    )))
    node = edit.session.get(ProgramNode, node_id)
    if not binding_ids or node is None:
        return None
    return LessonUnbindOffer(program_node_id=node_id, topic_title=node.title,
                             binding_ids=binding_ids)


# --- добавление материала --------------------------------------------------------------


def _project_material(session: Session, project_id: UUID, material_id: UUID | None
                      ) -> tuple[Material, ProjectMaterial]:
    material = session.get(Material, material_id) if material_id else None
    link = session.get(ProjectMaterial, (project_id, material_id)) if material_id else None
    if material is None or link is None:
        raise _invalid("Материал не входит в проект", "lesson_source_unavailable")
    return material, link


def _require_whole_piece(ref: LessonSourceRef) -> LessonSourceRef:
    """Область страницы — картинка: резать, склеивать и показывать текстом её нечем."""
    if ref.region_bbox is not None:
        raise _invalid("Область страницы — картинка: её можно только удалить", "lesson_ref_region")
    return ref


def _node_for_page(edit: _Edit, material_id: UUID, page: int) -> UUID:
    """Урок по нескольким темам: кусок идёт к теме, чей диапазон содержит страницу (§4.4)."""
    topic_ids = edit.topic_ids()
    if not topic_ids:
        raise ProjectNotFoundError("Тема урока не найдена")
    if len(topic_ids) > 1:
        ranges = _load_program(edit.session, edit.lesson.project_id).ranges
        for node_id in topic_ids:
            page_range = ranges.get(node_id, {}).get(material_id)
            if page_range and page_range[0] <= page <= page_range[1]:
                return node_id
    return topic_ids[0]


def _create_source(
    edit: _Edit, material: Material, link: ProjectMaterial, bounds: Bounds, node_id: UUID,
    origin: LessonBlockOrigin, region_bbox: list[float] | None = None,
) -> LessonBlock:
    block = edit.new_block(LessonBlockKind.SOURCE, origin=origin, bound_program_node_id=node_id)
    edit.insert(block, edit.command.after_block_id)
    edit.session.flush()
    edit.session.add(LessonSourceRef(
        id=uuid4(), block_id=block.id, role=LessonRefRole.CONTENT, material_id=material.id,
        source_name_snapshot=_source_name(material, link, material.original_name),
        material_revision=material.active_parse_revision or None,
        page_from=bounds.page_from, page_to=bounds.page_to,
        from_fragment_id=bounds.from_fragment_id, to_fragment_id=bounds.to_fragment_id,
        region_bbox=region_bbox,
        # Область — вырез оригинала: текстового представления у неё нет.
        always_pages=region_bbox is not None, boundary_shifted=False,
    ))
    return block


def _add_manual_bounds(edit: _Edit, material: Material, link: ProjectMaterial,
                       bounds: Bounds) -> None:
    """Ручной выбор — `manual/lesson` на содержательные фрагменты именно выбранного."""
    requested = edit.command.program_node_id
    if requested is not None and requested not in edit.topic_ids():
        raise _invalid("Тема не входит в урок", "lesson_topic_missing")
    node_id = requested or _node_for_page(edit, material.id, bounds.page_from)
    _create_source(edit, material, link, bounds, node_id, LessonBlockOrigin.MANUAL)
    order = refs_module.load_order(edit.session, material, bounds.page_from, bounds.page_to)
    edit.binding_ids += _bind_fragments(
        edit.session, edit.lesson.project_id, node_id, material.id,
        refs_module.content_fragment_ids(order, bounds), manual=True,
    )


def _add_page(edit: _Edit) -> None:
    command = edit.command
    material, link = _project_material(edit.session, edit.lesson.project_id, command.material_id)
    if command.page_from is None:
        raise _invalid("Выберите материал и страницу", "lesson_source_required")
    page_to = command.page_to or command.page_from
    if page_to < command.page_from or page_to > (material.page_count or 0):
        raise _invalid("Диапазон выходит за страницы материала", "lesson_page_range")
    _add_manual_bounds(edit, material, link, Bounds(command.page_from, page_to, None, None))


def _add_region(edit: _Edit) -> None:
    """Область страницы — схема или таблица, которой нет в текстовом слое (записка §4.3)."""
    command = edit.command
    material, link = _project_material(edit.session, edit.lesson.project_id, command.material_id)
    page = command.page_from
    if page is None or page > (material.page_count or 0):
        raise _invalid("Область берётся с одной страницы материала", "lesson_page_range")
    if command.region_bbox is None:
        raise _invalid("Область не выделена", "lesson_region_required")
    node_id = _node_for_page(edit, material.id, page)
    _create_source(edit, material, link, Bounds(page, page, None, None), node_id,
                   LessonBlockOrigin.MANUAL, region_bbox=command.region_bbox)
    edit.binding_ids += _bind_fragments(
        edit.session, edit.lesson.project_id, node_id, material.id,
        refs_module.fragments_in_region(edit.session, material, page, command.region_bbox),
        manual=True,
    )


def _fragment_page(session: Session, material: Material, fragment_id: UUID | None
                   ) -> tuple[MaterialFragment, int]:
    row = session.execute(
        select(MaterialFragment, MaterialPage.page_number)
        .join(MaterialPage, MaterialPage.id == MaterialFragment.page_id)
        .where(MaterialFragment.id == fragment_id, MaterialPage.material_id == material.id,
               MaterialPage.revision == material.active_parse_revision)
    ).first() if fragment_id else None
    if row is None:
        raise _invalid("Фрагмент не найден в текущей ревизии материала",
                       "lesson_fragment_not_found")
    return row[0], row[1]


def _add_fragments(edit: _Edit) -> None:
    command = edit.command
    material, link = _project_material(edit.session, edit.lesson.project_id, command.material_id)
    _, first_page = _fragment_page(edit.session, material, command.from_fragment_id)
    _, last_page = _fragment_page(edit.session, material, command.to_fragment_id)
    order = refs_module.load_order(
        edit.session, material, min(first_page, last_page), max(first_page, last_page)
    )
    bounds = refs_module.fragment_range(order, command.from_fragment_id, command.to_fragment_id)
    _add_manual_bounds(edit, material, link, bounds)


def _add_structure_block(edit: _Edit) -> None:
    """Структурный блок материала — заголовок с подчинёнными абзацами, по любому его фрагменту."""
    command = edit.command
    material, link = _project_material(edit.session, edit.lesson.project_id, command.material_id)
    fragment, _ = _fragment_page(edit.session, material, command.fragment_id)
    block = edit.session.get(MaterialBlock, fragment.block_id)
    order = refs_module.load_order(edit.session, material, block.page_from, block.page_to)
    positions = [i for i, item in enumerate(order.fragments) if item.block_id == block.id]
    bounds = refs_module.fragment_range(
        order, order.fragments[positions[0]].id, order.fragments[positions[-1]].id
    )
    _add_manual_bounds(edit, material, link, bounds)


def _add_outline(edit: _Edit) -> None:
    """«Добавить всё» — уточнённый диапазон оглавления темы и `machine/outline` (§4.4)."""
    command = edit.command
    session = edit.session
    material, link = _project_material(session, edit.lesson.project_id, command.material_id)
    topic_ids = edit.topic_ids()
    node_id = command.program_node_id or (topic_ids[0] if topic_ids else None)
    if node_id not in topic_ids:
        raise _invalid("Тема не входит в урок", "lesson_topic_missing")
    program = _load_program(session, edit.lesson.project_id)
    if material.id not in program.ranges.get(node_id, {}):
        raise _invalid("У темы нет диапазона в этом источнике", "lesson_source_without_range")
    node = _require_study_node(session, edit.lesson.project_id, node_id)
    plan = _plan_source(session, program, node, material, link)
    segment = boundaries.to_segment(plan.pages, plan.start, plan.end)
    if segment is None:
        page_from, page_to = plan.outline_range
        _create_source(edit, material, link, Bounds(page_from, page_to, None, None), node_id,
                       LessonBlockOrigin.OUTLINE)
        return
    bounds = Bounds(segment.page_from, segment.page_to,
                    segment.from_fragment_id, segment.to_fragment_id)
    _create_source(edit, material, link, bounds, node_id, LessonBlockOrigin.OUTLINE)
    ids, _ = _bind_segment_fragments(session, edit.lesson.project_id, node_id, plan, segment)
    edit.binding_ids += ids


def _add_note(edit: _Edit) -> None:
    block = edit.new_block(LessonBlockKind.NOTE, variant=edit.command.variant, body_md="")
    edit.insert(block, edit.command.after_block_id)


def _add_link(edit: _Edit) -> None:
    """Внешняя ссылка — карточка без предпросмотра: продукт офлайновый (записка §8, 12)."""
    url = (edit.command.media_url or "").strip()
    if not url.startswith(("http://", "https://")):
        raise _invalid("Ссылка должна начинаться с http:// или https://", "lesson_media_url")
    block = edit.new_block(LessonBlockKind.MEDIA, media_path=url,
                           body_md=(edit.command.caption or "").strip())
    edit.insert(block, edit.command.after_block_id)


# --- структура -------------------------------------------------------------------------


def _delete(edit: _Edit) -> None:
    block = edit.block()
    edit.offer = _unbind_offer(edit, block, block.bound_program_node_id)
    edit.blocks.remove(block)
    _drop_block(edit.session, block)


def _move(edit: _Edit) -> None:
    block = edit.block()
    index = edit.blocks.index(block)
    next_index = index + (-1 if edit.command.operation == "move_up" else 1)
    if not 0 <= next_index < len(edit.blocks):
        raise _invalid("Блок уже на краю урока", "lesson_block_edge")
    edit.blocks[index], edit.blocks[next_index] = edit.blocks[next_index], edit.blocks[index]


def _split(edit: _Edit) -> None:
    session = edit.session
    block = edit.block(LessonBlockKind.SOURCE)
    ref = _require_whole_piece(_content_ref(session, block))
    material = _ref_material(session, edit.lesson.project_id, ref)
    order = refs_module.load_order(session, material, ref.page_from, ref.page_to)
    first, second = refs_module.split(
        order, refs_module.bounds_of(ref), edit.command.fragment_id, edit.command.split_after_page
    )
    tail = edit.new_block(LessonBlockKind.SOURCE, origin=block.origin,
                          bound_program_node_id=block.bound_program_node_id)
    edit.insert(tail, block.id)
    session.flush()
    session.add(LessonSourceRef(
        id=uuid4(), block_id=tail.id, role=LessonRefRole.CONTENT, material_id=ref.material_id,
        source_name_snapshot=ref.source_name_snapshot, material_revision=ref.material_revision,
        page_from=second.page_from, page_to=second.page_to,
        from_fragment_id=second.from_fragment_id, to_fragment_id=second.to_fragment_id,
        always_pages=ref.always_pages, boundary_shifted=False,
    ))
    ref.page_from, ref.page_to = first.page_from, first.page_to
    ref.from_fragment_id, ref.to_fragment_id = first.from_fragment_id, first.to_fragment_id
    if edit.command.insert_note:
        note = edit.new_block(LessonBlockKind.NOTE, variant=edit.command.variant, body_md="")
        edit.insert(note, block.id)


def _merge(edit: _Edit) -> None:
    """«Убрать разрез»: кусок склеивается со следующим куском того же материала."""
    session = edit.session
    block = edit.block(LessonBlockKind.SOURCE)
    index = edit.blocks.index(block)
    following = edit.blocks[index + 1] if index + 1 < len(edit.blocks) else None
    if following is None or following.kind != LessonBlockKind.SOURCE:
        raise _invalid("Следующий блок — не кусок материала", "lesson_merge_not_adjacent")
    first_ref = _require_whole_piece(_content_ref(session, block))
    second_ref = _require_whole_piece(_content_ref(session, following))
    if first_ref.material_id != second_ref.material_id:
        raise _invalid("Склеить можно только куски одного материала", "lesson_merge_not_adjacent")
    if block.bound_program_node_id != following.bound_program_node_id:
        raise _invalid("Куски привязаны к разным темам", "lesson_merge_topics")
    material = _ref_material(session, edit.lesson.project_id, first_ref)
    order = refs_module.load_order(session, material, first_ref.page_from, second_ref.page_to)
    merged = refs_module.merge(
        order, refs_module.bounds_of(first_ref), refs_module.bounds_of(second_ref)
    )
    if merged is None:
        raise _invalid("Второй кусок не продолжает первый", "lesson_merge_not_adjacent")
    first_ref.page_to, first_ref.to_fragment_id = merged.page_to, merged.to_fragment_id
    first_ref.boundary_shifted = first_ref.boundary_shifted or second_ref.boundary_shifted
    edit.blocks.remove(following)
    _drop_block(session, following)


def _set_always_pages(edit: _Edit) -> None:
    if edit.command.always_pages is None:
        raise _invalid("Не указано, как показывать кусок", "lesson_always_pages_required")
    ref = _require_whole_piece(_content_ref(edit.session, edit.block(LessonBlockKind.SOURCE)))
    ref.always_pages = edit.command.always_pages


def _set_topic(edit: _Edit) -> None:
    """Смена темы куска: новые привязки по правилу пути, прежние — только предложением снять."""
    session = edit.session
    block = edit.block(LessonBlockKind.SOURCE)
    node_id = edit.command.program_node_id
    if node_id not in edit.topic_ids():
        raise _invalid("Тема не входит в урок", "lesson_topic_missing")
    if block.bound_program_node_id == node_id:
        return
    edit.offer = _unbind_offer(edit, block, block.bound_program_node_id)
    block.bound_program_node_id = node_id
    ref = _content_ref(session, block)
    material = session.get(Material, ref.material_id) if ref.material_id else None
    if material is not None:
        edit.binding_ids += _bind_fragments(
            session, edit.lesson.project_id, node_id, material.id,
            sorted(_block_fragments(session, edit.lesson.project_id, block)),
            manual=block.origin != LessonBlockOrigin.OUTLINE,
        )


def _add_topic(edit: _Edit) -> None:
    session = edit.session
    if edit.command.program_node_id is None:
        raise _invalid("Выберите тему", "lesson_topic_missing")
    node = _require_study_node(session, edit.lesson.project_id, edit.command.program_node_id)
    topics = edit.topic_ids()
    if node.id in topics:
        raise _invalid("Тема уже в уроке", "lesson_topic_exists")
    session.add(LessonTopic(
        lesson_id=edit.lesson.id, program_node_id=node.id, project_id=edit.lesson.project_id,
        sort_order=len(topics), topic_title_snapshot=node.title,
    ))


def _remove_topic(edit: _Edit) -> None:
    node_id = edit.command.program_node_id
    topics = edit.topic_ids()
    if node_id not in topics:
        raise _invalid("Тема не входит в урок", "lesson_topic_missing")
    if len(topics) == 1:
        raise _invalid("У урока должна остаться хотя бы одна тема", "lesson_topic_last")
    in_use = sum(1 for block in edit.blocks if block.bound_program_node_id == node_id)
    if in_use:
        raise ProjectDomainError(
            "К теме привязаны куски урока — сначала смените им тему", status=422,
            code="lesson_topic_in_use", context={"blocks": in_use},
        )
    session = edit.session
    session.delete(session.get(LessonTopic, (edit.lesson.id, node_id)))
    for index, topic_id in enumerate(item for item in topics if item != node_id):
        session.get(LessonTopic, (edit.lesson.id, topic_id)).sort_order = index


HANDLERS: dict[str, Callable[[_Edit], None]] = {
    "add_note": _add_note,
    "add_page": _add_page,
    "add_outline": _add_outline,
    "add_fragments": _add_fragments,
    "add_block": _add_structure_block,
    "add_region": _add_region,
    "add_link": _add_link,
    "delete": _delete,
    "move_up": _move,
    "move_down": _move,
    "split": _split,
    "merge": _merge,
    "set_topic": _set_topic,
    "add_topic": _add_topic,
    "remove_topic": _remove_topic,
    "set_always_pages": _set_always_pages,
}


def _apply_edit(
    session: Session, project_id: UUID, lesson_id: UUID, command: LessonBlockWrite,
    action: Callable[[_Edit], None],
) -> LessonChangeResult:
    """Структурное действие — один снимок урока и одна запись отмены."""
    with project_write_transaction(session, project_id):
        _require_lessons_project(session, project_id, writable=True)
        lesson = _require_lesson(session, project_id, lesson_id)
        _require_revision(lesson, command.expected_revision)
        edit = _Edit(session, lesson, _ordered_blocks(session, lesson.id), command)
        before = [_block_data(session, block) for block in edit.blocks]
        topics = _topics_data(session, lesson.id)
        action(edit)
        session.flush()
        for index, block in enumerate(edit.blocks):
            block.sort_order = index
        lesson.revision += 1
        lesson.updated_at = utc_now()
        session.add(ProjectActionLog(
            project_id=project_id, action_type=ACTION_LESSON_BLOCKS,
            phase="active", payload_version=1, target_title=lesson.title,
            inverse_data={"lesson_id": str(lesson.id), "blocks": before, "topics": topics,
                          "binding_ids": [str(item) for item in edit.binding_ids]},
        ))
        session.flush()
        return _change_result(session, lesson, edit.offer)


def edit_lesson_blocks(
    session: Session, project_id: UUID, lesson_id: UUID, command: LessonBlockWrite
) -> LessonChangeResult:
    """Структурная правка урока по таблице `HANDLERS`; изображение идёт через `add_lesson_image`."""
    handler = HANDLERS.get(command.operation)
    if handler is None:
        raise _invalid("Изображение загружается отдельным запросом", "lesson_block_operation")
    return _apply_edit(session, project_id, lesson_id, command, handler)


async def add_lesson_image(
    session: Session, project_id: UUID, lesson_id: UUID, upload: UploadFile,
    expected_revision: int, after_block_id: UUID | None, caption: str | None,
) -> LessonChangeResult:
    """Своё изображение или фото доски — `media`-блок; файл лежит в хранилище проекта."""
    _require_lessons_project(session, project_id, writable=True)  # отказ до чтения тела
    relative_path, _, _ = await store_namespaced_upload(
        "lessons", str(project_id), upload,
        allowed_suffixes=IMAGE_SUFFIXES, max_bytes=IMAGE_MAX_BYTES,
        unsupported_message="Поддерживаются PNG, JPG, JPEG, WEBP и GIF",
        error_code_prefix="lesson_image",
    )
    # Ранняя проверка и загрузка файла открыли транзакцию чтения: закрываем её,
    # чтобы запись пошла со свежего снимка и сразу с резервированием writer.
    session.rollback()

    command = LessonBlockWrite(expected_revision=expected_revision, operation="add_image",
                               after_block_id=after_block_id, caption=caption)

    def add(edit: _Edit) -> None:
        block = edit.new_block(LessonBlockKind.MEDIA, media_path=relative_path,
                               body_md=(caption or "").strip())
        edit.insert(block, after_block_id)

    return _apply_edit(session, project_id, lesson_id, command, add)


def lesson_image(session: Session, project_id: UUID, lesson_id: UUID, block_id: UUID
                 ) -> tuple[Path, str]:
    """Путь и тип файла изображения блока; тип — по расширению, присланному не доверяем."""
    _require_lessons_project(session, project_id, writable=False)
    _require_lesson(session, project_id, lesson_id)
    block = session.get(LessonBlock, block_id)
    if block is None or block.lesson_id != lesson_id or media_kind(block) != "image":
        raise ProjectNotFoundError("Изображение урока не найдено")
    path = material_path(block.media_path)
    return path, mimetypes.guess_type(path.name)[0] or "application/octet-stream"


# --- текст, проверка, снятие привязок ---------------------------------------------------


def update_lesson_note(
    session: Session, project_id: UUID, lesson_id: UUID,
    block_id: UUID, command: LessonNoteWrite,
) -> LessonChangeResult:
    """Текст пояснения или подпись медиа сохраняется с ревизией, без журнала."""
    with project_write_transaction(session, project_id):
        _require_lessons_project(session, project_id, writable=True)
        lesson = _require_lesson(session, project_id, lesson_id)
        _require_revision(lesson, command.expected_revision)
        block = session.get(LessonBlock, block_id)
        if block is None or block.lesson_id != lesson.id:
            raise ProjectNotFoundError("Блок урока не найден")
        if block.kind not in {LessonBlockKind.NOTE, LessonBlockKind.MEDIA}:
            raise _invalid("Текст можно менять только у пояснения или медиа", "lesson_not_note")
        block.body_md = command.body_md
        if command.variant is not None and block.kind == LessonBlockKind.NOTE:
            block.variant = command.variant
        block.updated_at = utc_now()
        lesson.revision += 1
        lesson.updated_at = utc_now()
        session.flush()
        return _change_result(session, lesson)


def confirm_lesson(
    session: Session, project_id: UUID, lesson_id: UUID, command: LessonConfirmWrite
) -> LessonChangeResult:
    """«Подтвердить»: снимки тем — по текущей программе, пометки сдвинутых разрезов снимаются.

    Тема, ушедшая из программы, покидает урок, если у него остаются другие темы.
    """
    with project_write_transaction(session, project_id):
        _require_lessons_project(session, project_id, writable=True)
        lesson = _require_lesson(session, project_id, lesson_id)
        _require_revision(lesson, command.expected_revision)
        topics = list(session.scalars(
            select(LessonTopic).where(LessonTopic.lesson_id == lesson.id)
            .order_by(LessonTopic.sort_order)
        ))
        alive: list[LessonTopic] = []
        for topic in topics:
            node = session.get(ProgramNode, topic.program_node_id)
            if node is not None and node.is_in_current_program and not node.is_archived:
                topic.topic_title_snapshot = node.title
                alive.append(topic)
        if alive:
            for topic in topics:
                if topic not in alive:
                    session.delete(topic)
            for index, topic in enumerate(alive):
                topic.sort_order = index
        for ref in session.scalars(
            select(LessonSourceRef).join(LessonBlock, LessonBlock.id == LessonSourceRef.block_id)
            .where(LessonBlock.lesson_id == lesson.id, LessonSourceRef.boundary_shifted)
        ):
            ref.boundary_shifted = False
        lesson.revision += 1
        lesson.updated_at = utc_now()
        session.flush()
        return _change_result(session, lesson)


def unbind_lesson_bindings(
    session: Session, project_id: UUID, lesson_id: UUID, command: LessonUnbindWrite
) -> LessonChangeResult:
    """Снимает предложенные привязки урока; одна запись журнала, отмена — прежний статус."""
    with project_write_transaction(session, project_id):
        _require_lessons_project(session, project_id, writable=True)
        lesson = _require_lesson(session, project_id, lesson_id)
        bindings = list(session.scalars(select(Binding).where(
            Binding.project_id == project_id, Binding.id.in_(command.binding_ids),
            Binding.status.in_(ACTIVE_STATUSES), Binding.mechanism.in_(LESSON_MECHANISMS),
        )))
        if not bindings:
            raise _invalid("Привязок для снятия уже нет", "lesson_unbind_empty")
        previous = [{"id": str(item.id), "status": item.status.value} for item in bindings]
        now = utc_now()
        for binding in bindings:
            binding.status = BindingStatus.REMOVED
            binding.updated_at = now
        session.add(ProjectActionLog(
            project_id=project_id, action_type=ACTION_LESSON_UNBIND, phase="active",
            payload_version=1, target_title=lesson.title,
            inverse_data={"lesson_id": str(lesson.id), "bindings": previous},
        ))
        session.flush()
        return _change_result(session, lesson)
