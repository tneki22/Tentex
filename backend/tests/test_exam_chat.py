from __future__ import annotations

import asyncio

import pytest
from conftest import make_exam_project, make_material, make_topic_node
from sqlalchemy.orm import Session, sessionmaker

from app.ai.gateway import ModelGateway
from app.ai.provider import FakeTransport, ProviderStreamEvent, ProviderUsage
from app.exam import chat as chat_service
from app.exam import router as chat_router
from app.exam.context import build_context
from app.exam.schemas import ChatAnswerWrite, ChatMessageWrite
from app.models import (
    AiSettings,
    ChatMessageRole,
    ReferenceAnswer,
    ReferenceAnswerMatchMethod,
    ReferenceAnswerOrigin,
)
from app.projects.errors import ProjectDomainError


def test_session_creation_orders_sequence_and_suffixes_title(session: Session) -> None:
    project = make_exam_project(session)
    topic = make_topic_node(session, project, title="Что такое функциональная зависимость")

    chat = chat_service.create_session(session, project.id, topic.id)
    first = chat_service.append_message(session, chat, role=ChatMessageRole.USER, text="один")
    second = chat_service.append_message(session, chat, role=ChatMessageRole.EXAMINER, text="два")
    assert (first.sequence, second.sequence) == (1, 2)

    again = chat_service.create_session(session, project.id, topic.id)
    assert again.title == f"{chat.title} · 2"


def test_draft_survives_read(session: Session) -> None:
    project = make_exam_project(session)
    topic = make_topic_node(session, project, title="Вопрос с черновиком")
    chat = chat_service.create_session(session, project.id, topic.id)

    chat_service.save_draft(session, project.id, chat.id, "черновик ответа")
    detail = chat_service.get_session_detail(session, project.id, chat.id)
    assert detail.draft_text == "черновик ответа"


def test_context_manifest_records_source_sizes(session: Session) -> None:
    project = make_exam_project(session)
    topic = make_topic_node(session, project, title="Размер вопроса")
    reference_text = "Короткий эталон"
    session.add(
        ReferenceAnswer(
            project_id=project.id,
            program_node_id=topic.id,
            text=reference_text,
            origin_kind=ReferenceAnswerOrigin.MANUAL,
            match_method=ReferenceAnswerMatchMethod.MANUAL,
            is_confirmed=True,
            is_active=True,
            revision=2,
        )
    )
    session.commit()
    chat = chat_service.create_session(session, project.id, topic.id)
    chat_service.append_message(session, chat, role=ChatMessageRole.USER, text="хвост")

    manifest = build_context(session, chat, for_judge=False).manifest
    entries = {entry["kind"]: entry for entry in manifest}

    assert entries["program_node"]["bytes"] == len(topic.title.encode())
    assert entries["reference_answer"]["bytes"] == len(reference_text.encode())
    assert entries["reference_answer"]["revision"] == 2
    assert entries["chat_tail"]["bytes"] == len("хвост".encode())


