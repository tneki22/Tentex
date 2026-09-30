"""Устная сдача сохраняет исправленный текст и доступные показатели речи."""

import json
from datetime import timedelta

import pytest
from conftest import make_exam_project, make_topic_node
from sqlalchemy import select

from app.ai.gateway import ModelGateway
from app.ai.provider import (
    FakeTransport,
    ProviderCompletion,
    ProviderError,
    ProviderTranscription,
    ProviderUsage,
    TimedWord,
)
from app.ai.settings import AiGatewayError
from app.exam import attempts, chat, oral
from app.models import (
    AiModelCatalogEntry,
    AiProviderConnection,
    AiSettings,
    OralRecording,
    ReferenceAnswer,
    ReferenceAnswerMatchMethod,
    ReferenceAnswerOrigin,
    utc_now,
)

WHISPER = "openai/whisper-large-v3-turbo"


def _setup(session, ai_config):
    del ai_config
    provider = session.query(AiProviderConnection).one()
    session.add(AiModelCatalogEntry(
        provider_id=provider.id, model_id=WHISPER, display_name="Whisper",
        input_modalities=["text", "audio"], output_modalities=["text"],
        pricing_snapshot_at=utc_now(), catalog_snapshot_at=utc_now(),
        is_manually_added=True, is_available=True,
    ))
    ai = session.get(AiSettings, 1)
    ai.default_speech_provider_id = provider.id
    ai.default_speech_model_id = WHISPER
    project = make_exam_project(session)
    node = make_topic_node(session, project, title="Что даёт индекс?")
    session.add(ReferenceAnswer(
        project_id=project.id, program_node_id=node.id,
        text="Индекс ускоряет поиск строк, но замедляет запись.",
        origin_kind=ReferenceAnswerOrigin.MANUAL,
        match_method=ReferenceAnswerMatchMethod.MANUAL,
        is_confirmed=True, is_active=True, revision=1,
    ))
    session.commit()
    return project, chat.create_session(session, project.id, node.id)


@pytest.mark.asyncio
@pytest.mark.parametrize("with_words", [True, False])
async def test_oral_draft_submit_retry_and_expiry(session, ai_config, with_words):
    project, conversation = _setup(session, ai_config)
    words = (
        TimedWord(start=0.4, end=0.8, word="Индекс"),
        TimedWord(start=1.6, end=2.0, word="ускоряет"),
    ) if with_words else ()
    fake = FakeTransport(
        transcriptions=[ProviderTranscription(
            text="Индекс ускорят поиск", actual_model_id=WHISPER,
            usage=ProviderUsage(), words=words,
        )],
        completions=[ProviderCompletion(
            content=json.dumps({
                "outcome": "partial",
                "credited": [{"point": "Ускоряет поиск", "quote": "ускоряет поиск",
                              "source_quote": "ускоряет поиск строк"}],
                "missed": [{"point": "Цена записи", "quote": "",
                            "source_quote": "замедляет запись"}],
                "wrong": [], "summary": "Поиск раскрыт, запись упущена.",
            }, ensure_ascii=False),
            actual_model_id="test/structured-model", usage=ProviderUsage(),
        )],
    )
    gateway = ModelGateway(session, fake)
    draft = await oral.create_draft(
        session, gateway, project.id, conversation.id, b"fake-audio", "webm", 3000,
    )
    assert draft.transcript == "Индекс ускорят поиск"
    assert fake.transcribe_requests[0]["timestamps"] is True
    assert draft.metrics["duration_ms"] == 3000
    if with_words:
        assert draft.metrics["pause_count"] == 1
        assert draft.metrics["time_to_first_word_ms"] == 400
    else:
        assert set(draft.metrics) == {"duration_ms"}

    corrected = "Индекс ускоряет поиск."
    submitted = await oral.submit_draft(
        session, gateway, project.id, conversation.id, draft.id, corrected, None,
    )
    assert submitted.attempt.text == corrected
    assert submitted.attempt.answer_modality == "oral"
    assert submitted.grade is not None and submitted.grade.outcome.value == "partial"
    assert submitted.messages[0].payload["speech_metrics"] == draft.metrics
    again = await oral.submit_draft(
        session, gateway, project.id, conversation.id, draft.id, "Новый текст", None,
    )
    assert again.attempt.id == submitted.attempt.id
    assert again.attempt.text == corrected
    assert fake.complete_calls == 1

    path = oral.audio_path(session, project.id, draft.id)
    assert path.read_bytes() == b"fake-audio"
    with session.begin():
        row = session.get(OralRecording, draft.id)
        row.audio_expires_at = utc_now() - timedelta(seconds=1)
    assert oral.cleanup_expired(session) == 1
    assert not path.exists()
    assert session.get(OralRecording, draft.id).audio_path is None


