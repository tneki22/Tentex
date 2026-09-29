"""И7.3–7.4: одна находка, один снимок, одна отмена."""

from uuid import UUID

import pytest
from sqlalchemy import select

from app.coverage.findings import apply, list_proposed, preview, reject, was_rejected
from app.coverage.schemas import (
    FindingApply,
    FindingApplyResult,
    FindingPreviewRead,
    FindingPreviewRequest,
    FindingReject,
)
from app.coverage.validation import normalize_title
from app.models import (
    Binding,
    BindingMechanism,
    BindingStatus,
    CoverageDecision,
    CoverageFinding,
    ProgramNode,
)
from app.projects.errors import ProjectConflictError
from app.projects.program import undo_last_project_action
from tests.test_coverage import add_block, launch, setup_source


def proposal(session, project, material, parent, title="Хеширование", *, order=0, run_id=None):
    """Настоящие блок и фрагмент с находкой после бесплатной подставной публикации."""
    block, refs = add_block(session, material, [(title, "heading", None)], sort_order=order)
    if run_id is None:
        run_id, _, _, _ = launch(session, project, material)
    finding = CoverageFinding(
        project_id=project.id,
        run_id=run_id,
        kind="new_topic",
        payload={
            "operations": [{"op": "create", "title": title, "parent": str(parent.id)}],
            "evidence": [{"key": "n0_0", "ref": str(refs[0])}],
            "explanation": "Своя тема",
        },
        evidence_refs=[{"target_id": str(block.id), "key": "n0_0"}],
    )
    session.add(finding)
    session.commit()
    return finding, block, refs[0]


def apply_command(view, *, title=None, parent_id=None):
    return FindingApply(
        finding_ids=view["finding_ids"],
        block_ids=view["block_ids"],
        title=title or view["title"],
        parent_id=parent_id if parent_id is not None else view["parent_id"],
        fragment_ids=[item["id"] for item in view["fragments"]],
        remove_parent_binding_ids=view["remove_parent_binding_ids"],
        proposal_version=view["proposal_version"],
        expected_program_revision=view["program_revision"],
        expected_coverage_revision=view["coverage_revision"],
    )


def test_group_apply_and_undo_restore_program_bindings_and_findings(session):
    project, parent, material = setup_source(session, 0)
    first, block, fragment_id = proposal(session, project, material, parent)
    second, _, _ = proposal(
        session, project, material, parent, " хеширование ", order=1, run_id=first.run_id
    )
    old = Binding(
        project_id=project.id,
        program_node_id=parent.id,
        fragment_id=fragment_id,
        material_id=material.id,
        block_id=block.id,
        status=BindingStatus.CONFIRMED,
        mechanism=BindingMechanism.MANUAL,
        semantic_kind="content",
        roles=["explanation"],
    )
    session.add(old)
    session.commit()

    groups = list_proposed(session, project.id)["items"]
    assert len(groups) == 1 and set(groups[0]["finding_ids"]) == {str(first.id), str(second.id)}
    assert groups[0]["title"] == "Хеширование"
    FindingPreviewRead.model_validate(groups[0])
    result = apply(session, project.id, apply_command(groups[0]))
    FindingApplyResult.model_validate(result)
    assert result["program_revision"] == groups[0]["program_revision"] + 1
    assert result["coverage_revision"] == groups[0]["coverage_revision"] + 1
    new = session.get(ProgramNode, UUID(result["node_id"]))
    assert normalize_title(new.title) == normalize_title("Хеширование")
    assert new.parent_id == parent.id
    assert old.status == BindingStatus.REMOVED
    decision = session.scalar(
        select(CoverageDecision).where(
            CoverageDecision.kind == "reject_link", CoverageDecision.project_id == project.id
        )
    )
    assert decision.payload["rejected"] is True
    assert first.state == second.state == "applied"
    assert {
        row.status
        for row in session.scalars(select(Binding).where(Binding.program_node_id == new.id))
    } == {BindingStatus.CONFIRMED}

    undo_last_project_action(session, project.id, result["action_sequence"])
    assert project.program_revision == groups[0]["program_revision"] + 2
    assert not new.is_in_current_program and new.is_archived
    assert old.status == BindingStatus.CONFIRMED
    assert (
        session.scalar(
            select(CoverageDecision).where(
                CoverageDecision.kind == "reject_link", CoverageDecision.project_id == project.id
            )
        )
        is None
    )
    assert first.state == second.state == "proposed"
    assert not list(session.scalars(select(Binding).where(Binding.program_node_id == new.id)))


