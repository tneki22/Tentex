from decimal import Decimal

import pytest
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.credentials import encrypt_secret
from app.ai.gateway import AiTextRequest, ModelGateway
from app.ai.provider import (
    FakeTransport,
    ProviderCompletion,
    ProviderError,
    ProviderStreamEvent,
    ProviderUsage,
)
from app.ai.schemas import AiMessage
from app.models import AiCacheEntry, AiConnection, AiModelCatalogEntry, AiRun, AiSettings
from app.projects.errors import ProjectDomainError


class ExampleResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer: str


def _request(*, confirmed: bool = False, marker: str = "one") -> AiTextRequest:
    return AiTextRequest(
        role="material_text_cleanup",
        messages=[AiMessage(role="user", content="data")],
        response_model=ExampleResult,
        source_fingerprint={"marker": marker},
        confirmed=confirmed,
    )


def _completion(answer: str = "ok") -> ProviderCompletion:
    return ProviderCompletion(
        content=f'{{"answer":"{answer}"}}',
        actual_model_id="test/structured-model",
        request_id="req-1",
        usage=ProviderUsage(
            input_tokens=100,
            output_tokens=20,
            reasoning_tokens=3,
            cached_tokens=4,
            cost_usd=Decimal("0.01"),
        ),
    )


@pytest.mark.asyncio
async def test_complete_records_usage_rubles_and_exact_cache(
    session: Session, ai_config: str
) -> None:
    del ai_config
    fake = FakeTransport(completions=[_completion()])
    gateway = ModelGateway(session, fake)
    first = await gateway.complete(_request())
    second = await gateway.complete(_request())
    assert first.value.answer == "ok"
    assert first.usage.actual_cost_usd == Decimal("0.01")
    assert first.usage.actual_cost_rub == Decimal("0.90")
    assert second.cached is True
    assert second.usage.actual_cost_usd == Decimal("0")
    assert fake.complete_calls == 1
    assert session.scalar(select(AiCacheEntry.hit_count)) == 1
    statuses = list(session.scalars(select(AiRun.status).order_by(AiRun.created_at)))
    assert statuses == ["succeeded", "cached"]


@pytest.mark.asyncio
async def test_cache_invalidation_uses_source_fingerprint(session: Session, ai_config: str) -> None:
    del ai_config
    fake = FakeTransport(completions=[_completion("one"), _completion("two")])
    gateway = ModelGateway(session, fake)
    assert (await gateway.complete(_request(marker="one"))).value.answer == "one"
    assert (await gateway.complete(_request(marker="two"))).value.answer == "two"
    assert fake.complete_calls == 2


@pytest.mark.asyncio
async def test_invalid_structured_output_is_not_cached(session: Session, ai_config: str) -> None:
    del ai_config
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
        await ModelGateway(session, fake).complete(_request())
    assert caught.value.code == "ai_invalid_structured_output"
    assert session.scalar(select(AiCacheEntry)) is None
    assert session.scalar(select(AiRun.status)) == "failed"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("provider_code", "expected_status"),
    [
        ("ai_invalid_credentials", 401),
        ("ai_rate_limited", 429),
        ("ai_timeout", 504),
        ("ai_provider_unavailable", 503),
    ],
)
async def test_provider_errors_are_normalized(
    session: Session,
    ai_config: str,
    provider_code: str,
    expected_status: int,
) -> None:
    del ai_config
    fake = FakeTransport(completions=[ProviderError(provider_code, "provider detail")])
    with pytest.raises(ProjectDomainError) as caught:
        await ModelGateway(session, fake).complete(_request())
    assert caught.value.code == provider_code
    assert caught.value.status == expected_status
    assert session.scalar(select(AiRun.error_code)) == provider_code


