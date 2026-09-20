"""Уроки учебникового проекта: чтение, быстрый и пустой урок, название и статус.

Контракт — `docs/architecture/lessons.md`; модель и правила границ — записка
вертикали «Уроки» (§3, §4.1, §4.4).
"""

import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from uuid import UUID, uuid4

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db import project_write_transaction
from app.lessons import boundaries
from app.lessons import refs as refs_module
from app.lessons.boundaries import FragmentView, NextItem, OutlineRange, Pages, Piece, Position
from app.lessons.schemas import (
    LessonBlockRead,
    LessonChangeResult,
    LessonManualWrite,
    LessonQuickWrite,
    LessonRead,
    LessonRefRead,
    LessonSourceRangeRead,
    LessonsOverviewRead,
    LessonSummaryRead,
    LessonTopicRead,
    LessonTopicSourcesRead,
    LessonUnbindOffer,
    LessonUpdateWrite,
)
from app.materials.naming import material_display_name, project_material_display_name
from app.models import (
    Binding,
    BindingMechanism,
    BindingStatus,
    BlockClass,
    Lesson,
    LessonBlock,
    LessonBlockKind,
    LessonBlockOrigin,
    LessonNoteVariant,
    LessonRefRole,
    LessonSourceRef,
    LessonStatus,
    LessonTopic,
    Material,
    MaterialBlock,
    MaterialFragment,
    MaterialPage,
    ModuleKey,
    NodeType,
    PageQuality,
    ProgramNode,
    ProgramNodeSourcePageRange,
    Project,
    ProjectActionLog,
    ProjectMaterial,
    ProjectStatus,
    SourceRole,
    WorkspaceVariant,
    utc_now,
)
from app.projects.errors import ProjectConflictError, ProjectDomainError, ProjectNotFoundError
from app.projects.heading_match import HeadingIndex, normalize_answer_heading
from app.projects.schemas import LatestUndoableAction

STUDY_NODE_TYPES = {NodeType.TOPIC, NodeType.SUBPOINT}
ROLE_ORDER = {SourceRole.MAIN: 0, SourceRole.ADDITIONAL: 1, SourceRole.REFERENCE: 2}
ACTION_LESSON_CREATE = "lesson_create"
ACTION_LESSON_BLOCKS = "lesson_blocks"
ACTION_LESSON_UNBIND = "lesson_unbind"
ACTION_LESSON_BULK = "lesson_bulk_create"
LESSON_ACTIONS = {ACTION_LESSON_CREATE, ACTION_LESSON_BLOCKS, ACTION_LESSON_UNBIND}
SECTION_NUMBER_RE = re.compile(r"^\s*(?:§\s*)?\d+(?:\.\d+)*\.?\s+")


# --- проект и программа ---------------------------------------------------------------


def _require_lessons_project(session: Session, project_id: UUID, *, writable: bool) -> Project:
    project = session.get(Project, project_id)
    if project is None or project.status == ProjectStatus.DRAFT:
        raise ProjectNotFoundError()
    if (
        project.workspace_variant != WorkspaceVariant.TEXTBOOK
        or ModuleKey.LESSONS.value not in (project.enabled_modules or [])
    ):
        raise ProjectConflictError(
            "Уроки доступны только в учебниковом проекте с включённым разделом «Уроки»",
            code="lessons_unavailable",
        )
    if writable and project.status != ProjectStatus.ACTIVE:
        raise ProjectConflictError(
            "Архивный или завершённый проект нельзя изменять",
            code="project_read_only",
            context={"current_status": project.status.value},
        )
    return project


@dataclass(frozen=True, slots=True)
class _Program:
    """Текущая программа в порядке обхода и диапазоны узлов по материалам."""

    ordered: list[tuple[ProgramNode, int]]
    ranges: dict[UUID, dict[UUID, tuple[int, int]]]

    def index_of(self, node_id: UUID) -> int:
        return next(i for i, (node, _) in enumerate(self.ordered) if node.id == node_id)

    def subtree_end(self, index: int) -> int:
        depth = self.ordered[index][1]
        end = index + 1
        while end < len(self.ordered) and self.ordered[end][1] > depth:
            end += 1
        return end


