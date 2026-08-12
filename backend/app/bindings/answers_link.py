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
from app.projects.answers import normalize_answer_heading
from app.projects.errors import ProjectConflictError, ProjectNotFoundError

STUDY_NODE_TYPES = {NodeType.TOPIC, NodeType.SUBPOINT}


@dataclass(slots=True)
class AnswersLinkResult:
    linked_sections: int = 0
    linked_fragments: int = 0
    created_answers: int = 0
    updated_answers: int = 0
    kept_answers: int = 0
    unmatched_headings: list[str] = field(default_factory=list)
    duplicate_headings: list[str] = field(default_factory=list)


@dataclass(slots=True)
class _Section:
    node_ids: list[UUID]
    title: str
    fragments: list[MaterialFragment]
    page_from: int
    page_to: int

    def bindable_fragments(self) -> list[MaterialFragment]:
        """Раздел без строки заголовка: она повторяет вопрос, а не отвечает на него —
        привязывать её как свидетельство бессмысленно и выглядит дублем в списке."""
        return [
            fragment
            for fragment in self.fragments
            if not (fragment.element_kind == "heading" and fragment.text.strip() == self.title)
        ]

    def answer_text(self) -> str:
        body = [fragment.text for fragment in self.bindable_fragments()]
        return "\n".join(text for text in body if text.strip()).strip()


def find_answers_material(session: Session, project_id: UUID) -> ProjectMaterial | None:
    """Файл эталонных ответов у проекта ровно один — на этом держится автозаполнение."""
    for link in session.scalars(
        select(ProjectMaterial).where(ProjectMaterial.project_id == project_id)
    ):
        if MaterialPurpose.REFERENCE_ANSWERS.value in (link.purposes or []):
            return link
    return None


def _sections(
    session: Session, project_id: UUID, material: Material
) -> tuple[list[_Section], list[str], list[str]]:
    title_index: dict[str, list[UUID]] = defaultdict(list)
    for node in session.scalars(
        select(ProgramNode).where(
            ProgramNode.project_id == project_id,
            ProgramNode.node_type.in_(STUDY_NODE_TYPES),
            ProgramNode.is_in_current_program.is_(True),
            ProgramNode.is_archived.is_(False),
        )
    ):
        title_index[normalize_answer_heading(node.title)].append(node.id)

    fragments_by_block: dict[UUID, list[MaterialFragment]] = defaultdict(list)
    for fragment, _page in session.execute(
        select(MaterialFragment, MaterialPage.page_number)
        .join(MaterialPage, MaterialPage.id == MaterialFragment.page_id)
        .where(
            MaterialFragment.material_id == material.id,
            MaterialPage.revision == material.active_parse_revision,
        )
        .order_by(MaterialPage.page_number, MaterialFragment.sort_order)
    ).all():
        fragments_by_block[fragment.block_id].append(fragment)

    sections: list[_Section] = []
    unmatched: list[str] = []
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
        node_ids = title_index.get(normalize_answer_heading(block.title), [])
        if not node_ids:
            unmatched.append(block.title)
            continue
        if len(node_ids) > 1:
            # Формулировка повторяется в программе — ответ один и тот же,
            # поэтому привязываем ко всем повторам, но говорим об этом.
            duplicates.append(block.title)
        fragments = fragments_by_block.get(block.id, [])
        if not fragments:
            continue
        sections.append(
            _Section(node_ids, block.title, fragments, block.page_from, block.page_to)
        )
    return sections, unmatched, duplicates


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
    now = utc_now()
    created: list[UUID] = []
    linked_fragments = 0
    for section in sections:
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
        text = section.answer_text()
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
                        match_method=ReferenceAnswerMatchMethod.EXACT_TITLE,
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
            if not ours or answer.is_confirmed or answer.text.strip() == text:
                kept += 1
                continue
            answer.text = text
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


def link_answers_material(
    session: Session, project_id: UUID, material_id: UUID
) -> AnswersLinkResult:
    """Вызывается из воркера после разбора и кнопкой «Привязать заново»."""
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

    sections, unmatched, duplicates = _sections(session, project_id, material)
    linked_fragments, created_ids = _rebind(session, project_id, material, sections)
    label = link.display_name or material.original_name
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
        unmatched_headings=unmatched,
        duplicate_headings=duplicates,
    )
