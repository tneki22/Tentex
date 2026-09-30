"""Свободное изучение поверх учебниковой среды — docs/architecture/free-study-wizard.md."""

import json
from decimal import Decimal

import pytest
from conftest import link_material, make_free_project, make_material, make_topic_node
from sqlalchemy.orm import Session

from app.ai.gateway import ModelGateway
from app.ai.provider import FakeTransport, ProviderCompletion, ProviderUsage
from app.chat import common as chat_common
from app.chat import project_sessions
from app.exam import chat as exam_chat
from app.models import (
    ChatMessage,
    ChatMessageRole,
    ChatMode,
    ChatPayloadKind,
    ChatSession,
    ExaminerPersona,
    ExaminerStrictness,
    GoalPassport,
    GoalRole,
    ProgramBasisKind,
    ProgramNodeSourcePageRange,
    ProjectMaterial,
    StartingLevel,
)
from app.projects import program, program_chat


def test_program_hides_page_ranges_of_detached_material(session: Session) -> None:
    project = make_free_project(session)
    topic = make_topic_node(session, project, title="Свёртка")
    kept = make_material(session, "a1")
    detached = make_material(session, "b2")
    link_material(session, project, kept)
    link_material(session, project, detached)
    for material, page in ((kept, 3), (detached, 9)):
        session.add(ProgramNodeSourcePageRange(
            project_id=project.id,
            program_node_id=topic.id,
            material_id=material.id,
            source_name_snapshot=material.original_name,
            outline_item_key=f"{material.id}:1",
            page_from=page,
            page_to=page + 1,
        ))
    session.commit()
    session.delete(session.get(ProjectMaterial, (project.id, detached.id)))
    session.commit()

    state = program.read_program(session, project.id)
    ranges = next(node for node in state.nodes if node.id == topic.id).source_page_ranges
    assert [item.material_id for item in ranges] == [kept.id]


def test_project_chat_list_skips_program_sessions(session: Session) -> None:
    project = make_free_project(session)
    project_sessions.create_session(session, project.id, program_chat.CHANNEL)
    session.add(ChatSession(
        project_id=project.id,
        program_node_id=None,
        title="Свободное изучение",
        persona=ExaminerPersona.NEUTRAL_EXAMINER,
        strictness=ExaminerStrictness.NORMAL,
        mode=ChatMode.STUDY,
    ))
    session.commit()

    sessions = exam_chat.list_sessions(session, project.id, None)
    assert [chat.mode for chat in sessions] == [ChatMode.STUDY]


def _diff(session: Session, chat: ChatSession, operations: list[dict[str, object]]) -> ChatMessage:
    return chat_common.append_message(
        session, chat,
        role=ChatMessageRole.ASSISTANT,
        text="Предложение",
        payload_kind=ChatPayloadKind.PROGRAM_DIFF,
        payload={
            "summary": "Предложение", "pros": [], "cons": [],
            "operations": operations,
            "operation_states": ["pending"] * len(operations),
            "rejected": False,
        },
    )


@pytest.mark.asyncio
async def test_free_chat_without_materials_uses_free_prompt(
    session: Session, ai_config: str,
) -> None:
    del ai_config
    project = make_free_project(session)
    session.add(GoalPassport(
        project_id=project.id,
        goal="Разобраться в свёрточных сетях",
        starting_level=StartingLevel.BEGINNER,
    ))
    session.commit()
    chat = project_sessions.create_session(session, project.id, program_chat.CHANNEL)
    reply = {
        "summary": "Черновик программы", "pros": [], "cons": [],
        "operations": [{
            "op": "add", "parent_node_id": None, "after_node_id": None, "node_type": "topic",
            "title": "Операция свёртки", "rationale": "Ядро цели", "goal_role": "target",
            "search_queries": ["операция свёртки нейросети"], "material_kind": "lecture",
            "children": [],
        }],
    }
    fake = FakeTransport(completions=[ProviderCompletion(
        content=json.dumps(reply),
        actual_model_id="test/structured-model",
        usage=ProviderUsage(input_tokens=10, output_tokens=10, cost_usd=Decimal("0.001")),
    )])
    message = await program_chat.send_message(
        session, ModelGateway(session, fake), project.id, chat.id, "Составь программу по моей цели",
    )

    request = fake.complete_requests[0]
    assert "программу свободного" in request["messages"][0]["content"]
    assert "starting_level: beginner" in request["messages"][1]["content"]
    assert "(оглавления источников не переданы" in request["messages"][1]["content"]
    assert message.payload["operations"][0]["search_queries"] == ["операция свёртки нейросети"]


def test_free_apply_keeps_hints_only_for_topics_without_outline(session: Session) -> None:
    project = make_free_project(session)
    material = make_material(session, "c3")
    material.outline = [{"level": 1, "title": "Свёрточные сети", "page": 5}]
    session.commit()
    link_material(session, project, material)
    chat = project_sessions.create_session(session, project.id, program_chat.CHANNEL)
    message = _diff(session, chat, [
        {"op": "add", "node_type": "section", "title": "Основы", "goal_role": "prerequisite",
         "search_queries": ["основы нейросетей"], "material_kind": "textbook", "children": [
             {"op": "add", "node_type": "topic", "title": "Градиентный спуск",
              "goal_role": "prerequisite", "search_queries": ["градиентный спуск", "backprop"],
              "material_kind": "lecture", "children": []},
         ]},
        {"op": "add", "node_type": "topic", "title": "Свёрточные сети",
         "search_queries": ["свёрточные сети"], "material_kind": "article", "children": [],
         "outline_ref": {
             "material_id": str(material.id),
             "outline_item_key": f"{material.id}:embedded:0:5:1",
         }},
    ])

    result = program_chat.apply_proposal(
        session, project.id, message.id,
        program_chat.ProgramChatApplyWrite(selected=[0, 1], expected_program_revision=0),
    )
    by_title = {node.title: node for node in result.program.nodes}
    section, topic, from_outline = (
        by_title["Основы"], by_title["Градиентный спуск"], by_title["Свёрточные сети"],
    )
    assert section.goal_role == GoalRole.PREREQUISITE
    assert section.material_search_queries == [] and section.material_kind is None
    assert topic.needs_material and topic.goal_role == GoalRole.PREREQUISITE
    assert topic.material_search_queries == ["градиентный спуск", "backprop"]
    assert topic.material_kind == "lecture"
    assert from_outline.basis_kind == ProgramBasisKind.OUTLINE
    assert from_outline.material_search_queries == [] and not from_outline.needs_material

    action = result.latest_undoable_action
    assert action is not None
    undone = program.undo_last_project_action(session, project.id, action.sequence)
    assert not [node for node in undone.program.nodes if node.is_in_current_program]