def _load_program(session: Session, project_id: UUID) -> _Program:
    nodes = [
        node
        for node in session.scalars(select(ProgramNode).where(ProgramNode.project_id == project_id))
        if node.is_in_current_program and not node.is_archived
    ]
    children: dict[UUID | None, list[ProgramNode]] = defaultdict(list)
    for node in nodes:
        children[node.parent_id].append(node)
    for siblings in children.values():
        siblings.sort(key=lambda node: (node.sort_order, str(node.id)))
    ordered: list[tuple[ProgramNode, int]] = []

    def visit(parent_id: UUID | None, depth: int) -> None:
        for child in children.get(parent_id, []):
            ordered.append((child, depth))
            visit(child.id, depth + 1)

    visit(None, 0)
    ranges: dict[UUID, dict[UUID, tuple[int, int]]] = defaultdict(dict)
    for item in session.scalars(
        select(ProgramNodeSourcePageRange).where(
            ProgramNodeSourcePageRange.project_id == project_id
        )
    ):
        current = ranges[item.program_node_id].get(item.material_id)
        ranges[item.program_node_id][item.material_id] = (
            (item.page_from, item.page_to)
            if current is None
            else (min(current[0], item.page_from), max(current[1], item.page_to))
        )
    return _Program(ordered, ranges)


def _require_study_node(session: Session, project_id: UUID, node_id: UUID) -> ProgramNode:
    node = session.get(ProgramNode, node_id)
    if (
        node is None
        or node.project_id != project_id
        or node.is_archived
        or not node.is_in_current_program
    ):
        raise ProjectNotFoundError("Тема программы не найдена")
    if node.node_type not in STUDY_NODE_TYPES:
        raise ProjectDomainError(
            "Урок создаётся по теме; раздел ведёт в массовую подготовку",
            status=422,
            code="lesson_requires_study_node",
        )
    return node


# --- материал и границы ----------------------------------------------------------------


@lru_cache(maxsize=512)
def _heading_index(title: str) -> HeadingIndex:
    return HeadingIndex([(UUID(int=0), title)])


def titles_match(heading: str, title: str) -> bool:
    """Заголовок материала и формулировка узла программы — одно и то же.

    Номер пункта («2.3.1 ») снимается заранее: у `normalize_answer_heading`
    маркер обязан кончаться точкой или скобкой, а в учебниках его часто нет.
    """
    heading = SECTION_NUMBER_RE.sub("", heading)
    title = SECTION_NUMBER_RE.sub("", title)
    if normalize_answer_heading(heading) == normalize_answer_heading(title):
        return True
    return _heading_index(title).match(heading).matched


@dataclass(frozen=True, slots=True)
class _SourcePlan:
    material: Material
    link: ProjectMaterial
    outline_range: tuple[int, int]
    pages: Pages
    block_start_page: dict[UUID, int]
    start: Position
    end: Position
    pieces: list[Piece]


