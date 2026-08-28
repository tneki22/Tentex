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

from app.bindings import answer_sections
from app.marker_labels import material_image_label
from app.materials.schemas import ExamMaterialSlot, MaterialPurpose
from app.models import (
    Binding,
    BindingMechanism,
    BindingStatus,
    ExamKind,
    Material,
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
from app.projects.heading_match import normalize_answer_heading

STUDY_NODE_TYPES = {NodeType.TOPIC, NodeType.SUBPOINT}

# Слот файла ответов сужает, какие узлы программы он вообще может закрыть:
# ответы на вопросы не должны попасть в нумерацию решений задач и наоборот.
# Файл без слота (старый общий эталон) видит всё дерево — `None` в значении.
_ANSWERS_SLOT_KIND: dict[str | None, ExamKind | None] = {
    ExamMaterialSlot.QUESTION_ANSWERS.value: ExamKind.QUESTION,
    ExamMaterialSlot.TASK_ANSWERS.value: ExamKind.TASK,
    None: None,
}
@dataclass(slots=True)
class HeadingSuggestionCandidate:
    node_id: UUID
    node_title: str
    score: float


@dataclass(slots=True)
class HeadingSuggestion:
    """Заголовок, для которого вопрос не определён уверенно — выбор за пользователем."""

    anchor_fragment_id: UUID
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
    expected_questions: int = 0
    linked_node_ids: list[UUID] = field(default_factory=list)
    missing_node_ids: list[UUID] = field(default_factory=list)
    ambiguous_sections: list[str] = field(default_factory=list)
    ambiguous_pages: list[int] = field(default_factory=list)


@dataclass(slots=True)
class _Section:
    node_ids: list[UUID]
    title: str
    fragments: list[MaterialFragment]
    page_from: int
    page_to: int
    method: ReferenceAnswerMatchMethod = ReferenceAnswerMatchMethod.EXACT_TITLE
    header_fragment_ids: set[UUID] = field(default_factory=set)

    def bindable_fragments(self) -> list[MaterialFragment]:
        """Раздел без строки заголовка: она повторяет вопрос, а не отвечает на него —
        привязывать её как свидетельство бессмысленно и выглядит дублем в списке."""
        if self.header_fragment_ids:
            return [
                fragment
                for fragment in self.fragments
                if fragment.id not in self.header_fragment_ids
            ]
        return [
            fragment
            for fragment in self.fragments
            if not (fragment.element_kind == "heading" and fragment.text.strip() == self.title)
        ]

    def answer_text(self, material: Material) -> str:
        fragments = self.bindable_fragments()
        if fragments and all(fragment.element_kind == "image" for fragment in fragments):
            # Эталон без единой текстовой строки нечем сверять — источник
            # открывается напрямую (`source_only`).
            return ""
        body: list[str] = []
        for fragment in fragments:
            if fragment.element_kind in {"image", "table"} and fragment.asset_path:
                label = material_image_label(
                    material.id, material.original_name, fragment.asset_path
                )
                body.append(f"[изображение: {label}]")
            elif fragment.element_kind == "formula" and fragment.text.strip():
                formula = fragment.text.strip()
                body.append(formula if formula.startswith("$$") else f"$${formula}$$")
            else:
                body.append(fragment.text)
        return "\n".join(body)


def _expand_duplicate_sections(
    nodes: list[ProgramNode], sections: list[_Section]
) -> list[_Section]:
    """Одинаковая формулировка вопроса — одинаковый эталон на все её вхождения.

    Заголовок в файле ответов встречается один раз даже если вопрос в программе
    задублирован (импортирован с сохранением исходной нумерации), поэтому раздел
    находит только один узел. Здесь раздел раздаётся на всех тёзок сразу — так же,
    как если бы автор ответов расписал эталон под каждым повтором отдельно.
    """
    node_by_id = {node.id: node for node in nodes}
    groups: dict[str, list[UUID]] = defaultdict(list)
    for node in nodes:
        groups[node.title.casefold()].append(node.id)

    expanded: list[_Section] = []
    for section in sections:
        ids: list[UUID] = []
        seen: set[UUID] = set()
        for node_id in section.node_ids:
            node = node_by_id.get(node_id)
            group = groups[node.title.casefold()] if node is not None else [node_id]
            for group_id in group:
                if group_id not in seen:
                    seen.add(group_id)
                    ids.append(group_id)
        expanded.append(
            _Section(
                node_ids=ids,
                title=section.title,
                fragments=section.fragments,
                page_from=section.page_from,
                page_to=section.page_to,
                method=section.method,
                header_fragment_ids=section.header_fragment_ids,
            )
        )
    return expanded


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


def _ordered_study_nodes(
    session: Session, project_id: UUID, exam_kind: ExamKind | None = None
) -> list[ProgramNode]:
    """Изучаемые узлы в порядке обхода дерева, при необходимости — только

    одного вида (`question` или `task`). Раздельная автопривязка ответов и
    решений держится на этом сужении: без слота (`exam_kind=None`) видно всё
    дерево, как у прежнего общего файла ответов.
    """
    filters = [
        ProgramNode.project_id == project_id,
        ProgramNode.is_in_current_program.is_(True),
        ProgramNode.is_archived.is_(False),
    ]
    if exam_kind is not None:
        filters.append(ProgramNode.exam_kind == exam_kind)
    nodes = list(session.scalars(select(ProgramNode).where(*filters)))
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
        if not section.bindable_fragments():
            continue
        text = section.answer_text(material)
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
                answer.text == text
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
) -> tuple[Material, str, ExamKind | None]:
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
    exam_kind = _ANSWERS_SLOT_KIND.get(link.exam_slot)
    return material, link.display_name or material.original_name, exam_kind


