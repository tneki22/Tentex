import hashlib
import shutil
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

import pymupdf as fitz
from fastapi import UploadFile
from sqlalchemy import delete, desc, func, select
from sqlalchemy.orm import Session

from app.bindings import answers_link
from app.bindings.search import delete_material_index, reindex_material
from app.bindings.service import (
    affected_projects_preview,
    binding_count_for_material,
    delete_project_material_bindings,
    transfer_bindings_on_revision,
)
from app.config import settings
from app.materials.external import fetch_web_page, fetch_youtube_transcript
from app.materials.parsers.base import ParsedElement, ParsedPage
from app.materials.parsers.native import inspect, parse_text_page
from app.materials.schemas import (
    BlockRead,
    ExamProgramImportWrite,
    ExamProgramPreview,
    ExamProgramPreviewNode,
    ExternalMaterialCreate,
    FragmentRead,
    LibraryMaterialRead,
    LibraryUsageRead,
    MaterialAnswerImportResult,
    MaterialCapabilities,
    MaterialDeletePreview,
    MaterialPurpose,
    MaterialRead,
    MaterialUpdate,
    PageCorrectionRead,
    PageRead,
    PageTextUpdate,
    ProcessingStart,
    ProcessingTaskRead,
    TextMaterialCreate,
)
from app.materials.segmentation import build_blocks
from app.materials.storage import material_path, store_text, store_upload
from app.models import (
    BlockClass,
    ExamFormat,
    GoalPassport,
    Material,
    MaterialBlock,
    MaterialFragment,
    MaterialPage,
    MaterialSourceKind,
    MaterialState,
    PageQuality,
    ParserMode,
    ProcessingStage,
    ProcessingTask,
    ProcessingTaskKind,
    ProcessingTaskState,
    Project,
    ProjectMaterial,
    ProjectStatus,
    ReferenceAnswer,
    SourceRole,
    utc_now,
)
from app.projects import answers, program
from app.projects.errors import ProjectConflictError, ProjectDomainError, ProjectNotFoundError
from app.projects.importer import ExamImportError, ParsedExamProgram, parse_exam_program
from app.projects.schemas import ReferenceAnswerImportWrite

ACTIVE_TASK_STATES = {
    ProcessingTaskState.QUEUED,
    ProcessingTaskState.RUNNING,
    ProcessingTaskState.PAUSED,
}
PURPOSE_VALUES = {purpose.value for purpose in MaterialPurpose}


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


def _latest_task(session: Session, material_id: UUID) -> ProcessingTask | None:
    return session.scalar(
        select(ProcessingTask)
        .where(ProcessingTask.material_id == material_id)
        .order_by(desc(ProcessingTask.created_at))
        .limit(1)
    )


def _task_read(task: ProcessingTask | None) -> ProcessingTaskRead | None:
    return ProcessingTaskRead.model_validate(task) if task else None


def _latest_tasks_by_material(
    session: Session, material_ids: list[UUID]
) -> dict[UUID, ProcessingTask]:
    """Одним запросом вместо `_latest_task` на каждый материал (Р7, аудит N+1)."""
    if not material_ids:
        return {}
    latest: dict[UUID, ProcessingTask] = {}
    for task in session.scalars(
        select(ProcessingTask)
        .where(ProcessingTask.material_id.in_(material_ids))
        .order_by(ProcessingTask.material_id, desc(ProcessingTask.created_at))
    ):
        latest.setdefault(task.material_id, task)
    return latest


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
        created_at=material.created_at,
        updated_at=material.updated_at,
    )


def _guard_single_answers_file(
    session: Session, project_id: UUID, purposes: list[MaterialPurpose], material_id: UUID | None
) -> None:
    """Файл эталонных ответов у проекта один.

    На этом держится автозаполнение: эталон вопроса собирается из привязок
    ровно одного источника, иначе непонятно, чей текст побеждает. Учебных
    материалов при этом сколько угодно.
    """
    if MaterialPurpose.REFERENCE_ANSWERS not in purposes:
        return
    existing = answers_link.find_answers_material(session, project_id)
    if existing is None or existing.material_id == material_id:
        return
    material = session.get(Material, existing.material_id)
    name = existing.display_name or (material.original_name if material else "")
    raise ProjectConflictError(
        f"Эталонные ответы уже загружены: «{name}». Сначала снимите это назначение",
        code="reference_answers_already_set",
        context={"material_id": str(existing.material_id), "display_name": name},
    )


