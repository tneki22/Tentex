"""И5: чтение опор, ручные решения и общий undo покрытия."""

from uuid import UUID, uuid4

import pytest
from sqlalchemy import event, select

from app.coverage.interaction import apply_decision, blocks_page, topic_evidence, topics_page
from app.coverage.queries import overview
from app.coverage.research import prepare_task, process_coverage_job, publish_packet
from app.coverage.schemas import DecisionWrite
from app.models import (
    Binding,
    BindingMechanism,
    BindingStatus,
    CoverageBlockResult,
    MaterialFragment,
)
from app.projects.errors import ProjectConflictError, ProjectDomainError
from app.projects.program import undo_last_project_action
from tests.conftest import make_topic_node
from tests.test_coverage import answer, first_task, launch, setup_source


def _decision(project, action, revision, **values):
    return DecisionWrite(
        request_key=str(uuid4()),
        expected_coverage_revision=revision,
        action=action,
        **values,
    )


def test_gaps_skip_chapters_whose_subtopics_carry_the_content(session):
    """Глава из оглавления не пробел: проход 2 привязывает блоки к её подтемам."""
    project, topic, material = setup_source(session, 3)
    chapter = make_topic_node(session, project, title="ТЕМА 3. Рынки благ")
    empty = make_topic_node(session, project, title="ТЕМА 17. Ничего не загружено")
    topic.parent_id = chapter.id
    session.commit()
    _, job, _, _ = launch(session, project, material)
    process_coverage_job(session, job, lambda task: answer(task, topic.id))

    gaps = topics_page(session, project.id, "gaps", 0, 10)
    assert [item["node_id"] for item in gaps["items"]] == [str(empty.id)]
    readable = topics_page(session, project.id, "readable", 0, 10)
    assert [item["node_id"] for item in readable["items"]] == [str(topic.id)]


def test_topic_groups_rank_preference_hide_legacy_and_gaps(session):
    project, topic, material = setup_source(session, 3)
    fragment_ids = list(session.scalars(select(MaterialFragment.id).order_by(MaterialFragment.id)))
    gap = make_topic_node(session, project, title="Планировщики")
    fragment = session.get(MaterialFragment, fragment_ids[0])
    session.add(
        Binding(
            project_id=project.id,
            program_node_id=gap.id,
            fragment_id=fragment.id,
            material_id=material.id,
            block_id=fragment.block_id,
            status=BindingStatus.MANUAL,
            mechanism=BindingMechanism.MANUAL,
            semantic_kind="mention",
            roles=["reference"],
        )
    )
    legacy_fragment = session.get(MaterialFragment, fragment_ids[1])
    session.add(
        Binding(
            project_id=project.id,
            program_node_id=gap.id,
            fragment_id=legacy_fragment.id,
            material_id=material.id,
            block_id=legacy_fragment.block_id,
            status=BindingStatus.MANUAL,
            mechanism=BindingMechanism.MANUAL,
            semantic_kind=None,
            roles=[],
        )
    )
    session.commit()
    _, job, _, _ = launch(session, project, material)
    process_coverage_job(session, job, lambda task: answer(task, topic.id))
    bindings = list(
        session.scalars(
            select(Binding)
            .where(Binding.program_node_id == topic.id)
            .order_by(Binding.fragment_id)
        )
    )
    bindings[0].roles = ["example"]
    bindings[1].roles = ["definition"]
    bindings[2].roles = ["explanation"]
    session.commit()

    gaps = topics_page(session, project.id, "gaps", 0, 10)
    assert [item["node_id"] for item in gaps["items"]] == [str(gap.id)]
    gap_groups = topic_evidence(session, project.id, gap.id)
    assert len(gap_groups["mentions"]) == 1
    assert len(gap_groups["legacy"]) == 1
    grouped = topic_evidence(session, project.id, topic.id)
    definition_id = grouped["starter"][0]["id"]
    example = grouped["practice"][0]
    assert grouped["best_evidence_id"] == definition_id

    receipt = apply_decision(
        session,
        project.id,
        _decision(
            project,
            "prefer",
            grouped["coverage_revision"],
            binding_id=example["binding_id"],
        ),
    )
    preferred = topic_evidence(session, project.id, topic.id)
    assert preferred["best_evidence_id"] == example["id"]
    assert topics_page(session, project.id, "readable", 0, 10)["items"][0][
        "best_evidence_id"
    ] == example["id"]
    hidden_receipt = apply_decision(
        session,
        project.id,
        _decision(
            project,
            "hide",
            receipt["coverage_revision"],
            binding_id=example["binding_id"],
        ),
    )
    hidden = topic_evidence(session, project.id, topic.id)
    assert hidden["best_evidence_id"] == definition_id
    assert hidden["hidden"][0]["id"] == example["id"]
    undo_last_project_action(session, project.id, hidden_receipt["action_sequence"])
    assert topic_evidence(session, project.id, topic.id)["best_evidence_id"] == example["id"]