@pytest.mark.asyncio
async def test_transcription_error_leaves_no_draft(session, ai_config):
    project, conversation = _setup(session, ai_config)
    fake = FakeTransport(transcriptions=[ProviderError("ai_invalid_request", "bad audio")])
    with pytest.raises(AiGatewayError):
        await oral.create_draft(
            session, ModelGateway(session, fake), project.id, conversation.id,
            b"bad-audio", "webm", 2000,
        )
    assert session.scalar(select(OralRecording)) is None


@pytest.mark.asyncio
async def test_unavailable_judge_keeps_oral_attempt_for_later(session, ai_config):
    project, conversation = _setup(session, ai_config)
    fake = FakeTransport(
        transcriptions=[ProviderTranscription(
            text="Индекс ускоряет поиск", actual_model_id=WHISPER, usage=ProviderUsage(),
        )],
        completions=[ProviderError("ai_invalid_request", "model unavailable")],
    )
    gateway = ModelGateway(session, fake)
    draft = await oral.create_draft(
        session, gateway, project.id, conversation.id, b"audio", "webm", 2000,
    )
    submitted = await oral.submit_draft(
        session, gateway, project.id, conversation.id, draft.id,
        "Индекс ускоряет поиск", None,
    )
    assert submitted.grade is None
    assert draft.attempt_id == submitted.attempt.id

    retry = FakeTransport(completions=[ProviderCompletion(
        content=json.dumps({
            "outcome": "passed",
            "credited": [{"point": "Поиск", "quote": "ускоряет поиск",
                          "source_quote": "ускоряет поиск строк"}],
            "missed": [], "wrong": [], "summary": "Суть верна.",
        }, ensure_ascii=False),
        actual_model_id="test/structured-model", usage=ProviderUsage(),
    )])
    grade = await attempts.check_attempt(
        session, ModelGateway(session, retry), project.id, submitted.attempt.id,
    )
    assert grade.outcome.value == "passed"
    assert retry.complete_calls == 1


@pytest.mark.asyncio
async def test_same_text_has_same_content_verdict_in_oral_and_text(session, ai_config):
    project, conversation = _setup(session, ai_config)
    answer = "Индекс ускоряет выборку."
    fake = FakeTransport(
        transcriptions=[ProviderTranscription(
            text=answer, actual_model_id=WHISPER, usage=ProviderUsage(),
        )],
        completions=[ProviderCompletion(
            content=json.dumps({
                "outcome": "partial",
                "credited": [{"point": "Поиск", "quote": "ускоряет выборку",
                              "source_quote": "ускоряет поиск строк"}],
                "missed": [{"point": "Запись", "quote": "",
                            "source_quote": "замедляет запись"}],
                "wrong": [], "summary": "Нет оговорки о записи.",
            }, ensure_ascii=False),
            actual_model_id="test/structured-model", usage=ProviderUsage(),
        )],
    )
    gateway = ModelGateway(session, fake)
    written = await attempts.submit_answer(
        session, gateway, project.id, conversation.id, answer,
    )
    draft = await oral.create_draft(
        session, gateway, project.id, conversation.id, b"audio", "webm", 2000,
    )
    spoken = await oral.submit_draft(
        session, gateway, project.id, conversation.id, draft.id, answer, None,
    )
    assert written.grade is not None and spoken.grade is not None
    assert written.grade.outcome == spoken.grade.outcome
    assert written.grade.credited_points == spoken.grade.credited_points
    assert written.grade.missed_points == spoken.grade.missed_points