def _inspect(path: Path) -> tuple[int, int, int, list[str]]:
    try:
        return inspect(path)
    except PermissionError as error:
        raise ProjectDomainError(str(error), status=422, code="material_encrypted") from error
    except OverflowError as error:
        raise ProjectDomainError(str(error), status=422, code="material_too_many_pages") from error
    except (ValueError, OSError) as error:
        raise ProjectDomainError(str(error), status=422, code="material_corrupt") from error


async def upload_material(
    session: Session,
    project_id: UUID,
    upload: UploadFile,
    source_role: SourceRole,
    purposes: list[MaterialPurpose],
) -> MaterialRead:
    _project(session, project_id, writable=True)
    session.rollback()
    sha256, storage_path, size, original_name, media_type = await store_upload(upload)
    path = material_path(storage_path)
    page_count, scan_pages, estimate, diagnostics = _inspect(path)
    with session.begin():
        _project(session, project_id, writable=True)
        material = session.scalar(select(Material).where(Material.sha256 == sha256))
        if material is None:
            now = utc_now()
            material = Material(
                sha256=sha256,
                original_name=original_name,
                storage_path=storage_path,
                media_type=media_type,
                source_kind=(
                    MaterialSourceKind.AUDIO
                    if Path(original_name).suffix.lower()
                    in {".mp3", ".wav", ".m4a", ".ogg", ".flac"}
                    else MaterialSourceKind.FILE
                ),
                size_bytes=size,
                page_count=page_count,
                status=MaterialState.READY_TO_PROCESS,
                active_parse_revision=0,
                scan_page_count=scan_pages,
                ocr_low_page_count=0,
                estimated_seconds=estimate,
                diagnostics=diagnostics,
                created_at=now,
                updated_at=now,
            )
            session.add(material)
            session.flush()
        if session.get(ProjectMaterial, (project_id, material.id)) is not None:
            raise ProjectConflictError(
                "Этот файл уже добавлен в проект", code="material_already_attached"
            )
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
        return _read(link, material, _latest_task(session, material.id))


def create_text_material(
    session: Session, project_id: UUID, command: TextMaterialCreate
) -> MaterialRead:
    _project(session, project_id, writable=True)
    session.rollback()
    sha256, storage_path, size, original_name, media_type = store_text(command.name, command.text)
    with session.begin():
        _project(session, project_id, writable=True)
        material = session.scalar(select(Material).where(Material.sha256 == sha256))
        if material is None:
            now = utc_now()
            material = Material(
                sha256=sha256,
                original_name=original_name,
                storage_path=storage_path,
                media_type=media_type,
                source_kind=MaterialSourceKind.TEXT,
                size_bytes=size,
                page_count=1,
                status=MaterialState.READY_TO_PROCESS,
                active_parse_revision=0,
                scan_page_count=0,
                ocr_low_page_count=0,
                estimated_seconds=1,
                diagnostics=[],
                created_at=now,
                updated_at=now,
            )
            session.add(material)
            session.flush()
        if session.get(ProjectMaterial, (project_id, material.id)) is not None:
            raise ProjectConflictError(
                "Этот текст уже добавлен в проект", code="material_already_attached"
            )
        _guard_single_answers_file(session, project_id, command.purposes, material.id)
        link = ProjectMaterial(
            project_id=project_id,
            material_id=material.id,
            source_role=command.source_role,
            priority=0,
            affects_program=command.source_role != SourceRole.REFERENCE,
            purposes=[purpose.value for purpose in command.purposes],
            created_at=utc_now(),
        )
        session.add(link)
        session.flush()
        return _read(link, material, _latest_task(session, material.id))


