from __future__ import annotations

import json
from decimal import Decimal

import pytest
from conftest import make_exam_project, make_topic_node
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai.gateway import ModelGateway
from app.ai.provider import FakeTransport, ProviderCompletion, ProviderUsage
from app.exam import attempts as attempt_service
from app.exam import chat as chat_service
from app.models import (
    AiSettings,
    Attempt,
    AttemptOutcome,
    ChatMessage,
    ChatMessageRole,
    Grade,
    GradeMethod,
    ReferenceAnswer,
    ReferenceAnswerMatchMethod,
    ReferenceAnswerOrigin,
)
from app.projects.errors import ProjectDomainError


def _add_reference(session: Session, project_id, node_id, text: str) -> None:
    session.add(
        ReferenceAnswer(
            project_id=project_id,
            program_node_id=node_id,
            text=text,
            origin_kind=ReferenceAnswerOrigin.MANUAL,
            match_method=ReferenceAnswerMatchMethod.MANUAL,
            is_confirmed=True,
            is_active=True,
            revision=3,
        )
    )
    session.commit()


def _completion(payload: dict) -> ProviderCompletion:
    return ProviderCompletion(
        content=json.dumps(payload, ensure_ascii=False),
        actual_model_id="test/structured-model",
        request_id="judge-1",
        usage=ProviderUsage(
            input_tokens=120,
            output_tokens=40,
            cost_usd=Decimal("0.01"),
        ),
    )


@pytest.mark.asyncio
async def test_submit_answer_uses_judge_without_chat_tail_and_verifies_quotes(
    session: Session, ai_config: str
) -> None:
    project = make_exam_project(session)
    topic = make_topic_node(session, project, title="Что даёт индекс базе данных?")
    _add_reference(
        session,
        project.id,
        topic.id,
        "Индекс ускоряет поиск строк в таблице, но занимает место и замедляет запись.",
    )
    chat = chat_service.create_session(session, project.id, topic.id)
    chat_service.append_message(
        session, chat, role=ChatMessageRole.USER, text="секрет из хвоста чата"
    )
    fake = FakeTransport(
        completions=[
            _completion(
                {
                    "outcome": "partial",
                    "credited": [
                        {
                            "point": "Назначение индекса",
                            "quote": "ускоряет выборку",
                        }
                    ],
                    "missed": [{"point": "Цена индекса", "quote": ""}],
                    "wrong": [
                        {
                            "point": "Выдуманный вывод",
                            "quote": "удаляет таблицу",
                        }
                    ],
                    "summary": "Суть названа, ограничения упущены.",
                }
            )
        ]
    )

    result = await attempt_service.submit_answer(
        session,
        ModelGateway(session, fake),
        project.id,
        chat,
        "Индекс ускоряет выборку.",
    )

    assert result.grade.method is GradeMethod.AI_JUDGE
    assert result.grade.outcome is AttemptOutcome.PARTIAL
    assert result.grade.credited_points[0]["quote_start"] == 7
    assert result.grade.credited_points[0]["quote_end"] == 23
    assert result.grade.wrong_points[0]["quote"] == "удаляет таблицу"
    assert result.grade.wrong_points[0]["quote_start"] is None
    assert [message.payload_kind.value for message in result.messages] == [
        "answer_form",
        "verdict",
    ]
    assert result.messages[0].attempt_id == result.attempt.id
    assert result.messages[1].grade_attempt_id == result.attempt.id
    assert result.messages[1].payload["usage"]["actual_cost_usd"] == "0.01"
    sent_messages = fake.complete_requests[0]["messages"]
    assert "секрет из хвоста чата" not in json.dumps(sent_messages, ensure_ascii=False)
    assert result.attempt.context_snapshot["reference_revision"] == 3
    assert result.attempt.context_snapshot["tail_count"] == 0
    assert ai_config == "test/structured-model"

    repeated = await attempt_service.submit_answer(
        session,
        ModelGateway(session, fake),
        project.id,
        chat.id,
        "Индекс ускоряет выборку.",
    )
    assert repeated.attempt.ordinal == 2
    assert repeated.grade.method is GradeMethod.AI_JUDGE
    assert repeated.grade.ai_run_id != result.grade.ai_run_id
    assert repeated.messages[1].payload["cached"] is True
    assert repeated.messages[1].payload["usage"]["actual_cost_usd"] == "0"
    assert fake.complete_calls == 1


