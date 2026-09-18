"""И2: инварианты публикации и restart без реального провайдера."""

from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.bindings.service import remove_binding
from app.coverage.budget import ResearchBudget, budget_usage
from app.coverage.lifecycle import ExecutionToken, control_run
from app.coverage.queries import evidence_read, overview, run_read
from app.coverage.research import prepare_task, process_coverage_job, publish_packet
from app.coverage.schemas import Evidence, RunControl, RunPlan, RunStart
from app.coverage.service import preflight, start_run
from app.coverage.validation import CheckedDecision, Unit, merge_refinement, repair_evidence
from app.materials.worker import claim_job
from app.models import (
    BackgroundJob,
    BackgroundJobState,
    Binding,
    BindingMechanism,
    BindingStatus,
    BlockClass,
    CoverageBlockResult,
    CoverageDecision,
    CoverageRun,
    CoverageTask,
    MaterialBlock,
    MaterialFragment,
    MaterialPage,
    PageQuality,
    Project,
    utc_now,
)
from app.projects.errors import ProjectConflictError, ProjectNotFoundError
from tests.conftest import link_material, make_material, make_textbook_project, make_topic_node


def setup_source(session, count=3):
    project = make_textbook_project(session)
    topic = make_topic_node(session, project, title="Потоки")
    material = make_material(session, uuid4().hex)
    link_material(session, project, material)
    page = MaterialPage(
        id=uuid4(),
        material_id=material.id,
        revision=1,
        page_number=1,
        width=100,
        height=100,
        quality=PageQuality.NATIVE,
    )
    session.add(page)
    session.flush()
    for index in range(count):
        block = MaterialBlock(
            id=uuid4(),
            material_id=material.id,
            revision=1,
            sort_order=index,
            block_class=BlockClass.CONTENT,
            page_from=1,
            page_to=1,
        )
        session.add(block)
        session.flush()
        session.add(
            MaterialFragment(
                id=uuid4(),
                material_id=material.id,
                page_id=page.id,
                block_id=block.id,
                sort_order=index,
                text=f"Потоки выполняют задачи {index}",
                bbox=[0, 0, 1, 1],
                element_kind="paragraph",
                quality=PageQuality.NATIVE,
            )
        )
    session.commit()
    return project, topic, material


def launch(session, project, material, **kwargs):
    plan = RunPlan(
        material_ids=[material.id], expected_program_revision=project.program_revision, **kwargs
    )
    command = RunStart(
        **plan.model_dump(),
        request_key=str(uuid4()),
        preflight_fingerprint=preflight(session, project.id, plan)["fingerprint"],
    )
    run_id = start_run(session, project.id, command)
    job = claim_job(session, "test-worker", "ai")
    assert job is not None
    token = ExecutionToken(run_id, job.checkpoint["coverage_generation"], job.lease_owner)
    return run_id, job, token, command


def answer(task_input, topic_id):
    result = []
    for target in task_input.targets:
        units = [u for u in task_input.seen.values() if u.block_id == target]
        result.append(
            {
                "target_id": target,
                "outcome": "linked",
                "dispositions": [
                    {"fragment_id": u.ref, "start": 0, "end": len(u.text), "outcome": "content"}
                    for u in units
                ],
                "links": [
                    {
                        "topic_id": str(topic_id),
                        "fragment_id": u.ref,
                        "semantic_kind": "content",
                        "roles": ["explanation"],
                        "evidence": [{"key": f"e{i}", "ref": u.ref}],
                    }
                    for i, u in enumerate(units)
                ],
            }
        )
    return result


def first_task(session, run_id):
    return session.scalar(
        select(CoverageTask).where(CoverageTask.run_id == run_id).order_by(CoverageTask.task_key)
    )


