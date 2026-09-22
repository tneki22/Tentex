from __future__ import annotations

import asyncio
import logging
from uuid import UUID, uuid4

from sqlalchemy import delete, func, insert, select
from sqlalchemy.orm import Session

from app.models import (
    BackgroundJob,
    BackgroundJobKind,
    BackgroundJobState,
    EmbeddingBackendKind,
    EmbeddingProfile,
    Material,
    MaterialState,
    RetrievalChunk,
    RetrievalIndex,
    RetrievalIndexState,
    RetrievalSettings,
    utc_now,
)
from app.projects.errors import ProjectConflictError, ProjectNotFoundError
from app.retrieval.chunking import ChunkDraft, material_chunks
from app.retrieval.embeddings import backend_for_profile
from app.retrieval.jobs import finish, write_job
from app.retrieval.schemas import RetrievalIndexBuildRead, RetrievalIndexBuildWrite
from app.retrieval.vector import vector_blob

QWEN_CPU_MAX_BATCH_SIZE = 4
EXTERNAL_MAX_BATCH_SIZE = 4
log = logging.getLogger("tentex.retrieval")


def embedding_batch_size(profile: EmbeddingProfile) -> int:
    """Вернуть размер запроса, который локальная модель успевает обработать.

    Qwen3 0.6B на CPU не успевает обработать 32 куска по 384–480 токенов за
    HTTP-таймаут model service. Четыре куска сохраняют предсказуемое время
    одного запроса, а весь индекс продолжает строиться checkpoint-пакетами.
    """
    if profile.backend_kind == EmbeddingBackendKind.OPENAI_COMPATIBLE:
        # LM Studio исполняет элементы одного OpenAI batch как внутреннюю очередь.
        # Пакет 32 давал `+27 queued`, после чего сервер рвал следующее соединение.
        return min(profile.batch_size, EXTERNAL_MAX_BATCH_SIZE)
    if (
        profile.backend_kind == EmbeddingBackendKind.LOCAL_HF
        and profile.model_id == "Qwen/Qwen3-Embedding-0.6B"
    ):
        return min(profile.batch_size, QWEN_CPU_MAX_BATCH_SIZE)
    return profile.batch_size


def _settings(session: Session) -> RetrievalSettings:
    row = session.get(RetrievalSettings, 1)
    if row is None:
        row = RetrievalSettings(id=1)
        session.add(row)
        session.flush()
    return row


def start_index_build(
    session: Session, command: RetrievalIndexBuildWrite
) -> RetrievalIndexBuildRead:
    """Зафиксировать корпус и поставить сборку кандидата в общую очередь."""
    with session.begin():
        profile = session.get(EmbeddingProfile, command.profile_id)
        if profile is None:
            raise ProjectNotFoundError("Embedding-профиль не найден")
        materials_query = select(Material).where(
            Material.status == MaterialState.READY,
            Material.active_parse_revision > 0,
        )
        if command.material_ids:
            materials_query = materials_query.where(Material.id.in_(command.material_ids))
        materials = list(session.scalars(materials_query.order_by(Material.created_at)))
        if not materials:
            raise ProjectConflictError(
                "Нет готовых материалов для индексации", code="retrieval_empty_corpus"
            )
        manifest = [
            {
                "material_id": str(material.id),
                "name": material.display_name,
                "revision": material.active_parse_revision,
                "size_bytes": material.size_bytes,
                "source_kind": material.source_kind.value,
            }
            for material in materials
        ]
        if (
            profile.backend_kind == EmbeddingBackendKind.OPENAI_COMPATIBLE
            and not command.cloud_consent
        ):
            raise ProjectConflictError(
                "Для отправки текста внешнему embedding-провайдеру нужно подтверждение",
                code="retrieval_cloud_consent_required",
                context={
                    "materials": manifest,
                    "material_count": len(manifest),
                    "size_bytes": sum(int(item["size_bytes"] or 0) for item in manifest),
                    "estimated_cost_usd": None,
                    "includes_typst_sources": any(
                        item["source_kind"] == "typst" for item in manifest
                    ),
                },
            )
        index = RetrievalIndex(
            id=uuid4(),
            profile_id=profile.id,
            state=RetrievalIndexState.BUILDING,
            preset=command.preset,
            chunk_target_tokens=command.chunk_target_tokens,
            chunk_max_tokens=command.chunk_max_tokens,
            chunk_overlap_tokens=command.chunk_overlap_tokens,
            material_count=len(materials),
            corpus_manifest=manifest,
        )
        job = BackgroundJob(
            id=uuid4(),
            kind=BackgroundJobKind.RETRIEVAL_INDEX,
            state=BackgroundJobState.QUEUED,
            total=len(materials),
            checkpoint={"index_id": str(index.id), "profile_id": str(profile.id)},
        )
        session.add_all([index, job])
    return RetrievalIndexBuildRead.model_validate(
        {"index": index, "job_id": job.id}, from_attributes=True
    )


