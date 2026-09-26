"""«Описать изображения» готового материала и роль изображений ревизии.

Сценарий в три шага, и ни один не платит раньше времени:

1. **Инвентарь** (`inventory`) — изображения активной ревизии разложены на
   «уйдут по умолчанию», «сомнительные» и «исключённые» с причинами.
2. **Оценка** (`estimate`) — по явному списку и модели: число запросов после
   склейки одинаковых вырезов и верхняя цена.
3. **Запуск** (`start` → `process_job`) — фоновая задача сохраняет ответ по
   каждому изображению в checkpoint, проверяет отмену перед следующим платным
   вызовом и публикует **одну** новую ревизию. Если активная ревизия за это
   время изменилась, публикации нет: конфликт виден, ответы остаются в
   checkpoint, а повтор тех же вырезов с той же подписью берётся из кэша шлюза.

Ручная проза страниц не трогается: меняются только элементы-изображения,
которые человек не исправлял. Привязки переносятся, FTS пересобирается;
векторный индекс устаревает и обновляется отдельно, явно.
"""

from __future__ import annotations

import logging
from collections import Counter
from dataclasses import replace
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.job_budget import JobBudget, budget_state
from app.ai.roles import get_role_spec
from app.ai.schemas import AiModelSelection
from app.ai.settings import resolve_model
from app.bindings.search import reindex_material
from app.bindings.service import transfer_bindings_on_revision
from app.db import job_write_transaction
from app.materials import header_footer, library
from app.materials import revisions as revision_registry
from app.materials.image_candidates import auto_send, classify, repeat_counts, repeat_key
from app.materials.image_meta import element_meta, needs_description
from app.materials.parsers.base import IMAGE_PLACEHOLDER, ImageMeta, ParsedElement
from app.materials.parsers.cloud_vlm import IMAGE_PROMPT_VERSION, IMAGE_ROLE, CloudRecognizer
from app.materials.parsers.native import describe_elements
from app.materials.processing_plan import page_model
from app.materials.schemas import (
    ImageCandidateRead,
    ImageDescriptionEstimateRead,
    ImageDescriptionEstimateWrite,
    ImageDescriptionStart,
    ImageDescriptionStartRead,
    ImageInventoryRead,
)
from app.models import (
    AiModelCatalogEntry,
    AiProviderConnection,
    BackgroundJob,
    BackgroundJobKind,
    BackgroundJobState,
    Material,
    MaterialFragment,
    MaterialPage,
    MaterialRevisionOrigin,
    RetrievalIndex,
    RetrievalIndexState,
    utc_now,
)
from app.ocr import cloud_catalog
from app.projects.errors import ProjectConflictError, ProjectDomainError, ProjectNotFoundError

log = logging.getLogger("tentex.worker")

ACTIVE_STATES = (BackgroundJobState.QUEUED, BackgroundJobState.RUNNING, BackgroundJobState.PAUSED)
# Запас попыток сверх числа запросов: по одному повтору и два сверху.
CALLS_RETRY_FACTOR = 2
CALLS_SLACK = 2
MIN_BUDGET_USD = Decimal("0.01")
# Роли изображения, которые человек видит как исключённые из описания.
EXCLUDED_ROLES = frozenset({"service", "decorative"})


# ── Роль изображений ревизии ────────────────────────────────────────────────


def _revision_pages(session: Session, material_id: UUID, revision: int) -> list[MaterialPage]:
    return list(
        session.scalars(
            select(MaterialPage)
            .where(MaterialPage.material_id == material_id, MaterialPage.revision == revision)
            .order_by(MaterialPage.page_number)
        )
    )


def _header_footer_images(pages: list[MaterialPage]) -> set[tuple[int, int]]:
    """Изображения из найденных серий колонтитулов: (страница, индекс элемента)."""
    result: set[tuple[int, int]] = set()
    for candidate in header_footer.detect(pages):
        for occurrence in candidate.occurrences:
            if occurrence.image_hash is None:
                continue
            result.update((occurrence.page, index) for index in occurrence.indexes)
    return result


