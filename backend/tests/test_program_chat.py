"""Чат построения программы учебника — часть 2 вертикали «Программа учебника»."""

import json
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from app.ai.gateway import ModelGateway
from app.ai.jobs import process_ai_job
from app.ai.provider import FakeTransport, ProviderCompletion, ProviderUsage
from app.background.registry import get_job
from app.chat import common as chat_common
from app.models import (
    BackgroundJob,
    BackgroundJobState,
    ChatMessage,
    ChatMessageRole,
    ChatMode,
    ChatPayloadKind,
    ChatSession,
    ChatToolRun,
    Material,
    MaterialSourceKind,
    MaterialState,
    NodeType,
    ProgramBasisKind,
    ProgramNode,
    ProgramNodeSourcePageRange,
    Project,
    ProjectMaterial,
    ProjectStatus,
    SourceRole,
    TemplateKey,
    WorkspaceVariant,
    utc_now,
)
from app.projects import program, program_chat
from app.projects.errors import ProjectConflictError, ProjectDomainError


def _project(session: Session, *, status: ProjectStatus = ProjectStatus.ACTIVE) -> Project:
    project = Project(
        template_key=TemplateKey.TEXTBOOK,
        workspace_variant=WorkspaceVariant.TEXTBOOK,
        status=status,
        name="Учебник",
    )
    session.add(project)
    session.commit()
    return project


def _material(
    session: Session,
    project: Project,
    name: str,
    *,
    priority: int = 0,
    outline: list[dict[str, object]] | None = None,
) -> Material:
    digest = uuid4().hex * 2
    material = Material(
        sha256=digest,
        original_name=name,
        storage_path=f"text/{uuid4()}.txt",
        media_type="text/plain",
        source_kind=MaterialSourceKind.TEXT,
        size_bytes=100,
        page_count=40,
        status=MaterialState.READY,
        outline=outline or [],
    )
    session.add(material)
    session.flush()
    session.add(
        ProjectMaterial(
            project_id=project.id,
            material_id=material.id,
            source_role=SourceRole.MAIN if priority == 0 else SourceRole.ADDITIONAL,
            priority=priority,
            affects_program=True,
            display_name=name,
            purposes=["study_source"],
            created_at=utc_now(),
        )
    )
    session.commit()
    return material


def _node(session: Session, project: Project, title: str, **fields: object) -> ProgramNode:
    node = ProgramNode(
        project_id=project.id,
        parent_id=fields.get("parent_id"),
        node_type=fields.get("node_type", NodeType.TOPIC),
        sort_order=fields.get("sort_order", 0),
        title=title,
        is_in_current_program=True,
        needs_material=False,
        is_archived=False,
        basis_kind=fields.get("basis_kind", ProgramBasisKind.CUSTOM),
        created_at=utc_now(),
        updated_at=utc_now(),
    )
    session.add(node)
    session.commit()
    return node


def _reply_completion(
    summary: str, operations: list[dict[str, object]], *, pros: list[str] | None = None,
) -> ProviderCompletion:
    payload = {"summary": summary, "pros": pros or [], "cons": [], "operations": operations}
    return ProviderCompletion(
        content=json.dumps(payload),
        actual_model_id="test/structured-model",
        usage=ProviderUsage(input_tokens=50, output_tokens=50, cost_usd=Decimal("0.001")),
    )


def test_create_session_requires_textbook_project_but_allows_draft(
    session: Session, ai_config: str,
) -> None:
    del ai_config
    exam_project = Project(
        template_key=TemplateKey.EXAM, workspace_variant=WorkspaceVariant.EXAM,
        status=ProjectStatus.ACTIVE, name="Экзамен",
    )
    session.add(exam_project)
    session.commit()
    with pytest.raises(ProjectDomainError):
        program_chat.create_session(session, exam_project.id)

    draft_project = _project(session, status=ProjectStatus.DRAFT)
    chat = program_chat.create_session(session, draft_project.id)
    assert chat.program_node_id is None
    assert chat.mode == ChatMode.PROGRAM
    assert chat.context_flags == program_chat.default_context_flags()


@pytest.mark.asyncio
async def test_send_message_creates_program_diff_message(session: Session, ai_config: str) -> None:
    del ai_config
    project = _project(session)
    chat = program_chat.create_session(session, project.id)
    chat.draft_text = "Составь программу"
    session.commit()
    fake = FakeTransport(completions=[
        _reply_completion("Добавим раздел", [
            {"op": "add", "parent_node_id": None, "after_node_id": None, "node_type": "section",
             "title": "Введение", "rationale": "Нужен обзорный раздел", "children": []},
        ]),
    ])
    gateway = ModelGateway(session, fake)
    message = await program_chat.send_message(
        session, gateway, project.id, chat.id, "Составь программу",
    )
    assert message.payload_kind == ChatPayloadKind.PROGRAM_DIFF
    assert message.payload["operations"][0]["op"] == "add"
    assert message.payload["operation_states"] == ["pending"]
    session.refresh(chat)
    assert chat.draft_text == ""
    request = fake.complete_requests[0]
    assert "oneOf" not in json.dumps(request["response_schema"])
    schema = request["response_schema"]
    assert set(schema["required"]) == set(schema["properties"])