def create_external_material(
    session: Session, project_id: UUID, command: ExternalMaterialCreate
) -> MaterialRead:
    _project(session, project_id, writable=True)
    if command.kind == "youtube":
        name, text, source_url, retrieved_at = fetch_youtube_transcript(command.url)
        source_kind = MaterialSourceKind.YOUTUBE
    else:
        name, text, source_url, retrieved_at = fetch_web_page(command.url)
        source_kind = MaterialSourceKind.URL
    session.rollback()
    sha256, storage_path, size, original_name, media_type = store_text(name, text)
    with session.begin():
        _project(session, project_id, writable=True)
        material = session.scalar(select(Material).where(Material.sha256 == sha256))
        if material is None:
            now = utc_now()
            material = Material(
                sha256=sha256,
                original_name=original_name,
                storage_path=storage_path,
                media_type=media_type,
                source_kind=source_kind,
                source_url=source_url,
                retrieved_at=retrieved_at,
                size_bytes=size,
                page_count=1,
                status=MaterialState.READY_TO_PROCESS,
                active_parse_revision=0,
                scan_page_count=0,
                ocr_low_page_count=0,
                estimated_seconds=1,
                diagnostics=[],
                created_at=now,
                updated_at=now,
            )
            session.add(material)
            session.flush()
        if session.get(ProjectMaterial, (project_id, material.id)) is not None:
            raise ProjectConflictError(
                "Этот источник уже добавлен в проект", code="material_already_attached"
            )
        _guard_single_answers_file(session, project_id, command.purposes, material.id)
        link = ProjectMaterial(
            project_id=project_id,
            material_id=material.id,
            source_role=command.source_role,
            priority=0,
            affects_program=command.source_role != SourceRole.REFERENCE,
            purposes=[purpose.value for purpose in command.purposes],
            created_at=utc_now(),
        )
        session.add(link)
        session.flush()
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
        if "purposes" in values:
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
    with session.begin():
        _project(session, project_id, writable=True)
        link = _link(session, project_id, material_id)
        material = session.get(Material, material_id)
        if material is None:
            raise ProjectNotFoundError("Материал не найден")
        task = _latest_task(session, material_id)
        if task and task.state in ACTIVE_TASK_STATES:
            raise ProjectConflictError("Разбор уже запущен", code="material_processing_active")
        if command.parser_mode == ParserMode.TEXTBOOK:
            raise ProjectConflictError(
                "Режим «Учебник» ещё не проверен на этой GPU",
                code="parser_mode_unavailable",
            )
        revision = material.active_parse_revision + 1
        task = ProcessingTask(
            material_id=material_id,
            kind=ProcessingTaskKind.PARSE,
            state=ProcessingTaskState.QUEUED,
            stage=ProcessingStage.QUEUED,
            parser_mode=command.parser_mode,
            done=0,
            total=material.page_count or 1,
            checkpoint={"revision": revision, "next_page": 1},
            diagnostics=[],
            pause_requested=False,
            created_at=utc_now(),
            updated_at=utc_now(),
        )
        material.status = MaterialState.QUEUED
        material.parser_mode = command.parser_mode
        material.error = None
        session.add(task)
        session.flush()
        return _read(link, material, _latest_task(session, material.id))


def control_task(
    session: Session, project_id: UUID, material_id: UUID, action: str
) -> MaterialRead:
    with session.begin():
        _project(session, project_id, writable=True)
        link = _link(session, project_id, material_id)
        material = session.get(Material, material_id)
        task = _latest_task(session, material_id)
        if material is None or task is None:
            raise ProjectNotFoundError("Задача разбора не найдена")
        if action == "pause" and task.state == ProcessingTaskState.RUNNING:
            task.pause_requested = True
        elif action == "resume" and task.state == ProcessingTaskState.PAUSED:
            task.state = ProcessingTaskState.QUEUED
            task.pause_requested = False
            task.lease_owner = None
            task.lease_expires_at = None
            material.status = MaterialState.QUEUED
        elif action == "retry" and task.state == ProcessingTaskState.FAILED:
            task.state = ProcessingTaskState.QUEUED
            task.error = None
            task.lease_owner = None
            task.lease_expires_at = None
            material.status = MaterialState.QUEUED
            material.error = None
        else:
            raise ProjectConflictError(
                "Действие недоступно в текущем состоянии", code="task_action_invalid"
            )
        task.updated_at = utc_now()
        session.flush()
        return _read(link, material, _latest_task(session, material.id))