@pytest.mark.asyncio
async def test_exact_match_stops_before_model(session: Session, ai_config: str) -> None:
    del ai_config
    project = make_exam_project(session)
    topic = make_topic_node(session, project, title="Что такое ключ?")
    _add_reference(session, project.id, topic.id, "Ключ однозначно определяет строку.")
    chat = chat_service.create_session(session, project.id, topic.id)
    fake = FakeTransport()

    result = await attempt_service.submit_answer(
        session,
        ModelGateway(session, fake),
        project.id,
        chat.id,
        "Ключ — однозначно определяет строку!",
    )

    assert result.grade.method is GradeMethod.EXACT_MATCH
    assert result.grade.outcome is AttemptOutcome.PASSED
    assert fake.complete_calls == 0


@pytest.mark.asyncio
async def test_disabled_ai_saves_preliminary_grade_and_separate_self_assessment(
    session: Session, ai_config: str
) -> None:
    del ai_config
    project = make_exam_project(session)
    topic = make_topic_node(session, project, title="Вопрос без эталона")
    chat = chat_service.create_session(session, project.id, topic.id)
    settings = session.get(AiSettings, 1)
    assert settings is not None
    settings.external_models_enabled = False
    session.commit()

    result = await attempt_service.submit_answer(
        session,
        ModelGateway(session, FakeTransport()),
        project.id,
        chat.id,
        "Мой ответ сохраняется офлайн.",
    )

    assert result.grade.outcome is AttemptOutcome.UNSCORED
    assert result.grade.method is GradeMethod.KEY_TERMS
    assert "внешние модели выключены" in result.grade.summary

    updated = attempt_service.set_self_assessment(
        session,
        project.id,
        result.attempt.id,
        AttemptOutcome.PARTIAL,
    )
    assert updated.outcome is AttemptOutcome.UNSCORED
    assert updated.self_assessment is AttemptOutcome.PARTIAL
    assert updated.method is GradeMethod.SELF_ASSESSMENT


@pytest.mark.asyncio
async def test_broken_judge_keeps_attempt_without_grade(
    session: Session, ai_config: str
) -> None:
    del ai_config
    project = make_exam_project(session)
    topic = make_topic_node(session, project, title="Вопрос с ошибкой судьи")
    chat = chat_service.create_session(session, project.id, topic.id)
    fake = FakeTransport(
        completions=[
            ProviderCompletion(
                content="not-json",
                actual_model_id="test/structured-model",
                usage=ProviderUsage(),
            )
        ]
    )

    with pytest.raises(ProjectDomainError) as caught:
        await attempt_service.submit_answer(
            session,
            ModelGateway(session, fake),
            project.id,
            chat.id,
            "Ответ, который надо сохранить.",
        )

    assert caught.value.code == "ai_invalid_structured_output"
    assert session.scalar(select(func.count(Attempt.id))) == 1
    assert session.scalar(select(Grade)) is None
    answer_message = session.scalar(
        select(ChatMessage).where(ChatMessage.attempt_id.is_not(None))
    )
    assert answer_message is not None


@pytest.mark.asyncio
async def test_attempt_ordinals_and_history_are_per_node(
    session: Session, ai_config: str
) -> None:
    del ai_config
    project = make_exam_project(session)
    topic = make_topic_node(session, project, title="Вопрос с историей")
    _add_reference(session, project.id, topic.id, "Один эталонный ответ.")
    chat = chat_service.create_session(session, project.id, topic.id)

    first = await attempt_service.submit_answer(
        session, ModelGateway(session, FakeTransport()), project.id, chat.id, "Один ответ"
    )
    second = await attempt_service.submit_answer(
        session, ModelGateway(session, FakeTransport()), project.id, chat.id, "Один ответ"
    )
    history = attempt_service.list_attempts(session, project.id, topic.id)

    assert (first.attempt.ordinal, second.attempt.ordinal) == (1, 2)
    assert [item.attempt.ordinal for item in history] == [2, 1]
    assert all(item.grade is not None for item in history)
