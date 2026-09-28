import json
from decimal import Decimal

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from openai import AsyncOpenAI
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai import dictation
from app.ai.dictation import _audio_format
from app.ai.gateway import MAX_AUDIO_BYTES, ModelGateway
from app.ai.provider import (
    FakeTransport,
    OpenAITransport,
    ProviderCompletion,
    ProviderError,
    ProviderTranscription,
    ProviderUsage,
    _timed_word,
)
from app.ai.schemas import AiModelSelection
from app.ai.settings import AiGatewayError
from app.db import get_session
from app.models import AiModelCatalogEntry, AiProviderConnection, AiRun, AiSettings, utc_now

WHISPER = "openai/whisper-large-v3-turbo"


def test_word_timestamp_parser_ignores_invalid_marks():
    assert _timed_word({"start": 0.2, "end": 0.5, "word": "слово"}).word == "слово"
    assert _timed_word({"start": None, "end": 0.5, "word": "слово"}) is None
    assert _timed_word({"start": 0.5, "end": 0.2, "word": "слово"}) is None


@pytest.fixture
def speech_config(session: Session, ai_config: str) -> AiModelSelection:
    """К текстовой модели из `ai_config` добавляется Whisper — по умолчанию для речи."""
    del ai_config
    provider = session.query(AiProviderConnection).one()
    now = utc_now()
    session.add(
        AiModelCatalogEntry(
            provider_id=provider.id,
            model_id=WHISPER,
            display_name="Whisper",
            # У OpenRouter Whisper приходит с `text` во входе — тест держит именно этот случай.
            input_modalities=["text", "audio"],
            output_modalities=["text"],
            pricing_snapshot_at=now,
            catalog_snapshot_at=now,
            is_manually_added=True,
            is_available=True,
        )
    )
    settings_row = session.get(AiSettings, 1)
    assert settings_row is not None
    settings_row.default_speech_provider_id = provider.id
    settings_row.default_speech_model_id = WHISPER
    session.commit()
    return AiModelSelection(provider_id=provider.id, model_id=WHISPER)


def _transcription(text: str = "привет мир") -> ProviderTranscription:
    return ProviderTranscription(
        text=text, actual_model_id=WHISPER, usage=ProviderUsage(cost_usd=Decimal("0.0001"))
    )


@pytest.mark.asyncio
async def test_transcribe_sends_audio_and_logs_run_without_text(
    session: Session, speech_config: AiModelSelection
) -> None:
    fake = FakeTransport(transcriptions=[_transcription("  привет мир \n")])
    result = await ModelGateway(session, fake).transcribe(b"audio-bytes", "webm")

    assert result.text == "привет мир"
    assert fake.transcribe_requests == [
        {"model": WHISPER, "bytes": 11, "format": "webm", "language": "ru", "via_chat": False}
    ]
    run = session.scalar(select(AiRun))
    assert run is not None
    assert (run.role, run.modality, run.status) == ("speech_transcription", "speech", "succeeded")
    assert run.provider_id == speech_config.provider_id
    assert run.actual_cost_usd == Decimal("0.0001")
    # Расшифровка — личный текст: в журнал уходит только факт вызова.
    assert run.response_payload == {}
    assert "привет" not in json.dumps(run.context_manifest, ensure_ascii=False)


@pytest.mark.asyncio
async def test_multimodal_chat_model_is_asked_through_chat(
    session: Session, speech_config: AiModelSelection
) -> None:
    """Gemini принимает аудио, но у него нет `/audio/transcriptions` — идём через чат."""
    now = utc_now()
    session.add(
        AiModelCatalogEntry(
            provider_id=speech_config.provider_id,
            model_id="google/gemini-flash",
            display_name="Gemini",
            input_modalities=["text", "image", "audio"],
            output_modalities=["text"],
            pricing_snapshot_at=now,
            catalog_snapshot_at=now,
            is_manually_added=True,
            is_available=True,
        )
    )
    settings_row = session.get(AiSettings, 1)
    assert settings_row is not None
    settings_row.default_speech_model_id = "google/gemini-flash"
    session.commit()
    fake = FakeTransport(transcriptions=[_transcription()])

    await ModelGateway(session, fake).transcribe(b"audio-bytes", "wav")

    assert fake.transcribe_requests[0]["via_chat"] is True


