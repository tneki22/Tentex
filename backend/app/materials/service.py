from pathlib import Path
from uuid import UUID

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.bindings import answers_link
from app.bindings.service import delete_project_material_bindings
from app.materials import library
from app.materials.library import (
    PURPOSE_VALUES,
)
from app.materials.library import (
    guard_single_answers_file as _guard_single_answers_file,
)
from app.materials.library import (
    latest_task as _latest_task,
)
from app.materials.library import (
    latest_tasks_by_material as _latest_tasks_by_material,
)
from app.materials.library import (
    task_read as _task_read,
)
from app.materials.schemas import (
    ExamProgramDraftImportWrite,
    ExamProgramImportWrite,
    ExamProgramPreview,
    ExamProgramPreviewNode,
    ExternalMaterialCreate,
    MaterialAnswerImportResult,
    MaterialPurpose,
    MaterialRead,
    MaterialUpdate,
    PageCorrectionRead,
    PageRead,
    PageTextUpdate,
    ProcessingStart,
    TextMaterialCreate,
)
from app.materials.storage import material_path
from app.models import (
    ExamFormat,
    GoalPassport,
    Material,
    MaterialFragment,
    MaterialPage,
    MaterialState,
    ProcessingTask,
    Project,
    ProjectMaterial,
    ProjectStatus,
    ReferenceAnswer,
    SourceRole,
    utc_now,
)
from app.projects import answers, program
from app.projects.errors import ProjectConflictError, ProjectNotFoundError
from app.projects.importer import ExamImportError, ParsedExamProgram, parse_exam_program
from app.projects.schemas import ReferenceAnswerImportWrite


def _project(
    session: Session, project_id: UUID, *, writable: bool, allow_draft: bool = True
) -> Project:
    project = session.get(Project, project_id)
    if project is None or (project.status == ProjectStatus.DRAFT and not allow_draft):
        raise ProjectNotFoundError()
    if writable and project.status not in {ProjectStatus.ACTIVE, ProjectStatus.DRAFT}:
        raise ProjectConflictError(
            "Архивный или завершённый проект нельзя изменять",
            code="project_read_only",
            context={"current_status": project.status.value},
        )
    return project


def _link(session: Session, project_id: UUID, material_id: UUID) -> ProjectMaterial:
    link = session.get(ProjectMaterial, (project_id, material_id))
    if link is None:
        raise ProjectNotFoundError("Материал проекта не найден")
    return link


def _read(link: ProjectMaterial, material: Material, task: ProcessingTask | None) -> MaterialRead:
    purposes = [purpose for purpose in link.purposes if purpose in PURPOSE_VALUES]
    return MaterialRead(
        id=material.id,
        original_name=material.original_name,
        display_name=link.display_name or material.original_name,
        media_type=material.media_type,
        source_kind=material.source_kind,
        source_url=material.source_url,
        retrieved_at=material.retrieved_at,
        size_bytes=material.size_bytes,
        page_count=material.page_count,
        source_role=link.source_role,
        priority=link.priority,
        instruction=link.instruction,
        purposes=purposes or [MaterialPurpose.STUDY_SOURCE],
        status=material.status,
        parser_mode=material.parser_mode,
        active_parse_revision=material.active_parse_revision,
        scan_page_count=material.scan_page_count,
        ocr_low_page_count=material.ocr_low_page_count,
        estimated_seconds=material.estimated_seconds,
        outline=material.outline,
        diagnostics=material.diagnostics,
        error=material.error,
        task=_task_read(task),
        attached_at=link.created_at,
        created_at=material.created_at,
        updated_at=material.updated_at,
    )


def _release_existing_answers_file(
    session: Session, project_id: UUID, material_id: UUID
) -> None:
    """Снимает назначение со старого эталона внутри транзакции обновления нового."""
    existing = answers_link.find_answers_material(session, project_id)
    if existing is None or existing.material_id == material_id:
        return
    purposes = [
        purpose
        for purpose in existing.purposes
        if purpose != MaterialPurpose.REFERENCE_ANSWERS.value
    ]
    existing.purposes = purposes or [MaterialPurpose.STUDY_SOURCE.value]