def _classified(pages: list[MaterialPage]) -> dict[int, tuple[list[ParsedElement], bool]]:
    """Элементы страниц с ролью изображений по всей ревизии и флаг «страница изменилась».

    Инвентарь зовёт это без сохранения: у страниц, разобранных до явных осей
    (или переписанных с выведенным состоянием), роль иначе осталась бы
    «не ясна», и всё уходило бы в «сомнительные».
    """
    parsed = {page.page_number: [library.element_to_parsed(item) for item in page.elements]
              for page in pages}
    if not any(item.kind == "image" for elements in parsed.values() for item in elements):
        return {number: (elements, False) for number, elements in parsed.items()}
    counts = repeat_counts(parsed.items())
    margins = _header_footer_images(pages) if len(pages) >= 3 else set()
    conditional = all(page.width == 1 and page.height == 1 for page in pages)
    result: dict[int, tuple[list[ParsedElement], bool]] = {}
    for page in pages:
        elements = parsed[page.page_number]
        updated = False
        for index, element in enumerate(elements):
            if element.kind != "image":
                continue
            key = repeat_key(element)
            meta = classify(
                element,
                repeats=counts.get(key, 1) if key else 1,
                header_footer=(page.page_number, index) in margins,
                conditional_geometry=conditional,
            )
            if meta == element.image:
                continue
            text = element.text
            if meta.role in EXCLUDED_ROLES and meta.processing == "described":
                text = IMAGE_PLACEHOLDER
            elements[index] = replace(element, image=meta, text=text)
            updated = True
        result[page.page_number] = (elements, updated)
    return result


def refresh_image_roles(session: Session, material_id: UUID, revision: int) -> int:
    """Пересчитать роль изображений по всей ревизии; вернуть число изменённых страниц.

    Повтор виден только по нескольким страницам сразу, поэтому решение
    уточняется после того, как все страницы ревизии на месте. Изображение,
    ставшее служебным или декоративным, перестаёт индексироваться как знание:
    текст — заглушка, описание остаётся в состоянии для проверки человеком.
    """
    pages = _revision_pages(session, material_id, revision)
    classified = _classified(pages)
    changed = 0
    for page in pages:
        elements, updated = classified[page.page_number]
        if updated:
            page.elements = [library.element_to_json(item) for item in elements]
            changed += 1
    session.flush()
    return changed


def revision_image_summary(session: Session, material_id: UUID, revision: int) -> dict[str, Any]:
    """Сводка изображений ревизии для «Версий»."""
    metas = [
        element_meta(library.element_to_parsed(item)) or ImageMeta()
        for page in _revision_pages(session, material_id, revision)
        for item in page.elements
        if item.get("kind") == "image"
    ]
    if not metas:
        return {}
    return {"images": library.image_counts_of(metas).model_dump()}


# ── Инвентарь и оценка ──────────────────────────────────────────────────────


def _fragment_ids(session: Session, page: MaterialPage) -> list[UUID]:
    """ID фрагментов-изображений страницы в порядке элементов."""
    return list(
        session.scalars(
            select(MaterialFragment.id)
            .where(MaterialFragment.page_id == page.id, MaterialFragment.element_kind == "image")
            .order_by(MaterialFragment.sort_order)
        )
    )


def _candidate(
    page: MaterialPage, index: int, element: ParsedElement, fragment_id: UUID | None
) -> ImageCandidateRead:
    meta = element_meta(element) or ImageMeta()
    return ImageCandidateRead(
        id=f"{page.page_number}:{index}",
        page_number=page.page_number,
        element_index=index,
        fragment_id=fragment_id,
        bbox=list(element.bbox),
        has_asset=bool(element.asset_path),
        role=meta.role,
        processing=meta.processing,
        review=meta.review,
        reasons=list(meta.reasons),
        signals=list(meta.signals),
        caption=meta.caption,
        crop_hash=meta.crop_hash,
        text=element.text[:400],
        selectable=bool(element.asset_path) and needs_description(meta),
    )


def _selection(
    session: Session, provider_id: UUID | None, model_id: str | None
) -> AiModelSelection | None:
    if provider_id and model_id:
        return AiModelSelection(provider_id=provider_id, model_id=model_id)
    return page_model(session)


