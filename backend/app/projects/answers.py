import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.marker_labels import marker_label, material_image_label
from app.materials.storage import material_path, store_answer_upload
from app.models import (
    Binding,
    BindingStatus,
    Material,
    MaterialFragment,
    NodeType,
    ProgramNode,
    Project,
    ProjectStatus,
    ReferenceAnswer,
    ReferenceAnswerAttachment,
    ReferenceAnswerMatchMethod,
    ReferenceAnswerOrigin,
    WorkspaceVariant,
    utc_now,
)
from app.projects.answer_lifecycle import is_reference_answer_available
from app.projects.errors import ProjectConflictError, ProjectDomainError, ProjectNotFoundError
from app.projects.heading_match import HeadingIndex, HeadingMatch, normalize_answer_heading
from app.projects.program import read_program
from app.projects.schemas import (
    CoverageMapRead,
    CoverageMapRow,
    CoverageMapTotals,
    ProgramNodeRead,
    ReferenceAnswerAttachmentRead,
    ReferenceAnswerConfirm,
    ReferenceAnswerImportIssue,
    ReferenceAnswerImportResult,
    ReferenceAnswerImportWrite,
    ReferenceAnswerRead,
    ReferenceAnswerSlot,
    ReferenceAnswerStatus,
    ReferenceAnswerWrite,
)

ANSWER_PREFIX_RE = re.compile(r"^\s*Ответ\s*:\s*(.*)$", re.IGNORECASE)
STUDY_NODE_TYPES = {NodeType.TOPIC, NodeType.SUBPOINT}


@dataclass(frozen=True, slots=True)
class ProgramNodeTitle:
    id: UUID
    title: str


@dataclass(frozen=True, slots=True)
class ParsedAnswerMatch:
    node_id: UUID
    heading: str
    text: str
    method: ReferenceAnswerMatchMethod = ReferenceAnswerMatchMethod.EXACT_TITLE


@dataclass(frozen=True, slots=True)
class ParsedAnswerSection:
    heading: str
    text: str | None
    candidate_node_ids: tuple[UUID, ...] = ()


@dataclass(frozen=True, slots=True)
class ParsedReferenceAnswers:
    matches: tuple[ParsedAnswerMatch, ...]
    ambiguous: tuple[ParsedAnswerSection, ...]
    unmatched_sections: tuple[ParsedAnswerSection, ...]
    empty_sections: tuple[str, ...]


def _answer_text(lines: list[str]) -> str:
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    if lines:
        prefix = ANSWER_PREFIX_RE.match(lines[0])
        if prefix:
            remainder = prefix.group(1).strip()
            lines = ([remainder] if remainder else []) + lines[1:]
    return "\n".join(lines).strip()


def parse_reference_answers(
    raw_text: str,
    study_nodes: Sequence[ProgramNodeTitle],
) -> ParsedReferenceAnswers:
    index = HeadingIndex((node.id, node.title) for node in study_nodes)

    matches: list[ParsedAnswerMatch] = []
    ambiguous: list[ParsedAnswerSection] = []
    unmatched: list[ParsedAnswerSection] = []
    empty: list[str] = []
    leading_lines: list[str] = []
    current_heading: str | None = None
    current_nodes: tuple[UUID, ...] = ()
    current_method = ReferenceAnswerMatchMethod.EXACT_TITLE
    current_lines: list[str] = []

    def flush_current() -> None:
        nonlocal current_heading, current_nodes, current_lines
        if current_heading is None:
            return
        text = _answer_text(current_lines)
        if not text:
            empty.append(current_heading)
        elif len(current_nodes) == 1:
            matches.append(
                ParsedAnswerMatch(
                    node_id=current_nodes[0],
                    heading=current_heading,
                    text=text,
                    method=current_method,
                )
            )
        else:
            ambiguous.append(
                ParsedAnswerSection(
                    heading=current_heading,
                    text=text,
                    candidate_node_ids=current_nodes,
                )
            )
        current_heading = None
        current_nodes = ()
        current_lines = []

    normalized_text = raw_text.replace("\r\n", "\n").replace("\r", "\n")
    for line in normalized_text.split("\n"):
        # Неуверенный подбор здесь не используется: в сплошном тексте отличить
        # заголовок от обычной строки нечем, и предложение кандидатов разрезало бы
        # ответ пополам. Разбор файла (answers_link) знает границы блоков и умеет.
        match = index.match(line) if line.strip() else HeadingMatch()
        if match.matched:
            flush_current()
            current_heading = line.strip()
            current_nodes = match.node_ids
            current_method = match.method or ReferenceAnswerMatchMethod.EXACT_TITLE
            continue
        if current_heading is None:
            leading_lines.append(line)
        else:
            current_lines.append(line)
    flush_current()

    leading_text = _answer_text(leading_lines)
    if leading_text:
        leading_parts = leading_text.splitlines()
        unmatched.append(
            ParsedAnswerSection(
                heading=leading_parts[0],
                text="\n".join(leading_parts[1:]).strip() or None,
            )
        )

    return ParsedReferenceAnswers(
        matches=tuple(matches),
        ambiguous=tuple(ambiguous),
        unmatched_sections=tuple(unmatched),
        empty_sections=tuple(empty),
    )


