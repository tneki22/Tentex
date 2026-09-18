"""Устойчивый исполнитель первичного обзора через общий ModelGateway."""

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select

from app.coverage.lifecycle import ExecutionToken, execution_boundary, fenced, stop_core
from app.coverage.protocol import (
    CoverageOverviewExecutor,
    PacketExecution,
    expand_compact_response,
)
from app.coverage.publication import publish_decision
from app.coverage.snapshots import block_units, fingerprint, snapshot_current
from app.coverage.validation import CheckedDecision, Unit, validate_target
from app.db import job_write_transaction
from app.models import BackgroundJobState, CoverageBlockResult, CoverageTask
from app.projects.errors import ProjectConflictError

log = logging.getLogger("tentex.coverage")
# Предохранитель хранения одного решения; пакет содержит не больше 16 targets.
MAX_DECISION_BYTES = 512 * 1024


@dataclass(frozen=True)
class TaskInput:
    """Порт не получает SQL-сессию и не может публиковать непроверенный результат."""

    task_id: UUID
    project_id: UUID
    targets: list[str]
    seen: dict
    topics: set[str]
    target_refs: dict[str, list[str]]
    context_refs: list[str]
    target_aliases: dict[str, str]
    fragment_aliases: dict[str, str]
    ref_by_alias: dict[str, str]
    topic_aliases: dict[str, tuple[str, str]]
    topic_by_alias: dict[str, str]
    sections: dict[str, str]
    model_roles: dict
    scope: dict
    kind: str = "overview"


def prepare_task(session, token, task_id):
    """Чтение ревизии и фиксация dependencies в одном коротком snapshot."""
    with job_write_transaction(session):
        run, _ = fenced(session, token)
        if not snapshot_current(session, run):
            raise ProjectConflictError("Снимок изменился", code="coverage_snapshot_changed")
        task = session.get(CoverageTask, task_id)
        if task.run_id != run.id:
            raise ValueError("task_scope")
        seen: dict[str, Unit] = {}
        target_refs: dict[str, list[str]] = {}
        target_specs = task.checkpoint.get("target_specs", {})
        for target in task.targets:
            row = session.scalar(
                select(CoverageBlockResult).where(
                    CoverageBlockResult.run_id == run.id,
                    CoverageBlockResult.block_id == UUID(target),
                )
            )
            units = block_units(session, UUID(target))
            if any(
                u["id"] not in units or fingerprint(units[u["id"]].text) != u["hash"]
                for u in row.manifest["fragments"]
            ):
                raise ProjectConflictError(
                    "Текст снимка изменился", code="coverage_snapshot_changed"
                )
            spec = target_specs.get(target)
            if spec and spec.get("parts"):
                clipped = {}
                for part in spec["parts"]:
                    unit = units.get(part["ref"])
                    if unit is None:
                        raise ProjectConflictError(
                            "Текст снимка изменился", code="coverage_snapshot_changed"
                        )
                    start, end = part["start"], part["end"]
                    clipped[unit.ref] = Unit(
                        unit.ref,
                        unit.text[start:end],
                        unit.block_id,
                        unit.page_ref,
                        unit.kind,
                        unit.quality,
                        {**unit.locator, "text_start": start, "text_end": end},
                        start,
                    )
                units = clipped
            seen.update(units)
            target_refs[target] = list(units)
            if row.work_state == "pending":
                row.work_state = "processing"
        context_refs = []
        for ref in task.checkpoint.get("context_refs", []):
            if ref in seen:
                continue
            context = _context_unit(session, run, ref)
            if context is not None:
                seen[ref] = context
                context_refs.append(ref)
        task.state = "processing"
        task.dependencies = {
            "reads": [{"ref": u.ref, "hash": fingerprint(u.text)} for u in seen.values()],
            "inspected": [],
            "scope": run.fingerprints,
        }
        topic_rows = [
            n
            for n in run.snapshot["program"]
            if n["is_in_current_program"] and not n["is_archived"] and n["node_type"] != "section"
        ]
        topic_aliases = {
            n["id"]: (f"T{index}", n["title"]) for index, n in enumerate(topic_rows, 1)
        }
        target_aliases = {target: f"B{index}" for index, target in enumerate(task.targets, 1)}
        fragment_aliases = {ref: f"F{index}" for index, ref in enumerate(seen, 1)}
        return TaskInput(
            task.id,
            run.project_id,
            list(task.targets),
            seen,
            set(topic_aliases),
            target_refs,
            context_refs,
            target_aliases,
            fragment_aliases,
            {alias: ref for ref, alias in fragment_aliases.items()},
            topic_aliases,
            {alias: topic for topic, (alias, _) in topic_aliases.items()},
            {
                target: target_specs.get(target, {}).get("section_key", "Без заголовка")
                for target in task.targets
            },
            run.model_roles,
            run.fingerprints,
            task.kind,
        )


