"""Проектонезависимое ядро общего материала: чтение, создание, обработка и версии.

Границу держим здесь: `Material` и его ревизии принадлежат установке, а
`ProjectMaterial` с ролями, назначениями и привязками — конкретному проекту.
Проектные endpoints делегируют сюда после проверки связи, поэтому один и тот же
разбор нельзя получить двумя разными путями.

Привязок в этом модуле нет и быть не должно: он только переносит уже
существующие связи при смене ревизии через общий `transfer_bindings_on_revision`.
"""

import hashlib
import shutil
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

import pymupdf as fitz
from fastapi import UploadFile
from sqlalchemy import delete, desc, func, select
from sqlalchemy.orm import Session

from app.bindings import answers_link
from app.bindings.search import delete_material_index, reindex_material, search_fragments
from app.bindings.service import (
    affected_projects_preview,
    binding_count_for_material,
    transfer_bindings_on_revision,
)
from app.config import settings
from app.materials import revisions as revision_registry
from app.materials.external import fetch_web_page, fetch_youtube_transcript
from app.materials.lexicon import index_text, query_terms
from app.materials.parsers.base import ParsedElement, ParsedPage
from app.materials.parsers.native import inspect, parse_text_page
from app.materials.schemas import (
    BlockRead,
    ExternalMaterialCreate,
    FragmentRead,
    LibraryMaterialAttachWrite,
    LibraryMaterialCapabilities,
    LibraryMaterialDetailRead,
    LibraryMaterialRead,
    LibrarySearchHit,
    LibrarySearchResult,
    LibraryUsageRead,
    MaterialDeletePreview,
    MaterialPresentationKind,
    MaterialPurpose,
    MaterialRevisionRead,
    OutlineItem,
    OutlineSource,
    PageCorrectionRead,
    PageRead,
    PageStateRead,
    PageTextUpdate,
    ProcessingStart,
    ProcessingTaskRead,
    SourceRefreshResult,
    TextMaterialCreate,
)
from app.materials.segmentation import build_blocks
from app.materials.storage import material_path, store_revision_text, store_text, store_upload
from app.models import (
    BlockClass,
    Material,
    MaterialBlock,
    MaterialFragment,
    MaterialPage,
    MaterialRevisionOrigin,
    MaterialSourceKind,
    MaterialState,
    PageQuality,
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
from app.ocr import settings as ocr_settings
from app.projects.errors import ProjectConflictError, ProjectDomainError, ProjectNotFoundError

ACTIVE_TASK_STATES = {
    ProcessingTaskState.QUEUED,
    ProcessingTaskState.RUNNING,
    ProcessingTaskState.PAUSED,
}
PURPOSE_VALUES = {purpose.value for purpose in MaterialPurpose}
AUDIO_SUFFIXES = {".mp3", ".wav", ".m4a", ".ogg", ".flac"}
DOCUMENT_MEDIA_TYPES = {
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/msword",
}
TEXT_MEDIA_TYPES = {"text/plain", "text/markdown", "text/x-markdown"}
# Оглавление из заголовков имеет смысл, пока его можно прочитать глазами.
RECOGNIZED_OUTLINE_LIMIT = 400
SEARCH_LIMIT_MAX = 100


# ── Материал и его вид ──────────────────────────────────────────────────────


def material_or_404(session: Session, material_id: UUID) -> Material:
    material = session.get(Material, material_id)
    if material is None:
        raise ProjectNotFoundError("Материал не найден", code="material_not_found")
    return material


def presentation_kind(material: Material) -> MaterialPresentationKind:
    """Один производный вид вместо проверок MIME по всему фронтенду."""
    if material.source_kind == MaterialSourceKind.YOUTUBE:
        return "youtube"
    if material.source_kind == MaterialSourceKind.AUDIO or material.media_type.startswith("audio/"):
        return "audio"
    if material.source_kind == MaterialSourceKind.URL:
        return "web"
    if material.media_type == "application/pdf":
        return "pdf"
    if material.media_type.startswith("image/"):
        return "image"
    if material.media_type in DOCUMENT_MEDIA_TYPES:
        return "document"
    # Неизвестный формат сюда не доходит: загрузка отклоняет его в storage.
    return "plain_text"


def _capabilities(
    material: Material,
    kind: MaterialPresentationKind,
    *,
    has_outline: bool,
    has_timeline: bool,
) -> LibraryMaterialCapabilities:
    return LibraryMaterialCapabilities(
        can_compare=kind in {"pdf", "image", "document", "plain_text", "web"},
        # У YouTube локального оригинала нет: материал — это сохранённая расшифровка.
        can_view_original=kind != "youtube",
        can_edit_text=material.active_parse_revision >= 1,
        can_run_ocr=kind in {"pdf", "image"},
        can_refresh_source=kind in {"web", "youtube"},
        has_outline=has_outline,
        has_timeline=has_timeline,
    )


def _recognized_outline(session: Session, material: Material) -> list[OutlineItem]:
    if material.active_parse_revision == 0:
        return []
    rows = session.execute(
        select(MaterialFragment.text, MaterialFragment.structure_level, MaterialPage.page_number)
        .join(MaterialPage, MaterialPage.id == MaterialFragment.page_id)
        .where(
            MaterialFragment.material_id == material.id,
            MaterialPage.revision == material.active_parse_revision,
            MaterialFragment.element_kind == "heading",
        )
        .order_by(MaterialPage.page_number, MaterialFragment.sort_order)
        .limit(RECOGNIZED_OUTLINE_LIMIT)
    ).all()
    return [
        OutlineItem(level=max(1, min(4, level or 1)), title=title.strip(), page=page_number)
        for title, level, page_number in rows
        if title.strip()
    ]


def _outline(session: Session, material: Material) -> tuple[list[OutlineItem], OutlineSource]:
    embedded = [
        OutlineItem(
            level=int(item.get("level", 1) or 1),
            title=str(item.get("title", "")).strip(),
            page=int(item.get("page", 1) or 1),
        )
        for item in material.outline or []
        if str(item.get("title", "")).strip()
    ]
    if embedded:
        return embedded, "embedded"
    recognized = _recognized_outline(session, material)
    if recognized:
        return recognized, "recognized"
    return [], "none"


# ── Задачи ──────────────────────────────────────────────────────────────────


def latest_task(session: Session, material_id: UUID) -> ProcessingTask | None:
    return session.scalar(
        select(ProcessingTask)
        .where(ProcessingTask.material_id == material_id)
        .order_by(desc(ProcessingTask.created_at))
        .limit(1)
    )


def task_read(task: ProcessingTask | None) -> ProcessingTaskRead | None:
    return ProcessingTaskRead.model_validate(task) if task else None


def latest_tasks_by_material(
    session: Session, material_ids: list[UUID]
) -> dict[UUID, ProcessingTask]:
    """Одним запросом вместо `latest_task` на каждый материал (Р7, аудит N+1)."""
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


# ── Сводка библиотеки ───────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class LibraryAggregate:
    quality_counts: dict[PageQuality, int]
    block_count: int
    fragment_count: int
    usage: list[tuple[ProjectMaterial, Project]]


EMPTY_LIBRARY_AGGREGATE = LibraryAggregate(
    quality_counts={}, block_count=0, fragment_count=0, usage=[]
)


def library_aggregates(session: Session, materials: list[Material]) -> dict[UUID, LibraryAggregate]:
    """Четыре запроса на всю библиотеку разом вместо четырёх на каждый материал (Р7, аудит N+1)."""
    material_ids = [material.id for material in materials]
    if not material_ids:
        return {}

    quality_counts: dict[UUID, dict[PageQuality, int]] = defaultdict(dict)
    for material_id, quality, reviewed_at, count in session.execute(
        select(
            MaterialPage.material_id,
            MaterialPage.quality,
            MaterialPage.reviewed_at,
            func.count(),
        )
        .join(Material, Material.id == MaterialPage.material_id)
        .where(
            MaterialPage.material_id.in_(material_ids),
            MaterialPage.revision == Material.active_parse_revision,
        )
        .group_by(MaterialPage.material_id, MaterialPage.quality, MaterialPage.reviewed_at)
    ).all():
        display_quality = (
            PageQuality.OCR
            if quality == PageQuality.OCR_LOW and reviewed_at is not None
            else quality
        )
        quality_counts[material_id][display_quality] = (
            quality_counts[material_id].get(display_quality, 0) + count
        )

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
        material.id: LibraryAggregate(
            quality_counts=quality_counts.get(material.id, {}),
            block_count=block_counts.get(material.id, 0),
            fragment_count=fragment_counts.get(material.id, 0),
            usage=usage_by_material.get(material.id, []),
        )
        for material in materials
    }


