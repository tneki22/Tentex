from __future__ import annotations

import pytest
from conftest import (
    add_page_with_fragments,
    link_material,
    make_exam_project,
    make_material,
    make_topic_node,
)
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.bindings import search as search_module
from app.chat_tools.executor import run_tool
from app.chat_tools.registry import get_tool_spec, list_tool_specs
from app.exam import chat as chat_service
from app.models import Binding
from app.projects.errors import ProjectDomainError


def _seed_material_with_fragments(session: Session, project) -> None:
    material = make_material(session, "a1")
    link_material(session, project, material)
    add_page_with_fragments(
        session,
        material,
        page_number=1,
        revision=1,
        fragments=["Формула Байеса связывает условные вероятности событий."],
        block_title="Формула Байеса",
    )
    search_module.reindex_material(session, material.id)
    session.commit()


def test_unknown_tool_key_differs_from_unavailable_tool(session: Session) -> None:
    project = make_exam_project(session)
    topic = make_topic_node(session, project, title="Различие кодов Tool")
    chat = chat_service.create_session(session, project.id, topic.id)

    with pytest.raises(ProjectDomainError) as unknown:
        run_tool(session, project.id, chat.id, "not_a_real_tool", {"query": "x"})
    assert unknown.value.code == "chat_tool_not_found"

    with pytest.raises(ProjectDomainError) as unavailable:
        run_tool(session, project.id, chat.id, "search_external_sources", {"query": "x"})
    assert unavailable.value.code == "chat_tool_unavailable"
    assert unknown.value.code != unavailable.value.code


def test_tool_cannot_run_for_foreign_project_session(session: Session) -> None:
    project = make_exam_project(session)
    other_project = make_exam_project(session)
    topic = make_topic_node(session, project, title="Своя тема")
    chat = chat_service.create_session(session, project.id, topic.id)

    with pytest.raises(ProjectDomainError) as excinfo:
        run_tool(session, other_project.id, chat.id, "search_project_materials", {"query": "x"})
    assert excinfo.value.code == "chat_session_not_found"


def test_search_project_materials_finds_bound_fragment(session: Session) -> None:
    project = make_exam_project(session)
    topic = make_topic_node(session, project, title="Формула Байеса")
    _seed_material_with_fragments(session, project)
    chat = chat_service.create_session(session, project.id, topic.id)

    run = run_tool(
        session, project.id, chat.id, "search_project_materials", {"query": "формула байеса"}
    )

    assert run.state.value == "succeeded"
    assert run.result is not None
    assert len(run.result["items"]) >= 1
    assert "Байес" in run.result["items"][0]["excerpt"]


def test_bm25_tool_does_not_call_model(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = make_exam_project(session)
    topic = make_topic_node(session, project, title="Без модели")
    _seed_material_with_fragments(session, project)
    chat = chat_service.create_session(session, project.id, topic.id)

    def _boom(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("BM25 tool must not call the model gateway")

    monkeypatch.setattr("app.ai.gateway.ModelGateway.complete", _boom)
    monkeypatch.setattr("app.ai.gateway.ModelGateway.stream", _boom)

    run = run_tool(
        session, project.id, chat.id, "search_project_materials", {"query": "байес"}
    )
    assert run.state.value == "succeeded"


def test_bm25_tool_does_not_create_binding(session: Session) -> None:
    project = make_exam_project(session)
    topic = make_topic_node(session, project, title="Без привязки")
    _seed_material_with_fragments(session, project)
    chat = chat_service.create_session(session, project.id, topic.id)

    before = session.scalar(select(func.count(Binding.id)))
    session.commit()
    run_tool(session, project.id, chat.id, "search_project_materials", {"query": "байес"})
    after = session.scalar(select(func.count(Binding.id)))
    assert before == after == 0


def test_history_returns_stored_tool_result_without_rerun(session: Session) -> None:
    project = make_exam_project(session)
    topic = make_topic_node(session, project, title="История без повтора")
    _seed_material_with_fragments(session, project)
    chat = chat_service.create_session(session, project.id, topic.id)

    run = run_tool(session, project.id, chat.id, "search_project_materials", {"query": "байес"})
    detail = chat_service.get_session_detail(session, project.id, chat.id)

    tool_messages = [m for m in detail.messages if m.payload_kind.value == "tool_result"]
    assert len(tool_messages) == 1
    assert tool_messages[0].payload["result"] == run.result
    assert tool_messages[0].skill == "search_project_materials"


def test_tool_input_is_validated(session: Session) -> None:
    project = make_exam_project(session)
    topic = make_topic_node(session, project, title="Валидация входа")
    chat = chat_service.create_session(session, project.id, topic.id)

    with pytest.raises(ProjectDomainError) as excinfo:
        run_tool(session, project.id, chat.id, "search_project_materials", {"query": ""})
    assert excinfo.value.code == "chat_tool_input_invalid"


def test_registry_lists_one_real_and_stub_tools() -> None:
    specs = list_tool_specs()
    real = [spec for spec in specs if spec.available]
    stubs = [spec for spec in specs if not spec.available]
    assert [spec.key for spec in real] == ["search_project_materials"]
    assert all(spec.handler is None for spec in stubs)
    assert get_tool_spec("search_project_materials") is not None
    assert get_tool_spec("does_not_exist") is None