def test_100_blocks_error_missing_pause_restart_and_receipts(session):
    project, topic, material = setup_source(session, 100)
    run_id, job, token, command = launch(session, project, material)
    first = True
    calls = 0

    def executor(task_input):
        nonlocal first, calls
        calls += 1
        response = answer(task_input, topic.id)
        if first:
            first = False
            response[0]["links"][0]["roles"] = ["несуществующая_роль"]
            response.pop()
            control_run(
                session,
                project.id,
                run_id,
                RunControl(action="pause", expected_generation=token.generation),
            )
        return response

    process_coverage_job(session, job, executor)
    paused = run_read(session, project.id, run_id)
    assert paused["state"] == "paused"
    assert paused["primary"]["inspected"] == 0
    assert calls == 1
    assert start_run(session, project.id, command) == run_id
    engine = session.get_bind()
    # Новая SQL-сессия и новый owner имитируют полную потерю памяти worker.
    session.commit()
    with Session(engine, expire_on_commit=False) as restarted:
        control_run(
            restarted,
            project.id,
            run_id,
            RunControl(action="resume", expected_generation=token.generation),
        )
        next_job = claim_job(restarted, "restarted", "ai")
        process_coverage_job(restarted, next_job, executor)
        result = run_read(restarted, project.id, run_id)
        assert result["state"] == "completed"
        assert result["primary"] == {
            "total": 100,
            "inspected": 98,
            "error": 2,
            "pending": 0,
            "processing": 0,
        }
        assert restarted.get(BackgroundJob, job.id).done == 98
        assert sum(result["outcomes"].values()) + result["primary"]["error"] == 100
        assert calls == 7  # Сохранённый первый ответ не вызывает executor повторно.
        assert restarted.scalar(select(func.count()).select_from(Binding)) == 98
        assert sum(overview(restarted, project.id)["distribution"].values()) == 100


def test_isolation_receipt_idempotency_and_original_text(session):
    project, topic, material = setup_source(session)
    run_id, _, token, _ = launch(session, project, material)
    task_input = prepare_task(session, token, first_task(session, run_id).id)
    raw = answer(task_input, topic.id)
    raw[0]["links"][0]["evidence"][0]["quote"] = "Потоки ... задачи"
    raw[1]["links"][0]["evidence"][0]["quote"] = "небылица без соответствия"
    publish_packet(session, token, task_input, raw)
    revision = session.get(Project, project.id).coverage_revision
    publish_packet(session, token, task_input, raw)
    assert session.get(Project, project.id).coverage_revision == revision
    assert session.scalar(select(func.count()).select_from(Binding)) == 2
    ref = next(iter(task_input.seen.values()))
    evidence = evidence_read(session, project.id, f"{task_input.task_id}:{ref.block_id}:e0")
    assert evidence["quote"] == ref.text
    assert evidence["repair"] == "approximate"
    other = make_textbook_project(session)
    with pytest.raises(ProjectNotFoundError):
        evidence_read(session, other.id, evidence["id"])


def test_quote_ladder_and_read_scope():
    unit = Unit("own", r"Значение $$x \in A$$ определено", "b", "page:m:1")
    neighbor = Unit("neighbor", "11.4. Процессы и потоки в Windows", "c", "page:m:1")
    evidence = Evidence(key="e", ref="own", quote=r"\(x ∈ A\)")
    checked = repair_evidence(evidence, {"own": unit}, set())
    assert checked["repair"] == "normalized" and checked["quote"] == unit.text
    evidence = Evidence(key="e", ref="own", quote=neighbor.text)
    assert repair_evidence(evidence, {"own": unit}, set()) is None
    checked = repair_evidence(evidence, {"own": unit, "neighbor": neighbor}, set())
    assert checked["ref"] == "neighbor" and checked["repair"] == "ref_corrected"
    assert (
        repair_evidence(
            Evidence(key="e", ref="own", quote="выдуманное значение"), {"own": unit}, set()
        )
        is None
    )


def test_primary_survives_failed_refinement(session):
    project, topic, material = setup_source(session, 1)
    run_id, _, token, _ = launch(session, project, material)
    task_input = prepare_task(session, token, first_task(session, run_id).id)
    publish_packet(session, token, task_input, answer(task_input, topic.id))
    primary = session.scalar(select(CoverageBlockResult))
    previous = primary.task_id
    refine = CoverageTask(
        run_id=run_id, kind="refine", task_key="refine:1", targets=task_input.targets
    )
    session.add(refine)
    session.commit()
    refine_input = prepare_task(session, token, refine.id)
    publish_packet(session, token, refine_input, [])
    assert primary.task_id == previous and primary.outcome == "linked"
    assert refine.result[task_input.targets[0]]["reason"] == "primary_preserved"
    checked = CheckedDecision(task_input.targets[0], True, "service")
    assert merge_refinement(checked, None) is checked