def _usage_read(material: Material, aggregate: LibraryAggregate) -> list[LibraryUsageRead]:
    return [
        LibraryUsageRead(
            project_id=project.id,
            project_name=project.name or "Без названия",
            project_status=project.status.value,
            display_name=link.display_name or material.original_name,
            source_role=link.source_role,
            purposes=[MaterialPurpose(value) for value in link.purposes if value in PURPOSE_VALUES],
        )
        for link, project in aggregate.usage
    ]


def library_read(material: Material, aggregate: LibraryAggregate) -> LibraryMaterialRead:
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
        parser_mode=material.parser_mode,
        ocr_page_count=aggregate.quality_counts.get(PageQuality.OCR, 0),
        ocr_low_page_count=aggregate.quality_counts.get(PageQuality.OCR_LOW, 0),
        block_count=aggregate.block_count,
        fragment_count=aggregate.fragment_count,
        sha256=material.sha256,
        created_at=material.created_at,
        usage=_usage_read(material, aggregate),
    )


def list_library_materials(session: Session) -> list[LibraryMaterialRead]:
    materials = list(session.scalars(select(Material).order_by(desc(Material.created_at))))
    aggregates = library_aggregates(session, materials)
    return [
        library_read(material, aggregates.get(material.id, EMPTY_LIBRARY_AGGREGATE))
        for material in materials
    ]


def read_library_material(session: Session, material_id: UUID) -> LibraryMaterialDetailRead:
    material = material_or_404(session, material_id)
    aggregate = library_aggregates(session, [material]).get(material.id, EMPTY_LIBRARY_AGGREGATE)
    outline, outline_source = _outline(session, material)
    kind = presentation_kind(material)
    return LibraryMaterialDetailRead(
        **library_read(material, aggregate).model_dump(),
        presentation_kind=kind,
        capabilities=_capabilities(
            material,
            kind,
            has_outline=outline_source != "none",
            has_timeline=kind in {"youtube", "audio"},
        ),
        outline=outline,
        outline_source=outline_source,
        page_states=[
            PageStateRead.model_validate(page)
            for page in session.scalars(
                select(MaterialPage)
                .where(
                    MaterialPage.material_id == material.id,
                    MaterialPage.revision == material.active_parse_revision,
                )
                .order_by(MaterialPage.page_number)
            )
        ],
        active_parse_revision=material.active_parse_revision,
        scan_page_count=material.scan_page_count,
        estimated_seconds=material.estimated_seconds,
        diagnostics=material.diagnostics,
        error=material.error,
        task=task_read(latest_task(session, material_id)),
        retrieved_at=material.retrieved_at,
        updated_at=material.updated_at,
    )


# ── Чтение страниц, исходника и версий ──────────────────────────────────────


def _resolve_revision(
    session: Session,
    material: Material,
    revision: int | None,
    task_id: UUID | None,
) -> int:
    """Какую ревизию читать: активную, зарегистрированную историческую или строящуюся.

    Строящаяся доступна только по id текущей активной задачи — иначе читатель
    увидел бы половину разбора и решил, что материал испорчен.
    """
    if task_id is not None:
        task = session.get(ProcessingTask, task_id)
        current = latest_task(session, material.id)
        if (
            task is None
            or task.material_id != material.id
            or current is None
            or current.id != task.id
            or task.state not in ACTIVE_TASK_STATES
        ):
            raise ProjectNotFoundError(
                "Эта задача разбора уже неактуальна", code="material_task_not_active"
            )
        return int(task.checkpoint.get("revision", material.active_parse_revision))
    if revision is None or revision == material.active_parse_revision:
        if material.active_parse_revision == 0:
            raise ProjectNotFoundError("Материал ещё не разобран", code="material_not_parsed")
        return material.active_parse_revision
    revision_registry.require_revision(session, material.id, revision)
    return revision


def _page_read(session: Session, page: MaterialPage) -> PageRead:
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
        reviewed_at=page.reviewed_at,
        diagnostics=page.diagnostics,
        fragments=[
            FragmentRead.model_validate(fragment).model_copy(
                update={"has_asset": bool(fragment.asset_path)}
            )
            for fragment in fragments
        ],
        blocks=[BlockRead.model_validate(block) for block in blocks],
    )


