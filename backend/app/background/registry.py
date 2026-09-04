"""Реестр фоновых операций: читает и отменяет `background_jobs` напрямую.

Одна таблица под все виды задач (Ш1 плана) — поэтому сам модуль тонкий: он не
знает деталей разбора материала или вызовов ИИ, только общую ось состояний.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.background.schemas import BackgroundJobRead
from app.materials import library
from app.models import (
    AiSettings,
    BackgroundJob,
    BackgroundJobKind,
    BackgroundJobState,
    Material,
    OcrEngineConfig,
    ParserMode,
    Project,
    utc_now,
)
from app.ocr.engines import DEFAULT_FAST_MODEL_ID
from app.projects.errors import ProjectConflictError, ProjectNotFoundError

ACTIVE_JOB_STATES = {
    BackgroundJobState.QUEUED,
    BackgroundJobState.RUNNING,
    BackgroundJobState.PAUSED,
}


def _subject(session: Session, job: BackgroundJob) -> str:
    """Над чем идёт работа — именем файла или проекта, а не идентификатором."""
    if job.material_id is not None:
        material = session.get(Material, job.material_id)
        if material is not None:
            return material.original_name
    if job.project_id is not None:
        project = session.get(Project, job.project_id)
        if project is not None:
            return project.name or "Проект без названия"
    return ""


def _model_label(session: Session, job: BackgroundJob) -> str:
    """Чем именно читается материал: локальный движок или внешняя модель.

    Заполняется только у разбора: у ролей ИИ модель выбирается по роли уже
    внутри шлюза, и в самой задаче её названия нет.
    """
    if job.kind != BackgroundJobKind.PARSE:
        return ""
    if job.parser_mode == ParserMode.CLOUD:
        row = session.get(AiSettings, 1)
        return (row.default_vision_model_id if row else None) or "внешняя модель"
    engine = session.get(OcrEngineConfig, "fast")
    return (engine.model_id if engine else None) or DEFAULT_FAST_MODEL_ID


def _read(session: Session, job: BackgroundJob) -> BackgroundJobRead:
    return BackgroundJobRead.model_validate(job).model_copy(
        update={"subject": _subject(session, job), "model_label": _model_label(session, job)}
    )


def _job_or_404(session: Session, job_id: UUID) -> BackgroundJob:
    job = session.get(BackgroundJob, job_id)
    if job is None:
        raise ProjectNotFoundError("Фоновая задача не найдена", code="background_job_not_found")
    return job


def list_jobs(
    session: Session,
    *,
    active_only: bool = False,
    project_id: UUID | None = None,
    material_id: UUID | None = None,
) -> list[BackgroundJobRead]:
    stmt = select(BackgroundJob).order_by(BackgroundJob.created_at.desc())
    if active_only:
        stmt = stmt.where(BackgroundJob.state.in_(ACTIVE_JOB_STATES))
    if project_id is not None:
        stmt = stmt.where(BackgroundJob.project_id == project_id)
    if material_id is not None:
        stmt = stmt.where(BackgroundJob.material_id == material_id)
    return [_read(session, job) for job in session.scalars(stmt)]


def get_job(session: Session, job_id: UUID) -> BackgroundJobRead:
    return _read(session, _job_or_404(session, job_id))


def cancel_job(session: Session, job_id: UUID) -> BackgroundJobRead:
    """Отменить задачу.

    Разбор материала (`kind == parse`) отменяется через уже существующий
    `library.control_task_core`: там же выбрасывается строящаяся ревизия и
    восстанавливается статус материала — материал-специфичная логика, которую
    здесь дублировать нельзя. У задач без этой логики (роли ИИ, привязка
    ответов) путь короче: `queued` снимается сразу, а `running` получает
    `pause_requested` и достаётся до конца сама воркером — досрочно оборвать
    уже идущий вызов модели или расчёт нечем, но результат он всё равно
    получит статус `cancelled`, а не `completed` (см. `app.ai.jobs`).
    """
    job = _job_or_404(session, job_id)
    if job.kind == BackgroundJobKind.PARSE:
        assert job.material_id is not None
        session.rollback()
        with session.begin():
            library.control_task_core(session, job.material_id, "cancel")
        session.expire_all()
        return get_job(session, job_id)
    if job.state == BackgroundJobState.QUEUED:
        with session.begin():
            job.state = BackgroundJobState.CANCELLED
            job.updated_at = utc_now()
    elif job.state == BackgroundJobState.RUNNING:
        with session.begin():
            job.pause_requested = True
            job.updated_at = utc_now()
    else:
        raise ProjectConflictError(
            "Задачу нельзя отменить в текущем состоянии", code="background_job_not_cancellable"
        )
    session.expire_all()
    return get_job(session, job_id)


def get_job_result(session: Session, job_id: UUID) -> dict[str, Any]:
    """Отдать разобранный ответ роли, сохранённый завершившейся задачей.

    Именно это делает уход с экрана безопасным: задача досчитывается в фоне, а
    вернувшийся диалог забирает готовое предложение отсюда, вместо того чтобы
    звать модель заново и платить за неё второй раз.
    """
    job = _job_or_404(session, job_id)
    if job.state != BackgroundJobState.COMPLETED:
        raise ProjectConflictError(
            "Задача ещё не завершена — результата пока нет",
            code="background_job_not_completed",
        )
    result = job.checkpoint.get("result")
    if result is None:
        raise ProjectNotFoundError(
            "Задача завершилась без сохранённого результата",
            code="background_job_result_missing",
        )
    return result