def get_page(session: Session, project_id: UUID, material_id: UUID, page_number: int) -> PageRead:
    _project(session, project_id, writable=False)
    _link(session, project_id, material_id)
    material = session.get(Material, material_id)
    if material is None or material.active_parse_revision == 0:
        raise ProjectNotFoundError("Страница ещё не готова")
    page = session.scalar(
        select(MaterialPage).where(
            MaterialPage.material_id == material_id,
            MaterialPage.revision == material.active_parse_revision,
            MaterialPage.page_number == page_number,
        )
    )
    if page is None:
        raise ProjectNotFoundError("Страница не найдена")
    fragments = list(
        session.scalars(
            select(MaterialFragment)
            .where(MaterialFragment.page_id == page.id)
            .order_by(MaterialFragment.sort_order)
        )
    )
    block_ids = {fragment.block_id for fragment in fragments}
    blocks = (
        list(
            session.scalars(
                select(MaterialBlock)
                .where(MaterialBlock.id.in_(block_ids))
                .order_by(MaterialBlock.sort_order)
            )
        )
        if block_ids
        else []
    )
    return PageRead(
        id=page.id,
        page_number=page.page_number,
        width=page.width,
        height=page.height,
        text=page.text,
        markdown=page.markdown,
        quality=page.quality,
        confidence=page.confidence,
        diagnostics=page.diagnostics,
        fragments=[
            FragmentRead.model_validate(fragment).model_copy(
                update={"has_asset": bool(fragment.asset_path)}
            )
            for fragment in fragments
        ],
        blocks=[BlockRead.model_validate(block) for block in blocks],
    )


