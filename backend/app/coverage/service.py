"""Preflight и атомарное планирование полного manifest прохода 2."""

from uuid import uuid4

from sqlalchemy import select

from app.ai.schemas import AiModelSelection
from app.ai.settings import resolve_model
from app.coverage.packets import build_packet_specs, input_token_budget
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
from app.projects.errors import ProjectConflictError, ProjectDomainError

ACTIVE = {BackgroundJobState.QUEUED, BackgroundJobState.RUNNING, BackgroundJobState.PAUSED}


def _role_override(plan, key):
    selection = plan.roles.get(key)
    if selection is None:
        return None
    return AiModelSelection(provider_id=selection.provider_id, model_id=selection.model_id)


def _resolve_roles(session, plan):
    """Обе роли требуют явной модели; default настроек сюда не просачивается."""
    result = {}
    for key, role in (("overview", "coverage_overview"), ("research", "coverage_research")):
        resolved = resolve_model(session, role, _role_override(plan, key))
        result[key] = {
            "provider_id": str(resolved.provider.id),
            "model_id": resolved.model_id,
            "model_source": resolved.source,
            "context_length": resolved.model.context_length,
            "prompt_version": resolved.role.prompt_version,
        }
    return result


def _preflight_details(session, fingerprints, plan):
    try:
        roles = _resolve_roles(session, plan)
        budget = input_token_budget(roles["overview"]["context_length"])
        issue = None
    except ProjectDomainError as error:
        roles, budget, issue = {}, input_token_budget(None), error.detail
    fingerprint_value = fingerprint(
        {"scope": fingerprints, "model_roles": roles, "packet_input_tokens": budget}
    )
    return roles, budget, issue, fingerprint_value


def preflight(session, project_id, plan):
    """Без платного вызова: снимок, диагностика источников и доступность ролей."""
    snapshot, fingerprints = build_snapshot(session, project_id, plan)
    roles, budget, issue, fingerprint_value = _preflight_details(session, fingerprints, plan)
    return {
        "fingerprint": fingerprint_value,
        "snapshot": snapshot,
        "blocks": sum(1 for _ in manifest_rows(session, snapshot)),
        "execution_available": issue is None,
        "execution_issue": issue,
        "model_roles": roles,
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
        roles, packet_budget, _, fingerprint_value = _preflight_details(
            session, fingerprints, plan
        )
        if fingerprint_value != command.preflight_fingerprint:
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
            model_roles=roles,
        )
        session.add(run)
        session.flush()
        manifest = list(manifest_rows(session, snapshot))
        for block, row_manifest in manifest:
            session.add(
                CoverageBlockResult(
                    run_id=run.id,
                    material_id=block.material_id,
                    material_revision=block.revision,
                    block_id=block.id,
                    sort_order=block.sort_order,
                    manifest=row_manifest,
                )
            )
        for packet in build_packet_specs(session, manifest, packet_budget):
            session.add(
                CoverageTask(
                    run_id=run.id,
                    task_key=packet.key,
                    targets=packet.targets,
                    checkpoint=packet.checkpoint,
                )
            )
        job.total = len(manifest)
        return run.id