def activate_index(session: Session, index_id: UUID) -> RetrievalIndex:
    """Атомарно переключить чтение; старый индекс остаётся доступным до очистки."""
    with session.begin():
        candidate = session.get(RetrievalIndex, index_id)
        if candidate is None:
            raise ProjectNotFoundError("Retrieval-индекс не найден")
        if candidate.state not in {RetrievalIndexState.READY, RetrievalIndexState.ACTIVE}:
            raise ProjectConflictError(
                "Активировать можно только успешно собранный индекс",
                code="retrieval_index_not_ready",
            )
        row = _settings(session)
        if row.active_index_id and row.active_index_id != candidate.id:
            previous = session.get(RetrievalIndex, row.active_index_id)
            if previous is not None:
                previous.state = RetrievalIndexState.READY
                previous.activated_at = None
        candidate.state = RetrievalIndexState.ACTIVE
        candidate.activated_at = utc_now()
        row.active_index_id = candidate.id
        row.default_profile_id = candidate.profile_id
    return candidate


def delete_inactive_index(session: Session, index_id: UUID) -> None:
    with session.begin():
        row = _settings(session)
        if row.active_index_id == index_id:
            raise ProjectConflictError(
                "Активный индекс нельзя удалить", code="retrieval_active_index_delete"
            )
        index = session.get(RetrievalIndex, index_id)
        if index is None:
            raise ProjectNotFoundError("Retrieval-индекс не найден")
        session.delete(index)


def queue_incremental_reindex(session: Session, material_id: UUID) -> None:
    """После публикации ревизии локально обновить только её часть активного индекса."""
    row = session.get(RetrievalSettings, 1)
    active = (
        session.get(RetrievalIndex, row.active_index_id) if row and row.active_index_id else None
    )
    if active is None:
        return
    profile = session.get(EmbeddingProfile, active.profile_id)
    if profile is None or profile.backend_kind != EmbeddingBackendKind.LOCAL_HF:
        return
    material = session.get(Material, material_id)
    if (
        material is None
        or material.status != MaterialState.READY
        or material.active_parse_revision <= 0
    ):
        return
    pending = session.scalar(
        select(BackgroundJob.id).where(
            BackgroundJob.kind == BackgroundJobKind.RETRIEVAL_INDEX,
            BackgroundJob.material_id == material_id,
            BackgroundJob.state.in_([BackgroundJobState.QUEUED, BackgroundJobState.RUNNING]),
        )
    )
    if pending is not None:
        return
    session.add(
        BackgroundJob(
            id=uuid4(),
            material_id=material_id,
            kind=BackgroundJobKind.RETRIEVAL_INDEX,
            state=BackgroundJobState.QUEUED,
            total=1,
            checkpoint={
                "index_id": str(active.id),
                "mode": "incremental",
                "material_id": str(material_id),
            },
        )
    )


