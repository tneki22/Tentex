"""Один target — одна транзакция и receipt; ручное изменение всегда выигрывает."""

from dataclasses import asdict
from uuid import UUID

from sqlalchemy import func, select

from app.coverage.decisions import link_rejected
from app.coverage.lifecycle import fenced, stop_core
from app.coverage.snapshots import decisions_fingerprint, snapshot_current
from app.db import project_write_transaction
from app.models import (
    BackgroundJobState,
    Binding,
    BindingMechanism,
    BindingStatus,
    CoverageBlockResult,
    CoverageFinding,
    CoverageRun,
    CoverageTask,
    MaterialFragment,
    Project,
)


def publish_decision(session, token, task_id, checked):
    """Receipt сохраняет и неприменённый ответ, но не повторяет связи и счётчики."""
    run = session.get(CoverageRun, token.run_id)
    project_id = run.project_id
    with project_write_transaction(session, project_id):
        session.expire_all()
        task = session.get(CoverageTask, task_id)
        if task is None or task.run_id != token.run_id or checked.target_id not in task.targets:
            raise ValueError("task_scope")
        if checked.target_id in task.result:
            return task.result[checked.target_id]
        run, job = fenced(session, token, allow_pause=True)
        row = session.scalar(
            select(CoverageBlockResult).where(
                CoverageBlockResult.run_id == run.id,
                CoverageBlockResult.block_id == UUID(checked.target_id),
            )
        )
        receipt = {
            "decision": asdict(checked),
            "applied": False,
            "version": row.result_version + 1,
            "reason": None,
        }
        if not snapshot_current(session, run):
            receipt["reason"] = "snapshot_changed"
            stop_core(run, job, BackgroundJobState.CANCELLED, "snapshot_changed")
        elif job.pause_requested:
            receipt["reason"] = "pause_requested"
            # Ответ можно повторно проверить при resume; receipt ещё не завершён.
            return receipt
        elif decisions_fingerprint(session, project_id) != run.fingerprints["decisions"]:
            receipt["reason"] = "manual_conflict"
            if row.publication_state != "applied":
                row.publication_state = "conflict"
                row.reason = "manual_conflict"
                row.result = asdict(checked)
                row.work_state = "inspected" if checked.valid else "error"
                row.outcome = checked.outcome
            session.get(Project, project_id).coverage_revision += 1
        elif (
            task.kind == "refine"
            and (not checked.valid or not checked.replacement_allowed)
            and row.result
            and row.result["valid"]
        ):
            receipt["reason"] = "primary_preserved"
        else:
            _apply_result(session, run, task, row, checked, receipt)
        task.result = {**task.result, checked.target_id: receipt}
        if set(task.result) == set(task.targets):
            task.state = "finished"
        session.flush()
        job.done = session.scalar(
            select(func.count())
            .select_from(CoverageBlockResult)
            .where(
                CoverageBlockResult.run_id == run.id, CoverageBlockResult.work_state == "inspected"
            )
        )
        return receipt


def _apply_result(session, run, task, row, checked, receipt):
    """Исторический ответ хранится отдельно от защищённой текущей проекции связей."""
    if checked.valid:
        retained = set()
        for link in checked.links:
            binding = _publish_link(session, run, task, row, link)
            if binding:
                retained.add(binding.id)
        if checked.outcome != "unresolved":
            _retire_owned_links(session, run, row, retained)
        for finding in checked.findings:
            session.add(
                CoverageFinding(
                    project_id=run.project_id,
                    run_id=run.id,
                    kind=finding["kind"],
                    evidence_refs=[_evidence_ref(task, row, e) for e in finding["evidence"]],
                    payload=finding,
                    dependencies=run.fingerprints,
                )
            )
    row.result = asdict(checked)
    row.result_version += 1
    row.task_id = task.id
    row.work_state = "inspected" if checked.valid else "error"
    row.outcome = checked.outcome
    row.reason = checked.reason or None
    row.publication_state = "applied" if checked.valid else "rejected"
    receipt["applied"] = checked.valid
    receipt["reason"] = checked.reason or None
    project = session.get(Project, run.project_id)
    project.coverage_revision += 1


def _evidence_ref(task, row, evidence):
    return {
        "task_id": str(task.id),
        "result_id": str(row.id),
        "version": row.result_version + 1,
        "target_id": str(row.block_id),
        "key": evidence["key"],
    }


def _publish_link(session, run, task, row, link):
    """Никакого create_bindings: REMOVED, MANUAL и CONFIRMED неприкосновенны."""
    topic_id, fragment_id = UUID(link["topic_id"]), UUID(link["fragment_id"])
    fragment = session.get(MaterialFragment, fragment_id)
    binding = session.scalar(
        select(Binding).where(
            Binding.project_id == run.project_id,
            Binding.program_node_id == topic_id,
            Binding.fragment_id == fragment_id,
        )
    )
    owned_retired = (
        binding
        and binding.status == BindingStatus.ORPHANED
        and binding.mechanism == BindingMechanism.PASS_TWO
        and (binding.evidence_ref or {}).get("retired_reason") == "rechecked"
    )
    if binding and binding.status != BindingStatus.MACHINE and not owned_retired:
        return binding
    if link_rejected(session, run.project_id, topic_id, fragment):
        return None
    if owned_retired:
        binding.status = BindingStatus.MACHINE
    if binding is None:
        binding = Binding(
            project_id=run.project_id,
            program_node_id=topic_id,
            fragment_id=fragment_id,
            material_id=row.material_id,
            block_id=row.block_id,
            status=BindingStatus.MACHINE,
            mechanism=BindingMechanism.PASS_TWO,
        )
        session.add(binding)
    elif binding.mechanism != BindingMechanism.PASS_TWO and binding.semantic_kind not in {
        None,
        "unknown",
        link["semantic_kind"],
    }:
        session.add(
            CoverageFinding(
                project_id=run.project_id,
                run_id=run.id,
                kind="conflict",
                payload={"binding_id": str(binding.id), "proposed": link},
                evidence_refs=[_evidence_ref(task, row, link["evidence"][0])],
                dependencies=run.fingerprints,
            )
        )
        return binding
    binding.semantic_kind = (
        "context" if link["semantic_kind"] == "prerequisite" else link["semantic_kind"]
    )
    binding.roles = link["roles"]
    binding.semantic_revision = (binding.semantic_revision or 0) + 1
    binding.evidence_ref = _evidence_ref(task, row, link["evidence"][0])
    session.flush()
    return binding


def _retire_owned_links(session, run, row, retained):
    bindings = session.scalars(
        select(Binding).where(
            Binding.project_id == run.project_id,
            Binding.block_id == row.block_id,
            Binding.status == BindingStatus.MACHINE,
            Binding.mechanism == BindingMechanism.PASS_TWO,
        )
    )
    for binding in bindings:
        if binding.id not in retained:
            # ORPHANED — машинный пересмотр, REMOVED зарезервирован для выбора человека.
            binding.status = BindingStatus.ORPHANED
            binding.evidence_ref = {**(binding.evidence_ref or {}), "retired_reason": "rechecked"}