def page_image_path(
    session: Session, project_id: UUID, material_id: UUID, page_number: int
) -> Path:
    _project(session, project_id, writable=False)
    _link(session, project_id, material_id)
    material = session.get(Material, material_id)
    if material is None:
        raise ProjectNotFoundError("Материал не найден")
    source = material_path(material.storage_path)
    if source.suffix.lower() in {".jpg", ".jpeg", ".png"}:
        return source
    if source.suffix.lower() != ".pdf":
        raise ProjectDomainError(
            "У этого формата нет исходной страницы", status=422, code="page_image_unavailable"
        )
    cache = settings.storage_dir / "pages" / str(material_id) / f"{page_number}.png"
    if not cache.exists():
        cache.parent.mkdir(parents=True, exist_ok=True)
        document = fitz.open(source)
        if page_number < 1 or page_number > len(document):
            raise ProjectNotFoundError("Страница не найдена")
        document[page_number - 1].get_pixmap(matrix=fitz.Matrix(1.5, 1.5), alpha=False).save(cache)
    return cache


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
) -> PageRead:
    with session.begin():
        _project(session, project_id, writable=True)
        _link(session, project_id, material_id)
        material = session.get(Material, material_id)
        if material is None or material.active_parse_revision == 0:
            raise ProjectNotFoundError("Материал ещё не разобран")
        if (
            command.expected_revision is not None
            and material.active_parse_revision != command.expected_revision
        ):
            raise ProjectConflictError(
                "Страница изменилась после предпросмотра",
                code="stale_material_revision",
                context={"current_revision": material.active_parse_revision},
            )
        old_pages = list(
            session.scalars(
                select(MaterialPage)
                .where(
                    MaterialPage.material_id == material_id,
                    MaterialPage.revision == material.active_parse_revision,
                )
                .order_by(MaterialPage.page_number)
            )
        )
        if not any(page.page_number == page_number for page in old_pages):
            raise ProjectNotFoundError("Страница не найдена")
        current_page = next(page for page in old_pages if page.page_number == page_number)
        current_source = current_page.markdown or current_page.text
        current_hash = hashlib.sha256(current_source.encode()).hexdigest()
        if command.expected_source_hash and current_hash != command.expected_source_hash:
            raise ProjectConflictError(
                "Текст страницы изменился после предпросмотра",
                code="stale_material_source",
                context={"current_source_hash": current_hash},
            )
        old_revision = material.active_parse_revision
        old_pages_by_id = {page.id: page for page in old_pages}
        old_fragments_by_page: dict[int, list[MaterialFragment]] = defaultdict(list)
        for fragment in session.scalars(
            select(MaterialFragment)
            .join(MaterialPage, MaterialPage.id == MaterialFragment.page_id)
            .where(
                MaterialFragment.material_id == material_id,
                MaterialPage.revision == old_revision,
            )
            .order_by(MaterialFragment.sort_order)
        ):
            old_fragments_by_page[old_pages_by_id[fragment.page_id].page_number].append(fragment)
        revision = material.active_parse_revision + 1
        parsed_pages: list[ParsedPage] = []
        stored_pages: dict[int, MaterialPage] = {}
        new_fragments_by_page: dict[int, list[MaterialFragment]] = defaultdict(list)
        for old in old_pages:
            if old.page_number == page_number:
                corrected = parse_text_page(command.text, old.page_number)
                # Картинки страницы правкой текста не задеваются: их в текстовом
                # поле нет, и терять их при исправлении опечатки нельзя.
                images = tuple(
                    ParsedElement(
                        item["kind"],
                        item["text"],
                        tuple(item["bbox"]),
                        item.get("level"),
                        item.get("confidence"),
                        item.get("time_from"),
                        item.get("time_to"),
                        item.get("asset_path"),
                    )
                    for item in old.elements
                    if item["kind"] == "image"
                )
                parsed = ParsedPage(
                    corrected.page_number,
                    old.width,
                    old.height,
                    corrected.markdown,
                    corrected.plain_text,
                    old.quality.value,
                    corrected.elements + images,
                    tuple(sorted({*old.diagnostics, "manual_correction"})),
                    None,
                )
            else:
                parsed = ParsedPage(
                    old.page_number,
                    old.width,
                    old.height,
                    old.markdown,
                    old.text,
                    old.quality.value,
                    tuple(
                        ParsedElement(
                            item["kind"],
                            item["text"],
                            tuple(item["bbox"]),
                            item.get("level"),
                            item.get("confidence"),
                            item.get("time_from"),
                            item.get("time_to"),
                            item.get("asset_path"),
                        )
                        for item in old.elements
                    ),
                    tuple(old.diagnostics),
                    old.confidence,
                )
            row = MaterialPage(
                material_id=material_id,
                revision=revision,
                page_number=parsed.page_number,
                width=parsed.width,
                height=parsed.height,
                text=parsed.plain_text,
                markdown=parsed.markdown,
                quality=PageQuality(parsed.quality),
                confidence=parsed.confidence,
                elements=[
                    {
                        "kind": item.kind,
                        "text": item.text,
                        "bbox": list(item.bbox),
                        "level": item.level,
                        "confidence": item.confidence,
                        "time_from": item.time_from,
                        "time_to": item.time_to,
                        "asset_path": item.asset_path,
                    }
                    for item in parsed.elements
                ],
                diagnostics=list(parsed.diagnostics),
                image_path=old.image_path,
                created_at=utc_now(),
            )
            session.add(row)
            session.flush()
            stored_pages[row.page_number] = row
            parsed_pages.append(parsed)

        page_orders: dict[int, int] = {}
        for block_order, spec in enumerate(build_blocks(parsed_pages)):
            page_numbers = [number for number, _ in spec.elements] or [1]
            block = MaterialBlock(
                material_id=material_id,
                revision=revision,
                sort_order=block_order,
                title=spec.title,
                block_class=BlockClass.SERVICE if spec.service_reason else BlockClass.CONTENT,
                service_reason=spec.service_reason,
                page_from=min(page_numbers),
                page_to=max(page_numbers),
            )
            session.add(block)
            session.flush()
            for number, element in spec.elements:
                page = stored_pages[number]
                order = page_orders.get(number, 0)
                new_fragment = MaterialFragment(
                    material_id=material_id,
                    page_id=page.id,
                    block_id=block.id,
                    sort_order=order,
                    text=element.text,
                    bbox=list(element.bbox),
                    element_kind=element.kind,
                    structure_level=element.level,
                    asset_path=element.asset_path,
                    degraded_structure=not any(
                        item.kind == "heading" for item in parsed_pages[number - 1].elements
                    ),
                    quality=page.quality,
                )
                session.add(new_fragment)
                new_fragments_by_page[number].append(new_fragment)
                page_orders[number] = order + 1
        material.active_parse_revision = revision
        material.updated_at = utc_now()
        session.flush()
        transfer = transfer_bindings_on_revision(
            session, material_id, old_fragments_by_page, new_fragments_by_page
        )
        reindex_material(session, material_id)
        page_state = get_page(session, project_id, material_id, page_number)
    return PageCorrectionRead(
        page=page_state,
        transferred_bindings=transfer.transferred,
        orphaned_binding_ids=transfer.orphaned,
    )