def _require_exam_project(session: Session, project_id: UUID, *, writable: bool) -> Project:
    project = session.get(Project, project_id)
    if project is None or project.status == ProjectStatus.DRAFT:
        raise ProjectNotFoundError()
    if project.workspace_variant != WorkspaceVariant.EXAM:
        raise ProjectConflictError(
            "Эталонные ответы этапа 4 доступны только экзаменационным проектам",
            code="reference_answers_require_exam_project",
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
            "Эталонный ответ можно добавить только к изучаемому узлу",
            status=422,
            code="reference_answer_requires_study_node",
        )
    return node


def reference_answer_status(
    answer: ReferenceAnswer | None,
    current_title: str,
) -> ReferenceAnswerStatus:
    if not is_reference_answer_available(answer):
        return ReferenceAnswerStatus.MISSING
    if (
        answer.origin_kind == ReferenceAnswerOrigin.IMPORT
        and answer.matched_title is not None
        and normalize_answer_heading(answer.matched_title)
        != normalize_answer_heading(current_title)
    ):
        return ReferenceAnswerStatus.NEEDS_REVIEW
    if answer.origin_kind == ReferenceAnswerOrigin.MANUAL:
        return ReferenceAnswerStatus.MANUAL
    if answer.is_confirmed:
        return ReferenceAnswerStatus.CONFIRMED
    return ReferenceAnswerStatus.AUTO_MATCHED


def _answer_read(answer: ReferenceAnswer | None) -> ReferenceAnswerRead | None:
    if answer is None:
        return None
    value = ReferenceAnswerRead.model_validate(answer, from_attributes=True)
    return value.model_copy(
        update={"source_only": bool(answer.source_material_id and not answer.text.strip())}
    )


def _slot(node: ProgramNode, answer: ReferenceAnswer | None) -> ReferenceAnswerSlot:
    return ReferenceAnswerSlot(
        project_id=node.project_id,
        node_id=node.id,
        node_title=node.title,
        status=reference_answer_status(answer, node.title),
        answer=_answer_read(answer),
    )


def get_reference_answer(
    session: Session,
    project_id: UUID,
    node_id: UUID,
) -> ReferenceAnswerSlot:
    _require_exam_project(session, project_id, writable=False)
    node = _require_study_node(session, project_id, node_id)
    answer = session.get(ReferenceAnswer, (project_id, node_id))
    return _slot(node, answer)


def _check_revision(answer: ReferenceAnswer, expected_revision: int) -> None:
    if answer.revision != expected_revision:
        raise ProjectConflictError(
            "Эталонный ответ уже изменён в другой вкладке",
            code="stale_reference_answer_revision",
            context={"current_reference_answer_revision": answer.revision},
        )