def _context_unit(session, run, ref: str) -> Unit | None:
    """Контекст читается только из проверенного manifest того же snapshot."""
    try:
        fragment_id = UUID(ref)
    except ValueError:
        return None
    rows = session.scalars(
        select(CoverageBlockResult).where(CoverageBlockResult.run_id == run.id)
    )
    row = next(
        (item for item in rows if any(part["id"] == ref for part in item.manifest["fragments"])),
        None,
    )
    if row is None:
        return None
    unit = block_units(session, row.block_id).get(str(fragment_id))
    expected = next(part["hash"] for part in row.manifest["fragments"] if part["id"] == ref)
    if unit is None or fingerprint(unit.text) != expected:
        raise ProjectConflictError("Текст снимка изменился", code="coverage_snapshot_changed")
    return unit


def publish_packet(session, token, task_input, raw):
    """Пакет может быть сломан целиком; каждый target всё равно получает свой receipt."""
    items = raw if isinstance(raw, list) else []
    for target in task_input.targets:
        candidates = [
            item
            for item in items
            if isinstance(item, dict) and str(item.get("target_id")) == target
        ]
        units = {ref: unit for ref, unit in task_input.seen.items() if unit.block_id == target}
        checked = validate_target(
            target,
            candidates,
            units,
            task_input.seen,
            set(),
            task_input.topics,
            origin=task_input.kind,
        )
        if not checked.valid:
            checked = _isolated_unresolved(checked, units)
        _apply_offsets(checked, units)
        receipt = publish_decision(session, token, task_input.task_id, checked)
        if receipt["reason"] in {"snapshot_changed", "pause_requested"}:
            break


def _isolated_unresolved(checked: CheckedDecision, units: dict[str, Unit]) -> CheckedDecision:
    """Ошибка одного ответа становится unresolved этого target, а не потерей пакета."""
    return CheckedDecision(
        target_id=checked.target_id,
        valid=True,
        outcome="unresolved",
        reason=f"invalid_decision:{checked.reason}",
        dispositions=[
            {
                "fragment_id": ref,
                "start": 0,
                "end": len(unit.text),
                "outcome": "unresolved",
            }
            for ref, unit in units.items()
        ],
        diagnostics=[*checked.diagnostics, {"reason": checked.reason}],
        origin=checked.origin,
        replacement_allowed=False,
    )


def _apply_offsets(checked: CheckedDecision, units: dict[str, Unit]) -> None:
    """Диапазоны интервала переводятся обратно в координаты исходного фрагмента."""
    for disposition in checked.dispositions:
        unit = units.get(disposition["fragment_id"])
        if unit is not None and unit.start_offset:
            disposition["start"] += unit.start_offset
            disposition["end"] += unit.start_offset


def _bounded_response(raw, targets):
    """Два ответа на target достаточно сохранить, чтобы доказать дубликат."""
    result, counts = [], {}
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict) or str(item.get("target_id")) not in targets:
            continue
        target = str(item["target_id"])
        counts[target] = counts.get(target, 0) + 1
        if counts[target] > 2:
            continue
        if len(json.dumps(item, ensure_ascii=False).encode()) > MAX_DECISION_BYTES:
            item = {"target_id": target, "error": "decision_too_large"}
        result.append(item)
    return result