def test_lease_fencing_and_snapshot_change(session):
    project, topic, material = setup_source(session, 1)
    run_id, job, token, _ = launch(session, project, material)
    task_input = prepare_task(session, token, first_task(session, run_id).id)
    stored_job = session.get(BackgroundJob, job.id)
    stored_job.lease_expires_at = utc_now() - timedelta(seconds=1)
    session.commit()
    replacement = claim_job(session, "replacement", "ai")
    assert replacement.checkpoint["coverage_generation"] == 2
    with pytest.raises(ProjectConflictError, match="Worker"):
        publish_packet(session, token, task_input, answer(task_input, topic.id))
    next_token = ExecutionToken(run_id, 2, "replacement")
    material.active_parse_revision = 2
    session.commit()
    publish_packet(session, next_token, task_input, answer(task_input, topic.id))
    assert session.get(BackgroundJob, job.id).state == BackgroundJobState.CANCELLED
    assert session.get(CoverageRun, run_id).stop_reason == "snapshot_changed"
    assert session.scalar(select(func.count()).select_from(Binding)) == 0


def test_manual_removal_wins_and_survives_binding_delete(session):
    project, topic, material = setup_source(session, 1)
    run_id, _, token, _ = launch(session, project, material)
    task_input = prepare_task(session, token, first_task(session, run_id).id)
    fragment_id = UUID(next(iter(task_input.seen)))
    binding = Binding(
        project_id=project.id,
        program_node_id=topic.id,
        fragment_id=fragment_id,
        material_id=material.id,
        status=BindingStatus.MANUAL,
        mechanism=BindingMechanism.MANUAL,
    )
    session.add(binding)
    session.commit()
    remove_binding(session, project.id, binding.id)
    publish_packet(session, token, task_input, answer(task_input, topic.id))
    assert binding.status == BindingStatus.REMOVED
    assert session.scalar(select(CoverageBlockResult)).publication_state == "conflict"
    assert session.scalar(select(CoverageDecision)).payload["rejected"]
    session.delete(binding)
    session.commit()
    assert session.scalar(select(CoverageDecision)).payload["rejected"]


def test_current_queries_ignore_pending_runs_and_display_order(session):
    project, topic, material = setup_source(session, 1)
    run_id, job, _, _ = launch(session, project, material)
    process_coverage_job(session, job, lambda task: answer(task, topic.id))
    assert overview(session, project.id)["topics"]["with_content"] == 1
    topic.sort_order = 9
    session.commit()
    assert not run_read(session, project.id, run_id)["stale"]
    launch(session, project, material)
    assert overview(session, project.id)["distribution"]["linked"] == 1
    topic.title = "Другой смысл"
    session.commit()
    assert overview(session, project.id)["distribution"]["stale"] == 1
    assert overview(session, project.id)["topics"]["with_content"] == 0


def test_budget_is_shared_persistent_and_counts_uncertain_attempts(session):
    project, _, material = setup_source(session)
    run_id, _, token, _ = launch(session, project, material, limits={"max_calls": 2})
    task = first_task(session, run_id)
    budget = ResearchBudget(session, token, task.id)
    first = budget.reserve(100, None)
    budget.settle(first, None)
    budget.reserve(200, None)
    with pytest.raises(ProjectConflictError) as error:
        ResearchBudget(session, token, task.id).reserve(1, None)
    assert error.value.code == "coverage_budget_exhausted"
    assert budget_usage(session, run_id) == {
        "calls": 2,
        "tokens": 300,
        "cost_usd": 0,
        "uncertain_calls": 2,
    }


def test_existing_manual_removed_and_other_machine_mechanism_are_preserved(session):
    project, topic, material = setup_source(session)
    fragments = list(
        session.scalars(select(MaterialFragment).order_by(MaterialFragment.sort_order))
    )
    statuses = [BindingStatus.MANUAL, BindingStatus.REMOVED, BindingStatus.MACHINE]
    for fragment, status in zip(fragments, statuses, strict=True):
        session.add(
            Binding(
                project_id=project.id,
                program_node_id=topic.id,
                fragment_id=fragment.id,
                material_id=material.id,
                block_id=fragment.block_id,
                status=status,
                mechanism=BindingMechanism.SEARCH,
            )
        )
    session.commit()
    _, job, _, _ = launch(session, project, material)
    process_coverage_job(session, job, lambda task: answer(task, topic.id))
    bindings = list(session.scalars(select(Binding).order_by(Binding.fragment_id)))
    assert len(bindings) == 3
    assert {b.mechanism for b in bindings} == {BindingMechanism.SEARCH}
    manual = next(b for b in bindings if b.status == BindingStatus.MANUAL)
    assert manual.semantic_kind is None
    assert next(b for b in bindings if b.status == BindingStatus.MACHINE).semantic_kind == "content"
    assert overview(session, project.id)["distribution"]["unresolved"] == 2