def _load_pages(
    session: Session, material: Material, page_from: int, page_to: int
) -> tuple[dict[int, list[FragmentView]], dict[UUID, int]]:
    revision = material.active_parse_revision
    if revision <= 0:
        return {}, {}
    pages: dict[int, list[FragmentView]] = {
        page_number: []
        for page_number in session.scalars(
            select(MaterialPage.page_number).where(
                MaterialPage.material_id == material.id,
                MaterialPage.revision == revision,
                MaterialPage.page_number.between(page_from, page_to),
            )
        )
    }
    block_start_page: dict[UUID, int] = {}
    rows = session.execute(
        select(MaterialFragment, MaterialPage.page_number, MaterialBlock)
        .join(MaterialPage, MaterialPage.id == MaterialFragment.page_id)
        .join(MaterialBlock, MaterialBlock.id == MaterialFragment.block_id)
        .where(
            MaterialPage.material_id == material.id,
            MaterialPage.revision == revision,
            MaterialPage.page_number.between(page_from, page_to),
        )
        .order_by(MaterialPage.page_number, MaterialFragment.sort_order)
    )
    for fragment, page_number, block in rows:
        block_start_page[block.id] = block.page_from
        pages.setdefault(page_number, []).append(
            FragmentView(
                id=fragment.id,
                text=fragment.text,
                is_heading=fragment.element_kind == "heading",
                level=fragment.structure_level,
                is_content=block.block_class == BlockClass.CONTENT,
                block_id=block.id,
            )
        )
    return pages, block_start_page


def _plan_source(
    session: Session,
    program: _Program,
    node: ProgramNode,
    material: Material,
    link: ProjectMaterial,
) -> _SourcePlan:
    page_from, page_to = program.ranges[node.id][material.id]
    index = program.index_of(node.id)
    end_index = program.subtree_end(index)
    children = [
        OutlineRange(child.id, child.title, *program.ranges[child.id][material.id], depth=depth)
        for child, depth in program.ordered[index + 1 : end_index]
        if material.id in program.ranges.get(child.id, {})
    ]
    next_item = next(
        (
            NextItem(candidate.title, program.ranges[candidate.id][material.id][0])
            for candidate, _ in program.ordered[end_index:]
            if material.id in program.ranges.get(candidate.id, {})
            and program.ranges[candidate.id][material.id][0] >= page_from
        ),
        None,
    )
    parsed = material.active_parse_revision > 0
    pages, block_start_page = _load_pages(session, material, page_from, page_to + 1)
    start, end = boundaries.refine_range(
        pages,
        title=node.title,
        page_from=page_from,
        page_to=page_to,
        # Без разбора уточнять нечем: урок идёт по страницам оглавления.
        next_item=next_item if parsed else None,
        page_count=material.page_count,
        matches=titles_match,
    )
    pieces = boundaries.split_by_children(
        pages, start=start, end=end, children=children, matches=titles_match
    )
    return _SourcePlan(
        material, link, (page_from, page_to), pages, block_start_page, start, end, pieces
    )


def _source_name(material: Material | None, link: ProjectMaterial | None, fallback: str) -> str:
    if material is not None and link is not None:
        return project_material_display_name(material, link)
    return material_display_name(material) if material is not None else fallback


def _topic_sources(
    session: Session, program: _Program, node: ProgramNode
) -> list[tuple[Material, ProjectMaterial]]:
    """Источники темы с диапазоном: по роли, затем по приоритету."""
    result: list[tuple[Material, ProjectMaterial]] = []
    for material_id in program.ranges.get(node.id, {}):
        link = session.get(ProjectMaterial, (node.project_id, material_id))
        material = session.get(Material, material_id)
        if link is not None and material is not None:
            result.append((material, link))
    result.sort(key=lambda pair: (ROLE_ORDER[pair[1].source_role], pair[1].priority))
    return result


# --- чтение ----------------------------------------------------------------------------


def _latest_action(session: Session, project_id: UUID) -> ProjectActionLog | None:
    return session.scalar(
        select(ProjectActionLog)
        .where(
            ProjectActionLog.project_id == project_id,
            ProjectActionLog.phase == "active",
            ProjectActionLog.undone_at.is_(None),
        )
        .order_by(ProjectActionLog.sequence.desc())
        .limit(1)
    )


