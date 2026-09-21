from __future__ import annotations

import fnmatch
import hashlib
import logging
import re
import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from uuid import UUID, uuid4

from huggingface_hub import hf_hub_download, list_repo_files, snapshot_download
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import (
    BackgroundJob,
    BackgroundJobKind,
    BackgroundJobState,
    EmbeddingProfile,
    RetrievalIndex,
)
from app.projects.errors import ProjectConflictError
from app.retrieval.jobs import finish, write_job
from app.retrieval.schemas import LocalModelRead

_MODEL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9][A-Za-z0-9._-]*$")
log = logging.getLogger("tentex.retrieval")

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


def _partial_path(model_id: str) -> Path:
    """Куда идёт скачивание: в финальный каталог модель попадает только целиком."""
    final = model_path(model_id)
    return final.with_name(f"{final.name}.partial")


def _active_install_jobs(session: Session) -> dict[str, UUID]:
    """Незавершённые установки: `model_id` → задача. Ключ лежит в checkpoint."""
    jobs = session.scalars(
        select(BackgroundJob).where(
            BackgroundJob.kind == BackgroundJobKind.RETRIEVAL_MODEL_INSTALL,
            BackgroundJob.state.in_((BackgroundJobState.QUEUED, BackgroundJobState.RUNNING)),
        )
    )
    return {str(job.checkpoint["model_id"]): job.id for job in jobs}


def list_models(session: Session) -> list[LocalModelRead]:
    installing = _active_install_jobs(session)
    curated = [
        LocalModelRead(
            model_id=model_id,
            label=label,
            role=role,
            installed=model_path(model_id).is_dir(),
            installing=model_id in installing,
            recommended_for=recommended_for,
        )
        for model_id, label, role, recommended_for in CURATED_MODELS
    ]
    known = {item.model_id for item in curated}
    custom_profiles = session.scalars(
        select(EmbeddingProfile).order_by(EmbeddingProfile.created_at)
    )
    for profile in custom_profiles:
        if profile.model_id in known or profile.backend_kind.value != "local_hf":
            continue
        curated.append(LocalModelRead(
            model_id=profile.model_id,
            label=profile.label,
            role="embedding",
            installed=model_path(profile.model_id).is_dir(),
            installing=profile.model_id in installing,
            recommended_for="Добавленная вручную модель",
        ))
    return curated


def start_install(session: Session, model_id: str, revision: str | None) -> UUID:
    validate_model_id(model_id)
    with session.begin():
        running = _active_install_jobs(session).get(model_id)
        if running is not None:
            # Повторный клик по «Скачать» не ставит в очередь второе скачивание тех же гигабайт.
            return running
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
    root = settings.embedding_models_dir.resolve()
    for path in (model_path(model_id).resolve(), _partial_path(model_id).resolve()):
        if path.parent != root:
            raise ProjectConflictError(
                "Небезопасный путь модели", code="retrieval_invalid_model_path"
            )
        if path.exists():
            shutil.rmtree(path)


# Репозитории sentence-transformers держат одни и те же веса в нескольких форматах:
# у MiniLM это 4,6 ГБ ради 470 МБ, которые реально читает PyTorch.
_NEVER_NEEDED = (
    "onnx/*", "openvino/*", "coreml/*", "*.onnx", "*.h5", "*.msgpack", "*.ot", "*.tflite", "*.gguf",
)


def _skipped_files(model_id: str, revision: str | None) -> list[str]:
    patterns = list(_NEVER_NEEDED)
    try:
        files = list_repo_files(model_id, revision=revision)
    except Exception:
        # Не смогли перечислить файлы — качаем всё, кроме заведомо лишнего: недоступность
        # каталога не повод отказывать в установке.
        return patterns
    if any(name.endswith(".safetensors") for name in files):
        patterns.append("pytorch_model*.bin")
    return patterns


def process_install_job(session: Session, detached_job: BackgroundJob) -> None:
    job_id = detached_job.id
    job = session.get(BackgroundJob, job_id)
    if job is None:
        return
    model_id = str(job.checkpoint["model_id"])
    revision = job.checkpoint.get("revision")
    # Скачивание идёт без открытого снимка базы: несколько гигабайт качаются
    # минутами, и всё это время соединение не должно держать читателя.
    session.rollback()
    try:
        validate_model_id(model_id)
        partial = _partial_path(model_id)
        # Недокачанный `.partial` остаётся на диске: huggingface_hub докачивает его,
        # а `installed` не видит его до переименования.
        ignored = _skipped_files(model_id, str(revision) if revision else None)
        downloaded_by_snapshot = False
        try:
            files = [
                name for name in list_repo_files(
                    model_id, revision=str(revision) if revision else None
                )
                if not any(fnmatch.fnmatch(name, pattern) for pattern in ignored)
            ]
        except Exception as error:
            # Каталог может быть недоступен, хотя сам snapshot endpoint отвечает.
            # В этом режиме сохраняем прежний путь и честно показываем одну задачу.
            log.warning("Не удалось перечислить файлы модели %s: %s", model_id, error)
            write_job(session, job_id, lambda _, job: setattr(job, "total", 1))
            snapshot_download(
                repo_id=model_id,
                revision=str(revision) if revision else None,
                local_dir=partial,
                ignore_patterns=ignored,
            )
            files = []
            downloaded_by_snapshot = True
        if not downloaded_by_snapshot:
            if not files:
                raise RuntimeError("В репозитории embedding-модели нет подходящих файлов")

            def set_total(inner: Session, job: BackgroundJob) -> None:
                job.total = len(files)
                job.done = 0

            write_job(session, job_id, set_total)

            # В отличие от snapshot_download этот короткий слой знает, когда файл
            # целиком появился в каталоге. Так панель показывает реальный чекпоинт,
            # а повтор после сбоя продолжает докачку уже существующих файлов.
            with ThreadPoolExecutor(max_workers=min(4, len(files))) as pool:
                futures = [pool.submit(
                    hf_hub_download,
                    model_id,
                    name,
                    revision=str(revision) if revision else None,
                    local_dir=partial,
                ) for name in files]
                for completed, future in enumerate(as_completed(futures), start=1):
                    future.result()
                    write_job(
                        session,
                        job_id,
                        lambda _, job, completed=completed: setattr(job, "done", completed),
                    )
        final = model_path(model_id)
        if final.exists():
            shutil.rmtree(final)
        partial.rename(final)
    except Exception as error:
        reason = str(error)
        write_job(
            session,
            job_id,
            lambda _, job: finish(job, BackgroundJobState.FAILED, error=reason),
        )
        return
    write_job(session, job_id, lambda _, job: finish(job, BackgroundJobState.COMPLETED))
