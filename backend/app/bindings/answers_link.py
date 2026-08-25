"""Файл эталонных ответов связывается с вопросами сам, по заголовкам разделов.

Отличие от остальных материалов: у файла ответов заголовок раздела дословно
повторяет формулировку вопроса программы, поэтому связь ставится без модели и
без поиска — сравнением нормализованных заголовков. Отсюда же берётся текст
эталона: раздел ответа целиком, кроме самого заголовка.

Механизм привязки — `answers_file`: не ручная (её никто не ставил руками) и не
проход 2 (тот появится на этапе 8). Ручные привязки пользователя эта операция
не трогает, а свои прошлые — пересоздаёт, поэтому повтор идемпотентен.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from uuid import UUID, uuid4

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.marker_labels import material_image_label
from app.materials.schemas import MaterialPurpose
from app.models import (
    Binding,
    BindingMechanism,
    BindingStatus,
    BlockClass,
    Material,
    MaterialBlock,
    MaterialFragment,
    MaterialPage,
    MaterialState,
    NodeType,
    ProgramNode,
    Project,
    ProjectActionLog,
    ProjectMaterial,
    ProjectStatus,
    ReferenceAnswer,
    ReferenceAnswerMatchMethod,
    ReferenceAnswerOrigin,
    WorkspaceVariant,
    utc_now,
)
from app.projects.errors import ProjectConflictError, ProjectNotFoundError
from app.projects.heading_match import HeadingIndex, normalize_answer_heading
from app.projects.numbered_series import select_numbered_series

STUDY_NODE_TYPES = {NodeType.TOPIC, NodeType.SUBPOINT}
PREVIEW_LIMIT = 180


def _block_preview(fragments: list[MaterialFragment]) -> str | None:
    """Первые слова раздела: по ним видно, что за ответ, не открывая документ."""
    for fragment in fragments:
        text = " ".join(fragment.text.split())
        if text:
            return text if len(text) <= PREVIEW_LIMIT else f"{text[: PREVIEW_LIMIT - 1]}…"
    return None


@dataclass(slots=True)
class HeadingSuggestionCandidate:
    node_id: UUID
    node_title: str
    score: float


@dataclass(slots=True)
class HeadingSuggestion:
    """Заголовок, для которого вопрос не определён уверенно — выбор за пользователем."""

    block_id: UUID
    heading: str
    preview: str | None
    page_from: int
    candidates: list[HeadingSuggestionCandidate] = field(default_factory=list)


@dataclass(slots=True)
class AnswersLinkResult:
    linked_sections: int = 0
    linked_fragments: int = 0
    created_answers: int = 0
    updated_answers: int = 0
    kept_answers: int = 0
    numbered_sections: int = 0
    extra_sections: int = 0
    ordinal_rejected_reason: str | None = None
    fuzzy_headings: list[str] = field(default_factory=list)
    unmatched_headings: list[str] = field(default_factory=list)
    duplicate_headings: list[str] = field(default_factory=list)
    suggestions: list[HeadingSuggestion] = field(default_factory=list)


@dataclass(slots=True)
class _Section:
    node_ids: list[UUID]
    title: str
    fragments: list[MaterialFragment]
    page_from: int
    page_to: int
    method: ReferenceAnswerMatchMethod = ReferenceAnswerMatchMethod.EXACT_TITLE

    def bindable_fragments(self) -> list[MaterialFragment]:
        """Раздел без строки заголовка: она повторяет вопрос, а не отвечает на него —
        привязывать её как свидетельство бессмысленно и выглядит дублем в списке."""
        return [
            fragment
            for fragment in self.fragments
            if not (fragment.element_kind == "heading" and fragment.text.strip() == self.title)
        ]

    def answer_text(self, material: Material) -> str:
        body = [
            (
                "[изображение: "
                f"{material_image_label(material.id, material.original_name, fragment.asset_path)}]"
                if fragment.element_kind == "image" and fragment.asset_path
                else fragment.text
            )
            for fragment in self.bindable_fragments()
        ]
        return "\n".join(body).strip()


@dataclass(slots=True)
class _OrdinalSections:
    sections: list[_Section] = field(default_factory=list)
    extra_sections: int = 0
    rejected_reason: str | None = None


def find_answers_material(session: Session, project_id: UUID) -> ProjectMaterial | None:
    """Файл эталонных ответов у проекта ровно один — на этом держится автозаполнение."""
    for link in session.scalars(
        select(ProjectMaterial).where(ProjectMaterial.project_id == project_id)
    ):
        if MaterialPurpose.REFERENCE_ANSWERS.value in (link.purposes or []):
            return link
    return None


def _resolution_index(session: Session, project_id: UUID, material: Material) -> dict[str, UUID]:
    """Что пользователь уже разрешил руками, помнится самим эталоном.

    Разрешая заголовок, мы пишем его в `matched_title` созданного ответа. Повторная
    привязка того же файла находит его здесь и не спрашивает второй раз — отдельная
    таблица «решений пользователя» ради этого не нужна.
    """
    index: dict[str, UUID] = {}
    for answer in session.scalars(
        select(ReferenceAnswer).where(
            ReferenceAnswer.project_id == project_id,
            ReferenceAnswer.source_material_id == material.id,
            ReferenceAnswer.match_method == ReferenceAnswerMatchMethod.RESOLVED_TITLE,
            ReferenceAnswer.is_active.is_(True),
        )
    ):
        if answer.matched_title:
            index[normalize_answer_heading(answer.matched_title)] = answer.program_node_id
    return index


def _ordered_study_nodes(session: Session, project_id: UUID) -> list[ProgramNode]:
    nodes = list(
        session.scalars(
            select(ProgramNode).where(
                ProgramNode.project_id == project_id,
                ProgramNode.is_in_current_program.is_(True),
                ProgramNode.is_archived.is_(False),
            )
        )
    )
    children: dict[UUID | None, list[ProgramNode]] = defaultdict(list)
    for node in nodes:
        children[node.parent_id].append(node)
    for siblings in children.values():
        siblings.sort(key=lambda node: (node.sort_order, str(node.id)))

    ordered: list[ProgramNode] = []

    def visit(parent_id: UUID | None) -> None:
        for node in children.get(parent_id, []):
            if node.node_type in STUDY_NODE_TYPES:
                ordered.append(node)
            visit(node.id)

    visit(None)
    return ordered


def _ordered_fragments(
    session: Session, material: Material
) -> list[tuple[MaterialFragment, int]]:
    return list(
        session.execute(
            select(MaterialFragment, MaterialPage.page_number)
            .join(MaterialPage, MaterialPage.id == MaterialFragment.page_id)
            .where(
                MaterialFragment.material_id == material.id,
                MaterialPage.revision == material.active_parse_revision,
            )
            .order_by(MaterialPage.page_number, MaterialFragment.sort_order)
        ).all()
    )


def _title_sections(
    session: Session,
    project_id: UUID,
    material: Material,
    nodes: list[ProgramNode],
    ordered_fragments: list[tuple[MaterialFragment, int]],
) -> tuple[list[_Section], list[HeadingSuggestion], list[str]]:
    index = HeadingIndex((node.id, node.title) for node in nodes)
    resolved = _resolution_index(session, project_id, material)

    fragments_by_block: dict[UUID, list[MaterialFragment]] = defaultdict(list)
    for fragment, _page in ordered_fragments:
        fragments_by_block[fragment.block_id].append(fragment)

    sections: list[_Section] = []
    suggestions: list[HeadingSuggestion] = []
    duplicates: list[str] = []
    for block in session.scalars(
        select(MaterialBlock)
        .where(
            MaterialBlock.material_id == material.id,
            MaterialBlock.revision == material.active_parse_revision,
            MaterialBlock.block_class == BlockClass.CONTENT,
        )
        .order_by(MaterialBlock.sort_order)
    ):
        if not block.title:
            continue
        fragments = fragments_by_block.get(block.id, [])

        resolved_node = resolved.get(normalize_answer_heading(block.title))
        if resolved_node is not None:
            node_ids = [resolved_node]
            method = ReferenceAnswerMatchMethod.RESOLVED_TITLE
        else:
            match = index.match(block.title)
            if not match.matched:
                if fragments:
                    suggestions.append(
                        HeadingSuggestion(
                            block_id=block.id,
                            heading=block.title,
                            preview=_block_preview(fragments),
                            page_from=block.page_from,
                            candidates=[
                                HeadingSuggestionCandidate(
                                    node_id=candidate.node_id,
                                    node_title=candidate.title,
                                    score=round(candidate.score, 3),
                                )
                                for candidate in match.candidates
                            ],
                        )
                    )
                continue
            node_ids = list(match.node_ids)
            method = match.method or ReferenceAnswerMatchMethod.EXACT_TITLE

        if len(node_ids) > 1:
            # Формулировка повторяется в программе — ответ один и тот же,
            # поэтому привязываем ко всем повторам, но говорим об этом.
            duplicates.append(block.title)
        if not fragments:
            continue
        sections.append(
            _Section(node_ids, block.title, fragments, block.page_from, block.page_to, method)
        )
    return sections, suggestions, duplicates


def _ordinal_sections(
    nodes: list[ProgramNode],
    ordered_fragments: list[tuple[MaterialFragment, int]],
) -> _OrdinalSections:
    if not nodes:
        return _OrdinalSections(rejected_reason="В программе нет вопросов для связывания")
    headings = [
        (index, fragment, page_number)
        for index, (fragment, page_number) in enumerate(ordered_fragments)
        if fragment.element_kind == "heading"
    ]
    selection = select_numbered_series([fragment.text for _, fragment, _ in headings])
    if selection.ambiguous:
        return _OrdinalSections(
            rejected_reason="В файле найдено несколько равноправных нумерованных серий"
        )
    if not selection.items:
        return _OrdinalSections(rejected_reason="В файле не найдена основная нумерация ответов")
    if selection.items[0].number != 1:
        return _OrdinalSections(rejected_reason="Основная нумерация ответов начинается не с 1")
    if len(selection.items) < len(nodes):
        return _OrdinalSections(
            rejected_reason=(
                f"В основной серии {len(selection.items)} ответов, "
                f"а в программе {len(nodes)} вопросов"
            )
        )

    starts = [headings[item.source_index][0] for item in selection.items]
    if selection.source_end < len(headings):
        series_end = headings[selection.source_end][0]
    else:
        series_end = len(ordered_fragments)

    sections: list[_Section] = []
    for ordinal, (_item, start) in enumerate(zip(selection.items, starts, strict=True)):
        end = starts[ordinal + 1] if ordinal + 1 < len(starts) else series_end
        if ordinal >= len(nodes):
            continue
        rows = ordered_fragments[start:end]
        if not rows:
            continue
        fragments = [fragment for fragment, _page in rows]
        pages = [page for _fragment, page in rows]
        title = ordered_fragments[start][0].text.strip()
        sections.append(
            _Section(
                node_ids=[nodes[ordinal].id],
                title=title,
                fragments=fragments,
                page_from=min(pages),
                page_to=max(pages),
                method=ReferenceAnswerMatchMethod.NUMBERED_ORDER,
            )
        )
    return _OrdinalSections(
        sections=sections,
        extra_sections=max(0, len(selection.items) - len(nodes)),
    )


def _bind_section(
    session: Session, project_id: UUID, material: Material, section: _Section
) -> tuple[int, list[UUID]]:
    now = utc_now()
    created: list[UUID] = []
    linked_fragments = 0
    for node_id in section.node_ids:
        for fragment in section.bindable_fragments():
            existing = session.scalar(
                select(Binding).where(
                    Binding.project_id == project_id,
                    Binding.program_node_id == node_id,
                    Binding.fragment_id == fragment.id,
                )
            )
            if existing is not None:
                # Пользователь уже связал этот фрагмент руками — уважаем.
                continue
            binding = Binding(
                id=uuid4(),
                project_id=project_id,
                program_node_id=node_id,
                fragment_id=fragment.id,
                material_id=material.id,
                block_id=fragment.block_id,
                status=BindingStatus.MANUAL,
                mechanism=BindingMechanism.ANSWERS_FILE,
                created_at=now,
                updated_at=now,
            )
            session.add(binding)
            created.append(binding.id)
            linked_fragments += 1
    session.flush()
    return linked_fragments, created


def _rebind(
    session: Session, project_id: UUID, material: Material, sections: list[_Section]
) -> tuple[int, list[UUID]]:
    """Свои прошлые привязки сносим и ставим заново; ручные — не трогаем."""
    session.execute(
        delete(Binding).where(
            Binding.project_id == project_id,
            Binding.material_id == material.id,
            Binding.mechanism == BindingMechanism.ANSWERS_FILE,
        )
    )
    created: list[UUID] = []
    linked_fragments = 0
    for section in sections:
        linked, ids = _bind_section(session, project_id, material, section)
        linked_fragments += linked
        created.extend(ids)
    return linked_fragments, created


def _fill_answers(
    session: Session, project_id: UUID, material: Material, label: str, sections: list[_Section]
) -> tuple[int, int, int]:
    """Эталон собирается из привязанного раздела.

    Переписываем только то, что сами и создали из этого файла и что пользователь
    не подтвердил: правку руками автоматика забирать не имеет права.
    """
    created = updated = kept = 0
    now = utc_now()
    for section in sections:
        text = section.answer_text(material)
        if not text:
            continue
        for node_id in section.node_ids:
            answer = session.get(ReferenceAnswer, (project_id, node_id))
            if answer is None:
                session.add(
                    ReferenceAnswer(
                        project_id=project_id,
                        program_node_id=node_id,
                        text=text,
                        origin_kind=ReferenceAnswerOrigin.IMPORT,
                        match_method=section.method,
                        matched_title=section.title,
                        is_confirmed=False,
                        is_active=True,
                        revision=0,
                        source_label=label,
                        source_material_id=material.id,
                        source_page_from=section.page_from,
                        source_page_to=section.page_to,
                        created_at=now,
                        updated_at=now,
                    )
                )
                created += 1
                continue
            ours = answer.source_material_id == material.id
            same_import = (
                answer.text.strip() == text
                and answer.match_method == section.method
                and answer.matched_title == section.title
                and answer.source_page_from == section.page_from
                and answer.source_page_to == section.page_to
            )
            if not ours or answer.is_confirmed or same_import:
                kept += 1
                continue
            answer.text = text
            answer.match_method = section.method
            answer.matched_title = section.title
            answer.source_label = label
            answer.source_page_from = section.page_from
            answer.source_page_to = section.page_to
            answer.is_active = True
            answer.revision += 1
            answer.updated_at = now
            updated += 1
    session.flush()
    return created, updated, kept


def _require_answers_material(
    session: Session, project_id: UUID, material_id: UUID
) -> tuple[Material, str]:
    project = session.get(Project, project_id)
    if project is None or project.status != ProjectStatus.ACTIVE:
        raise ProjectNotFoundError("Активный проект не найден")
    if project.workspace_variant != WorkspaceVariant.EXAM:
        raise ProjectConflictError(
            "Автопривязка ответов есть только у экзаменационного проекта",
            code="bindings_require_exam_project",
        )
    link = session.get(ProjectMaterial, (project_id, material_id))
    if link is None or MaterialPurpose.REFERENCE_ANSWERS.value not in (link.purposes or []):
        raise ProjectConflictError(
            "Файл не отмечен как эталонные ответы", code="material_not_reference_answers"
        )
    material = session.get(Material, material_id)
    if material is None or material.status != MaterialState.READY:
        raise ProjectConflictError("Сначала завершите разбор файла", code="material_not_ready")
    return material, link.display_name or material.original_name


def link_answers_material(
    session: Session, project_id: UUID, material_id: UUID
) -> AnswersLinkResult:
    """Вызывается из воркера после разбора и кнопкой «Привязать заново»."""
    material, label = _require_answers_material(session, project_id, material_id)

    nodes = _ordered_study_nodes(session, project_id)
    ordered_fragments = _ordered_fragments(session, material)
    title_sections, suggestions, duplicates = _title_sections(
        session, project_id, material, nodes, ordered_fragments
    )
    ordinal = _ordinal_sections(nodes, ordered_fragments)
    title_node_ids = {
        node_id for section in title_sections for node_id in section.node_ids
    }
    numbered_sections = [
        section
        for section in ordinal.sections
        if section.node_ids[0] not in title_node_ids
    ]
    sections = [*title_sections, *numbered_sections]
    if ordinal.rejected_reason is None:
        # Уверенная серия уже объясняет внутренние подзаголовки; не выдаём их
        # за сотни якобы не найденных вопросов.
        suggestions = []
    linked_fragments, created_ids = _rebind(session, project_id, material, sections)
    created, updated, kept = _fill_answers(session, project_id, material, label, sections)

    if created_ids:
        session.add(
            ProjectActionLog(
                project_id=project_id,
                action_type="binding_create",
                phase="active",
                payload_version=1,
                target_title=label,
                inverse_data={"binding_ids": [str(value) for value in created_ids]},
            )
        )
    session.flush()
    return AnswersLinkResult(
        linked_sections=len(sections),
        linked_fragments=linked_fragments,
        created_answers=created,
        updated_answers=updated,
        kept_answers=kept,
        numbered_sections=len(numbered_sections),
        extra_sections=ordinal.extra_sections,
        ordinal_rejected_reason=ordinal.rejected_reason,
        fuzzy_headings=[
            section.title
            for section in sections
            if section.method == ReferenceAnswerMatchMethod.FUZZY_TITLE
        ],
        unmatched_headings=[suggestion.heading for suggestion in suggestions],
        duplicate_headings=duplicates,
        suggestions=suggestions,
    )


def resolve_answers_heading(
    session: Session, project_id: UUID, material_id: UUID, block_id: UUID, node_id: UUID
) -> AnswersLinkResult:
    """Пользователь сам указал вопрос для заголовка, который система не опознала.

    Решение запоминается в `matched_title` созданного эталона, поэтому повторная
    привязка того же файла восстановит его сама (см. `_resolution_index`).
    """
    material, label = _require_answers_material(session, project_id, material_id)
    block = session.get(MaterialBlock, block_id)
    if (
        block is None
        or block.material_id != material.id
        or block.revision != material.active_parse_revision
    ):
        raise ProjectNotFoundError("Раздел файла ответов не найден")
    node = session.get(ProgramNode, node_id)
    if node is None or node.project_id != project_id or node.node_type not in STUDY_NODE_TYPES:
        raise ProjectNotFoundError("Вопрос программы не найден")

    fragments = list(
        session.scalars(
            select(MaterialFragment)
            .join(MaterialPage, MaterialPage.id == MaterialFragment.page_id)
            .where(
                MaterialFragment.block_id == block.id,
                MaterialPage.revision == material.active_parse_revision,
            )
            .order_by(MaterialPage.page_number, MaterialFragment.sort_order)
        )
    )
    if not fragments:
        raise ProjectConflictError("В разделе нет текста", code="answers_section_empty")

    section = _Section(
        [node.id],
        block.title or node.title,
        fragments,
        block.page_from,
        block.page_to,
        ReferenceAnswerMatchMethod.RESOLVED_TITLE,
    )
    linked_fragments, created_ids = _bind_section(session, project_id, material, section)
    created, updated, kept = _fill_answers(session, project_id, material, label, [section])
    if created_ids:
        session.add(
            ProjectActionLog(
                project_id=project_id,
                action_type="binding_create",
                phase="active",
                payload_version=1,
                target_title=node.title,
                inverse_data={"binding_ids": [str(value) for value in created_ids]},
            )
        )
    session.flush()
    return AnswersLinkResult(
        linked_sections=1,
        linked_fragments=linked_fragments,
        created_answers=created,
        updated_answers=updated,
        kept_answers=kept,
    )