def read_library_page(
    session: Session,
    material_id: UUID,
    page_number: int,
    *,
    revision: int | None = None,
    task_id: UUID | None = None,
) -> PageRead:
    material = material_or_404(session, material_id)
    target = _resolve_revision(session, material, revision, task_id)
    page = session.scalar(
        select(MaterialPage).where(
            MaterialPage.material_id == material_id,
            MaterialPage.revision == target,
            MaterialPage.page_number == page_number,
        )
    )
    if page is None:
        raise ProjectNotFoundError("Страница не найдена", code="material_page_not_found")
    return _page_read(session, page)


def confirm_library_page_review(
    session: Session, material_id: UUID, page_number: int
) -> LibraryMaterialDetailRead:
    """Подтвердить сверку слабого OCR, не меняя техническое качество страницы."""
    session.rollback()
    with session.begin():
        material = material_or_404(session, material_id)
        if material.active_parse_revision == 0:
            raise ProjectNotFoundError("Материал ещё не разобран", code="material_not_parsed")
        page = session.scalar(
            select(MaterialPage).where(
                MaterialPage.material_id == material.id,
                MaterialPage.revision == material.active_parse_revision,
                MaterialPage.page_number == page_number,
            )
        )
        if page is None:
            raise ProjectNotFoundError("Страница не найдена", code="material_page_not_found")
        if page.quality != PageQuality.OCR_LOW:
            raise ProjectConflictError(
                "Эту страницу подтверждать не требуется",
                code="page_review_not_required",
            )
        if page.reviewed_at is None:
            page.reviewed_at = utc_now()
            material.updated_at = page.reviewed_at
            refresh_material_counters(session, material, material.active_parse_revision)
            registered = revision_registry.get_revision(
                session, material.id, material.active_parse_revision
            )
            if registered is not None:
                registered.summary = revision_registry.revision_summary(
                    session, material.id, material.active_parse_revision
                )
    return read_library_material(session, material_id)


def library_fragment_asset_path(session: Session, material_id: UUID, fragment_id: UUID) -> Path:
    fragment = session.get(MaterialFragment, fragment_id)
    if fragment is None or fragment.material_id != material_id or not fragment.asset_path:
        raise ProjectNotFoundError(
            "У этого фрагмента нет картинки", code="material_asset_not_found"
        )
    return material_path(fragment.asset_path)


def library_page_image_path(session: Session, material_id: UUID, page_number: int) -> Path:
    material = material_or_404(session, material_id)
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
            raise ProjectNotFoundError("Страница не найдена", code="material_page_not_found")
        document[page_number - 1].get_pixmap(matrix=fitz.Matrix(1.5, 1.5), alpha=False).save(cache)
    return cache


@dataclass(frozen=True, slots=True)
class SourceFile:
    path: Path
    media_type: str
    filename: str


def library_source(
    session: Session, material_id: UUID, *, revision: int | None = None
) -> SourceFile:
    """Исходник для просмотра, воспроизведения и скачивания.

    Для веба и YouTube снимок принадлежит своей версии, поэтому исторический
    просмотр отдаёт именно её файл, а не текущий.
    """
    material = material_or_404(session, material_id)
    storage_path, _ = revision_registry.revision_source_path(session, material, revision)
    path = material_path(storage_path)
    if not path.exists():
        raise ProjectNotFoundError("Файл источника не найден", code="material_source_missing")
    return SourceFile(path=path, media_type=material.media_type, filename=material.original_name)


def list_library_revisions(session: Session, material_id: UUID) -> list[MaterialRevisionRead]:
    material = material_or_404(session, material_id)
    return [
        MaterialRevisionRead(
            revision=row.revision,
            origin=row.origin.value,
            parser_mode=row.parser_mode,
            parent_revision=row.parent_revision,
            scope=row.scope,
            summary=row.summary,
            created_at=row.created_at,
            is_current=row.revision == material.active_parse_revision,
        )
        for row in revision_registry.list_revisions(session, material_id)
    ]


def search_library_material(
    session: Session,
    material_id: UUID,
    query: str,
    *,
    revision: int | None = None,
    limit: int = 50,
) -> LibrarySearchResult:
    """Поиск внутри одного материала, без всякого проекта.

    По активной версии работает готовый FTS5/BM25 с русской лемматизацией.
    Историческая версия в индексе не лежит — по ней идёт ограниченный перебор
    её собственных фрагментов: это редкий сценарий чтения, а не рабочий поиск.
    """
    material = material_or_404(session, material_id)
    limit = max(1, min(SEARCH_LIMIT_MAX, limit))
    target = material.active_parse_revision if revision is None else revision
    if not query.strip() or target == 0:
        return LibrarySearchResult(query=query, revision=target, hits=[])
    if target != material.active_parse_revision:
        revision_registry.require_revision(session, material_id, target)
        return LibrarySearchResult(
            query=query,
            revision=target,
            hits=_scan_revision(session, material_id, target, query, limit),
        )

    # BM25 группирует совпадения по блоку; в просмотрщике полезнее список мест,
    # поэтому каждое совпадение раскрывается в свои фрагменты с номерами страниц.
    hits: list[LibrarySearchHit] = []
    for hit in search_fragments(session, [material_id], query, limit=limit):
        for fragment_id in hit.fragment_ids:
            fragment = session.get(MaterialFragment, fragment_id)
            page = session.get(MaterialPage, fragment.page_id) if fragment else None
            if fragment is None or page is None:
                continue
            hits.append(
                LibrarySearchHit(
                    fragment_id=fragment.id,
                    page_number=page.page_number,
                    block_title=hit.block_title,
                    bbox=list(fragment.bbox),
                    text=fragment.text,
                    rank=float(len(hits)),
                )
            )
            if len(hits) >= limit:
                break
        if len(hits) >= limit:
            break
    return LibrarySearchResult(query=query, revision=target, hits=hits)