def test_new_run_obeys_durable_rejection_after_binding_was_deleted(session):
    from app.coverage.decisions import remember_binding_choice

    project, topic, material = setup_source(session, 1)
    fragment = session.scalar(select(MaterialFragment))
    binding = Binding(
        project_id=project.id,
        program_node_id=topic.id,
        fragment_id=fragment.id,
        material_id=material.id,
        block_id=fragment.block_id,
        status=BindingStatus.REMOVED,
        mechanism=BindingMechanism.MANUAL,
    )
    session.add(binding)
    session.flush()
    remember_binding_choice(session, binding)
    session.delete(binding)
    session.commit()
    _, job, _, _ = launch(session, project, material)
    process_coverage_job(session, job, lambda task: answer(task, topic.id))
    assert session.scalar(select(func.count()).select_from(Binding)) == 0
    assert overview(session, project.id)["distribution"]["unresolved"] == 1


def test_partial_fragment_failure_keeps_valid_link_and_unknown_remainder(session):
    project, topic, material = setup_source(session, 1)
    original = session.scalar(select(MaterialFragment))
    extra = MaterialFragment(
        material_id=material.id,
        page_id=original.page_id,
        block_id=original.block_id,
        sort_order=1,
        text="Другой фрагмент",
        bbox=[0, 0, 1, 1],
        element_kind="paragraph",
        quality=PageQuality.NATIVE,
    )
    session.add(extra)
    session.commit()
    run_id, _, token, _ = launch(session, project, material)
    task_input = prepare_task(session, token, first_task(session, run_id).id)
    raw = answer(task_input, topic.id)
    raw[0]["links"][1]["evidence"][0]["quote"] = "совершенно выдуманная цитата"
    publish_packet(session, token, task_input, raw)
    row = session.scalar(select(CoverageBlockResult))
    assert row.work_state == "inspected" and row.outcome == "unresolved"
    assert row.result["dispositions"][1]["outcome"] == "unresolved"
    assert session.scalar(select(func.count()).select_from(Binding)) == 1


def test_default_handler_is_offline_and_cancel_from_registry_handles_pause(session, monkeypatch):
    from app.background.registry import cancel_job

    project, _, material = setup_source(session, 1)
    run_id, job, _, _ = launch(session, project, material)
    process_coverage_job(session, job)
    assert run_read(session, project.id, run_id)["stop_reason"] == "executor_unavailable"
    assert cancel_job(session, job.id).state == BackgroundJobState.CANCELLED


def test_current_count_does_not_promote_mentions_or_exercise_to_reading_basis(session):
    project, topic, material = setup_source(session, 2)
    _, job, _, _ = launch(session, project, material)

    def executor(task):
        raw = answer(task, topic.id)
        raw[0]["links"][0].update(semantic_kind="mention", roles=["reference"])
        raw[0]["dispositions"][0]["outcome"] = "mention"
        raw[1]["links"][0]["roles"] = ["exercise"]
        return raw

    process_coverage_job(session, job, executor)
    summary = overview(session, project.id)
    assert summary["topics"] == {"total": 1, "with_content": 1, "reading_basis": 0, "legacy": 0}
    assert summary["material_ratio"]["numerator"] == 1


def test_api_offline_preflight_scope_and_request_key_conflict(session):
    from fastapi.testclient import TestClient

    from app.db import get_session
    from app.main import create_app

    project, _, material = setup_source(session, 1)
    app = create_app()
    app.dependency_overrides[get_session] = lambda: session
    client = TestClient(app)
    base = f"/api/projects/{project.id}/coverage"
    plan = {"material_ids": [str(material.id)], "expected_program_revision": 0}
    checked = client.post(f"{base}/preflight", json=plan)
    assert checked.status_code == 200 and not checked.json()["execution_available"]
    command = {
        **plan,
        "request_key": "same-key",
        "preflight_fingerprint": checked.json()["fingerprint"],
    }
    started = client.post(f"{base}/runs", json=command)
    assert started.status_code == 202
    assert client.post(f"{base}/runs", json=command).json()["id"] == started.json()["id"]
    command["limits"] = {"max_calls": 1}
    assert client.post(f"{base}/runs", json=command).status_code == 409
    other = make_textbook_project(session)
    assert (
        client.get(f"/api/projects/{other.id}/coverage/runs/{started.json()['id']}").status_code
        == 404
    )
    assert client.get(f"{base}/overview").json()["total"] == 1