@pytest.mark.asyncio
async def test_transcribe_records_provider_failure(
    session: Session, speech_config: AiModelSelection
) -> None:
    del speech_config
    fake = FakeTransport(
        transcriptions=[ProviderError("ai_rate_limited", "Провайдер ограничил запросы")]
    )
    with pytest.raises(AiGatewayError) as raised:
        await ModelGateway(session, fake).transcribe(b"audio-bytes", "webm")
    assert (raised.value.code, raised.value.status) == ("ai_rate_limited", 429)
    run = session.scalar(select(AiRun))
    assert run is not None and (run.status, run.error_code) == ("failed", "ai_rate_limited")


@pytest.mark.asyncio
async def test_transcribe_rejects_empty_and_oversized_audio(
    session: Session, speech_config: AiModelSelection
) -> None:
    del speech_config
    gateway = ModelGateway(session, FakeTransport())
    with pytest.raises(AiGatewayError) as empty:
        await gateway.transcribe(b"", "webm")
    assert empty.value.code == "ai_audio_empty"
    with pytest.raises(AiGatewayError) as large:
        await gateway.transcribe(bytes(MAX_AUDIO_BYTES + 1), "webm")
    assert (large.value.code, large.value.status) == ("ai_audio_too_large", 413)
    assert session.scalar(select(AiRun)) is None


@pytest.mark.asyncio
async def test_transcribe_needs_configured_speech_model(
    session: Session, ai_config: str
) -> None:
    del ai_config
    with pytest.raises(AiGatewayError) as raised:
        await ModelGateway(session, FakeTransport()).transcribe(b"audio-bytes", "webm")
    assert raised.value.code == "ai_model_not_configured"


@pytest.mark.asyncio
async def test_speech_model_test_sends_silence_instead_of_a_chat_request(
    session: Session, speech_config: AiModelSelection
) -> None:
    fake = FakeTransport(transcriptions=[_transcription("")])
    result = await ModelGateway(session, fake).test_model(speech_config)

    assert (result.status, result.kind) == ("answered", "speech")
    assert fake.complete_calls == 0
    request = fake.transcribe_requests[0]
    assert request["format"] == "wav"
    assert isinstance(request["bytes"], int) and request["bytes"] > 32_000
    run = session.get(AiRun, result.run_id)
    assert run is not None and run.role == "settings_speech_model_test"


@pytest.mark.asyncio
async def test_speech_model_test_reports_provider_error(
    session: Session, speech_config: AiModelSelection
) -> None:
    fake = FakeTransport(
        transcriptions=[ProviderError("ai_provider_unavailable", "Провайдер отклонил запрос")]
    )
    with pytest.raises(AiGatewayError) as raised:
        await ModelGateway(session, fake).test_model(speech_config)
    assert raised.value.code == "ai_provider_unavailable"


@pytest.mark.asyncio
async def test_text_model_test_still_uses_chat(
    session: Session, speech_config: AiModelSelection, ai_config: str
) -> None:
    fake = FakeTransport(
        completions=[
            ProviderCompletion(
                content="работает", actual_model_id=ai_config, usage=ProviderUsage()
            )
        ]
    )
    result = await ModelGateway(session, fake).test_model(
        AiModelSelection(provider_id=speech_config.provider_id, model_id=ai_config)
    )
    assert result.kind == "text"
    assert fake.transcribe_requests == []