def test_apply_rejects_stale_program_and_coverage_revisions(session):
    project, parent, material = setup_source(session, 0)
    finding, _, _ = proposal(session, project, material, parent)
    view = preview(session, project.id, FindingPreviewRequest(finding_ids=[finding.id]))
    command = apply_command(view)
    command.expected_program_revision += 1
    with pytest.raises(ProjectConflictError) as error:
        apply(session, project.id, command)
    assert error.value.code == "stale_program_revision"
    assert finding.state == "proposed"
    command = apply_command(view)
    command.expected_coverage_revision += 1
    with pytest.raises(ProjectConflictError) as error:
        apply(session, project.id, command)
    assert error.value.code == "stale_coverage_revision"


def test_block_without_finding_creates_topic_from_selected_fragments(session):
    project, _, material = setup_source(session, 0)
    block, refs = add_block(session, material, [("Дек", "heading", None)], sort_order=0)
    view = preview(session, project.id, FindingPreviewRequest(block_ids=[block.id]))
    assert view["finding_ids"] == [] and view["block_ids"] == [str(block.id)]
    result = apply(session, project.id, apply_command(view, title="Дек"))
    binding = session.scalar(
        select(Binding).where(Binding.program_node_id == UUID(result["node_id"]))
    )
    assert binding.fragment_id == refs[0] and binding.status == BindingStatus.CONFIRMED
    undo_last_project_action(session, project.id, result["action_sequence"])
    assert (
        session.scalar(select(Binding).where(Binding.program_node_id == UUID(result["node_id"])))
        is None
    )


def test_reject_suppresses_same_anchors_new_anchor_returns_and_undo(session):
    project, parent, material = setup_source(session, 0)
    finding, _, fragment_id = proposal(session, project, material, parent)
    view = preview(session, project.id, FindingPreviewRequest(finding_ids=[finding.id]))
    result = reject(
        session,
        project.id,
        FindingReject(
            finding_ids=[finding.id],
            expected_coverage_revision=view["coverage_revision"],
            proposal_version=view["proposal_version"],
            feedback="Это заголовок раздела",
        ),
    )
    assert finding.state == "rejected" and finding.feedback["reason"] == "Это заголовок раздела"
    candidate = {
        "operations": [{"op": "create", "title": "ХЕШИРОВАНИЕ"}],
        "evidence": [{"ref": str(fragment_id)}],
    }
    assert was_rejected(session, project.id, candidate)
    _, new_refs = add_block(session, material, [("Новая опора", "paragraph", None)], sort_order=1)
    candidate["evidence"] = [{"ref": str(new_refs[0])}]
    assert not was_rejected(session, project.id, candidate)
    undo_last_project_action(session, project.id, result["action_sequence"])
    assert finding.state == "proposed" and finding.feedback is None


def test_apply_undo_refuses_a_binding_changed_after_application(session):
    project, parent, material = setup_source(session, 0)
    finding, _, _ = proposal(session, project, material, parent)
    view = preview(session, project.id, FindingPreviewRequest(finding_ids=[finding.id]))
    result = apply(session, project.id, apply_command(view))
    binding = session.scalar(
        select(Binding).where(Binding.program_node_id == UUID(result["node_id"]))
    )
    binding.roles = ["example"]
    session.commit()
    with pytest.raises(ProjectConflictError) as error:
        undo_last_project_action(session, project.id, result["action_sequence"])
    assert error.value.code == "coverage_undo_conflict"