def queue_material_reindex(session: Session, material_id: UUID) -> UUID:
    """Добавить готовый материал в активный локальный индекс без полной пересборки."""
    with session.begin():
        row = _settings(session)
        if row.active_index_id is None:
            raise ProjectConflictError(
                "Сначала активируйте индекс, затем добавляйте в него материалы",
                code="retrieval_active_index_missing",
            )
        active = session.get(RetrievalIndex, row.active_index_id)
        material = session.get(Material, material_id)
        if active is None or material is None:
            raise ProjectNotFoundError("Индекс или материал не найден")
        if active.state != RetrievalIndexState.ACTIVE:
            raise ProjectConflictError(
                "Активный индекс ещё не готов", code="retrieval_index_not_ready"
            )
        profile = session.get(EmbeddingProfile, active.profile_id)
        if profile is None or profile.backend_kind != EmbeddingBackendKind.LOCAL_HF:
            raise ProjectConflictError(
                "Добавление одного материала доступно для локальной embedding-модели",
                code="retrieval_incremental_cloud_unsupported",
            )
        if material.status != MaterialState.READY or material.active_parse_revision <= 0:
            raise ProjectConflictError("Материал ещё не подготовлен", code="material_not_ready")
        queue_incremental_reindex(session, material_id)
        job = session.scalar(
            select(BackgroundJob.id).where(
                BackgroundJob.kind == BackgroundJobKind.RETRIEVAL_INDEX,
                BackgroundJob.material_id == material_id,
                BackgroundJob.state.in_((BackgroundJobState.QUEUED, BackgroundJobState.RUNNING)),
            )
        )
        if job is None:
            raise ProjectConflictError(
                "Материал уже входит в активный индекс",
                code="retrieval_material_already_indexed",
            )
        return job


def pause_index_build(session: Session, job_id: UUID) -> BackgroundJob:
    """Поставить сбор candidate на паузу, не выбрасывая записанные куски."""
    job = session.get(BackgroundJob, job_id)
    if job is None or job.kind != BackgroundJobKind.RETRIEVAL_INDEX:
        raise ProjectNotFoundError("Задача сборки индекса не найдена")
    if job.checkpoint.get("mode") == "incremental":
        raise ProjectConflictError(
            "Пауза доступна только для полной сборки кандидата",
            code="retrieval_index_incremental_control_unsupported",
        )
    state = job.state
    session.rollback()
    if state == BackgroundJobState.QUEUED:
        def pause_queued(_inner: Session, current: BackgroundJob) -> None:
            current.state = BackgroundJobState.PAUSED
            current.updated_at = utc_now()

        write_job(session, job_id, pause_queued)
    elif state == BackgroundJobState.RUNNING:
        def request_pause(_inner: Session, current: BackgroundJob) -> None:
            current.pause_requested = True
            current.updated_at = utc_now()

        write_job(session, job_id, request_pause)
    elif state != BackgroundJobState.PAUSED:
        raise ProjectConflictError(
            "Сбор уже нельзя поставить на паузу", code="retrieval_index_not_running"
        )
    session.expire_all()
    result = session.get(BackgroundJob, job_id)
    assert result is not None
    return result


def resume_index_build(session: Session, job_id: UUID) -> BackgroundJob:
    """Вернуть остановленный candidate в очередь с прежним чекпоинтом."""
    job = session.get(BackgroundJob, job_id)
    if job is None or job.kind != BackgroundJobKind.RETRIEVAL_INDEX:
        raise ProjectNotFoundError("Задача сборки индекса не найдена")
    if job.checkpoint.get("mode") == "incremental":
        raise ProjectConflictError(
            "Возобновление доступно только для полной сборки кандидата",
            code="retrieval_index_incremental_control_unsupported",
        )
    if job.state != BackgroundJobState.PAUSED:
        raise ProjectConflictError(
            "Возобновить можно только индекс на паузе", code="retrieval_index_not_paused"
        )
    session.rollback()

    def resume(inner: Session, current: BackgroundJob) -> None:
        index_id = UUID(str(current.checkpoint["index_id"]))
        index = inner.get(RetrievalIndex, index_id)
        if index is not None:
            index.state = RetrievalIndexState.BUILDING
            index.completed_at = None
        current.state = BackgroundJobState.QUEUED
        current.pause_requested = False
        current.checkpoint.pop("finish_requested", None)
        current.updated_at = utc_now()

    write_job(session, job_id, resume)
    session.expire_all()
    result = session.get(BackgroundJob, job_id)
    assert result is not None
    return result