def _image_prices(
    session: Session, selection: AiModelSelection | None
) -> tuple[Decimal | None, Decimal | None]:
    if selection is None:
        return None, None
    row = session.get(AiModelCatalogEntry, (selection.provider_id, selection.model_id))
    if row is None or row.prompt_price_usd is None or row.completion_price_usd is None:
        return None, None
    if row.prompt_price_usd < 0 or row.completion_price_usd < 0:
        return None, None
    typical = cloud_catalog.price_per_image(row.prompt_price_usd, row.completion_price_usd)
    max_output = int(get_role_spec(IMAGE_ROLE).default_parameters.get("max_output_tokens", 3000))
    upper = (
        row.prompt_price_usd * cloud_catalog.IMAGE_INPUT_TOKENS
        + row.completion_price_usd * max_output
    )
    return typical, upper


def _vector_index_stale(session: Session, material: Material) -> bool:
    """Активный векторный индекс знает прежнюю ревизию материала."""
    index = session.scalar(
        select(RetrievalIndex).where(RetrievalIndex.state == RetrievalIndexState.ACTIVE)
    )
    if index is None:
        return False
    revisions = {str(item["material_id"]): item["revision"] for item in index.corpus_manifest}
    known = revisions.get(str(material.id))
    return known is not None and known != material.active_parse_revision


def _active_job(session: Session, material_id: UUID) -> BackgroundJob | None:
    return session.scalar(
        select(BackgroundJob)
        .where(
            BackgroundJob.material_id == material_id,
            BackgroundJob.kind.in_((BackgroundJobKind.IMAGE_DESCRIPTIONS, BackgroundJobKind.PARSE)),
            BackgroundJob.state.in_(ACTIVE_STATES),
        )
        .limit(1)
    )


def inventory(
    session: Session,
    material_id: UUID,
    provider_id: UUID | None = None,
    model_id: str | None = None,
) -> ImageInventoryRead:
    """Изображения активной ревизии по группам, модель и цена одного описания."""
    material = library.material_or_404(session, material_id)
    if material.active_parse_revision <= 0:
        raise ProjectNotFoundError("Материал ещё не разобран", code="material_not_parsed")
    targets: list[ImageCandidateRead] = []
    doubtful: list[ImageCandidateRead] = []
    excluded: list[ImageCandidateRead] = []
    pages = _revision_pages(session, material_id, material.active_parse_revision)
    classified = _classified(pages)
    for page in pages:
        elements = classified[page.page_number][0]
        if not any(item.kind == "image" for item in elements):
            continue
        fragment_ids = iter(_fragment_ids(session, page))
        for index, element in enumerate(elements):
            if element.kind != "image":
                continue
            candidate = _candidate(page, index, element, next(fragment_ids, None))
            meta = element_meta(element) or ImageMeta()
            if not needs_description(meta):
                excluded.append(candidate.model_copy(update={"selectable": False}))
            elif auto_send(meta) and element.asset_path:
                targets.append(candidate)
            else:
                selectable = bool(element.asset_path)
                doubtful.append(candidate.model_copy(update={"selectable": selectable}))
    selection = _selection(session, provider_id, model_id)
    provider = session.get(AiProviderConnection, selection.provider_id) if selection else None
    typical, upper = _image_prices(session, selection)
    active = _active_job(session, material_id)
    return ImageInventoryRead(
        material_id=material_id,
        revision=material.active_parse_revision,
        targets=targets,
        doubtful=doubtful,
        excluded=excluded,
        model_id=selection.model_id if selection else None,
        provider_id=selection.provider_id if selection else None,
        provider_label=provider.label if provider else "",
        price_known=upper is not None,
        cost_per_image_typical_usd=typical,
        cost_per_image_upper_usd=upper,
        active_job_id=active.id if active else None,
        vector_index_stale=_vector_index_stale(session, material),
    )