def _scan_revision(
    session: Session, material_id: UUID, revision: int, query: str, limit: int
) -> list[LibrarySearchHit]:
    terms = set(query_terms(query))
    if not terms:
        return []
    rows = session.execute(
        select(MaterialFragment, MaterialPage.page_number, MaterialBlock.title)
        .join(MaterialPage, MaterialPage.id == MaterialFragment.page_id)
        .join(MaterialBlock, MaterialBlock.id == MaterialFragment.block_id)
        .where(
            MaterialFragment.material_id == material_id,
            MaterialPage.revision == revision,
        )
        .order_by(MaterialPage.page_number, MaterialFragment.sort_order)
    ).all()
    hits: list[LibrarySearchHit] = []
    for fragment, page_number, block_title in rows:
        lemmas = set(index_text(fragment.text).split())
        matched = len(terms & lemmas)
        if not matched:
            continue
        hits.append(
            LibrarySearchHit(
                fragment_id=fragment.id,
                page_number=page_number,
                block_title=block_title,
                bbox=list(fragment.bbox),
                text=fragment.text,
                rank=float(len(terms) - matched),
            )
        )
        if len(hits) >= limit * 4:
            break
    hits.sort(key=lambda item: (item.rank, item.page_number))
    return hits[:limit]


# ── Создание общего материала и подключение к проекту ───────────────────────


def _inspect_file(path: Path) -> tuple[int, int, int, list[str]]:
    try:
        return inspect(path)
    except PermissionError as error:
        raise ProjectDomainError(str(error), status=422, code="material_encrypted") from error
    except OverflowError as error:
        raise ProjectDomainError(str(error), status=422, code="material_too_many_pages") from error
    except (ValueError, OSError) as error:
        raise ProjectDomainError(str(error), status=422, code="material_corrupt") from error


def _existing_or_new(
    session: Session,
    *,
    sha256: str,
    original_name: str,
    storage_path: str,
    media_type: str,
    source_kind: MaterialSourceKind,
    size_bytes: int,
    page_count: int | None,
    scan_page_count: int = 0,
    estimated_seconds: int | None = None,
    diagnostics: list[str] | None = None,
    source_url: str | None = None,
    retrieved_at: Any = None,
) -> Material:
    """Дедупликация по содержимому: один файл в установке хранится один раз."""
    material = session.scalar(select(Material).where(Material.sha256 == sha256))
    if material is not None:
        return material
    now = utc_now()
    material = Material(
        sha256=sha256,
        original_name=original_name,
        storage_path=storage_path,
        media_type=media_type,
        source_kind=source_kind,
        source_url=source_url,
        retrieved_at=retrieved_at,
        size_bytes=size_bytes,
        page_count=page_count,
        status=MaterialState.READY_TO_PROCESS,
        active_parse_revision=0,
        scan_page_count=scan_page_count,
        ocr_low_page_count=0,
        estimated_seconds=estimated_seconds,
        diagnostics=diagnostics or [],
        created_at=now,
        updated_at=now,
    )
    session.add(material)
    session.flush()
    return material


@dataclass(frozen=True, slots=True)
class UploadedFile:
    sha256: str
    storage_path: str
    size_bytes: int
    original_name: str
    media_type: str
    page_count: int
    scan_page_count: int
    estimated_seconds: int
    diagnostics: list[str]


async def store_uploaded_file(upload: UploadFile) -> UploadedFile:
    """Записать файл и осмотреть его. Транзакции здесь нет и быть не должно:
    держать её открытой на время загрузки стомегабайтного PDF нельзя."""
    sha256, storage_path, size, original_name, media_type = await store_upload(upload)
    page_count, scan_pages, estimate, diagnostics = _inspect_file(material_path(storage_path))
    return UploadedFile(
        sha256=sha256,
        storage_path=storage_path,
        size_bytes=size,
        original_name=original_name,
        media_type=media_type,
        page_count=page_count,
        scan_page_count=scan_pages,
        estimated_seconds=estimate,
        diagnostics=diagnostics,
    )


def register_uploaded_material(session: Session, uploaded: UploadedFile) -> Material:
    """Строка материала для уже сохранённого файла. Транзакцией управляет вызывающий."""
    return _existing_or_new(
        session,
        sha256=uploaded.sha256,
        original_name=uploaded.original_name,
        storage_path=uploaded.storage_path,
        media_type=uploaded.media_type,
        source_kind=(
            MaterialSourceKind.AUDIO
            if Path(uploaded.original_name).suffix.lower() in AUDIO_SUFFIXES
            else MaterialSourceKind.FILE
        ),
        size_bytes=uploaded.size_bytes,
        page_count=uploaded.page_count,
        scan_page_count=uploaded.scan_page_count,
        estimated_seconds=uploaded.estimated_seconds,
        diagnostics=uploaded.diagnostics,
    )


async def create_library_upload(session: Session, upload: UploadFile) -> LibraryMaterialDetailRead:
    """Файл в Библиотеку без всякого проекта."""
    uploaded = await store_uploaded_file(upload)
    session.rollback()
    with session.begin():
        material = register_uploaded_material(session, uploaded)
        material_id = material.id
    return read_library_material(session, material_id)


def create_library_text(session: Session, command: TextMaterialCreate) -> LibraryMaterialDetailRead:
    session.rollback()
    with session.begin():
        material_id = create_text_material_row(session, command).id
    return read_library_material(session, material_id)


def create_library_external(
    session: Session, command: ExternalMaterialCreate
) -> LibraryMaterialDetailRead:
    fetched = fetch_external(command)
    session.rollback()
    with session.begin():
        material_id = create_external_material_row(session, *fetched).id
    return read_library_material(session, material_id)


def create_text_material_row(session: Session, command: TextMaterialCreate) -> Material:
    sha256, storage_path, size, original_name, media_type = store_text(command.name, command.text)
    return _existing_or_new(
        session,
        sha256=sha256,
        original_name=original_name,
        storage_path=storage_path,
        media_type=media_type,
        source_kind=MaterialSourceKind.TEXT,
        size_bytes=size,
        page_count=1,
        estimated_seconds=1,
    )


def fetch_external(
    command: ExternalMaterialCreate,
) -> tuple[str, str, str, Any, MaterialSourceKind]:
    """Сеть трогается до открытия транзакции: держать её на время запроса нельзя."""
    if command.kind == "youtube":
        name, text, source_url, retrieved_at = fetch_youtube_transcript(command.url)
        return name, text, source_url, retrieved_at, MaterialSourceKind.YOUTUBE
    name, text, source_url, retrieved_at = fetch_web_page(command.url)
    return name, text, source_url, retrieved_at, MaterialSourceKind.URL


def create_external_material_row(
    session: Session,
    name: str,
    text: str,
    source_url: str,
    retrieved_at: Any,
    source_kind: MaterialSourceKind,
) -> Material:
    sha256, storage_path, size, original_name, media_type = store_text(name, text)
    return _existing_or_new(
        session,
        sha256=sha256,
        original_name=original_name,
        storage_path=storage_path,
        media_type=media_type,
        source_kind=source_kind,
        size_bytes=size,
        page_count=1,
        estimated_seconds=1,
        source_url=source_url,
        retrieved_at=retrieved_at,
    )