@pytest.mark.asyncio
async def test_stream_collects_text_and_completes(
    session: Session, ai_config: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = make_exam_project(session)
    topic = make_topic_node(session, project, title="Вопрос в потоке")
    chat = chat_service.create_session(session, project.id, topic.id)

    fake = FakeTransport(
        streams=[
            [
                ProviderStreamEvent(delta="При"),
                ProviderStreamEvent(
                    delta="вет",
                    usage=ProviderUsage(input_tokens=3, output_tokens=2),
                    actual_model_id=ai_config,
                    request_id="req-1",
                ),
            ]
        ]
    )
    monkeypatch.setattr("app.ai.gateway.production_transport", lambda db, modality: fake)
    test_session_local = sessionmaker(bind=session.bind, expire_on_commit=False)
    monkeypatch.setattr(chat_router, "SessionLocal", test_session_local)

    response = await chat_router.post_chat_message(
        project_id=project.id,
        session_id=chat.id,
        command=ChatMessageWrite(text="Объясни коротко"),
        session=session,
        gateway=ModelGateway(session),
    )
    frames = [chunk async for chunk in response.body_iterator]
    joined = "".join(frames)
    assert "event: started" in joined
    assert "event: completed" in joined

    detail = chat_service.get_session_detail(session, project.id, chat.id)
    examiner = next(message for message in detail.messages if message.role == "examiner")
    assert examiner.text == "Привет"
    assert examiner.stream_state == "complete"
    assert examiner.ai_run_id is not None


@pytest.mark.asyncio
async def test_stopped_stream_keeps_partial_text(
    session: Session, ai_config: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    del ai_config
    project = make_exam_project(session)
    topic = make_topic_node(session, project, title="Вопрос с обрывом")
    chat = chat_service.create_session(session, project.id, topic.id)

    class SlowFake(FakeTransport):
        async def stream(
            self,
            *,
            model: str,
            messages: list,
            max_output_tokens: int,
            parameters: dict[str, object],
        ):
            del model, messages, max_output_tokens, parameters
            self.stream_calls += 1
            yield ProviderStreamEvent(delta="Часть ")
            await asyncio.sleep(5)
            yield ProviderStreamEvent(delta="никогда не должна попасть в базу")

    fake = SlowFake()
    monkeypatch.setattr("app.ai.gateway.production_transport", lambda db, modality: fake)
    test_session_local = sessionmaker(bind=session.bind, expire_on_commit=False)
    monkeypatch.setattr(chat_router, "SessionLocal", test_session_local)

    response = await chat_router.post_chat_message(
        project_id=project.id,
        session_id=chat.id,
        command=ChatMessageWrite(text="вопрос"),
        session=session,
        gateway=ModelGateway(session),
    )
    body = response.body_iterator
    await body.__anext__()  # started
    await body.__anext__()  # delta "Часть "
    pending = asyncio.ensure_future(body.__anext__())
    await asyncio.sleep(0.2)
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending

    detail = chat_service.get_session_detail(session, project.id, chat.id)
    examiner = next(message for message in detail.messages if message.role == "examiner")
    assert examiner.stream_state == "stopped"
    assert examiner.text == "Часть "


@pytest.mark.asyncio
async def test_offline_blocks_message_but_answer_still_saves(
    session: Session, ai_config: str
) -> None:
    del ai_config
    project = make_exam_project(session)
    topic = make_topic_node(session, project, title="Вопрос офлайн")
    chat = chat_service.create_session(session, project.id, topic.id)
    project_id, chat_id = project.id, chat.id

    settings = session.get(AiSettings, 1)
    assert settings is not None
    settings.external_models_enabled = False
    session.commit()

    with pytest.raises(ProjectDomainError) as caught:
        await chat_router.post_chat_message(
            project_id=project_id,
            session_id=chat_id,
            command=ChatMessageWrite(text="вопрос"),
            session=session,
            gateway=ModelGateway(session),
        )
    assert caught.value.code == "ai_disabled"
    # В реальном приложении каждый запрос получает свежую сессию через
    # get_session; здесь одна и та же session-фикстура обслуживает два вызова
    # подряд. rollback() закрывает зависшую автотранзакцию после чтения, но
    # заодно истекает загруженные объекты — id взяты заранее как простые
    # значения, чтобы их чтение после rollback не открыло новую автотранзакцию
    # раньше собственной транзакции сохранения попытки.
    session.rollback()

    result = await chat_router.post_chat_answer(
        project_id=project_id,
        session_id=chat_id,
        command=ChatAnswerWrite(text="мой ответ на вопрос билета"),
        session=session,
        gateway=ModelGateway(session),
    )
    assert [message.payload_kind for message in result.messages] == [
        "answer_form",
        "verdict",
    ]
    assert result.messages[0].payload["ordinal"] == 1
    assert result.attempt.ordinal == 1
    assert result.grade.outcome == "unscored"


@pytest.mark.asyncio
async def test_source_only_reference_disables_textual_check(session: Session) -> None:
    project = make_exam_project(session)
    topic = make_topic_node(session, project, title="Вопрос с ответом-картинкой")
    material = make_material(session, "a17")
    session.add(
        ReferenceAnswer(
            project_id=project.id,
            program_node_id=topic.id,
            text="",
            origin_kind=ReferenceAnswerOrigin.IMPORT,
            match_method=ReferenceAnswerMatchMethod.EXACT_TITLE,
            matched_title=topic.title,
            source_material_id=material.id,
            is_confirmed=False,
            is_active=True,
            revision=1,
        )
    )
    session.commit()
    chat = chat_service.create_session(session, project.id, topic.id)

    with pytest.raises(ProjectDomainError) as error:
        await chat_router.post_chat_answer(
            project_id=project.id,
            session_id=chat.id,
            command=ChatAnswerWrite(text="Мой текстовый ответ"),
            session=session,
            gateway=ModelGateway(session),
        )

    assert error.value.code == "textual_check_unavailable"
