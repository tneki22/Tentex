"""Ответ чата в режиме «Разобраться»: источники, кадры потока, ошибки."""

from __future__ import annotations

import json
from uuid import uuid4

import pytest
from conftest import make_exam_project, make_topic_node
from sqlalchemy.orm import Session, sessionmaker

from app.ai.gateway import ModelGateway
from app.ai.provider import FakeTransport, ProviderError, ProviderStreamEvent
from app.exam import chat as chat_service
from app.exam import router as chat_router
from app.exam import sources as chat_sources
from app.exam.schemas import ChatMessageWrite, ChatSettingsWrite
from app.models import ChatMessageRole, ChatMode, PageQuality
from app.projects.errors import ProjectDomainError
from app.retrieval.context import AssembledContext
from app.retrieval.schemas import (
    RetrievalHitRead,
    RetrievalLocatorRead,
    RetrievalSearchRead,
    RetrievalSearchWrite,
    SearchStrategy,
)


def _hit(text: str, *, page: int | None = 3, page_to: int | None = None, typst: str | None = None,
         line_from: int | None = None, line_to: int | None = None) -> RetrievalHitRead:
    return RetrievalHitRead(
        locator=RetrievalLocatorRead(
            chunk_id=uuid4(),
            material_id=uuid4(),
            material_name="Лекции по БД",
            block_id=None,
            block_title="Нормальные формы",
            page_from=page,
            page_to=page_to,
            fragment_ids=[],
            typst_path=typst,
            line_from=line_from,
            line_to=line_to,
        ),
        text=text,
        quality=PageQuality.OCR_LOW,
        score=1.0,
        signals=["lexical"],
        warning="Распознано с ошибками",
    )


def _stub_retrieval(monkeypatch: pytest.MonkeyPatch, hits: list[RetrievalHitRead]) -> None:
    class Retriever:
        async def search(
            self, session: Session, command: RetrievalSearchWrite
        ) -> RetrievalSearchRead:
            del session
            return RetrievalSearchRead(
                query=command.query, strategy=SearchStrategy.HYBRID, index_id=None,
                degraded=False, degradation_reasons=[], results=hits,
            )

    class Assembler:
        def assemble(self, session: Session, result: RetrievalSearchRead) -> AssembledContext:
            del session
            return AssembledContext(sources=result.results, token_count=0, truncated=False)

    monkeypatch.setattr(chat_sources, "HybridRetriever", Retriever)
    monkeypatch.setattr(chat_sources, "ContextAssembler", Assembler)


def _frames(chunks: list[str]) -> list[tuple[str, dict[str, object]]]:
    frames = []
    for chunk in chunks:
        event, data = chunk.strip().split("\n", 1)
        frames.append((event.removeprefix("event: "), json.loads(data.removeprefix("data: "))))
    return frames


Frames = list[tuple[str, dict[str, object]]]


async def _run_turn(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
    fake: FakeTransport,
    text: str = "Что такое 2НФ?",
) -> tuple[object, Frames]:
    project = make_exam_project(session)
    topic = make_topic_node(session, project, title="Нормальные формы")
    chat = chat_service.create_session(session, project.id, topic.id)
    chat_service.update_settings(
        session, project.id, chat.id, ChatSettingsWrite(mode=ChatMode.STUDY)
    )
    monkeypatch.setattr("app.ai.gateway.production_transport", lambda db, modality: fake)
    monkeypatch.setattr(
        chat_router, "SessionLocal", sessionmaker(bind=session.bind, expire_on_commit=False)
    )
    response = await chat_router.post_chat_message(
        project_id=project.id, session_id=chat.id, command=ChatMessageWrite(text=text),
        session=session, gateway=ModelGateway(session),
    )
    frames = _frames([chunk async for chunk in response.body_iterator])
    return chat, frames


