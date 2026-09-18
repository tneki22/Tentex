"""Офлайновый запуск и планирование manifest одной атомарной операцией."""

from uuid import uuid4

from sqlalchemy import select

from app.coverage.schemas import RunPlan
from app.coverage.snapshots import build_snapshot, fingerprint, manifest_rows, require_project
from app.db import project_write_transaction
from app.models import (
    BackgroundJob,
    BackgroundJobKind,
    BackgroundJobState,
    CoverageBlockResult,
    CoverageRun,
    CoverageTask,
)
from app.projects.errors import ProjectConflictError

# Ограничение хранилища одного участка; структурное пакетирование появится в И3.
TASK_BLOCK_LIMIT = 16
ACTIVE = {BackgroundJobState.QUEUED, BackgroundJobState.RUNNING, BackgroundJobState.PAUSED}


def preflight(session, project_id, plan):
    """Без сети: только снимок готовых источников и пределы запуска."""
    snapshot, fingerprints = build_snapshot(session, project_id, plan)
    return {
        "fingerprint": fingerprint(fingerprints),
        "snapshot": snapshot,
        "blocks": sum(1 for _ in manifest_rows(session, snapshot)),
        "execution_available": False,
        "limits": plan.limits.model_dump(),
    }


def start_run(session, project_id, command):
    """Writer берётся до проверки активного запуска, исключая два конкурентных manifest."""
    request_hash = fingerprint(command.model_dump(mode="json"))
    with project_write_transaction(session, project_id):
        session.expire_all()
        require_project(session, project_id, writable=True)
        previous = session.scalar(
            select(CoverageRun).where(
                CoverageRun.project_id == project_id, CoverageRun.request_key == command.request_key
            )
        )
        if previous:
            if previous.request_hash != request_hash:
                raise ProjectConflictError(
                    "Ключ уже использован с другим запросом", code="coverage_request_conflict"
                )
            return previous.id
        active = session.scalar(
            select(CoverageRun)
            .join(BackgroundJob, BackgroundJob.id == CoverageRun.job_id)
            .where(CoverageRun.project_id == project_id, BackgroundJob.state.in_(ACTIVE))
        )
        if active:
            return active.id
        plan = RunPlan.model_validate(
            command.model_dump(exclude={"request_key", "preflight_fingerprint"})
        )
        if plan.mode == "deep_program":
            raise ProjectConflictError(
                "Построение программы подключается отдельно", code="coverage_mode_unavailable"
            )
        snapshot, fingerprints = build_snapshot(session, project_id, plan)
        if fingerprint(fingerprints) != command.preflight_fingerprint:
            raise ProjectConflictError(
                "Снимок изменился после проверки", code="coverage_snapshot_changed"
            )
        job = BackgroundJob(
            id=uuid4(), project_id=project_id, kind=BackgroundJobKind.COVERAGE_RESEARCH
        )
        session.add(job)
        session.flush()
        run = CoverageRun(
            id=uuid4(),
            project_id=project_id,
            job_id=job.id,
            mode=plan.mode,
            request_key=command.request_key,
            request_hash=request_hash,
            snapshot=snapshot,
            fingerprints=fingerprints,
            limits=plan.limits.model_dump(),
            model_roles=plan.roles,
        )
        session.add(run)
        session.flush()
        targets = []
        for block, manifest in manifest_rows(session, snapshot):
            session.add(
                CoverageBlockResult(
                    run_id=run.id,
                    material_id=block.material_id,
                    material_revision=block.revision,
                    block_id=block.id,
                    sort_order=block.sort_order,
                    manifest=manifest,
                )
            )
            targets.append(str(block.id))
        for offset in range(0, len(targets), TASK_BLOCK_LIMIT):
            session.add(
                CoverageTask(
                    run_id=run.id,
                    task_key=f"overview:{offset}",
                    targets=targets[offset : offset + TASK_BLOCK_LIMIT],
                )
            )
        job.total = len(targets)
        return run.id