@dataclass(frozen=True, slots=True)
class _LibraryAggregate:
    quality_counts: dict[PageQuality, int]
    block_count: int
    fragment_count: int
    usage: list[tuple[ProjectMaterial, Project]]


_EMPTY_LIBRARY_AGGREGATE = _LibraryAggregate(
    quality_counts={}, block_count=0, fragment_count=0, usage=[]
)


def _library_aggregates(
    session: Session, materials: list[Material]
) -> dict[UUID, _LibraryAggregate]:
    """Четыре запроса на всю библиотеку разом вместо четырёх на каждый материал (Р7, аудит N+1)."""
    material_ids = [material.id for material in materials]
    if not material_ids:
        return {}

    quality_counts: dict[UUID, dict[PageQuality, int]] = defaultdict(dict)
    for material_id, quality, count in session.execute(
        select(MaterialPage.material_id, MaterialPage.quality, func.count())
        .join(Material, Material.id == MaterialPage.material_id)
        .where(
            MaterialPage.material_id.in_(material_ids),
            MaterialPage.revision == Material.active_parse_revision,
        )
        .group_by(MaterialPage.material_id, MaterialPage.quality)
    ).all():
        quality_counts[material_id][quality] = count

    block_counts: dict[UUID, int] = dict(
        session.execute(
            select(MaterialBlock.material_id, func.count())
            .join(Material, Material.id == MaterialBlock.material_id)
            .where(
                MaterialBlock.material_id.in_(material_ids),
                MaterialBlock.revision == Material.active_parse_revision,
            )
            .group_by(MaterialBlock.material_id)
        ).all()
    )

    fragment_counts: dict[UUID, int] = dict(
        session.execute(
            select(MaterialFragment.material_id, func.count())
            .join(MaterialPage, MaterialPage.id == MaterialFragment.page_id)
            .join(Material, Material.id == MaterialFragment.material_id)
            .where(
                MaterialFragment.material_id.in_(material_ids),
                MaterialPage.revision == Material.active_parse_revision,
            )
            .group_by(MaterialFragment.material_id)
        ).all()
    )

    usage_by_material: dict[UUID, list[tuple[ProjectMaterial, Project]]] = defaultdict(list)
    for link, project in session.execute(
        select(ProjectMaterial, Project)
        .join(Project, Project.id == ProjectMaterial.project_id)
        .where(ProjectMaterial.material_id.in_(material_ids))
        .order_by(Project.name, Project.created_at)
    ).all():
        usage_by_material[link.material_id].append((link, project))

    return {
        material.id: _LibraryAggregate(
            quality_counts=quality_counts.get(material.id, {}),
            block_count=block_counts.get(material.id, 0),
            fragment_count=fragment_counts.get(material.id, 0),
            usage=usage_by_material.get(material.id, []),
        )
        for material in materials
    }