def put_reference_answer(
    session: Session,
    project_id: UUID,
    node_id: UUID,
    command: ReferenceAnswerWrite,
) -> ReferenceAnswerSlot:
    with session.begin():
        _require_exam_project(session, project_id, writable=True)
        node = _require_study_node(session, project_id, node_id)
        answer = session.get(ReferenceAnswer, (project_id, node_id))
        now = utc_now()
        if answer is None:
            if command.expected_revision is not None:
                raise ProjectConflictError(
                    "Эталонный ответ был удалён или ещё не создан",
                    code="reference_answer_missing",
                )
            answer = ReferenceAnswer(
                project_id=project_id,
                program_node_id=node_id,
                text=command.text,
                origin_kind=ReferenceAnswerOrigin.MANUAL,
                match_method=ReferenceAnswerMatchMethod.MANUAL,
                matched_title=None,
                is_confirmed=True,
                is_active=True,
                revision=0,
                source_label=command.source_label,
                created_at=now,
                updated_at=now,
            )
            session.add(answer)
        else:
            if command.expected_revision is None:
                raise ProjectConflictError(
                    "У темы уже есть эталонный ответ",
                    code="reference_answer_exists",
                    context={"current_reference_answer_revision": answer.revision},
                )
            _check_revision(answer, command.expected_revision)
            answer.text = command.text
            answer.origin_kind = ReferenceAnswerOrigin.MANUAL
            answer.match_method = ReferenceAnswerMatchMethod.MANUAL
            answer.matched_title = None
            answer.is_confirmed = True
            answer.is_active = True
            answer.source_label = command.source_label
            answer.source_material_id = None
            answer.source_page_from = None
            answer.source_page_to = None
            answer.revision += 1
            answer.updated_at = now
        session.flush()
        return _slot(node, answer)


def confirm_reference_answer(
    session: Session,
    project_id: UUID,
    node_id: UUID,
    command: ReferenceAnswerConfirm,
) -> ReferenceAnswerSlot:
    with session.begin():
        _require_exam_project(session, project_id, writable=True)
        node = _require_study_node(session, project_id, node_id)
        answer = session.get(ReferenceAnswer, (project_id, node_id))
        if not is_reference_answer_available(answer):
            raise ProjectNotFoundError("Эталонный ответ не найден")
        _check_revision(answer, command.expected_revision)
        answer.is_confirmed = True
        answer.matched_title = node.title
        answer.revision += 1
        answer.updated_at = utc_now()
        session.flush()
        return _slot(node, answer)


def delete_reference_answer(
    session: Session,
    project_id: UUID,
    node_id: UUID,
    expected_revision: int,
) -> ReferenceAnswerSlot:
    with session.begin():
        _require_exam_project(session, project_id, writable=True)
        node = _require_study_node(session, project_id, node_id)
        answer = session.get(ReferenceAnswer, (project_id, node_id))
        if answer is None:
            raise ProjectNotFoundError("Эталонный ответ не найден")
        _check_revision(answer, expected_revision)
        if answer.is_active:
            answer.is_active = False
            answer.revision += 1
            answer.updated_at = utc_now()
            session.flush()
        return _slot(node, answer)


def _preview(text: str) -> str:
    collapsed = " ".join(text.split())
    return collapsed if len(collapsed) <= 180 else f"{collapsed[:177]}…"


def _preorder_nodes(nodes: Sequence[ProgramNodeRead]) -> list[ProgramNodeRead]:
    """Keep each section next to its descendants in API read models."""
    children: dict[UUID | None, list[ProgramNodeRead]] = {}
    for node in nodes:
        children.setdefault(node.parent_id, []).append(node)
    for siblings in children.values():
        siblings.sort(key=lambda node: (node.sort_order, str(node.id)))

    ordered: list[ProgramNodeRead] = []

    def visit(parent_id: UUID | None) -> None:
        for node in children.get(parent_id, []):
            ordered.append(node)
            visit(node.id)

    visit(None)
    return ordered