def test_blocks_views_keep_outside_separate_and_paginated(session):
    project, topic, material = setup_source(session, 3)
    _, job, _, _ = launch(session, project, material)

    def executor(task):
        raw = answer(task, topic.id)
        raw[0] = {
            "target_id": task.targets[0],
            "outcome": "outside_program",
            "dispositions": [
                {
                    "fragment_id": next(
                        unit.ref for unit in task.seen.values() if unit.block_id == task.targets[0]
                    ),
                    "start": 0,
                    "end": len(
                        next(
                            unit.text
                            for unit in task.seen.values()
                            if unit.block_id == task.targets[0]
                        )
                    ),
                    "outcome": "outside_program",
                }
            ],
            "links": [],
        }
        raw[1]["links"][0]["roles"] = ["invalid"]
        return raw

    process_coverage_job(session, job, executor)
    outside = blocks_page(session, project.id, "outside_program", 0, 1)
    issues = blocks_page(session, project.id, "needs_action", 0, 1)
    assert outside["total"] == 1 and outside["items"][0]["bucket"] == "outside_program"
    assert issues["total"] == 1 and issues["items"][0]["bucket"] == "unresolved"
    assert outside["coverage_revision"] == issues["coverage_revision"]


def test_decision_idempotency_revision_conflict_and_undo_fingerprint(session):
    project, topic, material = setup_source(session, 1)
    _, job, _, _ = launch(session, project, material)
    process_coverage_job(session, job, lambda task: answer(task, topic.id))
    binding = session.scalar(select(Binding))
    command = _decision(
        project,
        "confirm",
        session.get(type(project), project.id).coverage_revision,
        binding_id=binding.id,
    )
    first = apply_decision(session, project.id, command)
    assert apply_decision(session, project.id, command) == first
    with pytest.raises(ProjectConflictError, match="Ключ запроса"):
        apply_decision(session, project.id, command.model_copy(update={"action": "hide"}))
    with pytest.raises(ProjectConflictError) as stale:
        apply_decision(
            session,
            project.id,
            _decision(project, "hide", first["coverage_revision"] - 1, binding_id=binding.id),
        )
    assert stale.value.code == "stale_coverage_revision"

    binding.roles = ["example"]
    session.commit()
    with pytest.raises(ProjectConflictError) as unsafe:
        undo_last_project_action(session, project.id, first["action_sequence"])
    assert unsafe.value.code == "coverage_undo_conflict"


def test_block_reassigns_to_multiple_topics_atomically_and_undoes(session):
    project, first_topic, material = setup_source(session, 1)
    second_topic = make_topic_node(session, project, title="Синхронизация")
    run_id, _, token, _ = launch(session, project, material)
    task = first_task(session, run_id)
    task_input = prepare_task(session, token, task.id)
    unit = next(iter(task_input.seen.values()))
    raw = [{
        "target_id": task_input.targets[0],
        "outcome": "outside_program",
        "dispositions": [{
            "fragment_id": unit.ref,
            "start": 0,
            "end": len(unit.text),
            "outcome": "outside_program",
        }],
        "links": [],
    }]
    publish_packet(session, token, task_input, raw)
    block_id = session.scalar(select(CoverageBlockResult.block_id))
    revision = blocks_page(session, project.id, "outside_program", 0, 10)["coverage_revision"]
    receipt = apply_decision(
        session,
        project.id,
        _decision(
            project,
            "reassign",
            revision,
            block_id=block_id,
            topic_ids=[first_topic.id, second_topic.id],
        ),
    )
    bindings = list(session.scalars(select(Binding)))
    assert {binding.program_node_id for binding in bindings} == {first_topic.id, second_topic.id}
    assert all(binding.status == BindingStatus.MANUAL for binding in bindings)
    assert blocks_page(session, project.id, "outside_program", 0, 10)["total"] == 0

    undo_last_project_action(session, project.id, receipt["action_sequence"])
    assert list(session.scalars(select(Binding))) == []
    assert blocks_page(session, project.id, "outside_program", 0, 10)["total"] == 1


