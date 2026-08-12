import json
from decimal import Decimal

import pytest
from conftest import make_exam_project
from sqlalchemy.orm import Session

from app.ai.gateway import ModelGateway
from app.ai.provider import FakeTransport, ProviderCompletion, ProviderUsage
from app.models import ExamKind, NodeType, ProgramNode, utc_now
from app.projects import program, program_ai
from app.projects.errors import ProjectDomainError


def _nodes(session: Session, project_id) -> list[ProgramNode]:
    nodes = []
    for index in range(6):
        node = ProgramNode(
            project_id=project_id,
            parent_id=None,
            node_type=NodeType.TOPIC,
            exam_kind=ExamKind.QUESTION,
            sort_order=index,
            title=f"Вопрос номер {index + 1}",
            is_in_current_program=True,
            is_archived=False,
            created_at=utc_now(),
            updated_at=utc_now(),
        )
        session.add(node)
        nodes.append(node)
    session.commit()
    return nodes


def _completion(nodes: list[ProgramNode]) -> ProviderCompletion:
    payload = {
        "groups": [
            {
                "title": "Основы дисциплины",
                "rationale": "Базовые вопросы",
                "node_ids": [str(node.id) for node in nodes[:3]],
            },
            {
                "title": "Практические вопросы",
                "rationale": "Прикладная часть",
                "node_ids": [str(node.id) for node in nodes[3:]],
            },
        ]
    }
    return ProviderCompletion(
        content=json.dumps(payload),
        actual_model_id="test/structured-model",
        usage=ProviderUsage(
            input_tokens=100,
            output_tokens=50,
            cost_usd=Decimal("0.003"),
        ),
    )


@pytest.mark.asyncio
async def test_grouping_run_apply_and_common_undo(session: Session, ai_config: str) -> None:
    del ai_config
    project = make_exam_project(session)
    nodes = _nodes(session, project.id)
    original_ids = {node.id for node in nodes}
    fake = FakeTransport(completions=[_completion(nodes)])
    gateway = ModelGateway(session, fake)
    preview = await program_ai.preflight(session, gateway, project.id)
    run = await program_ai.run(
        session,
        gateway,
        project.id,
        program_ai.ProgramGroupingRunWrite(
            expected_program_revision=preview.program_revision,
            expected_source_hash=preview.source_hash,
        ),
    )
    result = program_ai.apply(
        session,
        project.id,
        program_ai.ProgramGroupingApplyWrite(
            run_id=run.run_id,
            expected_program_revision=preview.program_revision,
            expected_source_hash=preview.source_hash,
            groups=run.suggestion.groups,
        ),
    )
    assert result.program.revision == 1
    assert len([node for node in result.program.nodes if node.node_type == NodeType.SECTION]) == 2
    assert {
        node.id for node in result.program.nodes if node.node_type == NodeType.TOPIC
    } == original_ids
    action = result.latest_undoable_action
    assert action is not None and action.action_type == "ai_program_grouping"
    undone = program.undo_last_project_action(session, project.id, action.sequence)
    assert all(node.parent_id is None for node in undone.program.nodes)
    assert {node.id for node in undone.program.nodes} == original_ids


def test_grouping_rejects_missing_duplicate_and_foreign_ids(
    session: Session, ai_config: str
) -> None:
    del ai_config
    project = make_exam_project(session)
    nodes = _nodes(session, project.id)
    suggestion = program_ai.ProgramGroupingSuggestion(
        groups=[
            program_ai.GroupSuggestionItem(
                title="Первая группа",
                rationale="",
                node_ids=[nodes[0].id, nodes[1].id, nodes[2].id],
            ),
            program_ai.GroupSuggestionItem(
                title="Вторая группа",
                rationale="",
                node_ids=[nodes[2].id, nodes[3].id, nodes[4].id],
            ),
        ]
    )
    with pytest.raises(ProjectDomainError):
        program_ai.validate_suggestion(suggestion, {node.id for node in nodes})


@pytest.mark.asyncio
async def test_grouping_cache_and_revision_invalidation(session: Session, ai_config: str) -> None:
    del ai_config
    project = make_exam_project(session)
    nodes = _nodes(session, project.id)
    fake = FakeTransport(completions=[_completion(nodes)])
    gateway = ModelGateway(session, fake)
    preview = await program_ai.preflight(session, gateway, project.id)
    command = program_ai.ProgramGroupingRunWrite(
        expected_program_revision=preview.program_revision,
        expected_source_hash=preview.source_hash,
    )
    first = await program_ai.run(session, gateway, project.id, command)
    second = await program_ai.run(session, gateway, project.id, command)
    assert first.cached is False and second.cached is True
    assert fake.complete_calls == 1
    project.program_revision += 1
    session.commit()
    with pytest.raises(ProjectDomainError) as caught:
        await program_ai.run(session, gateway, project.id, command)
    assert caught.value.code == "stale_program_revision"
