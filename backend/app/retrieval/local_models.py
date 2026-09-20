from __future__ import annotations

import hashlib
import re
import shutil
from pathlib import Path
from uuid import UUID, uuid4

from huggingface_hub import snapshot_download
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import (
    BackgroundJob,
    BackgroundJobKind,
    BackgroundJobState,
    EmbeddingProfile,
    RetrievalIndex,
    utc_now,
)
from app.projects.errors import ProjectConflictError
from app.retrieval.schemas import LocalModelRead

_MODEL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9][A-Za-z0-9._-]*$")

CURATED_MODELS = (
    (
        "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
        "MiniLM multilingual",
        "embedding",
        "Быстро, CPU",
    ),
    ("intfloat/multilingual-e5-base", "Multilingual E5 Base", "embedding", "Базовая линия"),
    ("Qwen/Qwen3-Embedding-0.6B", "Qwen3 Embedding 0.6B", "embedding", "Максимум качества"),
    ("Qwen/Qwen3-Reranker-0.6B", "Qwen3 Reranker 0.6B", "reranker", "Профиль «Точно»"),
)


def validate_model_id(model_id: str) -> str:
    if not _MODEL_ID.fullmatch(model_id):
        raise ProjectConflictError(
            "Ожидается идентификатор Hugging Face вида owner/model",
            code="retrieval_invalid_model_id",
        )
    return model_id


def model_path(model_id: str) -> Path:
    validate_model_id(model_id)
    digest = hashlib.sha256(model_id.encode()).hexdigest()[:16]
    return settings.embedding_models_dir / f"{digest}-{model_id.rsplit('/', 1)[-1]}"


def list_models() -> list[LocalModelRead]:
    return [
        LocalModelRead(
            model_id=model_id,
            label=label,
            role=role,
            installed=model_path(model_id).is_dir(),
            recommended_for=recommended_for,
        )
        for model_id, label, role, recommended_for in CURATED_MODELS
    ]


def start_install(session: Session, model_id: str, revision: str | None) -> UUID:
    validate_model_id(model_id)
    with session.begin():
        job = BackgroundJob(
            id=uuid4(),
            kind=BackgroundJobKind.RETRIEVAL_MODEL_INSTALL,
            state=BackgroundJobState.QUEUED,
            total=1,
            checkpoint={"model_id": model_id, "revision": revision},
        )
        session.add(job)
    return job.id


def remove_model(session: Session, model_id: str) -> None:
    profile_ids = list(
        session.scalars(select(EmbeddingProfile.id).where(EmbeddingProfile.model_id == model_id))
    )
    if profile_ids and session.scalar(
        select(RetrievalIndex.id).where(RetrievalIndex.profile_id.in_(profile_ids)).limit(1)
    ):
        raise ProjectConflictError(
            "Модель используется retrieval-индексом; сначала удалите неактивные индексы",
            code="retrieval_model_in_use",
        )
    path = model_path(model_id).resolve()
    root = settings.embedding_models_dir.resolve()
    if path.parent != root:
        raise ProjectConflictError("Небезопасный путь модели", code="retrieval_invalid_model_path")
    if path.exists():
        shutil.rmtree(path)


def process_install_job(session: Session, detached_job: BackgroundJob) -> None:
    job = session.get(BackgroundJob, detached_job.id)
    if job is None:
        return
    try:
        model_id = validate_model_id(str(job.checkpoint["model_id"]))
        revision = job.checkpoint.get("revision")
        snapshot_download(
            repo_id=model_id,
            revision=str(revision) if revision else None,
            local_dir=model_path(model_id),
        )
        job.state = BackgroundJobState.COMPLETED
        job.done = 1
        job.completed_at = utc_now()
        job.lease_owner = None
        job.lease_expires_at = None
        job.updated_at = utc_now()
        session.commit()
    except Exception as error:
        session.rollback()
        job = session.get(BackgroundJob, detached_job.id)
        if job is not None:
            job.state = BackgroundJobState.FAILED
            job.error = str(error)
            job.lease_owner = None
            job.lease_expires_at = None
            job.updated_at = utc_now()
            session.commit()