def test_manual_decision_protects_active_publication(session):
    project, topic, material = setup_source(session, 1)
    run_id, _, token, _ = launch(session, project, material)
    task_input = prepare_task(session, token, first_task(session, run_id).id)
    fragment_id = next(iter(task_input.seen))
    fragment = next(iter(task_input.seen.values()))
    binding = Binding(
        project_id=project.id,
        program_node_id=topic.id,
        fragment_id=UUID(fragment_id),
        material_id=material.id,
        block_id=UUID(fragment.block_id),
        status=BindingStatus.MANUAL,
        mechanism=BindingMechanism.MANUAL,
        semantic_kind="content",
        roles=["explanation"],
    )
    session.add(binding)
    session.commit()
    revision = session.get(type(project), project.id).coverage_revision
    apply_decision(
        session,
        project.id,
        _decision(project, "confirm", revision, binding_id=binding.id),
    )
    publish_packet(session, token, task_input, answer(task_input, topic.id))
    row = session.scalar(select(CoverageBlockResult))
    assert row.publication_state == "conflict"
    assert binding.status == BindingStatus.CONFIRMED


def test_removed_binding_requires_explicit_restore_before_role_change(session):
    project, topic, material = setup_source(session, 1)
    _, job, _, _ = launch(session, project, material)
    process_coverage_job(session, job, lambda task: answer(task, topic.id))
    binding = session.scalar(select(Binding))
    revision = session.get(type(project), project.id).coverage_revision
    removed = apply_decision(
        session,
        project.id,
        _decision(project, "remove", revision, binding_id=binding.id),
    )

    with pytest.raises(ProjectDomainError) as invalid:
        apply_decision(
            session,
            project.id,
            _decision(
                project,
                "change_role",
                removed["coverage_revision"],
                binding_id=binding.id,
                role="definition",
            ),
        )
    assert invalid.value.code == "coverage_binding_removed"


def test_i5_http_contract_returns_revision_groups_detail_and_receipt(session):
    from fastapi.testclient import TestClient

    from app.db import get_session
    from app.main import create_app

    project, topic, material = setup_source(session, 1)
    _, job, _, _ = launch(session, project, material)
    process_coverage_job(session, job, lambda task: answer(task, topic.id))
    app = create_app()
    app.dependency_overrides[get_session] = lambda: session
    client = TestClient(app)
    base = f"/api/projects/{project.id}/coverage"

    topics = client.get(f"{base}/topics?view=readable").json()
    assert topics["coverage_revision"] >= 1
    assert topics["items"][0]["node_id"] == str(topic.id)
    grouped = client.get(f"{base}/topics/{topic.id}/evidence").json()
    evidence = grouped["starter"][0]
    detail = client.get(f"{base}/evidence/{evidence['id']}")
    assert detail.status_code == 200
    assert detail.json()["fragment_ids"] == [evidence["fragment_ids"][0]]

    receipt = client.post(
        f"{base}/decisions",
        json={
            "request_key": "http-confirm",
            "expected_coverage_revision": grouped["coverage_revision"],
            "action": "confirm",
            "binding_id": evidence["binding_id"],
        },
    )
    assert receipt.status_code == 200
    assert receipt.json()["coverage_revision"] == grouped["coverage_revision"] + 1


def test_coverage_read_queries_stay_bounded_as_bindings_grow(session):
    """Список опор не возвращается к одному SELECT тяжёлой задачи на каждую связь."""
    project, topic, material = setup_source(session, 24)
    _, job, _, _ = launch(session, project, material)
    process_coverage_job(session, job, lambda task: answer(task, topic.id))
    engine = session.get_bind()
    selects = 0

    def count_selects(_connection, _cursor, statement, _parameters, _context, _many):
        nonlocal selects
        selects += statement.lstrip().upper().startswith("SELECT")

    event.listen(engine, "before_cursor_execute", count_selects)
    try:
        overview(session, project.id)
        overview_selects = selects
        topics_page(session, project.id, "readable", 0, 24)
        topics_selects = selects - overview_selects
        topic_evidence(session, project.id, topic.id)
        evidence_selects = selects - overview_selects - topics_selects
    finally:
        event.remove(engine, "before_cursor_execute", count_selects)

    assert overview_selects <= 25
    assert topics_selects <= 18
    assert evidence_selects <= 18