def test_outline_build_runs_as_background_job_and_appends_message(
    session: Session, ai_config: str,
) -> None:
    del ai_config
    project = _project(session)
    chat = program_chat.create_session(session, project.id)
    fake = FakeTransport(completions=[
        _reply_completion("Программа по оглавлению", [
            {"op": "add", "parent_node_id": None, "after_node_id": None, "node_type": "section",
             "title": "Раздел 1", "rationale": "Из оглавления", "children": []},
        ]),
    ])
    gateway = ModelGateway(session, fake)
    start = program_chat.start_build(
        session, project.id, chat.id,
        program_chat.ProgramChatBuildWrite(scenario="outline", expected_program_revision=0),
    )
    job = session.get(BackgroundJob, start.job_id)
    assert job is not None
    process_ai_job(session, job, gateway)
    refreshed = get_job(session, start.job_id)
    assert refreshed.state == BackgroundJobState.COMPLETED

    detail = program_chat.get_session_detail(session, project.id, chat.id)
    assert len(detail.messages) == 1
    assert detail.messages[0].payload_kind == ChatPayloadKind.PROGRAM_DIFF


def test_goal_build_records_tool_run(session: Session, ai_config: str) -> None:
    del ai_config
    project = _project(session)
    chat = program_chat.create_session(session, project.id)
    fake = FakeTransport(completions=[
        ProviderCompletion(
            content=json.dumps({"queries": ["транспортный уровень"]}),
            actual_model_id="test/structured-model",
            usage=ProviderUsage(input_tokens=10, output_tokens=10),
        ),
        _reply_completion("Программа по цели", []),
    ])
    gateway = ModelGateway(session, fake)
    start = program_chat.start_build(
        session, project.id, chat.id,
        program_chat.ProgramChatBuildWrite(scenario="goal", expected_program_revision=0),
    )
    job = session.get(BackgroundJob, start.job_id)
    assert job is not None
    process_ai_job(session, job, gateway)
    refreshed = get_job(session, start.job_id)
    assert refreshed.state == BackgroundJobState.COMPLETED

    runs = session.query(ChatToolRun).filter(ChatToolRun.session_id == chat.id).all()
    assert len(runs) == 1
    assert runs[0].tool_key == "search_project_materials"
    assert runs[0].tool_input["queries"] == ["транспортный уровень"]


def _diff_message(
    session: Session, chat: ChatSession, operations: list[dict[str, object]],
) -> ChatMessage:
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


def test_apply_partial_then_conflict_then_reapply(session: Session, ai_config: str) -> None:
    del ai_config
    project = _project(session)
    chat = program_chat.create_session(session, project.id)
    existing = _node(session, project, "Старое название")
    message = _diff_message(session, chat, [
        {"op": "rename", "node_id": str(existing.id), "title": "Новое название", "rationale": "r"},
        {"op": "add", "parent_node_id": None, "after_node_id": None, "node_type": "topic",
         "title": "Новая тема", "rationale": "r", "children": []},
    ])

    result = program_chat.apply_proposal(
        session, project.id, message.id,
        program_chat.ProgramChatApplyWrite(selected=[0], expected_program_revision=0),
    )
    assert result.program.revision == 1
    renamed = next(node for node in result.program.nodes if node.id == existing.id)
    assert renamed.title == "Новое название"

    detail = program_chat.get_session_detail(session, project.id, chat.id)
    payload = detail.messages[0].payload
    assert payload["operation_states"] == ["applied", "pending"]

    second = program_chat.apply_proposal(
        session, project.id, message.id,
        program_chat.ProgramChatApplyWrite(selected=[1], expected_program_revision=1),
    )
    assert second.program.revision == 2
    created_titles = {node.title for node in second.program.nodes}
    assert "Новая тема" in created_titles
    new_node = next(node for node in second.program.nodes if node.title == "Новая тема")
    assert new_node.basis_kind == ProgramBasisKind.CUSTOM
    assert new_node.needs_material is True


def test_apply_rejects_stale_revision(session: Session, ai_config: str) -> None:
    del ai_config
    project = _project(session)
    chat = program_chat.create_session(session, project.id)
    existing = _node(session, project, "Тема")
    message = _diff_message(session, chat, [
        {"op": "rename", "node_id": str(existing.id), "title": "Иначе", "rationale": "r"},
    ])
    with pytest.raises(ProjectConflictError) as caught:
        program_chat.apply_proposal(
            session, project.id, message.id,
            program_chat.ProgramChatApplyWrite(selected=[0], expected_program_revision=5),
        )
    assert caught.value.code == "stale_program_revision"