def _resolve_targets(
    session: Session, material: Material, target_ids: list[str]
) -> list[dict[str, Any]]:
    """Явный список кандидатов → цели задачи; неизвестный или исключённый — ошибка."""
    wanted = list(dict.fromkeys(target_ids))
    revision_pages = _revision_pages(session, material.id, material.active_parse_revision)
    classified = _classified(revision_pages)
    pages = {page.page_number: page for page in revision_pages}
    result: list[dict[str, Any]] = []
    for target_id in wanted:
        try:
            page_text, index_text = target_id.split(":", 1)
            page = pages[int(page_text)]
            element = classified[page.page_number][0][int(index_text)]
        except (KeyError, ValueError, IndexError) as error:
            raise ProjectDomainError(
                "Изображение не найдено в текущей версии материала",
                status=422,
                code="image_target_invalid",
                context={"target_id": target_id},
            ) from error
        meta = element_meta(element)
        if meta is None or not element.asset_path or not needs_description(meta):
            raise ProjectDomainError(
                "Это изображение нельзя отправить на описание",
                status=422,
                code="image_target_invalid",
                context={"target_id": target_id},
            )
        result.append(
            {
                "id": target_id,
                "page": page.page_number,
                "index": int(index_text),
                "key": repeat_key(element) or target_id,
            }
        )
    return result


def estimate(
    session: Session, material_id: UUID, command: ImageDescriptionEstimateWrite
) -> ImageDescriptionEstimateRead:
    """Сколько запросов уйдёт и верхняя цена по явному списку."""
    material = library.material_or_404(session, material_id)
    targets = _resolve_targets(session, material, command.target_ids)
    unique = len({target["key"] for target in targets})
    selection = _selection(session, command.provider_id, command.model_id)
    typical, upper = _image_prices(session, selection)
    return ImageDescriptionEstimateRead(
        target_count=len(targets),
        requests=unique,
        reused_by_hash=len(targets) - unique,
        model_id=selection.model_id if selection else None,
        price_known=upper is not None,
        cost_typical_usd=typical * unique if typical is not None else None,
        cost_upper_usd=upper * unique if upper is not None else None,
    )


def start(
    session: Session, material_id: UUID, command: ImageDescriptionStart
) -> ImageDescriptionStartRead:
    """Поставить задачу описания. Бюджет, ревизия и модель проверяются здесь."""
    session.rollback()
    with job_write_transaction(session):
        material = library.material_or_404(session, material_id)
        if material.active_parse_revision != command.expected_revision:
            raise ProjectConflictError(
                "Материал изменился после просмотра списка изображений",
                code="stale_material_revision",
                context={"current_revision": material.active_parse_revision},
            )
        if _active_job(session, material_id) is not None:
            raise ProjectConflictError(
                "У материала уже идёт обработка", code="material_processing_active"
            )
        selection = _selection(session, command.provider_id, command.model_id)
        if selection is None:
            raise ProjectConflictError(
                "Модель для описаний не выбрана", code="ai_model_not_configured"
            )
        resolve_model(session, IMAGE_ROLE, selection)
        targets = _resolve_targets(session, material, command.target_ids)
        plan = estimate(session, material_id, command)
        if not plan.price_known and not command.confirm_unknown_price:
            raise ProjectConflictError(
                "Цена модели неизвестна: подтвердите запуск без оценки стоимости",
                code="ai_price_unknown",
                context={"model_id": selection.model_id},
            )
        max_cost = command.max_cost_usd or plan.cost_upper_usd
        job = BackgroundJob(
            material_id=material_id,
            kind=BackgroundJobKind.IMAGE_DESCRIPTIONS,
            state=BackgroundJobState.QUEUED,
            done=0,
            total=len(targets),
            checkpoint={
                "base_revision": material.active_parse_revision,
                "targets": targets,
                "model": selection.model_dump(mode="json"),
                "model_label": selection.model_id,
                "prompt_version": IMAGE_PROMPT_VERSION,
                "results": {},
                "next_index": 0,
                "budget": budget_state(
                    max_cost_usd=max(max_cost, MIN_BUDGET_USD) if max_cost else None,
                    max_calls=plan.requests * CALLS_RETRY_FACTOR + CALLS_SLACK,
                    allow_unknown_price=command.confirm_unknown_price,
                ),
            },
            diagnostics=[],
            pause_requested=False,
            created_at=utc_now(),
            updated_at=utc_now(),
        )
        session.add(job)
        session.flush()
        return ImageDescriptionStartRead(job_id=job.id, requests=plan.requests)