def _topic_reads(session: Session, lesson_id: UUID) -> list[LessonTopicRead]:
    topics: list[LessonTopicRead] = []
    for topic in session.scalars(
        select(LessonTopic)
        .where(LessonTopic.lesson_id == lesson_id)
        .order_by(LessonTopic.sort_order)
    ):
        node = session.get(ProgramNode, topic.program_node_id)
        alive = node is not None and node.is_in_current_program and not node.is_archived
        topics.append(
            LessonTopicRead(
                program_node_id=topic.program_node_id,
                title_snapshot=topic.topic_title_snapshot,
                current_title=node.title if alive else None,
                needs_review=not alive or node.title != topic.topic_title_snapshot,
            )
        )
    return topics


def _ref_read(
    session: Session, project_id: UUID, ref: LessonSourceRef, pages_shown: list[int]
) -> LessonRefRead:
    material = session.get(Material, ref.material_id) if ref.material_id else None
    link = session.get(ProjectMaterial, (project_id, ref.material_id)) if material else None
    parsed = material is not None and material.active_parse_revision > 0
    low_pages = (
        list(
            session.scalars(
                select(MaterialPage.page_number)
                .where(
                    MaterialPage.material_id == material.id,
                    MaterialPage.revision == material.active_parse_revision,
                    MaterialPage.page_number.between(ref.page_from, ref.page_to),
                    MaterialPage.quality == PageQuality.OCR_LOW,
                )
                .order_by(MaterialPage.page_number)
            )
        )
        if parsed
        else []
    )
    return LessonRefRead(
        id=ref.id,
        role=ref.role,
        material_id=ref.material_id,
        source_name=_source_name(material, link, ref.source_name_snapshot),
        source_role=link.source_role if link is not None else None,
        material_revision=ref.material_revision,
        page_from=ref.page_from,
        page_to=ref.page_to,
        from_fragment_id=ref.from_fragment_id,
        to_fragment_id=ref.to_fragment_id,
        region_bbox=ref.region_bbox,
        always_pages=ref.always_pages,
        is_available=link is not None,
        is_parsed=parsed,
        low_quality_pages=low_pages,
        boundary_shifted=ref.boundary_shifted
        or (
            parsed
            and ref.material_revision is not None
            and ref.material_revision != material.active_parse_revision
            and (ref.from_fragment_id is not None or ref.to_fragment_id is not None)
        ),
        pages_shown=pages_shown,
    )


def _lesson_read(session: Session, lesson: Lesson) -> LessonRead:
    blocks = list(
        session.scalars(
            select(LessonBlock)
            .where(LessonBlock.lesson_id == lesson.id)
            .order_by(LessonBlock.sort_order)
        )
    )
    refs_by_block: dict[UUID, list[LessonSourceRef]] = defaultdict(list)
    if blocks:
        for ref in session.scalars(
            select(LessonSourceRef).where(LessonSourceRef.block_id.in_([b.id for b in blocks]))
        ):
            refs_by_block[ref.block_id].append(ref)
    content_refs = [
        ref
        for block in blocks
        for ref in refs_by_block[block.id]
        if ref.role == LessonRefRole.CONTENT
    ]
    shown = refs_module.shown_pages(session, content_refs)
    topics = _topic_reads(session, lesson.id)
    action = _latest_action(session, lesson.project_id)
    undo_sequence = (
        action.sequence
        if action is not None
        and action.action_type in LESSON_ACTIONS
        and action.inverse_data.get("lesson_id") == str(lesson.id)
        else None
    )
    return LessonRead(
        id=lesson.id,
        project_id=lesson.project_id,
        title=lesson.title,
        goal=lesson.goal,
        status=lesson.status,
        duration_minutes=lesson.duration_minutes,
        revision=lesson.revision,
        needs_review=any(topic.needs_review for topic in topics),
        last_block_id=lesson.last_block_id,
        completed_at=lesson.completed_at,
        undo_sequence=undo_sequence,
        topics=topics,
        blocks=[
            LessonBlockRead(
                id=block.id,
                sort_order=block.sort_order,
                kind=block.kind,
                variant=block.variant,
                body_md=block.body_md,
                origin=block.origin,
                basis=block.basis,
                bound_program_node_id=block.bound_program_node_id,
                media_kind=media_kind(block),
                media_url=block.media_path if media_kind(block) == "link" else None,
                refs=[
                    _ref_read(session, lesson.project_id, ref, shown.get(ref.id, []))
                    for ref in sorted(refs_by_block[block.id], key=lambda item: item.role.value)
                ],
            )
            for block in blocks
        ],
        created_at=lesson.created_at,
        updated_at=lesson.updated_at,
    )