def finish_index_build(session: Session, job_id: UUID) -> BackgroundJob:
    """Закончить сбор сейчас и оставить кандидат пригодным как частичный индекс."""
    job = session.get(BackgroundJob, job_id)
    if job is None or job.kind != BackgroundJobKind.RETRIEVAL_INDEX:
        raise ProjectNotFoundError("Задача сборки индекса не найдена")
    if job.checkpoint.get("mode") == "incremental":
        raise ProjectConflictError(
            "Завершение сейчас доступно только для полной сборки кандидата",
            code="retrieval_index_incremental_control_unsupported",
        )
    state, checkpoint = job.state, dict(job.checkpoint)
    if state not in {
        BackgroundJobState.QUEUED,
        BackgroundJobState.RUNNING,
        BackgroundJobState.PAUSED,
    }:
        raise ProjectConflictError("Сбор уже завершён", code="retrieval_index_not_running")
    session.rollback()
    index_id = UUID(str(checkpoint["index_id"]))
    if state == BackgroundJobState.RUNNING:
        # Внешний embedding-вызов нельзя оборвать надёжно. Воркер увидит флаг
        # перед следующей пачкой и завершит сразу после уже идущей операции.
        def request_finish(_inner: Session, current: BackgroundJob) -> None:
            current.checkpoint = {**current.checkpoint, "finish_requested": True}
            current.pause_requested = True
            current.updated_at = utc_now()

        write_job(session, job_id, request_finish)
    else:
        _stop_index_build(session, job_id, index_id, "finish")
    session.expire_all()
    result = session.get(BackgroundJob, job_id)
    assert result is not None
    return result


def process_index_job(session: Session, detached_job: BackgroundJob) -> None:
    """Собрать candidate index пакетно, сохраняя прогресс между материалами."""
    job_id = detached_job.id
    try:
        job = session.get(BackgroundJob, job_id)
        if job is None:
            return
        index = session.get(RetrievalIndex, UUID(job.checkpoint["index_id"]))
        if index is None:
            raise RuntimeError("Кандидатный retrieval-индекс исчез")
        profile = session.get(EmbeddingProfile, index.profile_id)
        if profile is None:
            raise RuntimeError("Embedding-профиль исчез")
        if job.checkpoint.get("mode") == "incremental":
            _process_incremental(session, job, index, profile)
            return
        index_id, profile_id = index.id, profile.id
        manifest = list(index.corpus_manifest)
        target, maximum, overlap = (
            index.chunk_target_tokens,
            index.chunk_max_tokens,
            index.chunk_overlap_tokens,
        )
        backend = backend_for_profile(session, profile)
        action = _requested_stop(session, job_id)
        if action:
            _stop_index_build(session, job_id, index_id, action)
            return
        # При возобновлении уже записанные материалы не пересчитываются и не
        # удаляются. Именно запись после каждого материала делает паузу
        # безопасной для уже собранной части корпуса.
        if job.done == 0:
            write_job(
                session,
                job_id,
                lambda inner, _: inner.execute(
                    delete(RetrievalChunk).where(RetrievalChunk.index_id == index_id)
                ),
            )
        next_order = _next_sort_order(session, index_id)
        for position, manifest_item in enumerate(manifest, start=1):
            if position <= job.done:
                continue
            action = _requested_stop(session, job_id)
            if action:
                _stop_index_build(session, job_id, index_id, action)
                return
            material = session.get(Material, UUID(manifest_item["material_id"]))
            if material is None or material.active_parse_revision != manifest_item["revision"]:
                note = f"{manifest_item['name']}: ревизия изменилась, доступен только BM25"
                _save_chunks(session, job_id, index_id, [], position, diagnostic=note)
                continue
            drafts = material_chunks(
                session, material, target_tokens=target, max_tokens=maximum,
                overlap_tokens=overlap,
            )
            # Эмбеддинги считаются вне транзакции: сотни векторов на материал
            # держали бы снимок соединения открытым минутами.
            rows: list[dict[str, object]] = []
            dimension: int | None = None
            batch_size = embedding_batch_size(profile)
            for start in range(0, len(drafts), batch_size):
                action = _requested_stop(session, job_id)
                if action:
                    _stop_index_build(session, job_id, index_id, action)
                    return
                batch = drafts[start : start + batch_size]
                vectors = asyncio.run(backend.embed_documents([draft.text for draft in batch]))
                if dimension is None and vectors:
                    dimension = len(vectors[0])
                for draft, vector in zip(batch, vectors, strict=True):
                    rows.append(_chunk_row(index_id, next_order, draft, vector))
                    next_order += 1
            _save_chunks(
                session, job_id, index_id, rows, position,
                profile_id=profile_id, dimension=dimension,
                indexed=True,
            )

        def _complete(inner: Session, job: BackgroundJob) -> None:
            index = inner.get(RetrievalIndex, index_id)
            assert index is not None
            index.chunk_count = _chunk_count(inner, index_id)
            index.state = RetrievalIndexState.READY
            index.completed_at = utc_now()
            finish(job, BackgroundJobState.COMPLETED)

        write_job(session, job_id, _complete)
    except Exception as error:
        reason = str(error)
        log.exception("retrieval index build failed job=%s", job_id)
        session.rollback()

        def _fail(inner: Session, job: BackgroundJob) -> None:
            failed_index_id = job.checkpoint.get("index_id")
            index = inner.get(RetrievalIndex, UUID(failed_index_id)) if failed_index_id else None
            if index is not None and job.checkpoint.get("mode") != "incremental":
                index.state = RetrievalIndexState.FAILED
                index.error = reason
            finish(job, BackgroundJobState.FAILED, error=reason)

        write_job(session, job_id, _fail)