@pytest.mark.asyncio
async def test_limits_and_unknown_price_stop_before_provider(
    session: Session, ai_config: str
) -> None:
    del ai_config
    settings = session.get(AiSettings, 1)
    assert settings is not None
    settings.operation_limit_usd = Decimal("0.000001")
    session.commit()
    fake = FakeTransport(completions=[_completion()])
    with pytest.raises(ProjectDomainError) as caught:
        await ModelGateway(session, fake).complete(_request())
    assert caught.value.code == "ai_operation_limit"
    assert fake.complete_calls == 0
    settings.operation_limit_usd = None
    model = session.get(AiModelCatalogEntry, ("text", "test/structured-model"))
    assert model is not None
    model.prompt_price_usd = None
    model.completion_price_usd = None
    session.commit()
    preflight = await ModelGateway(session, fake).preflight(_request())
    assert preflight.confirmation_reasons == ["unknown_price"]
    with pytest.raises(ProjectDomainError) as caught:
        await ModelGateway(session, fake).complete(_request())
    assert caught.value.code == "ai_confirmation_required"
    assert fake.complete_calls == 0


@pytest.mark.asyncio
async def test_disabled_missing_credentials_and_capability(
    session: Session, ai_config: str
) -> None:
    del ai_config
    settings = session.get(AiSettings, 1)
    assert settings is not None
    settings.external_models_enabled = False
    session.commit()
    with pytest.raises(ProjectDomainError) as caught:
        await ModelGateway(session, FakeTransport()).preflight(_request())
    assert caught.value.code == "ai_disabled"
    settings.external_models_enabled = True
    connection = session.get(AiConnection, "text")
    assert connection is not None
    connection.api_key_ciphertext = None
    session.commit()
    with pytest.raises(ProjectDomainError) as caught:
        await ModelGateway(session, FakeTransport()).preflight(_request())
    assert caught.value.code == "ai_credentials_missing"
    connection.api_key_ciphertext = encrypt_secret("test-secret")
    connection.default_model_id = None
    session.commit()
    with pytest.raises(ProjectDomainError) as caught:
        await ModelGateway(session, FakeTransport()).preflight(_request())
    assert caught.value.code == "ai_model_not_configured"
    connection.default_model_id = "test/structured-model"
    model = session.get(AiModelCatalogEntry, ("text", connection.default_model_id))
    assert model is not None
    model.supported_parameters = []
    session.commit()
    with pytest.raises(ProjectDomainError) as caught:
        await ModelGateway(session, FakeTransport()).preflight(_request())
    assert caught.value.code == "ai_capability_unsupported"


@pytest.mark.asyncio
async def test_daily_limit_stops_before_provider(session: Session, ai_config: str) -> None:
    del ai_config
    settings = session.get(AiSettings, 1)
    assert settings is not None
    settings.daily_limit_usd = Decimal("0")
    session.commit()
    fake = FakeTransport(completions=[_completion()])
    with pytest.raises(ProjectDomainError) as caught:
        await ModelGateway(session, fake).complete(_request())
    assert caught.value.code == "ai_daily_limit"
    assert fake.complete_calls == 0


@pytest.mark.asyncio
async def test_stream_records_final_usage(session: Session, ai_config: str) -> None:
    del ai_config
    fake = FakeTransport(
        streams=[
            [
                ProviderStreamEvent(delta="При"),
                ProviderStreamEvent(delta="вет"),
                ProviderStreamEvent(
                    usage=ProviderUsage(
                        input_tokens=4,
                        output_tokens=2,
                        cost_usd=Decimal("0.002"),
                    ),
                    actual_model_id="test/structured-model",
                    request_id="stream-1",
                ),
            ]
        ]
    )
    request = AiTextRequest(
        role="exam_chat_reply",
        messages=[AiMessage(role="user", content="Привет")],
    )
    events = [event async for event in ModelGateway(session, fake).stream(request)]
    assert "".join(event.delta for event in events) == "Привет"
    assert events[-1].kind == "completed"
    run = session.scalar(select(AiRun))
    assert run is not None
    assert run.output_tokens == 2
    assert run.actual_cost_rub == Decimal("0.180000000000")