def _coverage_map(session: Session, project: Project) -> CoverageMapRead:
    state = read_program(session, project.id)
    answers = {
        answer.program_node_id: answer
        for answer in session.scalars(
            select(ReferenceAnswer).where(ReferenceAnswer.project_id == project.id)
        )
    }
    rows: list[CoverageMapRow] = []
    current_statuses: list[ReferenceAnswerStatus] = []
    for node in _preorder_nodes(state.nodes):
        if node.is_archived:
            continue
        answer = answers.get(node.id)
        is_study = node.node_type in STUDY_NODE_TYPES
        status = reference_answer_status(answer, node.title) if is_study else None
        if is_study and node.is_in_current_program and status is not None:
            current_statuses.append(status)
        rows.append(
            CoverageMapRow(
                node_id=node.id,
                parent_id=node.parent_id,
                node_type=node.node_type,
                exam_kind=node.exam_kind,
                title=node.title,
                sort_order=node.sort_order,
                is_in_current_program=node.is_in_current_program,
                target_level=node.target_level,
                answer_status=status,
                answer_preview=(
                    _preview(answer.text) if is_reference_answer_available(answer) else None
                ),
                answer_revision=(answer.revision if answer is not None else None),
            )
        )
    with_answer = sum(status != ReferenceAnswerStatus.MISSING for status in current_statuses)
    return CoverageMapRead(
        project_id=project.id,
        program_revision=project.program_revision,
        rows=rows,
        totals=CoverageMapTotals(
            study_nodes=len(current_statuses),
            with_answer=with_answer,
            confirmed=sum(
                status in {ReferenceAnswerStatus.CONFIRMED, ReferenceAnswerStatus.MANUAL}
                for status in current_statuses
            ),
            needs_review=sum(
                status == ReferenceAnswerStatus.NEEDS_REVIEW for status in current_statuses
            ),
            missing=sum(status == ReferenceAnswerStatus.MISSING for status in current_statuses),
        ),
    )


def get_coverage_map(session: Session, project_id: UUID) -> CoverageMapRead:
    project = _require_exam_project(session, project_id, writable=False)
    return _coverage_map(session, project)


MAX_ATTACHMENT_BYTES = 20 * 1024 * 1024
ATTACHMENT_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".pdf", ".docx", ".txt", ".md"}
ACTIVE_BINDING_STATUSES = {BindingStatus.MANUAL, BindingStatus.CONFIRMED, BindingStatus.MACHINE}


def _unique_attachment_name(file_name: str, existing_names: set[str]) -> str:
    """Маркер вложения — это имя файла, поэтому в одном ответе оно однозначно."""
    if file_name not in existing_names:
        return file_name
    path = Path(file_name)
    index = 2
    while True:
        candidate = f"{path.stem} ({index}){path.suffix}"
        if candidate not in existing_names:
            return candidate
        index += 1


def list_attachments(
    session: Session, project_id: UUID, node_id: UUID
) -> list[ReferenceAnswerAttachmentRead]:
    _require_exam_project(session, project_id, writable=False)
    rows = session.scalars(
        select(ReferenceAnswerAttachment)
        .where(
            ReferenceAnswerAttachment.project_id == project_id,
            ReferenceAnswerAttachment.program_node_id == node_id,
        )
        .order_by(ReferenceAnswerAttachment.created_at)
    )
    return [ReferenceAnswerAttachmentRead.model_validate(row) for row in rows]


async def add_attachment(
    session: Session, project_id: UUID, node_id: UUID, upload: UploadFile
) -> ReferenceAnswerAttachmentRead:
    _require_exam_project(session, project_id, writable=False)  # ранний отказ до чтения тела
    storage_path, media_type, size, original_name = await store_answer_upload(
        str(project_id),
        upload,
        allowed_suffixes=ATTACHMENT_SUFFIXES,
        max_bytes=MAX_ATTACHMENT_BYTES,
    )
    # Ранняя проверка уже открыла транзакцию чтения: без её закрытия `begin()`
    # падает с «A transaction is already begun» (тот же приём в materials/service).
    session.rollback()
    with session.begin():
        _require_exam_project(session, project_id, writable=True)
        _require_study_node(session, project_id, node_id)
        existing_names = set(
            session.scalars(
                select(ReferenceAnswerAttachment.file_name).where(
                    ReferenceAnswerAttachment.project_id == project_id,
                    ReferenceAnswerAttachment.program_node_id == node_id,
                )
            )
        )
        bound_image_labels = {
            material_image_label(material.id, material.original_name, asset_path)
            for material, asset_path in session.execute(
                select(Material, MaterialFragment.asset_path)
                .join(Binding, Binding.material_id == Material.id)
                .join(MaterialFragment, MaterialFragment.id == Binding.fragment_id)
                .where(
                    Binding.project_id == project_id,
                    Binding.program_node_id == node_id,
                    Binding.status.in_(ACTIVE_BINDING_STATUSES),
                    MaterialFragment.element_kind == "image",
                    MaterialFragment.asset_path.is_not(None),
                )
            )
        }
        row = ReferenceAnswerAttachment(
            project_id=project_id,
            program_node_id=node_id,
            file_name=_unique_attachment_name(
                marker_label(original_name), existing_names | bound_image_labels
            ),
            storage_path=storage_path,
            media_type=media_type,
            size_bytes=size,
            created_at=utc_now(),
        )
        session.add(row)
        session.flush()
        return ReferenceAnswerAttachmentRead.model_validate(row)