def _process_incremental(
    session: Session,
    job: BackgroundJob,
    index: RetrievalIndex,
    profile: EmbeddingProfile,
) -> None:
    if _requested_stop(session, job.id):
        _cancel_incremental_reindex(session, job.id)
        return
    material_id = UUID(job.checkpoint["material_id"])
    material = session.get(Material, material_id)
    if material is None:
        raise RuntimeError("Материал для переиндексации исчез")
    drafts = material_chunks(
        session,
        material,
        target_tokens=index.chunk_target_tokens,
        max_tokens=index.chunk_max_tokens,
        overlap_tokens=index.chunk_overlap_tokens,
    )
    index_id, job_id = index.id, job.id
    revision, display_name, size_bytes = (
        material.active_parse_revision,
        material.display_name,
        material.size_bytes,
    )
    backend = backend_for_profile(session, profile)
    embedded: list[tuple[ChunkDraft, list[float]]] = []
    batch_size = embedding_batch_size(profile)
    for start in range(0, len(drafts), batch_size):
        # Общая отмена помечает running-задачу через `pause_requested`.
        # Для candidate-индекса это просьба остановиться и сохранить часть
        # корпуса, а для инкрементального обновления — отмена: его результат
        # ещё не записан, поэтому активный индекс остаётся нетронутым.
        if _requested_stop(session, job_id):
            _cancel_incremental_reindex(session, job_id)
            return
        batch = drafts[start : start + batch_size]
        vectors = asyncio.run(backend.embed_documents([draft.text for draft in batch]))
        embedded.extend(zip(batch, vectors, strict=True))

    def apply(inner: Session, job: BackgroundJob) -> None:
        # Команда могла прийти после последней пачки, пока в памяти уже лежат
        # векторы. Проверяем её внутри той же транзакции, которая иначе меняла
        # бы active index: отмена никогда не публикует готовый результат.
        if job.pause_requested:
            finish(job, BackgroundJobState.CANCELLED)
            return
        index = inner.get(RetrievalIndex, index_id)
        assert index is not None
        inner.execute(
            delete(RetrievalChunk).where(
                RetrievalChunk.index_id == index_id,
                RetrievalChunk.material_id == material_id,
            )
        )
        next_order = (
            inner.scalar(
                select(func.max(RetrievalChunk.sort_order)).where(
                    RetrievalChunk.index_id == index_id
                )
            )
            or -1
        ) + 1
        rows = []
        for draft, vector in embedded:
            rows.append(_chunk_row(index_id, next_order, draft, vector))
            next_order += 1
        if rows:
            inner.execute(insert(RetrievalChunk), rows)
        manifest = [
            {**item, "revision": revision, "name": display_name, "size_bytes": size_bytes}
            if item["material_id"] == str(material_id)
            else item
            for item in index.corpus_manifest
        ]
        if not any(item["material_id"] == str(material_id) for item in manifest):
            manifest.append({
                "material_id": str(material_id),
                "name": display_name,
                "revision": revision,
                "size_bytes": size_bytes,
                "source_kind": material.source_kind.value,
            })
        index.corpus_manifest = manifest
        index.material_count = len(manifest)
        index.chunk_count = _chunk_count(inner, index_id)
        finish(
            job,
            BackgroundJobState.CANCELLED
            if job.pause_requested
            else BackgroundJobState.COMPLETED,
        )

    write_job(session, job_id, apply)