def guard_single_answers_file(
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


def attach_material_to_project(
    session: Session, material_id: UUID, command: LibraryMaterialAttachWrite
) -> LibraryMaterialDetailRead:
    """Подключение — это только новая связь. Файл не копируется, разбор не запускается."""
    session.rollback()
    with session.begin():
        material_or_404(session, material_id)
        project = session.get(Project, command.project_id)
        if project is None:
            raise ProjectNotFoundError()
        if project.status not in {ProjectStatus.ACTIVE, ProjectStatus.DRAFT}:
            raise ProjectConflictError(
                "Архивный или завершённый проект нельзя изменять",
                code="project_read_only",
                context={"current_status": project.status.value},
            )
        if session.get(ProjectMaterial, (command.project_id, material_id)) is not None:
            raise ProjectConflictError(
                "Этот материал уже подключён к проекту", code="material_already_attached"
            )
        purposes = list(dict.fromkeys(command.purposes)) or [MaterialPurpose.STUDY_SOURCE]
        guard_single_answers_file(session, command.project_id, purposes, material_id)
        session.add(
            ProjectMaterial(
                project_id=command.project_id,
                material_id=material_id,
                source_role=command.source_role,
                priority=0,
                affects_program=command.source_role != SourceRole.REFERENCE,
                display_name=command.display_name,
                purposes=[purpose.value for purpose in purposes],
                created_at=utc_now(),
            )
        )
        session.flush()
    return read_library_material(session, material_id)


# ── Обработка ───────────────────────────────────────────────────────────────

# Частичный запуск требует безопасной единицы. У страниц PDF и изображений она
# есть; у снимка веба, субтитров и расшифровки — нет, там источник переразбирается
# целиком.
PAGE_SCOPED_KINDS = {"pdf", "image", "document"}


def _selected_pages(session: Session, material: Material, command: ProcessingStart) -> list[int]:
    kind = presentation_kind(material)
    page_count = material.page_count or 1
    if command.scope == "all":
        return list(range(1, page_count + 1))
    if material.active_parse_revision == 0:
        raise ProjectDomainError(
            "Область запуска выбирается после первой подготовки материала",
            status=422,
            code="material_scope_unsupported",
        )
    if command.scope == "needs_review":
        pages = list(
            session.scalars(
                select(MaterialPage.page_number)
                .where(
                    MaterialPage.material_id == material.id,
                    MaterialPage.revision == material.active_parse_revision,
                    MaterialPage.quality == PageQuality.OCR_LOW,
                    MaterialPage.reviewed_at.is_(None),
                )
                .order_by(MaterialPage.page_number)
            )
        )
        if not pages:
            raise ProjectConflictError(
                "Все страницы уже подготовлены без предупреждений",
                code="material_has_no_review_pages",
            )
        return pages
    if kind not in PAGE_SCOPED_KINDS:
        # У снимка веба, субтитров и расшифровки нет безопасной единицы
        # частичного запуска: страница там одна и она же весь источник.
        raise ProjectDomainError(
            "Этот источник разбирается целиком: выберите «Весь документ»",
            status=422,
            code="material_scope_unsupported",
        )
    if command.page_from is None or command.page_to is None:
        raise ProjectDomainError(
            "Укажите первую и последнюю страницу диапазона",
            status=422,
            code="material_range_invalid",
        )
    if command.page_to > page_count:
        raise ProjectDomainError(
            f"В материале {page_count} страниц",
            status=422,
            code="material_range_invalid",
            context={"page_count": page_count},
        )
    return list(range(command.page_from, command.page_to + 1))


def start_processing_core(
    session: Session, material_id: UUID, command: ProcessingStart
) -> ProcessingTask:
    """Поставить задачу разбора. Транзакцией управляет вызывающий."""
    material = material_or_404(session, material_id)
    task = latest_task(session, material_id)
    if task and task.state in ACTIVE_TASK_STATES:
        raise ProjectConflictError("Разбор уже запущен", code="material_processing_active")
    # Готовность движка спрашиваем у реестра распознавания, а не у сервиса
    # напрямую: там же считается статус на экране настроек, и разъехаться они
    # не могут. Для «Быстро» это в том числе проверка, что модели скачаны.
    ready, reason = ocr_settings.engine_ready(session, command.parser_mode.value)
    if not ready:
        raise ProjectConflictError(
            reason or "Этот режим распознавания сейчас недоступен",
            code="parser_mode_unavailable",
            context={"parser_mode": command.parser_mode.value},
        )
    pages = _selected_pages(session, material, command)
    revision = revision_registry.max_revision(session, material_id) + 1
    scope: dict[str, Any] = {"kind": command.scope}
    if command.scope == "range":
        scope |= {"page_from": command.page_from, "page_to": command.page_to}
    if command.scope == "needs_review":
        scope |= {"pages": pages}
    task = ProcessingTask(
        material_id=material_id,
        kind=ProcessingTaskKind.PARSE,
        state=ProcessingTaskState.QUEUED,
        stage=ProcessingStage.QUEUED,
        parser_mode=command.parser_mode,
        done=0,
        total=len(pages),
        checkpoint={
            "revision": revision,
            "source_revision": material.active_parse_revision,
            "selected_pages": pages,
            "next_index": 0,
            "scope": scope,
        },
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
    return task


def control_task_core(session: Session, material_id: UUID, action: str) -> ProcessingTask:
    material = material_or_404(session, material_id)
    task = latest_task(session, material_id)
    if task is None:
        raise ProjectNotFoundError("Задача разбора не найдена", code="material_task_not_found")
    if action == "pause" and task.state == ProcessingTaskState.RUNNING:
        task.pause_requested = True
    elif action == "resume" and task.state == ProcessingTaskState.PAUSED:
        task.state = ProcessingTaskState.QUEUED
        task.pause_requested = False
        task.lease_owner = None
        task.lease_expires_at = None
        material.status = MaterialState.QUEUED
    elif action == "cancel" and task.state in ACTIVE_TASK_STATES:
        # Отмена: разбор был на паузе, в очереди или ещё шёл, и его бросают, а не
        # возобновляют. Задача не создала зарегистрированную версию, поэтому её
        # строящаяся ревизия выбрасывается целиком, а материал возвращается к
        # прежнему готовому состоянию. Активная версия и привязки не страдают.
        building = int(task.checkpoint.get("revision") or 0)
        if building and building != material.active_parse_revision:
            discard_building_revision(session, material_id, building)
        session.delete(task)
        material.status = (
            MaterialState.READY
            if material.active_parse_revision > 0
            else MaterialState.READY_TO_PROCESS
        )
        material.error = None
        session.flush()
        return task
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
    return task


def start_library_processing(
    session: Session, material_id: UUID, command: ProcessingStart
) -> LibraryMaterialDetailRead:
    session.rollback()
    with session.begin():
        start_processing_core(session, material_id, command)
    return read_library_material(session, material_id)


def control_library_task(
    session: Session, material_id: UUID, action: str
) -> LibraryMaterialDetailRead:
    session.rollback()
    with session.begin():
        control_task_core(session, material_id, action)
    return read_library_material(session, material_id)


# ── Сборка ревизии: страницы → блоки → фрагменты ────────────────────────────


def element_to_parsed(item: dict[str, Any]) -> ParsedElement:
    return ParsedElement(
        item["kind"],
        item["text"],
        tuple(item["bbox"]),
        item.get("level"),
        item.get("confidence"),
        item.get("time_from"),
        item.get("time_to"),
        item.get("asset_path"),
        item.get("recognition_source", "native"),
    )


def element_to_json(element: ParsedElement) -> dict[str, Any]:
    return {
        "kind": element.kind,
        "text": element.text,
        "bbox": list(element.bbox),
        "level": element.level,
        "confidence": element.confidence,
        "time_from": element.time_from,
        "time_to": element.time_to,
        "asset_path": element.asset_path,
        "recognition_source": element.recognition_source,
    }


def page_to_parsed(page: MaterialPage) -> ParsedPage:
    return ParsedPage(
        page.page_number,
        page.width,
        page.height,
        page.markdown,
        page.text,
        page.quality.value,
        tuple(element_to_parsed(item) for item in page.elements),
        tuple(page.diagnostics),
        page.confidence,
    )


def copy_page(session: Session, page: MaterialPage, revision: int) -> MaterialPage:
    """Неизменённая страница переезжает в новую ревизию как есть, вместе с картинками."""
    row = MaterialPage(
        material_id=page.material_id,
        revision=revision,
        page_number=page.page_number,
        width=page.width,
        height=page.height,
        text=page.text,
        markdown=page.markdown,
        quality=page.quality,
        confidence=page.confidence,
        elements=list(page.elements),
        diagnostics=list(page.diagnostics),
        image_path=page.image_path,
        reviewed_at=page.reviewed_at,
        created_at=utc_now(),
    )
    session.add(row)
    session.flush()
    return row


def fragments_by_page(
    session: Session, material_id: UUID, revision: int
) -> dict[int, list[MaterialFragment]]:
    result: dict[int, list[MaterialFragment]] = defaultdict(list)
    if revision <= 0:
        return result
    for fragment, page_number in session.execute(
        select(MaterialFragment, MaterialPage.page_number)
        .join(MaterialPage, MaterialPage.id == MaterialFragment.page_id)
        .where(
            MaterialFragment.material_id == material_id,
            MaterialPage.revision == revision,
        )
        .order_by(MaterialFragment.sort_order)
    ).all():
        result[page_number].append(fragment)
    return result


def rebuild_structure(
    session: Session, material_id: UUID, revision: int
) -> dict[int, list[MaterialFragment]]:
    """Собрать блоки и фрагменты для всей ревизии заново.

    Вызывается один раз после того, как все страницы ревизии на месте: блоки
    режутся по заголовкам и могут пересекать границы страниц, поэтому частями
    их собирать нельзя.
    """
    pages = list(
        session.scalars(
            select(MaterialPage)
            .where(
                MaterialPage.material_id == material_id,
                MaterialPage.revision == revision,
            )
            .order_by(MaterialPage.page_number)
        )
    )
    # Повторный вызов после сбоя не должен удваивать структуру этой же ревизии.
    session.execute(
        delete(MaterialFragment).where(
            MaterialFragment.id.in_(
                select(MaterialFragment.id)
                .join(MaterialPage, MaterialPage.id == MaterialFragment.page_id)
                .where(
                    MaterialFragment.material_id == material_id,
                    MaterialPage.revision == revision,
                )
            )
        )
    )
    session.execute(
        delete(MaterialBlock).where(
            MaterialBlock.material_id == material_id,
            MaterialBlock.revision == revision,
        )
    )
    parsed_pages = [page_to_parsed(page) for page in pages]
    page_by_number = {page.page_number: page for page in pages}
    has_heading = {
        page.page_number: any(item.get("kind") == "heading" for item in page.elements)
        for page in pages
    }
    new_fragments: dict[int, list[MaterialFragment]] = defaultdict(list)
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
        for page_number, element in spec.elements:
            page = page_by_number[page_number]
            order = page_orders.get(page_number, 0)
            fragment = MaterialFragment(
                material_id=material_id,
                page_id=page.id,
                block_id=block.id,
                sort_order=order,
                text=element.text,
                bbox=list(element.bbox),
                element_kind=element.kind,
                structure_level=element.level,
                asset_path=element.asset_path,
                recognition_source=element.recognition_source,
                confidence=element.confidence,
                time_from=element.time_from,
                time_to=element.time_to,
                degraded_structure=not has_heading.get(page_number, False),
                quality=page.quality,
            )
            session.add(fragment)
            new_fragments[page_number].append(fragment)
            page_orders[page_number] = order + 1
    session.flush()
    return new_fragments


def discard_building_revision(session: Session, material_id: UUID, revision: int) -> None:
    """Стереть страницы, блоки и фрагменты недоактивированной строящейся ревизии.

    Зовётся только при отмене разбора: эта ревизия ещё не стала активной и не
    попала в реестр версий, поэтому её содержимое — не история, а мусор. Активную
    ревизию и её привязки функция не трогает: удаляет строго по номеру ревизии.
    """
    if revision <= 0:
        return
    session.execute(
        delete(MaterialFragment).where(
            MaterialFragment.id.in_(
                select(MaterialFragment.id)
                .join(MaterialPage, MaterialPage.id == MaterialFragment.page_id)
                .where(
                    MaterialFragment.material_id == material_id,
                    MaterialPage.revision == revision,
                )
            )
        )
    )
    session.execute(
        delete(MaterialBlock).where(
            MaterialBlock.material_id == material_id,
            MaterialBlock.revision == revision,
        )
    )
    session.execute(
        delete(MaterialPage).where(
            MaterialPage.material_id == material_id,
            MaterialPage.revision == revision,
        )
    )


def rebuild_checkpoint_page(session: Session, page: MaterialPage) -> None:
    """Expose one committed page of a building revision to its task viewer.

    Final blocks are still rebuilt across the whole revision by
    ``rebuild_structure``. This temporary one-page block exists only so a page
    becomes readable immediately after its checkpoint.
    """
    session.execute(delete(MaterialFragment).where(MaterialFragment.page_id == page.id))
    block = session.scalar(
        select(MaterialBlock).where(
            MaterialBlock.material_id == page.material_id,
            MaterialBlock.revision == page.revision,
            MaterialBlock.sort_order == page.page_number - 1,
        )
    )
    elements = [element_to_parsed(item) for item in page.elements]
    if block is None:
        heading = next((item.text for item in elements if item.kind == "heading"), None)
        block = MaterialBlock(
            material_id=page.material_id,
            revision=page.revision,
            sort_order=page.page_number - 1,
            title=heading,
            block_class=BlockClass.CONTENT,
            service_reason=None,
            page_from=page.page_number,
            page_to=page.page_number,
        )
        session.add(block)
        session.flush()
    degraded = not any(item.kind == "heading" for item in elements)
    for order, element in enumerate(elements):
        session.add(
            MaterialFragment(
                material_id=page.material_id,
                page_id=page.id,
                block_id=block.id,
                sort_order=order,
                text=element.text,
                bbox=list(element.bbox),
                element_kind=element.kind,
                structure_level=element.level,
                degraded_structure=degraded,
                quality=page.quality,
                recognition_source=element.recognition_source,
                confidence=element.confidence,
                asset_path=element.asset_path,
                time_from=element.time_from,
                time_to=element.time_to,
            )
        )


def activation_summary(session: Session, material_id: UUID, revision: int) -> dict[str, Any]:
    return revision_registry.revision_summary(session, material_id, revision)


def refresh_material_counters(session: Session, material: Material, revision: int) -> None:
    pages = list(
        session.scalars(
            select(MaterialPage).where(
                MaterialPage.material_id == material.id,
                MaterialPage.revision == revision,
            )
        )
    )
    material.ocr_low_page_count = sum(
        page.quality == PageQuality.OCR_LOW and page.reviewed_at is None for page in pages
    )
    material.diagnostics = sorted({item for page in pages for item in page.diagnostics})
    material.error = None


# ── Ручная правка страницы (общая для всех проектов) ────────────────────────


def update_page_text_core(
    session: Session, material_id: UUID, page_number: int, command: PageTextUpdate
) -> tuple[PageCorrectionRead, int]:
    """Правка текста страницы новой ревизией. Транзакцией управляет вызывающий.

    Возвращает результат и номер прежней активной ревизии — вызывающий по нему
    регистрирует запись в реестре версий.
    """
    material = material_or_404(session, material_id)
    if material.active_parse_revision == 0:
        raise ProjectNotFoundError("Материал ещё не разобран", code="material_not_parsed")
    if (
        command.expected_revision is not None
        and material.active_parse_revision != command.expected_revision
    ):
        raise ProjectConflictError(
            "Страница изменилась после предпросмотра",
            code="stale_material_revision",
            context={"current_revision": material.active_parse_revision},
        )
    old_revision = material.active_parse_revision
    old_pages = list(
        session.scalars(
            select(MaterialPage)
            .where(
                MaterialPage.material_id == material_id,
                MaterialPage.revision == old_revision,
            )
            .order_by(MaterialPage.page_number)
        )
    )
    current_page = next((page for page in old_pages if page.page_number == page_number), None)
    if current_page is None:
        raise ProjectNotFoundError("Страница не найдена", code="material_page_not_found")
    current_source = current_page.markdown or current_page.text
    current_hash = hashlib.sha256(current_source.encode()).hexdigest()
    if command.expected_source_hash and current_hash != command.expected_source_hash:
        raise ProjectConflictError(
            "Текст страницы изменился после предпросмотра",
            code="stale_material_source",
            context={"current_source_hash": current_hash},
        )

    old_fragments = fragments_by_page(session, material_id, old_revision)
    revision = revision_registry.max_revision(session, material_id) + 1
    for old in old_pages:
        if old.page_number != page_number:
            copy_page(session, old, revision)
            continue
        corrected = parse_text_page(command.text, old.page_number, "manual")
        # Исходные вырезы правкой текста не задеваются: их в текстовом поле нет,
        # и терять изображение, формулу или таблицу при исправлении опечатки нельзя.
        source_assets = tuple(
            element_to_parsed(item) for item in old.elements if item.get("asset_path")
        )
        session.add(
            MaterialPage(
                material_id=material_id,
                revision=revision,
                page_number=old.page_number,
                width=old.width,
                height=old.height,
                text=corrected.plain_text,
                markdown=corrected.markdown,
                quality=old.quality,
                confidence=None,
                elements=[
                    element_to_json(element) for element in (*corrected.elements, *source_assets)
                ],
                diagnostics=sorted({*old.diagnostics, "manual_correction"}),
                image_path=old.image_path,
                created_at=utc_now(),
            )
        )
    session.flush()
    new_fragments = rebuild_structure(session, material_id, revision)
    material.active_parse_revision = revision
    material.updated_at = utc_now()
    refresh_material_counters(session, material, revision)
    session.flush()
    transfer = transfer_bindings_on_revision(session, material_id, old_fragments, new_fragments)
    reindex_material(session, material_id)
    page_state = read_library_page(session, material_id, page_number)
    return (
        PageCorrectionRead(
            page=page_state,
            transferred_bindings=transfer.transferred,
            orphaned_binding_ids=transfer.orphaned,
        ),
        old_revision,
    )


def update_library_page_text(
    session: Session,
    material_id: UUID,
    page_number: int,
    command: PageTextUpdate,
    *,
    origin: MaterialRevisionOrigin = MaterialRevisionOrigin.MANUAL_EDIT,
    summary_extra: dict[str, Any] | None = None,
) -> PageCorrectionRead:
    session.rollback()
    with session.begin():
        result, old_revision = update_page_text_core(session, material_id, page_number, command)
        material = material_or_404(session, material_id)
        storage_path, source_hash = revision_registry.inherit_source(
            session, material, old_revision
        )
        revision_registry.record_revision(
            session,
            material_id,
            material.active_parse_revision,
            origin=origin,
            parser_mode=material.parser_mode,
            parent_revision=old_revision,
            source_storage_path=storage_path,
            source_hash=source_hash,
            scope={"kind": "page", "page": page_number},
            summary=activation_summary(session, material_id, material.active_parse_revision)
            | (summary_extra or {}),
        )
    return result


# ── Восстановление версии и обновление внешнего источника ───────────────────


def restore_revision(
    session: Session, material_id: UUID, revision: int
) -> LibraryMaterialDetailRead:
    """«Восстановить как новую»: указатель не отматывается, история не теряется."""
    session.rollback()
    with session.begin():
        material = material_or_404(session, material_id)
        revision_registry.require_revision(session, material_id, revision)
        if revision == material.active_parse_revision:
            raise ProjectConflictError(
                "Эта версия уже текущая", code="material_revision_is_current"
            )
        source_pages = list(
            session.scalars(
                select(MaterialPage)
                .where(
                    MaterialPage.material_id == material_id,
                    MaterialPage.revision == revision,
                )
                .order_by(MaterialPage.page_number)
            )
        )
        if not source_pages:
            raise ProjectConflictError(
                "У этой версии не осталось страниц", code="material_revision_empty"
            )
        old_revision = material.active_parse_revision
        old_fragments = fragments_by_page(session, material_id, old_revision)
        target = revision_registry.max_revision(session, material_id) + 1
        for page in source_pages:
            copy_page(session, page, target)
        session.flush()
        new_fragments = rebuild_structure(session, material_id, target)
        material.active_parse_revision = target
        material.updated_at = utc_now()
        refresh_material_counters(session, material, target)
        session.flush()
        transfer_bindings_on_revision(session, material_id, old_fragments, new_fragments)
        reindex_material(session, material_id)
        storage_path, source_hash = revision_registry.revision_source_path(
            session, material, revision
        )
        revision_registry.record_revision(
            session,
            material_id,
            target,
            origin=MaterialRevisionOrigin.RESTORE,
            parser_mode=material.parser_mode,
            parent_revision=revision,
            source_storage_path=storage_path,
            source_hash=source_hash,
            scope={"kind": "restore", "restored_from": revision},
            summary=activation_summary(session, material_id, target),
        )
    return read_library_material(session, material_id)


def refresh_source(session: Session, material_id: UUID) -> SourceRefreshResult:
    """Заново получить веб-снимок или субтитры. Прежний снимок остаётся на месте."""
    material = material_or_404(session, material_id)
    kind = presentation_kind(material)
    if kind not in {"web", "youtube"} or not material.source_url:
        raise ProjectDomainError(
            "Обновлять можно только сохранённую веб-страницу и субтитры",
            status=422,
            code="material_refresh_unsupported",
        )
    session.rollback()
    command = ExternalMaterialCreate(
        kind="youtube" if kind == "youtube" else "url", url=material.source_url
    )
    name, text, source_url, retrieved_at, _ = fetch_external(command)
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    changed = digest != material.sha256

    with session.begin():
        material = material_or_404(session, material_id)
        if digest == material.sha256:
            material.retrieved_at = retrieved_at
            material.updated_at = utc_now()
            session.flush()
        else:
            duplicate = session.scalar(
                select(Material).where(Material.sha256 == digest, Material.id != material_id)
            )
            if duplicate is not None:
                raise ProjectConflictError(
                    "Такой снимок уже сохранён другим материалом Библиотеки",
                    code="material_refresh_duplicate",
                    context={"material_id": str(duplicate.id)},
                )
            old_revision = material.active_parse_revision
            old_fragments = fragments_by_page(session, material_id, old_revision)
            target = revision_registry.max_revision(session, material_id) + 1
            # Снимок принадлежит своей версии: старый файл не перезаписывается,
            # поэтому историческая версия читается и после обновления.
            storage_path, size = store_revision_text(material_id, target, name, text)
            parsed = parse_text_page(text, 1)
            session.add(
                MaterialPage(
                    material_id=material_id,
                    revision=target,
                    page_number=1,
                    width=595,
                    height=842,
                    text=parsed.plain_text,
                    markdown=parsed.markdown,
                    quality=PageQuality.NATIVE,
                    confidence=None,
                    elements=[element_to_json(element) for element in parsed.elements],
                    diagnostics=["source_refreshed"],
                    created_at=utc_now(),
                )
            )
            session.flush()
            new_fragments = rebuild_structure(session, material_id, target)
            material.storage_path = storage_path
            material.sha256 = digest
            material.size_bytes = size
            material.source_url = source_url
            material.retrieved_at = retrieved_at
            material.original_name = name
            material.page_count = 1
            material.status = MaterialState.READY
            material.active_parse_revision = target
            material.updated_at = utc_now()
            refresh_material_counters(session, material, target)
            session.flush()
            transfer_bindings_on_revision(session, material_id, old_fragments, new_fragments)
            reindex_material(session, material_id)
            revision_registry.record_revision(
                session,
                material_id,
                target,
                origin=MaterialRevisionOrigin.SOURCE_REFRESH,
                parser_mode=material.parser_mode,
                parent_revision=old_revision or None,
                source_storage_path=storage_path,
                source_hash=digest,
                scope={"kind": "source_refresh"},
                summary=activation_summary(session, material_id, target),
            )
    detail = read_library_material(session, material_id)
    return SourceRefreshResult(
        material=detail, revision=detail.active_parse_revision, changed=changed
    )


# ── Удаление ────────────────────────────────────────────────────────────────


def material_delete_preview(session: Session, material_id: UUID) -> MaterialDeletePreview:
    material = material_or_404(session, material_id)
    task = latest_task(session, material_id)
    aggregate = library_aggregates(session, [material]).get(material.id, EMPTY_LIBRARY_AGGREGATE)
    return MaterialDeletePreview(
        material=library_read(material, aggregate),
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
    material = material_or_404(session, material_id)
    source = material_path(material.storage_path)
    cache = (settings.storage_dir / "pages" / str(material_id)).resolve()
    snapshots = (settings.storage_dir / "snapshots" / str(material_id)).resolve()
    root = settings.storage_dir.resolve()
    session.rollback()
    with session.begin():
        material = material_or_404(session, material_id)
        session.execute(delete(ProjectMaterial).where(ProjectMaterial.material_id == material_id))
        delete_material_index(session, material_id)
        session.delete(material)
    source.unlink(missing_ok=True)
    for directory in (cache, snapshots):
        if root in directory.parents and directory.exists():
            shutil.rmtree(directory)