def _attach(
    session: Session,
    project_id: UUID,
    material: Material,
    *,
    source_role: SourceRole,
    purposes: list[MaterialPurpose],
    duplicate_detail: str,
) -> ProjectMaterial:
    """Связь проекта с уже созданным общим материалом.

    Проектная часть добавления: само создание материала общее и живёт в
    `library`, поэтому загрузка из проекта и из Библиотеки дают один и тот же
    файл, а не два похожих.
    """
    if session.get(ProjectMaterial, (project_id, material.id)) is not None:
        raise ProjectConflictError(duplicate_detail, code="material_already_attached")
    _guard_single_answers_file(session, project_id, purposes, material.id)
    link = ProjectMaterial(
        project_id=project_id,
        material_id=material.id,
        source_role=source_role,
        priority=0,
        affects_program=source_role != SourceRole.REFERENCE,
        purposes=[purpose.value for purpose in dict.fromkeys(purposes)]
        or [MaterialPurpose.STUDY_SOURCE.value],
        created_at=utc_now(),
    )
    session.add(link)
    session.flush()
    return link


async def upload_material(
    session: Session,
    project_id: UUID,
    upload: UploadFile,
    source_role: SourceRole,
    purposes: list[MaterialPurpose],
) -> MaterialRead:
    _project(session, project_id, writable=True)
    session.rollback()
    # Файл пишется и проверяется вне транзакции: держать её на время загрузки нельзя.
    uploaded = await library.store_uploaded_file(upload)
    with session.begin():
        _project(session, project_id, writable=True)
        material = library.register_uploaded_material(session, uploaded)
        link = _attach(
            session,
            project_id,
            material,
            source_role=source_role,
            purposes=purposes,
            duplicate_detail="Этот файл уже добавлен в проект",
        )
        return _read(link, material, _latest_task(session, material.id))


def create_text_material(
    session: Session, project_id: UUID, command: TextMaterialCreate
) -> MaterialRead:
    _project(session, project_id, writable=True)
    session.rollback()
    with session.begin():
        _project(session, project_id, writable=True)
        material = library.create_text_material_row(session, command)
        link = _attach(
            session,
            project_id,
            material,
            source_role=command.source_role,
            purposes=command.purposes,
            duplicate_detail="Этот текст уже добавлен в проект",
        )
        return _read(link, material, _latest_task(session, material.id))


def create_external_material(
    session: Session, project_id: UUID, command: ExternalMaterialCreate
) -> MaterialRead:
    _project(session, project_id, writable=True)
    fetched = library.fetch_external(command)
    session.rollback()
    with session.begin():
        _project(session, project_id, writable=True)
        material = library.create_external_material_row(session, *fetched)
        link = _attach(
            session,
            project_id,
            material,
            source_role=command.source_role,
            purposes=command.purposes,
            duplicate_detail="Этот источник уже добавлен в проект",
        )
        return _read(link, material, _latest_task(session, material.id))


def list_materials(session: Session, project_id: UUID) -> list[MaterialRead]:
    _project(session, project_id, writable=False)
    rows = session.execute(
        select(ProjectMaterial, Material)
        .join(Material, Material.id == ProjectMaterial.material_id)
        .where(ProjectMaterial.project_id == project_id)
        .order_by(ProjectMaterial.priority, ProjectMaterial.created_at)
    ).all()
    material_ids = [material.id for _link, material in rows]
    tasks_by_material = _latest_tasks_by_material(session, material_ids)
    return [_read(link, material, tasks_by_material.get(material.id)) for link, material in rows]


def get_material(session: Session, project_id: UUID, material_id: UUID) -> MaterialRead:
    _project(session, project_id, writable=False)
    link = _link(session, project_id, material_id)
    material = session.get(Material, material_id)
    if material is None:
        raise ProjectNotFoundError("Материал не найден")
    return _read(link, material, _latest_task(session, material.id))