def _cancel_incremental_reindex(session: Session, job_id: UUID) -> None:
    """Закрыть отменённое обновление до записи в активный индекс."""

    def cancel(_inner: Session, current: BackgroundJob) -> None:
        finish(current, BackgroundJobState.CANCELLED)

    write_job(session, job_id, cancel)


def _chunk_count(session: Session, index_id: UUID) -> int:
    return (
        session.scalar(
            select(func.count()).select_from(RetrievalChunk).where(
                RetrievalChunk.index_id == index_id
            )
        )
        or 0
    )


def _next_sort_order(session: Session, index_id: UUID) -> int:
    """Продолжить порядок кусков после возобновления, не создавая дублей."""
    last = session.scalar(
        select(func.max(RetrievalChunk.sort_order)).where(RetrievalChunk.index_id == index_id)
    )
    return (last if last is not None else -1) + 1


def _requested_stop(session: Session, job_id: UUID) -> str | None:
    """Прочитать команду из свежей короткой транзакции, а не старого снимка."""
    return write_job(
        session,
        job_id,
        lambda _inner, job: (
            "finish"
            if job.checkpoint.get("finish_requested")
            else "pause"
            if job.pause_requested
            else None
        ),
    )


def _stop_index_build(session: Session, job_id: UUID, index_id: UUID, action: str) -> None:
    """Освободить воркер и сохранить уже записанную часть candidate-индекса."""
    def apply(inner: Session, job: BackgroundJob) -> None:
        index = inner.get(RetrievalIndex, index_id)
        if index is None:
            return
        index.chunk_count = _chunk_count(inner, index_id)
        job.lease_owner = None
        job.lease_expires_at = None
        job.updated_at = utc_now()
        if action == "pause":
            job.state = BackgroundJobState.PAUSED
            return
        index.state = RetrievalIndexState.READY
        index.completed_at = utc_now()
        index.diagnostics = [
            *index.diagnostics,
            "Сбор остановлен пользователем: "
            f"проиндексировано {index.indexed_material_count} из "
            f"{index.material_count} материалов.",
        ]
        job.state = BackgroundJobState.COMPLETED
        job.completed_at = utc_now()
        job.pause_requested = False
        job.updated_at = utc_now()

    write_job(session, job_id, apply)


def _chunk_row(
    index_id: UUID, sort_order: int, draft: ChunkDraft, vector: list[float]
) -> dict[str, object]:
    return {
        "index_id": index_id,
        "sort_order": sort_order,
        "material_id": draft.material_id,
        "revision": draft.revision,
        "block_id": draft.block_id,
        "kind": draft.kind,
        "title": draft.title,
        "text": draft.text,
        "token_count": draft.token_count,
        "page_from": draft.page_from,
        "page_to": draft.page_to,
        "quality": draft.quality,
        "fragment_ids": [str(value) for value in draft.fragment_ids],
        "locator": draft.locator,
        "content_hash": draft.content_hash,
        "embedding": vector_blob(vector),
    }


def _save_chunks(
    session: Session,
    job_id: UUID,
    index_id: UUID,
    rows: list[dict[str, object]],
    done: int,
    *,
    profile_id: UUID | None = None,
    dimension: int | None = None,
    diagnostic: str | None = None,
    indexed: bool = False,
) -> None:
    """Записать куски одного материала и прогресс одной транзакцией.

    Повтор после отказа по блокировке безопасен: до успешного коммита в базе
    нет ни одной строки этой пачки.
    """

    def apply(inner: Session, job: BackgroundJob) -> None:
        if rows:
            inner.execute(insert(RetrievalChunk), rows)
        if diagnostic is not None:
            index = inner.get(RetrievalIndex, index_id)
            if index is not None:
                index.diagnostics = [*index.diagnostics, diagnostic]
        if indexed:
            index = inner.get(RetrievalIndex, index_id)
            if index is not None:
                index.indexed_material_count += 1
        if profile_id is not None and dimension is not None:
            profile = inner.get(EmbeddingProfile, profile_id)
            if profile is not None and profile.dimension is None:
                profile.dimension = dimension
        job.done = done
        job.updated_at = utc_now()

    write_job(session, job_id, apply)
