"""Файл эталонных ответов связывается с вопросами сам, по заголовкам разделов.

Отличие от остальных материалов: у файла ответов заголовок раздела дословно
повторяет формулировку вопроса программы, поэтому связь ставится без модели и
без поиска — сравнением нормализованных заголовков. Отсюда же берётся текст
эталона: раздел ответа целиком, кроме самого заголовка.

Механизм привязки — `answers_file`: не ручная (её никто не ставил руками) и не
проход 2 (тот появится на этапе 8). Ручные привязки пользователя эта операция
не трогает, а свои прошлые — пересоздаёт, поэтому повтор идемпотентен.
"""

from collections import Counter, defaultdict
from collections.abc import Iterator
from dataclasses import dataclass, field
from enum import StrEnum
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
    WorkspaceVariant,
    utc_now,
)
from app.projects.answer_lifecycle import (
    AnswerImportAction,
    AnswerImportOutcome,
    ImportedAnswerCandidate,
    apply_imported_answer,
    is_reference_answer_available,
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


class AnswerLinkPhase(StrEnum):
    PREPARING = "preparing"
    MATCHING = "matching"
    BINDING = "binding"
    IMPORTING = "importing"
    VERIFYING = "verifying"


@dataclass(frozen=True, slots=True)
class AnswersLinkProgress:
    phase: AnswerLinkPhase
    completed: int
    total: int
    phase_completed: int = 0
    phase_total: int = 0


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
    restored_answers: int = 0
    unchanged_answers: int = 0
    preserved_answers: int = 0
    numbered_sections: int = 0
    extra_sections: int = 0
    ordinal_rejected_reason: str | None = None
    fuzzy_headings: list[str] = field(default_factory=list)
    unmatched_headings: list[str] = field(default_factory=list)
    duplicate_headings: list[str] = field(default_factory=list)
    suggestions: list[HeadingSuggestion] = field(default_factory=list)
    expected_questions: int = 0
    matched_node_ids: list[UUID] = field(default_factory=list)
    available_node_ids: list[UUID] = field(default_factory=list)
    unavailable_node_ids: list[UUID] = field(default_factory=list)
    missing_node_ids: list[UUID] = field(default_factory=list)
    ambiguous_sections: list[str] = field(default_factory=list)
    ambiguous_pages: list[int] = field(default_factory=list)
    complete: bool = False


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
    _clear_answer_bindings(session, project_id, material.id)
    created: list[UUID] = []
    linked_fragments = 0
    for section in sections:
        linked, ids = _bind_section(session, project_id, material, section)
        linked_fragments += linked
        created.extend(ids)
    return linked_fragments, created


def _clear_answer_bindings(session: Session, project_id: UUID, material_id: UUID) -> None:
    session.execute(
        delete(Binding).where(
            Binding.project_id == project_id,
            Binding.material_id == material_id,
            Binding.mechanism == BindingMechanism.ANSWERS_FILE,
        )
    )


def _fill_section_answers(
    session: Session,
    project_id: UUID,
    material: Material,
    label: str,
    section: _Section,
) -> list[AnswerImportOutcome]:
    if not section.bindable_fragments():
        return []
    text = section.answer_text(material)
    return [
        apply_imported_answer(
            session,
            ImportedAnswerCandidate(
                project_id=project_id,
                node_id=node_id,
                text=text,
                match_method=section.method,
                matched_title=section.title,
                source_label=label,
                source_material_id=material.id,
                source_page_from=section.page_from,
                source_page_to=section.page_to,
            ),
        )
        for node_id in section.node_ids
    ]


def _fill_answers(
    session: Session, project_id: UUID, material: Material, label: str, sections: list[_Section]
) -> list[AnswerImportOutcome]:
    """Собрать кандидатов из разделов; решение о слоте принимает lifecycle-модуль."""

    outcomes: list[AnswerImportOutcome] = []
    for section in sections:
        outcomes.extend(_fill_section_answers(session, project_id, material, label, section))
    session.flush()
    return outcomes


def _build_link_result(
    session: Session,
    nodes: list[ProgramNode],
    sections: list[_Section],
    *,
    linked_fragments: int,
    outcomes: list[AnswerImportOutcome],
    numbered_sections: int = 0,
    extra_sections: int = 0,
    ordinal_rejected_reason: str | None = None,
    fuzzy_headings: list[str] | None = None,
    unmatched_headings: list[str] | None = None,
    duplicate_headings: list[str] | None = None,
    suggestions: list[HeadingSuggestion] | None = None,
    ambiguous_sections: list[str] | None = None,
    ambiguous_pages: list[int] | None = None,
) -> AnswersLinkResult:
    """Сопоставление, привязки и доступность эталона считаются отдельно."""

    session.flush()
    node_ids = [node.id for node in nodes]
    answers = {
        answer.program_node_id: answer
        for answer in session.scalars(
            select(ReferenceAnswer).where(
                ReferenceAnswer.project_id == nodes[0].project_id,
                ReferenceAnswer.program_node_id.in_(node_ids),
            )
        )
    } if nodes else {}
    matched_ids = {node_id for section in sections for node_id in section.node_ids}
    available_ids = {
        node_id
        for node_id, answer in answers.items()
        if is_reference_answer_available(answer)
    }
    matched = [node.id for node in nodes if node.id in matched_ids]
    missing = [node.id for node in nodes if node.id not in matched_ids]
    available = [node.id for node in nodes if node.id in available_ids]
    unavailable = [node.id for node in nodes if node.id not in available_ids]
    ambiguous = ambiguous_sections or []
    counts = Counter(outcome.action for outcome in outcomes)
    complete = (
        not missing
        and not ambiguous
        and not unavailable
        and len(available) == len(nodes)
    )
    return AnswersLinkResult(
        linked_sections=len(sections),
        linked_fragments=linked_fragments,
        created_answers=counts[AnswerImportAction.CREATED],
        updated_answers=counts[AnswerImportAction.UPDATED],
        restored_answers=counts[AnswerImportAction.RESTORED],
        unchanged_answers=counts[AnswerImportAction.UNCHANGED],
        preserved_answers=counts[AnswerImportAction.PRESERVED],
        numbered_sections=numbered_sections,
        extra_sections=extra_sections,
        ordinal_rejected_reason=ordinal_rejected_reason,
        fuzzy_headings=fuzzy_headings or [],
        unmatched_headings=unmatched_headings or [],
        duplicate_headings=duplicate_headings or [],
        suggestions=suggestions or [],
        expected_questions=len(nodes),
        matched_node_ids=matched,
        available_node_ids=available,
        unavailable_node_ids=unavailable,
        missing_node_ids=missing,
        ambiguous_sections=ambiguous,
        ambiguous_pages=ambiguous_pages or [],
        complete=complete,
    )


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


def iter_link_answers_material(
    session: Session, project_id: UUID, material_id: UUID
) -> Iterator[AnswersLinkProgress | AnswersLinkResult]:
    """Выполнить сопоставление и отдать реальные серверные контрольные точки."""

    yield AnswersLinkProgress(AnswerLinkPhase.PREPARING, completed=0, total=0)
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

    section_total = len(sections)
    total = 2 + section_total * 2
    yield AnswersLinkProgress(
        AnswerLinkPhase.MATCHING,
        completed=1,
        total=total,
        phase_completed=section_total,
        phase_total=len(nodes),
    )

    _clear_answer_bindings(session, project_id, material.id)
    linked_fragments = 0
    created_ids: list[UUID] = []
    for index, section in enumerate(sections, start=1):
        section_linked, section_created = _bind_section(
            session, project_id, material, section
        )
        linked_fragments += section_linked
        created_ids.extend(section_created)
        yield AnswersLinkProgress(
            AnswerLinkPhase.BINDING,
            completed=1 + index,
            total=total,
            phase_completed=index,
            phase_total=section_total,
        )

    outcomes: list[AnswerImportOutcome] = []
    for index, section in enumerate(sections, start=1):
        outcomes.extend(
            _fill_section_answers(session, project_id, material, label, section)
        )
        yield AnswersLinkProgress(
            AnswerLinkPhase.IMPORTING,
            completed=1 + section_total + index,
            total=total,
            phase_completed=index,
            phase_total=section_total,
        )

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
    yield AnswersLinkProgress(
        AnswerLinkPhase.VERIFYING,
        completed=total - 1,
        total=total,
    )
    result = _build_link_result(
        session,
        nodes,
        sections,
        linked_fragments=linked_fragments,
        outcomes=outcomes,
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
        ambiguous_sections=[item.heading for item in detection.ambiguous],
        ambiguous_pages=sorted({item.page for item in detection.ambiguous}),
    )
    yield AnswersLinkProgress(
        AnswerLinkPhase.VERIFYING,
        completed=total,
        total=total,
        phase_completed=1,
        phase_total=1,
    )
    yield result


def link_answers_material(
    session: Session, project_id: UUID, material_id: UUID
) -> AnswersLinkResult:
    """Синхронный адаптер для воркера, тестов и прежнего HTTP-контракта."""

    result: AnswersLinkResult | None = None
    for event in iter_link_answers_material(session, project_id, material_id):
        if isinstance(event, AnswersLinkResult):
            result = event
    if result is None:  # pragma: no cover - генератор всегда заканчивается результатом
        raise RuntimeError("Сопоставление ответов завершилось без отчёта")
    return result


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
    outcomes = _fill_answers(session, project_id, material, label, sections)
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
    return _build_link_result(
        session,
        nodes,
        sections,
        linked_fragments=linked_fragments,
        outcomes=outcomes,
    )
