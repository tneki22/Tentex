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
from app.ai.schemas import AiMessage, AiModelSelection
from app.models import (
    AiCacheEntry,
    AiModelCatalogEntry,
    AiProviderConnection,
    AiRun,
    AiSettings,
)
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


def _invalid_json_completion() -> ProviderCompletion:
    return ProviderCompletion(
        content="not-json",
        actual_model_id="test/structured-model",
        usage=ProviderUsage(),
    )


# Паузы между повторами в тестах нулевые: проверяется число попыток, а не
# умение ждать. С боевыми паузами набор простаивал бы десятки секунд.
NO_WAIT = (0.0, 0.0, 0.0)


@pytest.mark.asyncio
async def test_invalid_structured_output_is_not_cached(session: Session, ai_config: str) -> None:
    del ai_config
    # Все ответы невалидны: попытки самоисправления не спасают, и вызов
    # проваливается, исчерпав ровно отведённое число обращений к транспорту.
    fake = FakeTransport(completions=[_invalid_json_completion() for _ in range(4)])
    with pytest.raises(ProjectDomainError) as caught:
        await ModelGateway(session, fake, NO_WAIT).complete(_request())
    assert caught.value.code == "ai_invalid_structured_output"
    assert session.scalar(select(AiCacheEntry)) is None
    assert session.scalar(select(AiRun.status)) == "failed"
    assert fake.complete_calls == 4


@pytest.mark.asyncio
async def test_retries_once_on_invalid_json_then_succeeds(
    session: Session, ai_config: str
) -> None:
    del ai_config
    fake = FakeTransport(completions=[_invalid_json_completion(), _completion()])
    result = await ModelGateway(session, fake, NO_WAIT).complete(_request())
    assert result.value.answer == "ok"
    assert fake.complete_calls == 2
    retry_messages = fake.complete_requests[1]["messages"]
    assert retry_messages[-2] == {"role": "assistant", "content": "not-json"}
    assert "проверку по схеме" in retry_messages[-1]["content"]
    assert session.scalar(select(AiRun.status)) == "succeeded"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "provider_code",
    ["ai_provider_unavailable", "ai_rate_limited", "ai_timeout", "ai_empty_response"],
)
async def test_retries_on_retryable_provider_error_then_succeeds(
    session: Session, ai_config: str, provider_code: str
) -> None:
    del ai_config
    # Три подряд временных отказа и успех с четвёртой попытки: ровно тот
    # случай, ради которого повторы и заведены — общий пул дешёвой модели
    # отдаёт 429 несколько запросов подряд, а потом отпускает.
    fake = FakeTransport(
        completions=[
            ProviderError(provider_code, "temporary hiccup"),
            ProviderError(provider_code, "temporary hiccup"),
            ProviderError(provider_code, "temporary hiccup"),
            _completion(),
        ]
    )
    result = await ModelGateway(session, fake, NO_WAIT).complete(_request())
    assert result.value.answer == "ok"
    assert fake.complete_calls == 4
    assert session.scalar(select(AiRun.status)) == "succeeded"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("provider_code", "expected_status", "retryable"),
    [
        ("ai_invalid_credentials", 401, False),
        ("ai_rate_limited", 429, True),
        ("ai_timeout", 504, True),
        ("ai_provider_unavailable", 503, True),
    ],
)
async def test_provider_errors_are_normalized(
    session: Session,
    ai_config: str,
    provider_code: str,
    expected_status: int,
    retryable: bool,
) -> None:
    del ai_config
    # Очередь заполнена под все попытки; невостребованные элементы остаются в
    # ней, если код не ретраится и вызов проваливается на первой же попытке.
    fake = FakeTransport(
        completions=[ProviderError(provider_code, "provider detail") for _ in range(4)]
    )
    with pytest.raises(ProjectDomainError) as caught:
        await ModelGateway(session, fake, NO_WAIT).complete(_request())
    assert caught.value.code == provider_code
    assert caught.value.status == expected_status
    assert session.scalar(select(AiRun.error_code)) == provider_code
    assert fake.complete_calls == (4 if retryable else 1)


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
    provider = session.query(AiProviderConnection).one()
    model = session.get(AiModelCatalogEntry, (provider.id, "test/structured-model"))
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
    provider = session.query(AiProviderConnection).one()
    provider.api_key_ciphertext = None
    session.commit()
    with pytest.raises(ProjectDomainError) as caught:
        await ModelGateway(session, FakeTransport()).preflight(_request())
    assert caught.value.code == "ai_credentials_missing"
    provider.api_key_ciphertext = encrypt_secret("test-secret")
    settings.default_text_provider_id = None
    settings.default_text_model_id = None
    session.commit()
    with pytest.raises(ProjectDomainError) as caught:
        await ModelGateway(session, FakeTransport()).preflight(_request())
    assert caught.value.code == "ai_model_not_configured"
    settings.default_text_provider_id = provider.id
    settings.default_text_model_id = "test/structured-model"
    model = session.get(AiModelCatalogEntry, (provider.id, settings.default_text_model_id))
    assert model is not None
    # Непустой список параметров без response_format — положительное свидетельство,
    # что структурный ответ не поддерживается: гейт срабатывает.
    model.supported_parameters = ["temperature", "max_tokens"]
    session.commit()
    with pytest.raises(ProjectDomainError) as caught:
        await ModelGateway(session, FakeTransport()).preflight(_request())
    assert caught.value.code == "ai_capability_unsupported"
    # Пустой список — «каталог параметров не заполнен» (модель добавлена вручную),
    # а не «не умеет». Не блокируем на отсутствии данных: вызов решит сам.
    model.supported_parameters = []
    session.commit()
    preflight = await ModelGateway(session, FakeTransport()).preflight(_request())
    assert preflight.model_id == "test/structured-model"


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


@pytest.mark.asyncio
async def test_model_test_uses_selected_provider_and_writes_safe_run(
    session: Session, ai_config: str
) -> None:
    provider = session.query(AiProviderConnection).one()
    fake = FakeTransport(
        completions=[
            ProviderCompletion(
                content="работает",
                actual_model_id=ai_config,
                usage=ProviderUsage(input_tokens=7, output_tokens=1),
            )
        ]
    )
    result = await ModelGateway(session, fake).test_model(
        AiModelSelection(provider_id=provider.id, model_id=ai_config)
    )
    run = session.get(AiRun, result.run_id)
    assert result.status == "answered"
    assert run is not None
    assert run.provider_id == provider.id
    assert run.role == "settings_model_test"
    assert run.context_manifest == []
    assert fake.complete_requests[0]["max_output_tokens"] == 1500