def _require_lesson(session: Session, project_id: UUID, lesson_id: UUID) -> Lesson:
    lesson = session.get(Lesson, lesson_id)
    if lesson is None or lesson.project_id != project_id:
        raise ProjectNotFoundError("Урок не найден")
    return lesson


def get_lesson(session: Session, project_id: UUID, lesson_id: UUID) -> LessonRead:
    _require_lessons_project(session, project_id, writable=False)
    return _lesson_read(session, _require_lesson(session, project_id, lesson_id))


def lessons_overview(session: Session, project_id: UUID) -> LessonsOverviewRead:
    _require_lessons_project(session, project_id, writable=False)
    lessons = list(
        session.scalars(
            select(Lesson).where(Lesson.project_id == project_id).order_by(Lesson.created_at)
        )
    )
    topics_by_lesson: dict[UUID, list[LessonTopic]] = defaultdict(list)
    for topic in session.scalars(
        select(LessonTopic)
        .where(LessonTopic.project_id == project_id)
        .order_by(LessonTopic.sort_order)
    ):
        topics_by_lesson[topic.lesson_id].append(topic)
    nodes = {
        node.id: node
        for node in session.scalars(select(ProgramNode).where(ProgramNode.project_id == project_id))
    }

    def needs_review(topic: LessonTopic) -> bool:
        node = nodes.get(topic.program_node_id)
        return (
            node is None
            or node.is_archived
            or not node.is_in_current_program
            or node.title != topic.topic_title_snapshot
        )

    return LessonsOverviewRead(
        lessons=[
            LessonSummaryRead(
                id=lesson.id,
                title=lesson.title,
                status=lesson.status,
                duration_minutes=lesson.duration_minutes,
                program_node_ids=[topic.program_node_id for topic in topics_by_lesson[lesson.id]],
                needs_review=any(needs_review(topic) for topic in topics_by_lesson[lesson.id]),
                completed_at=lesson.completed_at,
                updated_at=lesson.updated_at,
            )
            for lesson in lessons
        ]
    )


def topic_sources(session: Session, project_id: UUID, node_id: UUID) -> LessonTopicSourcesRead:
    _require_lessons_project(session, project_id, writable=False)
    node = _require_study_node(session, project_id, node_id)
    program = _load_program(session, project_id)
    ranges: list[LessonSourceRangeRead] = []
    for material, link in _topic_sources(session, program, node):
        plan = _plan_source(session, program, node, material, link)
        segment = boundaries.to_segment(plan.pages, plan.start, plan.end)
        page_from = segment.page_from if segment else plan.outline_range[0]
        page_to = segment.page_to if segment else plan.outline_range[1]
        ranges.append(
            LessonSourceRangeRead(
                material_id=material.id,
                source_name=_source_name(material, link, material.original_name),
                source_role=link.source_role,
                priority=link.priority,
                is_parsed=material.active_parse_revision > 0,
                outline_page_from=plan.outline_range[0],
                outline_page_to=plan.outline_range[1],
                page_from=page_from,
                page_to=page_to,
                starts_at_heading=segment is not None and segment.from_fragment_id is not None,
                ends_mid_page=segment is not None and segment.to_fragment_id is not None,
                default_selected=link.source_role != SourceRole.REFERENCE,
            )
        )
    return LessonTopicSourcesRead(program_node_id=node.id, ranges=ranges)


# --- создание --------------------------------------------------------------------------