def delete_attachment(session: Session, project_id: UUID, attachment_id: UUID) -> None:
    with session.begin():
        _require_exam_project(session, project_id, writable=True)
        row = session.get(ReferenceAnswerAttachment, attachment_id)
        if row is None or row.project_id != project_id:
            raise ProjectNotFoundError("Вложение не найдено")
        path = material_path(row.storage_path)
        session.delete(row)
    path.unlink(missing_ok=True)


def attachment_path(session: Session, project_id: UUID, attachment_id: UUID) -> Path:
    _require_exam_project(session, project_id, writable=False)
    row = session.get(ReferenceAnswerAttachment, attachment_id)
    if row is None or row.project_id != project_id:
        raise ProjectNotFoundError("Вложение не найдено")
    return material_path(row.storage_path)


def import_reference_answers(
    session: Session,
    project_id: UUID,
    command: ReferenceAnswerImportWrite,
) -> ReferenceAnswerImportResult:
    with session.begin():
        project = _require_exam_project(session, project_id, writable=True)
        nodes = list(
            session.scalars(
                select(ProgramNode).where(
                    ProgramNode.project_id == project_id,
                    ProgramNode.node_type.in_(STUDY_NODE_TYPES),
                    ProgramNode.is_in_current_program.is_(True),
                    ProgramNode.is_archived.is_(False),
                )
            )
        )
        parsed = parse_reference_answers(
            command.raw_text,
            [ProgramNodeTitle(id=node.id, title=node.title) for node in nodes],
        )
        occupied = {
            answer.program_node_id
            for answer in session.scalars(
                select(ReferenceAnswer).where(ReferenceAnswer.project_id == project_id)
            )
        }
        skipped: list[UUID] = []
        created = 0
        now = utc_now()
        node_by_id = {node.id: node for node in nodes}
        for match in parsed.matches:
            if match.node_id in occupied:
                if match.node_id not in skipped:
                    skipped.append(match.node_id)
                continue
            node = node_by_id[match.node_id]
            session.add(
                ReferenceAnswer(
                    project_id=project_id,
                    program_node_id=match.node_id,
                    text=match.text,
                    origin_kind=ReferenceAnswerOrigin.IMPORT,
                    match_method=match.method,
                    matched_title=node.title,
                    is_confirmed=False,
                    is_active=True,
                    revision=0,
                    source_label=command.source_label,
                    created_at=now,
                    updated_at=now,
                )
            )
            occupied.add(match.node_id)
            created += 1
        session.flush()
        return ReferenceAnswerImportResult(
            created=created,
            skipped_existing=skipped,
            ambiguous=[
                ReferenceAnswerImportIssue(
                    heading=section.heading,
                    preview=_preview(section.text) if section.text else None,
                    candidate_node_ids=list(section.candidate_node_ids),
                )
                for section in parsed.ambiguous
            ],
            unmatched_sections=[
                ReferenceAnswerImportIssue(
                    heading=section.heading,
                    preview=_preview(section.text) if section.text else None,
                )
                for section in parsed.unmatched_sections
            ],
            empty_sections=list(parsed.empty_sections),
            coverage_map=_coverage_map(session, project),
        )