@pytest.mark.asyncio
async def test_started_frame_carries_both_ids_and_sources_with_full_locators(
    session: Session, ai_config: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    del ai_config
    _stub_retrieval(monkeypatch, [
        _hit("Вторая нормальная форма", page=3, page_to=5),
        _hit("Типст-конспект", page=None, typst="lectures/db.typ", line_from=10, line_to=24),
    ])
    fake = FakeTransport(streams=[[ProviderStreamEvent(delta="2НФ — это [S1], см. также [S2].")]])

    chat, frames = await _run_turn(session, monkeypatch, fake)

    event, started = frames[0]
    assert event == "started"
    detail = chat_service.get_session_detail(session, chat.project_id, chat.id)
    user = next(message for message in detail.messages if message.role == ChatMessageRole.USER)
    assert started["user_message_id"] == str(user.id)
    sources = started["sources"]
    assert [source["id"] for source in sources] == ["S1", "S2"]
    assert sources[0]["locator"] == "стр. 3–5"
    assert sources[1]["locator"] == "lectures/db.typ, строки 10–24"
    assert sources[0]["quality"] == "ocr_low"
    assert sources[0]["warning"] == "Распознано с ошибками"
    assert sources[0]["text"] == "Вторая нормальная форма"
    assert frames[-1][0] == "completed"
    assert frames[-1][1]["message"]["context_snapshot"]["retrieval_sources"] == sources


@pytest.mark.asyncio
async def test_error_frame_keeps_structured_context(
    session: Session, ai_config: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    del ai_config
    _stub_retrieval(monkeypatch, [_hit("Факт")])
    fake = FakeTransport(streams=[ProviderError("ai_provider_unavailable", "Нет связи")])

    _, frames = await _run_turn(session, monkeypatch, fake)

    event, error = frames[-1]
    assert event == "error"
    assert error["code"] == "ai_provider_unavailable"
    assert isinstance(error["context"], dict)


@pytest.mark.asyncio
async def test_operation_is_recorded_and_reaches_the_prompt_without_the_command_words(
    session: Session, ai_config: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    del ai_config
    queries: list[str] = []
    _stub_retrieval(monkeypatch, [_hit("Первое место"), _hit("Второе место")])
    original = chat_sources.HybridRetriever.search

    async def spy(self, session, command):  # noqa: ANN001 — тестовая обёртка
        queries.append(command.query)
        return await original(self, session, command)

    monkeypatch.setattr(chat_sources.HybridRetriever, "search", spy)
    fake = FakeTransport(streams=[[ProviderStreamEvent(delta="Согласны [S1] и [S2].")]])

    project = make_exam_project(session)
    topic = make_topic_node(session, project, title="Нормальные формы")
    chat = chat_service.create_session(session, project.id, topic.id)
    chat_service.update_settings(
        session, project.id, chat.id, ChatSettingsWrite(mode=ChatMode.STUDY)
    )
    monkeypatch.setattr("app.ai.gateway.production_transport", lambda db, modality: fake)
    monkeypatch.setattr(
        chat_router, "SessionLocal", sessionmaker(bind=session.bind, expire_on_commit=False)
    )
    response = await chat_router.post_chat_message(
        project_id=project.id,
        session_id=chat.id,
        command=ChatMessageWrite(text="Нормальные формы", operation="compare_sources"),
        session=session,
        gateway=ModelGateway(session),
    )
    [chunk async for chunk in response.body_iterator]

    assert queries[0] == "Нормальные формы"
    system = fake.stream_requests[0]["messages"][0]["content"]
    assert "Операция: сравнить источники" in system
    detail = chat_service.get_session_detail(session, project.id, chat.id)
    user = next(message for message in detail.messages if message.role == ChatMessageRole.USER)
    assert user.skill == "compare_sources"


@pytest.mark.asyncio
async def test_empty_linked_topic_is_rejected_before_the_turn_is_written(
    session: Session, ai_config: str
) -> None:
    del ai_config
    project = make_exam_project(session)
    topic = make_topic_node(session, project, title="Без привязок")
    chat = chat_service.create_session(session, project.id, topic.id)
    chat_service.update_settings(
        session, project.id, chat.id, ChatSettingsWrite(mode=ChatMode.STUDY)
    )

    with pytest.raises(ProjectDomainError) as error:
        await chat_router.post_chat_message(
            project_id=project.id,
            session_id=chat.id,
            command=ChatMessageWrite(text="Что это?", retrieval_scope="linked_topic"),
            session=session,
            gateway=ModelGateway(session),
        )

    assert error.value.code == "retrieval_scope_empty"
    assert chat_service.get_session_detail(session, project.id, chat.id).messages == []