def _next_task(session, run_id):
    return session.scalar(
        select(CoverageTask)
        .where(CoverageTask.run_id == run_id, CoverageTask.state != "finished")
        .order_by(CoverageTask.task_key)
        .limit(1)
    )


def process_coverage_job(session, job, executor: Callable[[TaskInput], list[dict]] | None = None):
    """Выполняет пакеты по порядку; тестовый порт остаётся явным швом."""
    token = ExecutionToken(
        UUID(job.checkpoint["coverage_run_id"]),
        job.checkpoint["coverage_generation"],
        job.lease_owner,
    )
    owned_executor = executor is None
    if owned_executor:
        with job_write_transaction(session):
            coverage_run, _ = fenced(session, token, allow_pause=True)
            has_model = bool(coverage_run.model_roles.get("overview"))
        if not has_model:
            _finish(session, token, BackgroundJobState.PAUSED, "executor_unavailable")
            return
    real_executor = CoverageOverviewExecutor(session, job.id, token) if owned_executor else executor
    try:
        while execution_boundary(session, token):
            task = _next_task(session, token.run_id)
            if task is None:
                _finish(session, token, BackgroundJobState.COMPLETED, "work_exhausted")
                return
            task_input = prepare_task(session, token, task.id)
            # SQL-транзакция prepare_task завершена до входа во внешний порт.
            task = session.get(CoverageTask, task_input.task_id)
            saved = task.checkpoint.get("response")
            session.commit()
            response = saved if "response" in task.checkpoint else real_executor(task_input)
            if isinstance(response, PacketExecution):
                raw = expand_compact_response(task_input, response.decisions)
                descriptions = response.section_descriptions
                call_receipt = response.call_receipt
            else:
                raw, descriptions, call_receipt = response, [], None
            raw = _bounded_response(raw, task_input.targets)
            with job_write_transaction(session):
                fenced(session, token, allow_pause=True)
                task = session.get(CoverageTask, task_input.task_id)
                checkpoint = {
                    **task.checkpoint,
                    "response": raw,
                    "section_descriptions": descriptions,
                }
                # call_receipts — бюджетный журнал шлюза с собственной формой записи;
                # трасса модели лежит рядом и не попадает в счёт попыток и токенов.
                if call_receipt:
                    checkpoint["calls"] = [*checkpoint.get("calls", []), call_receipt]
                task.checkpoint = checkpoint
            publish_packet(session, token, task_input, raw)
    except ProjectConflictError as error:
        if error.code == "coverage_lease_lost":
            log.info("stale worker stopped run=%s", token.run_id)
            return
        log.warning("coverage stopped run=%s code=%s", token.run_id, error.code)
        state = (
            BackgroundJobState.CANCELLED
            if error.code == "coverage_snapshot_changed"
            else BackgroundJobState.PAUSED
        )
        reason = (
            "budget_limit"
            if error.code == "coverage_budget_exhausted"
            else error.code.removeprefix("coverage_")
        )
        _finish(session, token, state, reason)
    except Exception as error:
        log.exception("coverage transport failed run=%s", token.run_id)
        try:
            _record_task_error(session, token, type(error).__name__)
            _finish(session, token, BackgroundJobState.FAILED, "execution_error")
        except ProjectConflictError:
            log.info("failed worker already fenced run=%s", token.run_id)
    finally:
        if owned_executor:
            real_executor.close()


def _finish(session, token, state, reason):
    with job_write_transaction(session):
        run, job = fenced(session, token, allow_pause=True)
        if state == BackgroundJobState.COMPLETED:
            if not snapshot_current(session, run):
                state, reason = BackgroundJobState.CANCELLED, "snapshot_changed"
            elif job.pause_requested:
                state, reason = BackgroundJobState.PAUSED, "user_pause"
        stop_core(run, job, state, reason)


def _record_task_error(session, token, reason):
    task = _next_task(session, token.run_id)
    if task:
        for target in task.targets:
            publish_decision(session, token, task.id, CheckedDecision(target, False, reason=reason))
