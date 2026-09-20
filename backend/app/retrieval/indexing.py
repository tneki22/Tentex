from __future__ import annotations

import asyncio
from uuid import UUID, uuid4

from sqlalchemy import delete, func, select
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
from app.retrieval.schemas import RetrievalIndexBuildRead, RetrievalIndexBuildWrite
from app.retrieval.vector import vector_blob


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
            checkpoint={"index_id": str(index.id)},
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
    if str(material_id) not in {item["material_id"] for item in active.corpus_manifest}:
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
        backend = backend_for_profile(session, profile)
        session.execute(delete(RetrievalChunk).where(RetrievalChunk.index_id == index.id))
        session.commit()
        next_order = 0
        for position, manifest_item in enumerate(index.corpus_manifest, start=1):
            material = session.get(Material, UUID(manifest_item["material_id"]))
            if material is None or material.active_parse_revision != manifest_item["revision"]:
                index.diagnostics = [
                    *index.diagnostics,
                    f"{manifest_item['name']}: ревизия изменилась, доступен только BM25",
                ]
                _progress(session, job_id, position)
                continue
            drafts = material_chunks(
                session,
                material,
                target_tokens=index.chunk_target_tokens,
                max_tokens=index.chunk_max_tokens,
                overlap_tokens=index.chunk_overlap_tokens,
            )
            for start in range(0, len(drafts), profile.batch_size):
                batch = drafts[start : start + profile.batch_size]
                vectors = asyncio.run(backend.embed_documents([draft.text for draft in batch]))
                if profile.dimension is None and vectors:
                    profile.dimension = len(vectors[0])
                for draft, vector in zip(batch, vectors, strict=True):
                    session.add(
                        RetrievalChunk(
                            index_id=index.id,
                            sort_order=next_order,
                            material_id=draft.material_id,
                            revision=draft.revision,
                            block_id=draft.block_id,
                            kind=draft.kind,
                            title=draft.title,
                            text=draft.text,
                            token_count=draft.token_count,
                            page_from=draft.page_from,
                            page_to=draft.page_to,
                            quality=draft.quality,
                            fragment_ids=[str(value) for value in draft.fragment_ids],
                            locator=draft.locator,
                            content_hash=draft.content_hash,
                            embedding=vector_blob(vector),
                        )
                    )
                    next_order += 1
            session.commit()
            _progress(session, job_id, position)
        index = session.get(RetrievalIndex, index.id)
        job = session.get(BackgroundJob, job_id)
        assert index is not None and job is not None
        index.chunk_count = (
            session.scalar(
                select(func.count())
                .select_from(RetrievalChunk)
                .where(RetrievalChunk.index_id == index.id)
            )
            or 0
        )
        index.state = RetrievalIndexState.READY
        index.completed_at = utc_now()
        job.state = BackgroundJobState.COMPLETED
        job.done = job.total
        job.completed_at = utc_now()
        job.lease_owner = None
        job.lease_expires_at = None
        job.updated_at = utc_now()
        session.commit()
    except Exception as error:
        session.rollback()
        job = session.get(BackgroundJob, job_id)
        if job is not None:
            index_id = job.checkpoint.get("index_id")
            index = session.get(RetrievalIndex, UUID(index_id)) if index_id else None
            if index is not None and job.checkpoint.get("mode") != "incremental":
                index.state = RetrievalIndexState.FAILED
                index.error = str(error)
            job.state = BackgroundJobState.FAILED
            job.error = str(error)
            job.lease_owner = None
            job.lease_expires_at = None
            job.updated_at = utc_now()
            session.commit()


def _process_incremental(
    session: Session,
    job: BackgroundJob,
    index: RetrievalIndex,
    profile: EmbeddingProfile,
) -> None:
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
    backend = backend_for_profile(session, profile)
    embedded: list[tuple[ChunkDraft, list[float]]] = []
    for start in range(0, len(drafts), profile.batch_size):
        batch = drafts[start : start + profile.batch_size]
        vectors = asyncio.run(backend.embed_documents([draft.text for draft in batch]))
        embedded.extend(zip(batch, vectors, strict=True))
    session.execute(
        delete(RetrievalChunk).where(
            RetrievalChunk.index_id == index.id,
            RetrievalChunk.material_id == material_id,
        )
    )
    next_order = (
        session.scalar(
            select(func.max(RetrievalChunk.sort_order)).where(RetrievalChunk.index_id == index.id)
        )
        or -1
    ) + 1
    for draft, vector in embedded:
        session.add(
            RetrievalChunk(
                index_id=index.id,
                sort_order=next_order,
                material_id=draft.material_id,
                revision=draft.revision,
                block_id=draft.block_id,
                kind=draft.kind,
                title=draft.title,
                text=draft.text,
                token_count=draft.token_count,
                page_from=draft.page_from,
                page_to=draft.page_to,
                quality=draft.quality,
                fragment_ids=[str(value) for value in draft.fragment_ids],
                locator=draft.locator,
                content_hash=draft.content_hash,
                embedding=vector_blob(vector),
            )
        )
        next_order += 1
    index.corpus_manifest = [
        {
            **item,
            "revision": material.active_parse_revision,
            "name": material.display_name,
            "size_bytes": material.size_bytes,
        }
        if item["material_id"] == str(material.id)
        else item
        for item in index.corpus_manifest
    ]
    session.flush()
    index.chunk_count = (
        session.scalar(
            select(func.count())
            .select_from(RetrievalChunk)
            .where(RetrievalChunk.index_id == index.id)
        )
        or 0
    )
    job.state = (
        BackgroundJobState.CANCELLED if job.pause_requested else BackgroundJobState.COMPLETED
    )
    job.done = job.total
    job.completed_at = utc_now()
    job.lease_owner = None
    job.lease_expires_at = None
    job.updated_at = utc_now()
    session.commit()


def _progress(session: Session, job_id: UUID, done: int) -> None:
    job = session.get(BackgroundJob, job_id)
    if job is None:
        return
    job.done = done
    job.updated_at = utc_now()
    session.commit()
