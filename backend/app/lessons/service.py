"""Уроки учебникового проекта: чтение, быстрая и ручная сборка.

Контракт — `docs/architecture/lessons.md`; модель и правила границ — записка
вертикали «Уроки» (§3, §4.1, §4.4).
"""

import re
from collections import defaultdict
from dataclasses import dataclass
from functools import lru_cache
from uuid import UUID, uuid4

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.lessons import boundaries
from app.lessons.boundaries import FragmentView, NextItem, OutlineRange, Pages, Piece, Position
from app.lessons.schemas import (
    LessonBlockRead,
    LessonBlockWrite,
    LessonChangeResult,
    LessonManualWrite,
    LessonNoteWrite,
    LessonQuickWrite,
    LessonRead,
    LessonRefRead,
    LessonSourceRangeRead,
    LessonsOverviewRead,
    LessonSummaryRead,
    LessonTopicRead,
    LessonTopicSourcesRead,
    LessonUpdateWrite,
)
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
    if link is not None and link.display_name:
        return link.display_name
    return material.original_name if material is not None else fallback


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


def _ref_read(session: Session, project_id: UUID, ref: LessonSourceRef) -> LessonRefRead:
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
    topics = _topic_reads(session, lesson.id)
    action = _latest_action(session, lesson.project_id)
    undo_sequence = (
        action.sequence
        if action is not None
        and action.action_type in {ACTION_LESSON_CREATE, ACTION_LESSON_BLOCKS}
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
                refs=[
                    _ref_read(session, lesson.project_id, ref)
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


def create_quick_lesson(
    session: Session, project_id: UUID, command: LessonQuickWrite
) -> LessonChangeResult:
    with session.begin():
        project = _require_lessons_project(session, project_id, writable=True)
        node = _require_study_node(session, project_id, command.program_node_id)
        program = _load_program(session, project_id)
        sources = _topic_sources(session, program, node)
        if not sources:
            raise ProjectConflictError(
                "У темы нет страниц из оглавления — соберите урок вручную",
                code="lesson_no_ranges",
            )
        if command.material_ids is None:
            sources = sources[:1]
        else:
            wanted = set(command.material_ids)
            unknown = wanted - {material.id for material, _ in sources}
            if unknown or not wanted:
                raise ProjectDomainError(
                    "У темы нет диапазона в выбранном источнике",
                    status=422,
                    code="lesson_source_without_range",
                )
            sources = [pair for pair in sources if pair[0].id in wanted]

        now = utc_now()
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


def _change_result(session: Session, lesson: Lesson) -> LessonChangeResult:
    action = _latest_action(session, lesson.project_id)
    return LessonChangeResult(
        lesson=_lesson_read(session, lesson),
        latest_undoable_action=(
            LatestUndoableAction.model_validate(action) if action is not None else None
        ),
    )


def create_manual_lesson(
    session: Session, project_id: UUID, command: LessonManualWrite
) -> LessonChangeResult:
    """Пустой черновик доступен и для темы без диапазона оглавления."""
    with session.begin():
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


def _ordered_blocks(session: Session, lesson_id: UUID) -> list[LessonBlock]:
    return list(session.scalars(
        select(LessonBlock).where(LessonBlock.lesson_id == lesson_id)
        .order_by(LessonBlock.sort_order, LessonBlock.id)
    ))


def _require_revision(lesson: Lesson, expected: int) -> None:
    if lesson.revision != expected:
        raise ProjectConflictError(
            "Урок изменился в другом месте", code="stale_lesson_revision",
            context={"current_revision": lesson.revision},
        )


def _require_block(blocks: list[LessonBlock], block_id: UUID | None) -> LessonBlock:
    block = next((item for item in blocks if item.id == block_id), None)
    if block is None:
        raise ProjectNotFoundError("Блок урока не найден")
    return block


def _source_ref_data(ref: LessonSourceRef) -> dict:
    return {
        "id": str(ref.id), "role": ref.role.value,
        "material_id": str(ref.material_id) if ref.material_id else None,
        "source_name_snapshot": ref.source_name_snapshot,
        "material_revision": ref.material_revision, "page_from": ref.page_from,
        "page_to": ref.page_to,
        "from_fragment_id": str(ref.from_fragment_id) if ref.from_fragment_id else None,
        "to_fragment_id": str(ref.to_fragment_id) if ref.to_fragment_id else None,
        "region_bbox": ref.region_bbox, "always_pages": ref.always_pages,
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
        "refs": [_source_ref_data(ref) for ref in session.scalars(
            select(LessonSourceRef).where(LessonSourceRef.block_id == block.id)
        )],
    }


def _manual_bind_page(
    session: Session, project_id: UUID, node_id: UUID,
    material: Material, page_from: int, page_to: int,
) -> list[UUID]:
    """Ручной выбор привязывает содержательные фрагменты, не меняя существующие пары."""
    fragments = list(session.execute(
        select(MaterialFragment, MaterialBlock)
        .join(MaterialPage, MaterialPage.id == MaterialFragment.page_id)
        .join(MaterialBlock, MaterialBlock.id == MaterialFragment.block_id)
        .where(MaterialPage.material_id == material.id,
               MaterialPage.revision == material.active_parse_revision,
               MaterialPage.page_number.between(page_from, page_to),
               MaterialBlock.block_class == BlockClass.CONTENT)
    )) if material.active_parse_revision else []
    existing = set(session.scalars(select(Binding.fragment_id).where(
        Binding.project_id == project_id, Binding.program_node_id == node_id,
        Binding.fragment_id.in_([fragment.id for fragment, _ in fragments]),
    )))
    created: list[UUID] = []
    now = utc_now()
    for fragment, block in fragments:
        if fragment.id in existing:
            continue
        binding = Binding(
            id=uuid4(), project_id=project_id, program_node_id=node_id,
            fragment_id=fragment.id, material_id=material.id, block_id=block.id,
            status=BindingStatus.MANUAL, mechanism=BindingMechanism.LESSON,
            created_at=now, updated_at=now,
        )
        session.add(binding)
        created.append(binding.id)
        existing.add(fragment.id)
    return created


def _add_source_block(
    session: Session, lesson: Lesson, command: LessonBlockWrite,
    node_id: UUID,
) -> tuple[LessonBlock, list[UUID]]:
    """Проверяет источник в проекте и создаёт ссылку с привязками выбранного пути."""
    if command.material_id is None or command.page_from is None:
        raise ProjectDomainError(
            "Выберите материал и страницу", status=422, code="lesson_source_required"
        )
    material = session.get(Material, command.material_id)
    link = session.get(ProjectMaterial, (lesson.project_id, command.material_id))
    if material is None or link is None:
        raise ProjectDomainError(
            "Материал не входит в проект", status=422, code="lesson_source_unavailable"
        )
    page_from = command.page_from
    page_to = command.page_to or page_from
    if page_to < page_from or page_to > (material.page_count or 0):
        raise ProjectDomainError(
            "Диапазон выходит за страницы материала", status=422, code="lesson_page_range"
        )
    is_outline = command.operation == "add_outline"
    from_fragment_id = to_fragment_id = None
    if is_outline:
        program = _load_program(session, lesson.project_id)
        if material.id not in program.ranges.get(node_id, {}):
            raise ProjectDomainError("У темы нет диапазона в этом источнике", status=422,
                                     code="lesson_source_without_range")
        node = _require_study_node(session, lesson.project_id, node_id)
        plan = _plan_source(session, program, node, material, link)
        segment = boundaries.to_segment(plan.pages, plan.start, plan.end)
        if segment:
            page_from, page_to = segment.page_from, segment.page_to
            from_fragment_id, to_fragment_id = segment.from_fragment_id, segment.to_fragment_id
    now = utc_now()
    block = LessonBlock(
        id=uuid4(), lesson_id=lesson.id, sort_order=0, kind=LessonBlockKind.SOURCE,
        origin=LessonBlockOrigin.OUTLINE if is_outline else LessonBlockOrigin.MANUAL,
        bound_program_node_id=node_id, created_at=now, updated_at=now,
    )
    session.add(block)
    session.flush()
    session.add(LessonSourceRef(
        id=uuid4(), block_id=block.id, role=LessonRefRole.CONTENT,
        material_id=material.id,
        source_name_snapshot=_source_name(material, link, material.original_name),
        material_revision=material.active_parse_revision or None,
        page_from=page_from, page_to=page_to,
        from_fragment_id=from_fragment_id, to_fragment_id=to_fragment_id,
        always_pages=False,
    ))
    if is_outline:
        ids, _ = (
            _bind_segment_fragments(session, lesson.project_id, node_id, plan, segment)
            if segment else ([], 0)
        )
    else:
        ids = _manual_bind_page(session, lesson.project_id, node_id, material,
                                page_from, page_to)
    return block, ids


def edit_lesson_blocks(
    session: Session, project_id: UUID, lesson_id: UUID, command: LessonBlockWrite
) -> LessonChangeResult:
    """Структурное действие — один снимок порядка и одна запись отмены."""
    with session.begin():
        _require_lessons_project(session, project_id, writable=True)
        lesson = _require_lesson(session, project_id, lesson_id)
        _require_revision(lesson, command.expected_revision)
        blocks = _ordered_blocks(session, lesson.id)
        before = [_block_data(session, block) for block in blocks]
        binding_ids: list[UUID] = []
        if command.operation in {"add_note", "add_page", "add_outline"}:
            if command.operation == "add_note":
                now = utc_now()
                block = LessonBlock(
                    id=uuid4(), lesson_id=lesson.id, sort_order=0,
                    kind=LessonBlockKind.NOTE, variant=command.variant, body_md="",
                    origin=LessonBlockOrigin.MANUAL, created_at=now, updated_at=now,
                )
                session.add(block)
            else:
                node_id = session.scalar(select(LessonTopic.program_node_id).where(
                    LessonTopic.lesson_id == lesson.id).order_by(LessonTopic.sort_order).limit(1)
                )
                if node_id is None:
                    raise ProjectNotFoundError("Тема урока не найдена")
                block, binding_ids = _add_source_block(session, lesson, command, node_id)
            index = next((i + 1 for i, item in enumerate(blocks)
                          if item.id == command.after_block_id), len(blocks))
            blocks.insert(index, block)
        elif command.operation == "delete":
            block = _require_block(blocks, command.block_id)
            blocks.remove(block)
            session.execute(delete(LessonSourceRef).where(LessonSourceRef.block_id == block.id))
            session.delete(block)
        elif command.operation in {"move_up", "move_down"}:
            block = _require_block(blocks, command.block_id)
            index = blocks.index(block)
            next_index = index + (-1 if command.operation == "move_up" else 1)
            if next_index < 0 or next_index >= len(blocks):
                raise ProjectDomainError(
                    "Блок уже на краю урока", status=422, code="lesson_block_edge"
                )
            blocks[index], blocks[next_index] = blocks[next_index], blocks[index]
        else:
            raise ProjectDomainError("Неизвестное действие над блоком", status=422,
                                     code="lesson_block_operation")
        session.flush()
        for index, block in enumerate(blocks):
            block.sort_order = index
        lesson.revision += 1
        lesson.updated_at = utc_now()
        session.add(ProjectActionLog(
            project_id=project_id, action_type=ACTION_LESSON_BLOCKS,
            phase="active", payload_version=1, target_title=lesson.title,
            inverse_data={"lesson_id": str(lesson.id), "blocks": before,
                          "binding_ids": [str(item) for item in binding_ids]},
        ))
        session.flush()
        return _change_result(session, lesson)


def update_lesson_note(
    session: Session, project_id: UUID, lesson_id: UUID,
    block_id: UUID, command: LessonNoteWrite,
) -> LessonChangeResult:
    """Текст сохраняется с ревизией без записи каждого нажатия в журнал."""
    with session.begin():
        _require_lessons_project(session, project_id, writable=True)
        lesson = _require_lesson(session, project_id, lesson_id)
        _require_revision(lesson, command.expected_revision)
        block = _require_block(_ordered_blocks(session, lesson_id), block_id)
        if block.kind != LessonBlockKind.NOTE:
            raise ProjectDomainError("Текст можно менять только у пояснения", status=422,
                                     code="lesson_not_note")
        block.body_md = command.body_md
        if command.variant is not None:
            block.variant = command.variant
        block.updated_at = utc_now()
        lesson.revision += 1
        lesson.updated_at = utc_now()
        session.flush()
        return _change_result(session, lesson)


def apply_blocks_undo(session: Session, project_id: UUID, data: dict) -> None:
    """Возвращает структуру урока и убирает лишь привязки этого добавления."""
    lesson = session.get(Lesson, UUID(data["lesson_id"]))
    if lesson is None or lesson.project_id != project_id:
        raise ProjectNotFoundError("Урок для отмены не найден")
    binding_ids = [UUID(item) for item in data["binding_ids"]]
    if binding_ids:
        session.execute(delete(Binding).where(Binding.project_id == project_id,
                                             Binding.id.in_(binding_ids)))
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
        if existing is not None:
            existing.sort_order = item["sort_order"]
            continue
        block = LessonBlock(
            id=UUID(item["id"]), lesson_id=lesson.id, sort_order=item["sort_order"],
            kind=LessonBlockKind(item["kind"]),
            variant=LessonNoteVariant(item["variant"]) if item["variant"] else None,
            body_md=item["body_md"], origin=LessonBlockOrigin(item["origin"]),
            basis=item["basis"],
            ai_run_id=UUID(item["ai_run_id"]) if item["ai_run_id"] else None,
            activity_id=UUID(item["activity_id"]) if item["activity_id"] else None,
            media_path=item["media_path"],
            bound_program_node_id=UUID(item["bound_program_node_id"])
            if item["bound_program_node_id"] else None,
        )
        session.add(block)
        for ref in item["refs"]:
            session.add(LessonSourceRef(
                id=UUID(ref["id"]), block_id=block.id, role=LessonRefRole(ref["role"]),
                material_id=UUID(ref["material_id"]) if ref["material_id"] else None,
                source_name_snapshot=ref["source_name_snapshot"],
                material_revision=ref["material_revision"],
                page_from=ref["page_from"], page_to=ref["page_to"],
                from_fragment_id=UUID(ref["from_fragment_id"])
                if ref["from_fragment_id"] else None,
                to_fragment_id=UUID(ref["to_fragment_id"])
                if ref["to_fragment_id"] else None,
                region_bbox=ref["region_bbox"], always_pages=ref["always_pages"],
            ))
    lesson.revision += 1
    lesson.updated_at = utc_now()


def update_lesson(
    session: Session, project_id: UUID, lesson_id: UUID, command: LessonUpdateWrite
) -> LessonChangeResult:
    with session.begin():
        _require_lessons_project(session, project_id, writable=True)
        lesson = _require_lesson(session, project_id, lesson_id)
        if command.expected_revision != lesson.revision:
            raise ProjectConflictError(
                "Урок изменился в другом месте",
                code="stale_lesson_revision",
                context={"current_revision": lesson.revision},
            )
        if command.title is not None:
            lesson.title = command.title
        if command.status is not None:
            lesson.status = command.status
        lesson.revision += 1
        lesson.updated_at = utc_now()
        session.flush()
        return _change_result(session, lesson)


def apply_undo(session: Session, project_id: UUID, data: dict) -> None:
    """Отмена `lesson_create`: урок и только созданные им привязки.

    Вызывается из `projects.program.undo_last_project_action`.
    """
    binding_ids = [UUID(raw_id) for raw_id in data.get("binding_ids", [])]
    if binding_ids:
        session.execute(
            delete(Binding).where(Binding.project_id == project_id, Binding.id.in_(binding_ids))
        )
    lesson = session.get(Lesson, UUID(data["lesson_id"]))
    if lesson is not None and lesson.project_id == project_id:
        session.execute(delete(Lesson).where(Lesson.id == lesson.id))
        session.expunge(lesson)