# ── Фоновая задача ──────────────────────────────────────────────────────────


def _finish_job(
    session: Session,
    job_id: UUID,
    state: BackgroundJobState,
    *,
    error: str | None = None,
    result: dict[str, Any] | None = None,
) -> None:
    with job_write_transaction(session, job_id):
        job = session.get(BackgroundJob, job_id)
        if job is None:
            return
        job.state = state
        job.error = error
        if result is not None:
            job.checkpoint = {**job.checkpoint, "result": result}
        job.lease_owner = None
        job.lease_expires_at = None
        job.completed_at = utc_now()
        job.updated_at = utc_now()


def _save_result(
    session: Session, job_id: UUID, position: int, target_id: str, element: ParsedElement
) -> bool:
    """Ответ по изображению — в checkpoint; `False`, если просили отменить."""
    with job_write_transaction(session, job_id):
        job = session.get(BackgroundJob, job_id)
        if job is None:
            return False
        checkpoint = dict(job.checkpoint)
        checkpoint["results"] = {
            **checkpoint.get("results", {}),
            target_id: library.element_to_json(element),
        }
        checkpoint["next_index"] = position + 1
        job.checkpoint = checkpoint
        job.done = min(job.total, position + 1)
        job.heartbeat_at = utc_now()
        job.updated_at = utc_now()
        return not job.pause_requested


def _cancel_requested(session: Session, job_id: UUID) -> bool:
    session.expire_all()
    job = session.get(BackgroundJob, job_id)
    requested = job is None or job.pause_requested
    session.rollback()
    return requested


def process_job(session: Session, job: BackgroundJob) -> None:
    """Описать цели задачи по одной и опубликовать одну ревизию."""
    job_id, material_id = job.id, job.material_id
    checkpoint = dict(job.checkpoint)
    targets: list[dict[str, Any]] = list(checkpoint.get("targets") or [])
    start_at = int(checkpoint.get("next_index") or 0)
    base_revision = int(checkpoint["base_revision"])
    recognizer: CloudRecognizer | None = None
    try:
        assert material_id is not None
        session.rollback()
        pages = {
            page.page_number: [library.element_to_parsed(item) for item in page.elements]
            for page in _revision_pages(session, material_id, base_revision)
        }
        session.rollback()
        recognizer = CloudRecognizer(
            session,
            description_model=AiModelSelection.model_validate(checkpoint["model"]),
            budget=JobBudget(session, job_id),
        )
        for position in range(start_at, len(targets)):
            if _cancel_requested(session, job_id):
                _finish_job(session, job_id, BackgroundJobState.CANCELLED)
                return
            target = targets[position]
            elements = pages[int(target["page"])]
            described, _ = describe_elements(
                elements,
                int(target["page"]),
                recognizer,
                [int(target["index"])],
                source="describe_job",
                job_id=str(job_id),
            )
            if not _save_result(
                session, job_id, position, str(target["id"]), described[int(target["index"])]
            ):
                _finish_job(session, job_id, BackgroundJobState.CANCELLED)
                return
        publish(session, job_id)
    except Exception as error:
        session.rollback()
        log.exception("image descriptions failed job=%s: %s", job_id, error)
        _finish_job(session, job_id, BackgroundJobState.FAILED, error=str(error))
    finally:
        if recognizer is not None:
            recognizer.close()


