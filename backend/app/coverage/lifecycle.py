"""Состояние исследования в BackgroundJob, с fencing каждого writer."""

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select

from app.coverage.snapshots import require_project, snapshot_current
from app.db import job_write_transaction, project_write_transaction
from app.models import BackgroundJob, BackgroundJobState, CoverageRun, utc_now
from app.projects.errors import ProjectConflictError, ProjectNotFoundError


@dataclass(frozen=True)
class ExecutionToken:
    """Worker захватывает поколение один раз при claim, не перечитывает перед записью."""

    run_id: UUID
    generation: int
    owner: str


def require_run(session, project_id, run_id):
    """UUID другого проекта не даёт доступа к снимку или опорам."""
    require_project(session, project_id)
    run = session.get(CoverageRun, run_id)
    if run is None or run.project_id != project_id:
        raise ProjectNotFoundError("Исследование не найдено", code="coverage_run_not_found")
    return run


def fenced(session, token, *, allow_pause=False):
    """Вызывается после резервирования writer; старый lease не может публиковать."""
    session.expire_all()
    run = session.get(CoverageRun, token.run_id)
    job = session.get(BackgroundJob, run.job_id) if run else None
    if not (
        run
        and job
        and job.state == BackgroundJobState.RUNNING
        and run.execution_generation == token.generation
        and job.lease_owner == token.owner
        and job.lease_expires_at
        and job.lease_expires_at > utc_now()
    ):
        raise ProjectConflictError("Worker больше не владеет запуском", code="coverage_lease_lost")
    if job.pause_requested and not allow_pause:
        raise ProjectConflictError("Запрошена пауза", code="coverage_pause_requested")
    return run, job


def stop_core(run, job, state, reason):
    """Освобождает lease без подмены done на total."""
    job.state = state
    job.pause_requested = False
    job.lease_owner = None
    job.lease_expires_at = None
    job.updated_at = utc_now()
    run.stop_reason = reason
    if state in {
        BackgroundJobState.CANCELLED,
        BackgroundJobState.COMPLETED,
        BackgroundJobState.FAILED,
    }:
        run.finished_at = job.completed_at = utc_now()


def control_run(session, project_id, run_id, command):
    """Пауза — intent до границы участка; отмена сразу запрещает позднюю публикацию."""
    with project_write_transaction(session, project_id):
        session.expire_all()
        require_project(session, project_id, writable=True)
        run = require_run(session, project_id, run_id)
        job = session.get(BackgroundJob, run.job_id)
        if run.execution_generation != command.expected_generation:
            raise ProjectConflictError(
                "Поколение запуска изменилось", code="coverage_generation_changed"
            )
        if command.action == "cancel":
            if job.state != BackgroundJobState.CANCELLED:
                _require_state(
                    job,
                    {
                        BackgroundJobState.QUEUED,
                        BackgroundJobState.RUNNING,
                        BackgroundJobState.PAUSED,
                    },
                )
                stop_core(run, job, BackgroundJobState.CANCELLED, "user_cancelled")
        elif command.action == "pause":
            _require_state(
                job,
                {BackgroundJobState.QUEUED, BackgroundJobState.RUNNING, BackgroundJobState.PAUSED},
            )
            if job.state == BackgroundJobState.RUNNING:
                job.pause_requested = True
            else:
                stop_core(run, job, BackgroundJobState.PAUSED, "user_pause")
        else:
            _require_state(job, {BackgroundJobState.PAUSED, BackgroundJobState.QUEUED})
            if not snapshot_current(session, run):
                stop_core(run, job, BackgroundJobState.CANCELLED, "snapshot_changed")
            else:
                job.state = BackgroundJobState.QUEUED
                job.pause_requested = False
                run.stop_reason = None
        return run.id


def _require_state(job, states):
    if job.state not in states:
        raise ProjectConflictError("Переход недоступен", code="coverage_invalid_transition")


def execution_boundary(session, token) -> bool:
    """Проверяется перед чтением и после ответа, в коротком writer snapshot."""
    with job_write_transaction(session):
        run, job = fenced(session, token, allow_pause=True)
        if not snapshot_current(session, run):
            stop_core(run, job, BackgroundJobState.CANCELLED, "snapshot_changed")
            return False
        if job.pause_requested:
            stop_core(run, job, BackgroundJobState.PAUSED, "user_pause")
            return False
        return True


def claim_generation(session, job):
    """Вызывается внутри существующего claim_job writer, включая повтор после аварии."""
    run = session.scalar(select(CoverageRun).where(CoverageRun.job_id == job.id))
    run.execution_generation += 1
    job.checkpoint = {
        **job.checkpoint,
        "coverage_generation": run.execution_generation,
        "coverage_run_id": str(run.id),
    }