def update_material(
    session: Session, project_id: UUID, material_id: UUID, command: MaterialUpdate
) -> MaterialRead:
    with session.begin():
        _project(session, project_id, writable=True)
        link = _link(session, project_id, material_id)
        material = session.get(Material, material_id)
        if material is None:
            raise ProjectNotFoundError("Материал не найден")
        values = command.model_dump(exclude_unset=True)
        replace_reference_answers = values.pop("replace_reference_answers", False)
        if "purposes" in values:
            if replace_reference_answers:
                _release_existing_answers_file(session, project_id, material_id)
            _guard_single_answers_file(session, project_id, values["purposes"], material_id)
            values["purposes"] = [purpose.value for purpose in values["purposes"]]
        for field, value in values.items():
            setattr(link, field, value)
        if command.source_role is not None:
            link.affects_program = command.source_role != SourceRole.REFERENCE
        session.flush()
        return _read(link, material, _latest_task(session, material.id))


def detach_material(session: Session, project_id: UUID, material_id: UUID) -> None:
    with session.begin():
        _project(session, project_id, writable=True)
        link = _link(session, project_id, material_id)
        delete_project_material_bindings(session, project_id, material_id)
        session.delete(link)


def start_processing(
    session: Session, project_id: UUID, material_id: UUID, command: ProcessingStart
) -> MaterialRead:
    """Проектная обёртка над общим запуском: разбор один на всю установку."""
    with session.begin():
        _project(session, project_id, writable=True)
        link = _link(session, project_id, material_id)
        library.start_processing_core(session, material_id, command)
        material = library.material_or_404(session, material_id)
        return _read(link, material, _latest_task(session, material_id))


def control_task(
    session: Session, project_id: UUID, material_id: UUID, action: str
) -> MaterialRead:
    with session.begin():
        _project(session, project_id, writable=True)
        link = _link(session, project_id, material_id)
        library.control_task_core(session, material_id, action)
        material = library.material_or_404(session, material_id)
        return _read(link, material, _latest_task(session, material_id))


def get_page(
    session: Session,
    project_id: UUID,
    material_id: UUID,
    page_number: int,
    task_id: UUID | None = None,
) -> PageRead:
    _project(session, project_id, writable=False)
    _link(session, project_id, material_id)
    return library.read_library_page(session, material_id, page_number, task_id=task_id)


def page_image_path(
    session: Session, project_id: UUID, material_id: UUID, page_number: int
) -> Path:
    _project(session, project_id, writable=False)
    _link(session, project_id, material_id)
    return library.library_page_image_path(session, material_id, page_number)


def fragment_asset_path(
    session: Session, project_id: UUID, material_id: UUID, fragment_id: UUID
) -> Path:
    _project(session, project_id, writable=False)
    _link(session, project_id, material_id)
    fragment = session.get(MaterialFragment, fragment_id)
    if fragment is None or fragment.material_id != material_id or not fragment.asset_path:
        raise ProjectNotFoundError("У этого фрагмента нет картинки")
    return material_path(fragment.asset_path)


def update_page_text(
    session: Session,
    project_id: UUID,
    material_id: UUID,
    page_number: int,
    command: PageTextUpdate,
) -> PageCorrectionRead:
    """Проектная обёртка: правка текста общая для всех проектов с этим материалом."""
    _project(session, project_id, writable=True)
    _link(session, project_id, material_id)
    session.rollback()
    return library.update_library_page_text(session, material_id, page_number, command)


def _parsed_exam_from_material(
    session: Session, project_id: UUID, material_id: UUID
) -> tuple[ParsedExamProgram, Material, ProjectMaterial]:
    project = _project(session, project_id, writable=False)
    if project.workspace_variant.value != "exam":
        raise ProjectConflictError("Список вопросов относится только к экзаменационному проекту")
    link = _link(session, project_id, material_id)
    if MaterialPurpose.EXAM_STRUCTURE.value not in link.purposes:
        raise ProjectConflictError(
            "Сначала отметьте материал как список вопросов",
            code="material_not_exam_structure",
        )
    material = session.get(Material, material_id)
    if material is None or material.status != MaterialState.READY:
        raise ProjectConflictError("Сначала завершите разбор материала", code="material_not_ready")
    pages = list(
        session.scalars(
            select(MaterialPage)
            .where(
                MaterialPage.material_id == material_id,
                MaterialPage.revision == material.active_parse_revision,
            )
            .order_by(MaterialPage.page_number)
        )
    )
    raw_text = "\n".join(page.text for page in pages if page.text.strip())
    passport = session.get(GoalPassport, project_id)
    exam_format = (
        passport.exam_format if passport and passport.exam_format else ExamFormat.QUESTIONS
    )
    if exam_format == ExamFormat.UNKNOWN:
        exam_format = ExamFormat.QUESTIONS
    try:
        parsed = parse_exam_program(
            raw_text,
            exam_format,
            expected_item_count=passport.expected_item_count if passport else None,
        )
    except ExamImportError as error:
        raise ProjectConflictError(str(error), code="material_exam_parse_failed") from error
    return parsed, material, link