def test_reject_proposal_blocks_later_apply(session: Session, ai_config: str) -> None:
    del ai_config
    project = _project(session)
    chat = program_chat.create_session(session, project.id)
    existing = _node(session, project, "Тема")
    message = _diff_message(session, chat, [
        {"op": "rename", "node_id": str(existing.id), "title": "Иначе", "rationale": "r"},
    ])
    rejected = program_chat.reject_proposal(session, project.id, message.id)
    assert rejected.payload["rejected"] is True
    with pytest.raises(ProjectConflictError) as caught:
        program_chat.apply_proposal(
            session, project.id, message.id,
            program_chat.ProgramChatApplyWrite(selected=[0], expected_program_revision=0),
        )
    assert caught.value.code == "program_chat_proposal_rejected"


def test_apply_add_with_outline_ref_sets_basis_kind_and_invalid_ref_falls_back(
    session: Session, ai_config: str,
) -> None:
    del ai_config
    project = _project(session)
    chat = program_chat.create_session(session, project.id)
    material = _material(
        session, project, "Учебник",
        outline=[
            {"level": 1, "title": "Введение", "page": 1},
            {"level": 1, "title": "Основы", "page": 10},
        ],
    )
    valid_key = f"{material.id}:embedded:0:1:1"
    message = _diff_message(session, chat, [
        {"op": "add", "parent_node_id": None, "after_node_id": None, "node_type": "section",
         "title": "Введение", "rationale": "r", "children": [],
         "outline_ref": {"material_id": str(material.id), "outline_item_key": valid_key}},
        {"op": "add", "parent_node_id": None, "after_node_id": None, "node_type": "section",
         "title": "Выдуманное", "rationale": "r", "children": [],
         "outline_ref": {"material_id": str(material.id), "outline_item_key": "bogus-key"}},
    ])
    result = program_chat.apply_proposal(
        session, project.id, message.id,
        program_chat.ProgramChatApplyWrite(selected=[0, 1], expected_program_revision=0),
    )
    outline_node = next(node for node in result.program.nodes if node.title == "Введение")
    custom_node = next(node for node in result.program.nodes if node.title == "Выдуманное")
    assert outline_node.basis_kind == ProgramBasisKind.OUTLINE
    assert len(outline_node.source_page_ranges) == 1
    assert outline_node.source_page_ranges[0].page_from == 1
    assert outline_node.source_page_ranges[0].page_to == 9
    assert custom_node.basis_kind == ProgramBasisKind.CUSTOM


def test_merge_survivor_gets_unioned_ranges_and_others_hide(
    session: Session, ai_config: str,
) -> None:
    del ai_config
    project = _project(session)
    chat = program_chat.create_session(session, project.id)
    material = _material(session, project, "Учебник")
    survivor = _node(session, project, "Сети", basis_kind=ProgramBasisKind.OUTLINE)
    other = _node(session, project, "Компьютерные сети", basis_kind=ProgramBasisKind.OUTLINE)
    session.add_all([
        ProgramNodeSourcePageRange(
            project_id=project.id, program_node_id=survivor.id, material_id=material.id,
            source_name_snapshot="Учебник", outline_item_key="a", page_from=1, page_to=5,
        ),
        ProgramNodeSourcePageRange(
            project_id=project.id, program_node_id=other.id, material_id=material.id,
            source_name_snapshot="Учебник", outline_item_key="b", page_from=6, page_to=10,
        ),
    ])
    session.commit()

    message = _diff_message(session, chat, [
        {
            "op": "merge", "node_ids": [str(survivor.id), str(other.id)],
            "title": "Сети (объединено)", "rationale": "r",
        },
    ])
    result = program_chat.apply_proposal(
        session, project.id, message.id,
        program_chat.ProgramChatApplyWrite(selected=[0], expected_program_revision=0),
    )
    merged = next(node for node in result.program.nodes if node.id == survivor.id)
    hidden = next(node for node in result.program.nodes if node.id == other.id)
    assert merged.title == "Сети (объединено)"
    assert not hidden.is_in_current_program
    assert {r.outline_item_key for r in merged.source_page_ranges} == {"a", "b"}


def test_undo_after_apply_restores_everything(session: Session, ai_config: str) -> None:
    del ai_config
    project = _project(session)
    chat = program_chat.create_session(session, project.id)
    existing = _node(session, project, "Старое")
    message = _diff_message(session, chat, [
        {"op": "rename", "node_id": str(existing.id), "title": "Новое", "rationale": "r"},
        {"op": "add", "parent_node_id": None, "after_node_id": None, "node_type": "topic",
         "title": "Добавлено", "rationale": "r", "children": []},
    ])
    result = program_chat.apply_proposal(
        session, project.id, message.id,
        program_chat.ProgramChatApplyWrite(selected=[0, 1], expected_program_revision=0),
    )
    action = result.latest_undoable_action
    assert action is not None and action.action_type == "program_chat_apply"

    undone = program.undo_last_project_action(session, project.id, action.sequence)
    titles = {node.title for node in undone.program.nodes if node.is_in_current_program}
    assert "Старое" in titles
    assert "Добавлено" not in titles

    detail = program_chat.get_session_detail(session, project.id, chat.id)
    assert detail.messages[0].payload["operation_states"] == ["pending", "pending"]
