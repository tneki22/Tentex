"""Исполнитель И2: устойчивый цикл с подставным портом, без подключения модели."""

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select

from app.coverage.lifecycle import ExecutionToken, execution_boundary, fenced, stop_core
from app.coverage.publication import publish_decision
from app.coverage.snapshots import block_units, fingerprint, snapshot_current
from app.coverage.validation import CheckedDecision, validate_target
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
    targets: list[str]
    seen: dict
    topics: set[str]
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
        seen = {}
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
            seen.update(units)
            if row.work_state == "pending":
                row.work_state = "processing"
        task.state = "processing"
        task.dependencies = {
            "reads": [{"ref": u.ref, "hash": fingerprint(u.text)} for u in seen.values()],
            "inspected": [],
            "scope": run.fingerprints,
        }
        topics = {
            n["id"]
            for n in run.snapshot["program"]
            if n["is_in_current_program"] and not n["is_archived"] and n["node_type"] != "section"
        }
        return TaskInput(task.id, list(task.targets), seen, topics, task.kind)


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
        receipt = publish_decision(session, token, task_input.task_id, checked)
        if receipt["reason"] in {"snapshot_changed", "pause_requested"}:
            break


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
    """Никакого автоматического сетевого fallback; реальный адаптер — этап И3."""
    token = ExecutionToken(
        UUID(job.checkpoint["coverage_run_id"]),
        job.checkpoint["coverage_generation"],
        job.lease_owner,
    )
    try:
        while execution_boundary(session, token):
            task = _next_task(session, token.run_id)
            if task is None:
                _finish(session, token, BackgroundJobState.COMPLETED, "work_exhausted")
                return
            if executor is None:
                _finish(session, token, BackgroundJobState.PAUSED, "executor_unavailable")
                return
            task_input = prepare_task(session, token, task.id)
            # SQL-транзакция prepare_task завершена до входа во внешний порт.
            task = session.get(CoverageTask, task_input.task_id)
            saved = task.checkpoint.get("response")
            session.commit()
            raw = saved if "response" in task.checkpoint else executor(task_input)
            raw = _bounded_response(raw, task_input.targets)
            with job_write_transaction(session):
                fenced(session, token, allow_pause=True)
                task = session.get(CoverageTask, task_input.task_id)
                task.checkpoint = {**task.checkpoint, "response": raw}
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