def link_answers_material(
    session: Session, project_id: UUID, material_id: UUID
) -> AnswersLinkResult:
    """Вызывается из воркера после разбора и кнопкой «Привязать заново»."""
    material, label, exam_kind = _require_answers_material(session, project_id, material_id)

    nodes = _ordered_study_nodes(session, project_id, exam_kind)
    ordered_fragments = _ordered_fragments(session, material)
    detection = answer_sections.detect_sections(
        nodes,
        ordered_fragments,
        _resolution_index(session, project_id, material),
    )
    sections = [
        _Section(
            node_ids=list(section.node_ids),
            title=section.title,
            fragments=list(section.fragments),
            page_from=section.page_from,
            page_to=section.page_to,
            method=section.method,
            header_fragment_ids=set(section.header_fragment_ids),
        )
        for section in detection.sections
    ]
    sections = _expand_duplicate_sections(nodes, sections)
    suggestions = [
        HeadingSuggestion(
            anchor_fragment_id=item.anchor_fragment_id,
            heading=item.heading,
            preview=item.preview,
            page_from=item.page,
            candidates=[
                HeadingSuggestionCandidate(
                    node_id=candidate.node_id,
                    node_title=candidate.title,
                    score=round(candidate.score, 3),
                )
                for candidate in item.candidates
            ],
        )
        for item in detection.ambiguous
    ]
    numbered_sections = [
        section
        for section in sections
        if section.method == ReferenceAnswerMatchMethod.NUMBERED_ORDER
    ]
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
    linked_ids = {node_id for section in sections for node_id in section.node_ids}
    return AnswersLinkResult(
        linked_sections=len(sections),
        linked_fragments=linked_fragments,
        created_answers=created,
        updated_answers=updated,
        kept_answers=kept,
        numbered_sections=len(numbered_sections),
        extra_sections=detection.extra_sections,
        ordinal_rejected_reason=None,
        fuzzy_headings=[
            section.title
            for section in sections
            if section.method == ReferenceAnswerMatchMethod.FUZZY_TITLE
        ],
        unmatched_headings=[suggestion.heading for suggestion in suggestions],
        duplicate_headings=[],
        suggestions=suggestions,
        expected_questions=len(nodes),
        linked_node_ids=[node.id for node in nodes if node.id in linked_ids],
        missing_node_ids=[node.id for node in nodes if node.id not in linked_ids],
        ambiguous_sections=[item.heading for item in detection.ambiguous],
        ambiguous_pages=sorted({item.page for item in detection.ambiguous}),
    )


def resolve_answers_heading(
    session: Session,
    project_id: UUID,
    material_id: UUID,
    anchor_fragment_id: UUID,
    node_id: UUID,
) -> AnswersLinkResult:
    """Пользователь сам указал вопрос для заголовка, который система не опознала.

    Решение запоминается в `matched_title` созданного эталона, поэтому повторная
    привязка того же файла восстановит его сама (см. `_resolution_index`).
    """
    material, label, exam_kind = _require_answers_material(session, project_id, material_id)
    node = session.get(ProgramNode, node_id)
    if node is None or node.project_id != project_id or node.node_type not in STUDY_NODE_TYPES:
        raise ProjectNotFoundError("Вопрос программы не найден")

    nodes = _ordered_study_nodes(session, project_id, exam_kind)
    ordered_fragments = _ordered_fragments(session, material)
    detected = answer_sections.section_for_resolution(
        nodes, ordered_fragments, anchor_fragment_id, node_id
    )
    if detected is None:
        raise ProjectNotFoundError("Раздел файла ответов не найден")
    section = _Section(
        node_ids=list(detected.node_ids),
        title=detected.title,
        fragments=list(detected.fragments),
        page_from=detected.page_from,
        page_to=detected.page_to,
        method=detected.method,
        header_fragment_ids=set(detected.header_fragment_ids),
    )
    sections = _expand_duplicate_sections(nodes, [section])
    linked_fragments = 0
    created_ids: list[UUID] = []
    for item in sections:
        item_linked, item_created = _bind_section(session, project_id, material, item)
        linked_fragments += item_linked
        created_ids.extend(item_created)
    created, updated, kept = _fill_answers(session, project_id, material, label, sections)
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
    linked_ids = {item for sec in sections for item in sec.node_ids}
    return AnswersLinkResult(
        linked_sections=1,
        linked_fragments=linked_fragments,
        created_answers=created,
        updated_answers=updated,
        kept_answers=kept,
        expected_questions=len(nodes),
        linked_node_ids=[item.id for item in nodes if item.id in linked_ids],
        missing_node_ids=[item.id for item in nodes if item.id not in linked_ids],
    )