def preview_exam_program(
    session: Session, project_id: UUID, material_id: UUID
) -> ExamProgramPreview:
    parsed, material, link = _parsed_exam_from_material(session, project_id, material_id)
    nodes = []
    depths: list[int] = []
    for item in parsed.nodes:
        depth = depths[item.parent_index] + 1 if item.parent_index is not None else 0
        depths.append(depth)
        nodes.append(
            ExamProgramPreviewNode(
                node_type=item.node_type.value,
                exam_kind=item.exam_kind.value,
                title=item.title,
                depth=depth,
            )
        )
    return ExamProgramPreview(
        material_id=material.id,
        material_name=link.display_name or material.original_name,
        counts={"tickets": parsed.tickets, "questions": parsed.questions, "tasks": parsed.tasks},
        warnings=parsed.warnings,
        nodes=nodes,
    )


def import_exam_program_from_material(
    session: Session,
    project_id: UUID,
    material_id: UUID,
    command: ExamProgramImportWrite,
):
    parsed, material, link = _parsed_exam_from_material(session, project_id, material_id)
    material_name = link.display_name or material.original_name
    session.rollback()
    return program.replace_active_exam_program(
        session,
        project_id,
        expected_program_revision=command.expected_program_revision,
        parsed=parsed,
        material_id=material_id,
        material_name=material_name,
    )


def import_exam_draft_from_material(
    session: Session,
    project_id: UUID,
    material_id: UUID,
    command: ExamProgramDraftImportWrite,
):
    parsed, material, link = _parsed_exam_from_material(session, project_id, material_id)
    material_name = link.display_name or material.original_name
    session.rollback()
    return program.replace_draft_program(
        session,
        project_id,
        expected_draft_revision=command.expected_draft_revision,
        expected_program_revision=command.expected_program_revision,
        parsed=parsed,
        material_id=material_id,
        material_name=material_name,
    )


def import_answers_from_material(
    session: Session, project_id: UUID, material_id: UUID
) -> MaterialAnswerImportResult:
    _project(session, project_id, writable=True)
    link = _link(session, project_id, material_id)
    if MaterialPurpose.REFERENCE_ANSWERS.value not in link.purposes:
        raise ProjectConflictError(
            "Сначала отметьте файл как источник эталонных ответов",
            code="material_not_reference_answers",
        )
    material = session.get(Material, material_id)
    if material is None or material.status != MaterialState.READY:
        raise ProjectConflictError("Сначала завершите разбор файла", code="material_not_ready")
    pages = list(
        session.scalars(
            select(MaterialPage)
            .where(
                MaterialPage.material_id == material_id,
                MaterialPage.revision == material.active_parse_revision,
            )
            .order_by(MaterialPage.page_number)
        )
    )
    raw_text = "\n\n".join(page.text for page in pages if page.text.strip())
    label = f"{link.display_name or material.original_name} · Материал {material.id}"
    session.rollback()
    result = answers.import_reference_answers(
        session,
        project_id,
        ReferenceAnswerImportWrite(raw_text=raw_text, source_label=label),
    )
    with session.begin():
        imported = list(
            session.scalars(
                select(ReferenceAnswer).where(
                    ReferenceAnswer.project_id == project_id,
                    ReferenceAnswer.source_label == label,
                    ReferenceAnswer.source_material_id.is_(None),
                )
            )
        )
        for answer in imported:
            answer.source_material_id = material_id
    return MaterialAnswerImportResult(
        created=result.created,
        skipped_existing=len(result.skipped_existing),
        unmatched_sections=[issue.heading for issue in result.unmatched_sections],
        ambiguous_sections=[issue.heading for issue in result.ambiguous],
        empty_sections=result.empty_sections,
    )