def publish(session: Session, job_id: UUID) -> None:
    """Одна ревизия из ответов задачи — или ничего, если публиковать нечего."""
    with job_write_transaction(session, job_id):
        job = session.get(BackgroundJob, job_id)
        if job is None or job.material_id is None:
            return
        material = session.get(Material, job.material_id)
        if material is None:
            return
        checkpoint = dict(job.checkpoint)
        base_revision = int(checkpoint["base_revision"])
        results: dict[str, dict[str, Any]] = checkpoint.get("results") or {}
        outcomes = Counter(
            (item.get("image") or {}).get("processing", "unprocessed") for item in results.values()
        )
        summary = {
            "described": outcomes.get("described", 0),
            "errors": outcomes.get("error", 0),
            "needs_review": sum(
                (item.get("image") or {}).get("review") == "needs_review"
                for item in results.values()
            ),
            "targets": len(checkpoint.get("targets") or []),
            "budget": checkpoint.get("budget"),
            "model": (checkpoint.get("model") or {}).get("model_id"),
        }
        if material.active_parse_revision != base_revision:
            # Слепой rebase ответов на чужую ревизию мог бы перезаписать ручную
            # правку. Ответы остаются в checkpoint, новый запуск — по новому списку.
            job.state = BackgroundJobState.FAILED
            job.error = (
                "Материал изменился во время описания: ответы сохранены, "
                "откройте список изображений заново"
            )
            job.checkpoint = {
                **checkpoint,
                "result": summary | {"revision": None, "conflict": material.active_parse_revision},
            }
            job.lease_owner = None
            job.lease_expires_at = None
            job.updated_at = utc_now()
            return
        if not summary["described"]:
            job.state = BackgroundJobState.COMPLETED
            job.checkpoint = {**checkpoint, "result": summary | {"revision": None}}
            job.completed_at = utc_now()
            job.lease_owner = None
            job.lease_expires_at = None
            job.updated_at = utc_now()
            return
        revision = _publish_revision(session, material, base_revision, results, job.id)
        stale = _vector_index_stale(session, material)
        job.state = BackgroundJobState.COMPLETED
        job.checkpoint = {
            **checkpoint,
            "result": summary | {"revision": revision, "vector_index_stale": stale},
        }
        job.completed_at = utc_now()
        job.lease_owner = None
        job.lease_expires_at = None
        job.updated_at = utc_now()


def _replaceable(item: dict[str, Any]) -> bool:
    """Элемент можно заменить ответом: изображение, которое человек не правил."""
    if item.get("kind") != "image" or item.get("recognition_source") == "manual":
        return False
    return (item.get("image") or {}).get("review") != "manual"


def _publish_revision(
    session: Session,
    material: Material,
    base_revision: int,
    results: dict[str, dict[str, Any]],
    job_id: UUID,
) -> int:
    """Скопировать страницы, заменить описанные элементы, собрать структуру и FTS."""
    by_page: dict[int, dict[int, dict[str, Any]]] = {}
    for target_id, item in results.items():
        page_text, index_text = target_id.split(":", 1)
        by_page.setdefault(int(page_text), {})[int(index_text)] = item
    old_fragments = library.fragments_by_page(session, material.id, base_revision)
    revision = revision_registry.max_revision(session, material.id) + 1
    for page in _revision_pages(session, material.id, base_revision):
        copied = library.copy_page(session, page, revision)
        replacements = by_page.get(page.page_number)
        if not replacements:
            continue
        elements = list(copied.elements)
        for index, item in replacements.items():
            if index < len(elements) and _replaceable(elements[index]):
                elements[index] = item
        copied.elements = elements
    session.flush()
    new_fragments = library.rebuild_structure(session, material.id, revision)
    material.active_parse_revision = revision
    material.updated_at = utc_now()
    library.refresh_material_counters(session, material, revision)
    session.flush()
    transfer_bindings_on_revision(session, material.id, old_fragments, new_fragments)
    reindex_material(session, material.id)
    storage_path, source_hash = revision_registry.inherit_source(session, material, base_revision)
    revision_registry.record_revision(
        session,
        material.id,
        revision,
        origin=MaterialRevisionOrigin.IMAGE_DESCRIPTIONS,
        parser_mode=material.parser_mode,
        parent_revision=base_revision,
        task_id=job_id,
        source_storage_path=storage_path,
        source_hash=source_hash,
        scope={"kind": "image_descriptions", "targets": sorted(results)},
        summary=revision_registry.revision_summary(session, material.id, revision)
        | revision_image_summary(session, material.id, revision),
    )
    return revision