def _bind_segment_fragments(
    session: Session,
    project_id: UUID,
    node_id: UUID,
    plan: _SourcePlan,
    segment: boundaries.Segment,
) -> tuple[list[UUID], int]:
    """Машинные привязки фрагментов содержательных блоков, начавшихся внутри куска.

    Существующая привязка (тема, фрагмент) не трогается в любом статусе: снятая
    не воскресает, ручная не понижается. Возвращает созданные id и число символов.
    """
    created: list[UUID] = []
    characters = 0
    fragments = boundaries.fragments_in(plan.pages, segment.start, segment.end)
    first_position: dict[UUID, Position] = {}
    for page_number, page_fragments in plan.pages.items():
        for index, fragment in enumerate(page_fragments):
            position = (page_number, index)
            if fragment.block_id not in first_position or position < first_position[
                fragment.block_id
            ]:
                first_position[fragment.block_id] = position
    existing = set(
        session.scalars(
            select(Binding.fragment_id).where(
                Binding.project_id == project_id,
                Binding.program_node_id == node_id,
                Binding.fragment_id.in_([fragment.id for fragment in fragments]),
            )
        )
    )
    now = utc_now()
    for fragment in fragments:
        if not fragment.is_content:
            continue
        characters += len(fragment.text)
        block_start = first_position[fragment.block_id]
        starts_inside = (
            plan.block_start_page.get(fragment.block_id, 0) == block_start[0]
            and segment.start <= block_start < segment.end
        )
        if not starts_inside or fragment.id in existing:
            continue
        binding = Binding(
            id=uuid4(),
            project_id=project_id,
            program_node_id=node_id,
            fragment_id=fragment.id,
            material_id=plan.material.id,
            block_id=fragment.block_id,
            status=BindingStatus.MACHINE,
            mechanism=BindingMechanism.OUTLINE,
            created_at=now,
            updated_at=now,
        )
        session.add(binding)
        existing.add(fragment.id)
        created.append(binding.id)
    return created, characters


def _heading_markdown(title: str, depth: int) -> str:
    return f"{'#' * min(6, depth + 2)} {title}"


def new_lesson(
    session: Session, project_id: UUID, node: ProgramNode, now: datetime
) -> Lesson:
    """Пустой черновик по одной теме со снимком её формулировки."""
    lesson = Lesson(
        id=uuid4(),
        project_id=project_id,
        title=node.title,
        status=LessonStatus.DRAFT,
        revision=1,
        created_at=now,
        updated_at=now,
    )
    session.add(lesson)
    session.add(
        LessonTopic(
            lesson_id=lesson.id,
            program_node_id=node.id,
            project_id=project_id,
            sort_order=0,
            topic_title_snapshot=node.title,
        )
    )
    session.flush()
    return lesson


def quick_sources(
    session: Session, program: _Program, node: ProgramNode, material_ids: list[UUID] | None
) -> list[tuple[Material, ProjectMaterial]]:
    """Источники быстрого урока: первый по роли и приоритету либо выбранные вручную."""
    sources = _topic_sources(session, program, node)
    if not sources:
        raise ProjectConflictError(
            "У темы нет страниц из оглавления — соберите урок вручную",
            code="lesson_no_ranges",
            context={"program_node_id": str(node.id), "title": node.title},
        )
    if material_ids is None:
        return sources[:1]
    wanted = set(material_ids)
    unknown = wanted - {material.id for material, _ in sources}
    if unknown or not wanted:
        raise ProjectDomainError(
            "У темы нет диапазона в выбранном источнике",
            status=422,
            code="lesson_source_without_range",
        )
    return [pair for pair in sources if pair[0].id in wanted]