def _transport_over(profile: str, handler) -> OpenAITransport:
    transport = OpenAITransport("https://provider.test/v1", "key", profile)
    transport.client = AsyncOpenAI(
        base_url="https://provider.test/v1",
        api_key="key",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    return transport


@pytest.mark.asyncio
async def test_openai_compatible_profile_uploads_multipart_file() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["content_type"] = request.headers["content-type"]
        seen["body"] = request.read()
        return httpx.Response(200, json={"text": "привет"})

    result = await _transport_over("openai_compatible", handler).transcribe(
        model="whisper-large-v3-turbo", audio=b"RIFFdata", audio_format="wav", language="ru"
    )

    assert result.text == "привет"
    assert seen["path"] == "/v1/audio/transcriptions"
    assert str(seen["content_type"]).startswith("multipart/form-data")
    body = seen["body"]
    assert isinstance(body, bytes)
    assert b'filename="dictation.wav"' in body and b"whisper-large-v3-turbo" in body
    assert b"RIFFdata" in body


@pytest.mark.asyncio
async def test_openrouter_profile_sends_base64_json_and_reads_cost() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["json"] = json.loads(request.read())
        return httpx.Response(200, json={"text": "привет", "usage": {"cost": 0.0002}})

    result = await _transport_over("openrouter", handler).transcribe(
        model=WHISPER, audio=b"abc", audio_format="webm", language="ru"
    )

    assert result.text == "привет"
    assert result.usage.cost_usd == Decimal("0.0002")
    assert seen["path"] == "/v1/audio/transcriptions"
    assert seen["json"] == {
        "model": WHISPER,
        "input_audio": {"data": "YWJj", "format": "webm"},
        "language": "ru",
    }


def _chat_reply(content: str | None) -> httpx.Response:
    return httpx.Response(200, json={
        "id": "gen-1",
        "model": "google/gemini-flash",
        "choices": [{"index": 0, "finish_reason": "stop",
                     "message": {"role": "assistant", "content": content}}],
        "usage": {"prompt_tokens": 40, "completion_tokens": 5, "cost": 0.001},
    })


@pytest.mark.asyncio
async def test_via_chat_sends_audio_as_message_part() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["json"] = json.loads(request.read())
        return _chat_reply("привет мир")

    result = await _transport_over("openrouter", handler).transcribe(
        model="google/gemini-flash", audio=b"abc", audio_format="wav", language="ru",
        via_chat=True,
    )

    assert result.text == "привет мир"
    assert (result.usage.input_tokens, result.usage.cost_usd) == (40, Decimal("0.001"))
    assert seen["path"] == "/v1/chat/completions"
    body = seen["json"]
    assert isinstance(body, dict)
    parts = body["messages"][0]["content"]
    assert parts[1] == {"type": "input_audio", "input_audio": {"data": "YWJj", "format": "wav"}}
    assert body["usage"] == {"include": True}


@pytest.mark.asyncio
async def test_via_chat_empty_reply_means_no_speech_not_failure() -> None:
    transport = _transport_over("openai_compatible", lambda request: _chat_reply(None))
    result = await transport.transcribe(
        model="google/gemini-flash", audio=b"abc", audio_format="wav", language="ru",
        via_chat=True,
    )
    assert result.text == ""


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("profile", "expected"), [("openrouter", True), ("openai_compatible", False)]
)
async def test_usage_extension_is_sent_only_to_openrouter(profile: str, expected: bool) -> None:
    """Groq отвечает отказом на `usage.include`; OpenRouter без него не отдаёт стоимость."""
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["json"] = json.loads(request.read())
        return _chat_reply("работает")

    await _transport_over(profile, handler).complete(
        model="m", messages=[{"role": "user", "content": "hi"}], response_schema=None,
        max_output_tokens=16, parameters={},
    )

    assert ("usage" in seen["json"]) is expected  # type: ignore[operator]


@pytest.mark.asyncio
async def test_transport_maps_provider_rejection_to_readable_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(400, json={"error": {"message": "file is too short"}})

    with pytest.raises(ProviderError) as raised:
        await _transport_over("openai_compatible", handler).transcribe(
            model="whisper-large-v3-turbo", audio=b"x", audio_format="wav", language="ru"
        )
    assert raised.value.code == "ai_provider_unavailable"


def test_audio_format_follows_recorder_content_type() -> None:
    assert _audio_format("audio/webm;codecs=opus") == "webm"
    assert _audio_format("audio/mp4") == "m4a"
    assert _audio_format("Audio/OGG") == "ogg"
    with pytest.raises(AiGatewayError) as raised:
        _audio_format("text/plain")
    assert (raised.value.code, raised.value.status) == ("ai_audio_format_unsupported", 415)
    with pytest.raises(AiGatewayError):
        _audio_format(None)


def test_transcription_endpoint_returns_text(
    session: Session, speech_config: AiModelSelection, monkeypatch: pytest.MonkeyPatch
) -> None:
    del speech_config
    fake = FakeTransport(transcriptions=[_transcription("проверка связи")])
    monkeypatch.setattr(dictation, "ModelGateway", lambda db: ModelGateway(db, fake))
    app = FastAPI()
    app.include_router(dictation.router)
    app.dependency_overrides[get_session] = lambda: session

    response = TestClient(app).post(
        "/api/ai/transcriptions",
        files={"file": ("dictation.webm", b"audio-bytes", "audio/webm;codecs=opus")},
    )

    assert response.status_code == 200
    assert response.json()["text"] == "проверка связи"
    assert fake.transcribe_requests[0]["format"] == "webm"