def _library_read(material: Material, aggregate: _LibraryAggregate) -> LibraryMaterialRead:
    return LibraryMaterialRead(
        id=material.id,
        original_name=material.original_name,
        media_type=material.media_type,
        source_kind=material.source_kind,
        source_url=material.source_url,
        size_bytes=material.size_bytes,
        page_count=material.page_count,
        status=material.status,
        native_page_count=aggregate.quality_counts.get(PageQuality.NATIVE, 0),
        ocr_page_count=aggregate.quality_counts.get(PageQuality.OCR, 0),
        ocr_low_page_count=aggregate.quality_counts.get(PageQuality.OCR_LOW, 0),
        block_count=aggregate.block_count,
        fragment_count=aggregate.fragment_count,
        sha256=material.sha256,
        created_at=material.created_at,
        usage=[
            LibraryUsageRead(
                project_id=project.id,
                project_name=project.name or "Без названия",
                project_status=project.status.value,
                display_name=link.display_name or material.original_name,
                source_role=link.source_role,
                purposes=[
                    MaterialPurpose(value) for value in link.purposes if value in PURPOSE_VALUES
                ],
            )
            for link, project in aggregate.usage
        ],
    )


def list_library_materials(session: Session) -> list[LibraryMaterialRead]:
    materials = list(session.scalars(select(Material).order_by(desc(Material.created_at))))
    aggregates = _library_aggregates(session, materials)
    return [
        _library_read(material, aggregates.get(material.id, _EMPTY_LIBRARY_AGGREGATE))
        for material in materials
    ]


def material_delete_preview(session: Session, material_id: UUID) -> MaterialDeletePreview:
    material = session.get(Material, material_id)
    if material is None:
        raise ProjectNotFoundError("Материал не найден")
    task = _latest_task(session, material_id)
    aggregate = _library_aggregates(session, [material]).get(material.id, _EMPTY_LIBRARY_AGGREGATE)
    return MaterialDeletePreview(
        material=_library_read(material, aggregate),
        active_task=bool(task and task.state in ACTIVE_TASK_STATES),
        reference_answer_count=session.scalar(
            select(func.count())
            .select_from(ReferenceAnswer)
            .where(ReferenceAnswer.source_material_id == material_id)
        )
        or 0,
        binding_count=binding_count_for_material(session, material_id),
        affected_projects=affected_projects_preview(session, material_id),
    )


def delete_library_material(session: Session, material_id: UUID) -> None:
    material = session.get(Material, material_id)
    if material is None:
        raise ProjectNotFoundError("Материал не найден")
    source = material_path(material.storage_path)
    cache = (settings.storage_dir / "pages" / str(material_id)).resolve()
    root = settings.storage_dir.resolve()
    session.rollback()
    with session.begin():
        material = session.get(Material, material_id)
        if material is None:
            raise ProjectNotFoundError("Материал не найден")
        session.execute(delete(ProjectMaterial).where(ProjectMaterial.material_id == material_id))
        delete_material_index(session, material_id)
        session.delete(material)
    source.unlink(missing_ok=True)
    if root in cache.parents and cache.exists():
        shutil.rmtree(cache)


def _parsed_exam_from_material(
    session: Session, project_id: UUID, material_id: UUID
) -> tuple[ParsedExamProgram, Material, ProjectMaterial]:
    project = _project(session, project_id, writable=False, allow_draft=False)
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
        parsed = parse_exam_program(raw_text, exam_format)
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


def capabilities() -> MaterialCapabilities:
    return MaterialCapabilities(
        fast_available=True,
        fast_label="PP-OCRv5 · русский · CPU",
        textbook_available=False,
        textbook_reason="PaddleOCR-VL 1.6 ещё не проверен на RTX 5060 Laptop",
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