def fill_quick_lesson(
    session: Session,
    program: _Program,
    node: ProgramNode,
    sources: list[tuple[Material, ProjectMaterial]],
    lesson: Lesson,
    now: datetime,
) -> list[UUID]:
    """Блоки быстрого урока по плану каждого источника; возвращает созданные привязки."""
    project_id = lesson.project_id
    topic_depth = program.ordered[program.index_of(node.id)][1]
    order = 0

    def add_block(**fields: object) -> LessonBlock:
        nonlocal order
        block = LessonBlock(
            id=uuid4(),
            lesson_id=lesson.id,
            sort_order=order,
            origin=LessonBlockOrigin.OUTLINE,
            created_at=now,
            updated_at=now,
            **fields,
        )
        order += 1
        session.add(block)
        return block

    add_block(
        kind=LessonBlockKind.NOTE,
        variant=LessonNoteVariant.HEADING,
        body_md=_heading_markdown(node.title, 0),
    )
    created_bindings: list[UUID] = []
    characters = 0
    for material, link in sources:
        plan = _plan_source(session, program, node, material, link)
        for piece in plan.pieces:
            if piece.heading is not None:
                add_block(
                    kind=LessonBlockKind.NOTE,
                    variant=LessonNoteVariant.HEADING,
                    body_md=_heading_markdown(
                        piece.heading.title, piece.heading.depth - topic_depth
                    ),
                    bound_program_node_id=piece.heading.node_id,
                )
            if piece.segment is None:
                continue
            block = add_block(kind=LessonBlockKind.SOURCE, bound_program_node_id=node.id)
            session.flush()
            session.add(
                LessonSourceRef(
                    id=uuid4(),
                    block_id=block.id,
                    role=LessonRefRole.CONTENT,
                    material_id=material.id,
                    source_name_snapshot=_source_name(material, link, material.original_name),
                    material_revision=material.active_parse_revision or None,
                    page_from=piece.segment.page_from,
                    page_to=piece.segment.page_to,
                    from_fragment_id=piece.segment.from_fragment_id,
                    to_fragment_id=piece.segment.to_fragment_id,
                    always_pages=False,
                )
            )
            ids, segment_characters = _bind_segment_fragments(
                session, project_id, node.id, plan, piece.segment
            )
            created_bindings.extend(ids)
            characters += segment_characters
    lesson.duration_minutes = boundaries.estimate_minutes(characters)
    return created_bindings


def create_quick_lesson(
    session: Session, project_id: UUID, command: LessonQuickWrite
) -> LessonChangeResult:
    with project_write_transaction(session, project_id):
        project = _require_lessons_project(session, project_id, writable=True)
        node = _require_study_node(session, project_id, command.program_node_id)
        program = _load_program(session, project_id)
        sources = quick_sources(session, program, node, command.material_ids)
        now = utc_now()
        lesson = new_lesson(session, project_id, node, now)
        created_bindings = fill_quick_lesson(session, program, node, sources, lesson, now)
        session.add(
            ProjectActionLog(
                project_id=project.id,
                action_type=ACTION_LESSON_CREATE,
                phase="active",
                payload_version=1,
                target_title=lesson.title,
                inverse_data={
                    "lesson_id": str(lesson.id),
                    "binding_ids": [str(binding_id) for binding_id in created_bindings],
                },
            )
        )
        session.flush()
        return _change_result(session, lesson)


def _change_result(
    session: Session, lesson: Lesson, unbind_offer: LessonUnbindOffer | None = None
) -> LessonChangeResult:
    action = _latest_action(session, lesson.project_id)
    return LessonChangeResult(
        lesson=_lesson_read(session, lesson),
        latest_undoable_action=(
            LatestUndoableAction.model_validate(action) if action is not None else None
        ),
        unbind_offer=unbind_offer,
    )


def media_kind(block: LessonBlock) -> str | None:
    """У медиа-блока `media_path` — файл в хранилище или внешний адрес."""
    if block.kind != LessonBlockKind.MEDIA or not block.media_path:
        return None
    return "link" if block.media_path.startswith(("http://", "https://")) else "image"


