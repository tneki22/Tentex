"""Preflight и атомарное планирование полного manifest прохода 2."""

from math import ceil
from uuid import UUID, uuid4

from sqlalchemy import select

from app.ai.schemas import AiModelSelection
from app.ai.settings import resolve_model
from app.coverage.packets import (
    MAX_PACKET_TARGETS,
    build_packet_specs,
    input_token_budget,
)
from app.coverage.protocol import prompt_overhead_tokens
from app.coverage.queries import current_map
from app.coverage.schemas import RunPlan
from app.coverage.snapshots import (
    build_snapshot,
    fingerprint,
    manifest_rows,
    require_project,
)
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
# Статусы блока, при которых «Только нужное» читает его заново; результаты остальных
# блоков остаются актуальными (шаг 7.1) и запуск их не трогает.
NEEDS_RESEARCH = frozenset({"pending", "stale", "unresolved", "error"})
# Повтор по схеме и повтор транспорта тратят тот же бюджет, что и сам вызов.
GATEWAY_ATTEMPTS = 3


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


def scope_blocks(session, project_id, snapshot, plan) -> tuple[set[UUID], int, int]:
    """Область запуска: блоки, всего блоков источников и сколько из них «нужных».

    Полный запуск читает все блоки выбранных источников. «Только нужное» — те, что
    ждут обзора или его требуют (`pending`, `stale`, `unresolved`, `error`), и явные
    `block_ids`, например блоки родителя после создания новой темы.
    """
    materials = {source["id"] for source in snapshot["sources"]}
    blocks, _ = current_map(session, project_id)
    mine = [item for item in blocks if item["material_id"] in materials]
    every = {UUID(item["block_id"]) for item in mine}
    unknown = set(plan.block_ids) - every
    if unknown:
        raise ProjectDomainError(
            "Блок не входит в выбранные источники", status=422, code="coverage_block_unknown"
        )
    needed = {UUID(item["block_id"]) for item in mine if item["bucket"] in NEEDS_RESEARCH}
    needed |= set(plan.block_ids)
    return (needed if plan.mode == "incremental" else every), len(every), len(needed)


def _preflight_details(session, snapshot, fingerprints, plan, scope):
    overhead = prompt_overhead_tokens(snapshot["program"])
    try:
        roles = _resolve_roles(session, plan)
        budget = input_token_budget(roles["overview"]["context_length"], overhead)
        issue = None
    except ProjectDomainError as error:
        roles, budget, issue = {}, input_token_budget(None, overhead), error.detail
    # Область входит в отпечаток: блок, решённый после проверки, меняет «Только нужное».
    fingerprint_value = fingerprint(
        {
            "scope": fingerprints,
            "blocks": sorted(str(block_id) for block_id in scope),
            "model_roles": roles,
            "packet_input_tokens": budget,
        }
    )
    return roles, budget, issue, fingerprint_value


def preflight(session, project_id, plan):
    """Без платного вызова: снимок, диагностика источников и доступность ролей."""
    snapshot, fingerprints = build_snapshot(session, project_id, plan)
    scope, total, needed = scope_blocks(session, project_id, snapshot, plan)
    roles, budget, issue, fingerprint_value = _preflight_details(
        session, snapshot, fingerprints, plan, scope
    )
    blocks = len(scope)
    return {
        "fingerprint": fingerprint_value,
        "snapshot": snapshot,
        "blocks": blocks,
        "blocks_all": total,
        "blocks_needed": needed,
        "execution_available": issue is None,
        "execution_issue": issue,
        "model_roles": roles,
        "limits": plan.limits.model_dump(),
        # Предел выводится при запуске по готовым пакетам; здесь честная нижняя оценка.
        "packets_at_least": max(1, ceil(blocks / MAX_PACKET_TARGETS)),
        "prompt_overhead_tokens": prompt_overhead_tokens(snapshot["program"]),
        "packet_input_tokens": budget,
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
            # Прежний ID в ответ на другой запрос выглядел как «кнопка не работает»:
            # экран обновлялся, а область запуска оставалась чужой.
            raise ProjectConflictError(
                "Прежний запуск ещё не закончен: продолжите или отмените его",
                code="coverage_run_active",
                context={"run_id": str(active.id)},
            )
        plan = RunPlan.model_validate(
            command.model_dump(exclude={"request_key", "preflight_fingerprint"})
        )
        if plan.mode == "deep_program":
            raise ProjectConflictError(
                "Построение программы подключается отдельно", code="coverage_mode_unavailable"
            )
        snapshot, fingerprints = build_snapshot(session, project_id, plan)
        scope, _, _ = scope_blocks(session, project_id, snapshot, plan)
        roles, packet_budget, _, fingerprint_value = _preflight_details(
            session, snapshot, fingerprints, plan, scope
        )
        if fingerprint_value != command.preflight_fingerprint:
            raise ProjectConflictError(
                "Снимок изменился после проверки", code="coverage_snapshot_changed"
            )
        if not scope:
            raise ProjectConflictError(
                "Нечего исследовать: все блоки выбранных источников уже разобраны",
                code="coverage_scope_empty",
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
        manifest = list(manifest_rows(session, snapshot, only=scope))
        overhead = prompt_overhead_tokens(snapshot["program"])
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
        packets = build_packet_specs(session, manifest, packet_budget)
        for packet in packets:
            session.add(
                CoverageTask(
                    run_id=run.id,
                    task_key=packet.key,
                    targets=packet.targets,
                    checkpoint=packet.checkpoint,
                )
            )
        run.limits = resolved_limits(plan.limits, packets, overhead)
        job.total = len(manifest)
        return run.id


def resolved_limits(limits, packets, overhead) -> dict:
    """Выводит предел вызовов и токенов из готовых пакетов запуска.

    Плоские значения не знают размера книги: на одном учебнике они не расходуются,
    на другом останавливают обзор на середине. Денежный предел остаётся за человеком.
    """
    # Попытка schema repair переотправляет диалог вместе с предыдущим ответом, поэтому
    # попытка N стоит дороже первой. Равные попытки занижали предел втрое, и обзор
    # вставал на 102 блоках из 126 при потраченных $0,19 из $1.
    planned = 0
    for packet in packets:
        request = packet.checkpoint["input_tokens"] + overhead
        answer = packet.checkpoint["output_tokens"]
        planned += sum(request + attempt * answer for attempt in range(1, GATEWAY_ATTEMPTS + 1))
    return {
        "max_calls": limits.max_calls or len(packets) * GATEWAY_ATTEMPTS + 1,
        "max_total_tokens": limits.max_total_tokens or planned,
        "max_cost_usd": limits.max_cost_usd,
    }