def create_manual_lesson(
    session: Session, project_id: UUID, command: LessonManualWrite
) -> LessonChangeResult:
    """Пустой черновик доступен и для темы без диапазона оглавления."""
    with project_write_transaction(session, project_id):
        project = _require_lessons_project(session, project_id, writable=True)
        node = _require_study_node(session, project_id, command.program_node_id)
        now = utc_now()
        lesson = Lesson(
            id=uuid4(), project_id=project.id, title=node.title,
            status=LessonStatus.DRAFT, revision=1, created_at=now, updated_at=now,
        )
        session.add(lesson)
        session.add(LessonTopic(
            lesson_id=lesson.id, program_node_id=node.id, project_id=project.id,
            sort_order=0, topic_title_snapshot=node.title,
        ))
        session.flush()
        session.add(ProjectActionLog(
            project_id=project.id, action_type=ACTION_LESSON_CREATE,
            phase="active", payload_version=1, target_title=lesson.title,
            inverse_data={"lesson_id": str(lesson.id), "binding_ids": []},
        ))
        session.flush()
        return _change_result(session, lesson)


def _require_revision(lesson: Lesson, expected: int) -> None:
    """Правка по устаревшей ревизии не перезаписывает урок, а получает конфликт."""
    if lesson.revision != expected:
        raise ProjectConflictError(
            "Урок изменился в другом месте", code="stale_lesson_revision",
            context={"current_revision": lesson.revision},
        )


def update_lesson(
    session: Session, project_id: UUID, lesson_id: UUID, command: LessonUpdateWrite
) -> LessonChangeResult:
    """Название и статус урока; без записи в журнал."""
    with project_write_transaction(session, project_id):
        _require_lessons_project(session, project_id, writable=True)
        lesson = _require_lesson(session, project_id, lesson_id)
        _require_revision(lesson, command.expected_revision)
        if command.title is not None:
            lesson.title = command.title
        if command.status is not None:
            lesson.status = command.status
        lesson.revision += 1
        lesson.updated_at = utc_now()
        session.flush()
        return _change_result(session, lesson)


def delete_lesson(session: Session, project_id: UUID, lesson_id: UUID) -> None:
    """Удалить урок целиком: блоки, ссылки и темы уносит каскад.

    Привязки, сделанные уроком, остаются фактами проекта — снимать их молча нельзя,
    для этого есть отдельное предложение при удалении куска. Записи журнала об этом
    уроке гасятся: их отмена восстановить уже нечего.
    """
    with project_write_transaction(session, project_id):
        _require_lessons_project(session, project_id, writable=True)
        lesson = _require_lesson(session, project_id, lesson_id)
        now = utc_now()
        for action in session.scalars(
            select(ProjectActionLog).where(
                ProjectActionLog.project_id == project_id,
                ProjectActionLog.action_type.in_(LESSON_ACTIONS),
                ProjectActionLog.undone_at.is_(None),
            )
        ):
            if action.inverse_data.get("lesson_id") == str(lesson_id):
                action.undone_at = now
        session.execute(delete(Lesson).where(Lesson.id == lesson.id))


def apply_undo(session: Session, project_id: UUID, data: dict) -> None:
    """Отмена `lesson_create` и `lesson_bulk_create`: уроки и только созданные ими привязки.

    Вызывается из `projects.program.undo_last_project_action`. Массовая подготовка пишет
    `lesson_ids`, одиночное создание — `lesson_id`; остальное у них общее.
    """
    binding_ids = [UUID(raw_id) for raw_id in data.get("binding_ids", [])]
    if binding_ids:
        session.execute(
            delete(Binding).where(Binding.project_id == project_id, Binding.id.in_(binding_ids))
        )
    raw_lessons = data.get("lesson_ids") or [data["lesson_id"]]
    for raw_id in raw_lessons:
        lesson = session.get(Lesson, UUID(raw_id))
        if lesson is not None and lesson.project_id == project_id:
            session.execute(delete(Lesson).where(Lesson.id == lesson.id))
            session.expunge(lesson)
