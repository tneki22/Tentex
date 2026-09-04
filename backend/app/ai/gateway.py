from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import json
import math
import time
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from datetime import time as day_time
from decimal import Decimal
from io import BytesIO
from typing import Any
from uuid import UUID

from PIL import Image
from pydantic import BaseModel, ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai.catalog import production_transport
from app.ai.provider import (
    OpenAICompatibleTransport,
    ProviderError,
    ProviderUsage,
)
from app.ai.schemas import (
    AiImagePart,
    AiMessage,
    AiModelSelection,
    AiModelTestRead,
    AiPreflight,
    AiUsage,
)
from app.ai.settings import (
    AiGatewayError,
    ResolvedModel,
    credential,
    model_capabilities,
    resolve_model,
)
from app.models import (
    AiCacheEntry,
    AiModelCatalogEntry,
    AiRun,
    AiSettings,
    utc_now,
)

ZERO = Decimal("0")

# Сбой одной из этих причин обычно временный (роутинг провайдера, пустой
# ответ из-за неудачного размещения, упёршийся в потолок общий пул) — стоит
# попробовать тот же запрос ещё раз.
#
# `ai_rate_limited` здесь потому, что дешёвые модели живут в общем пуле
# провайдера: 429 прилетает не из-за нашего расхода, а из-за чужой нагрузки, и
# через несколько секунд тот же запрос проходит. Разбор материала — это сотни
# вызовов подряд, и без повтора один чужой всплеск ронял всю обработку.
# `ai_invalid_credentials` и лимиты стоимости не повторяются никогда: ключ и
# кошелёк от ожидания не чинятся.
_RETRYABLE_PROVIDER_CODES = {
    "ai_provider_unavailable",
    "ai_empty_response",
    "ai_rate_limited",
    "ai_timeout",
}

# Паузы между попытками, по одной на каждый повтор: длина задаёт и число
# повторов. Пауза растёт, чтобы не долбить провайдера, который и так ограничил
# запросы; суммарно ожидание не превышает полминуты — дальше отказ честнее,
# чем бесконечная «обработка».
RETRY_BACKOFF_SECONDS: tuple[float, ...] = (2.0, 6.0, 15.0)

# Человекочитаемые названия возможностей модели: попадают в текст ошибки,
# когда выбранная модель не умеет то, что нужно функции.
_CAPABILITY_LABELS = {
    "structured_output": "структурированный ответ (response_format)",
    "streaming": "потоковый вывод",
    "audio_transcription": "приём аудио",
    "image_input": "приём изображений",
}

# Оценка стоимости картинки в токенах. Модели считают её плитками: изображение
# режется на квадраты 768×768, каждая плитка стоит фиксированно, а всё, что
# мельче 384×384, идёт одной плиткой. Коэффициенты взяты у Gemini; у других
# провайдеров они отличаются, но порядок тот же — числа нужны, чтобы
# предупредить о стоимости заранее, а не чтобы вести бухгалтерию. Фактический
# расход всё равно приходит в `usage` от провайдера.
IMAGE_TILE_PX = 768
IMAGE_SMALL_PX = 384
IMAGE_TILE_TOKENS = 258


def _data_url_bytes(url: str) -> bytes | None:
    """Содержимое `data:`-URL. Ссылки наружу мы не отправляем, так что иначе — None."""
    marker = "base64,"
    index = url.find(marker)
    if not url.startswith("data:") or index < 0:
        return None
    try:
        return base64.b64decode(url[index + len(marker):], validate=True)
    except (binascii.Error, ValueError):
        return None


def _image_tokens(url: str) -> int:
    """Во сколько токенов обойдётся картинка. Неизвестный формат — одна плитка."""
    payload = _data_url_bytes(url)
    if payload is None:
        return IMAGE_TILE_TOKENS
    try:
        with Image.open(BytesIO(payload)) as image:
            width, height = image.size
    except (OSError, ValueError):
        return IMAGE_TILE_TOKENS
    if width <= IMAGE_SMALL_PX and height <= IMAGE_SMALL_PX:
        return IMAGE_TILE_TOKENS
    tiles = math.ceil(width / IMAGE_TILE_PX) * math.ceil(height / IMAGE_TILE_PX)
    return tiles * IMAGE_TILE_TOKENS


@dataclass(frozen=True)
class AiTextRequest[T: BaseModel]:
    role: str
    messages: list[AiMessage]
    response_model: type[T] | None = None
    project_id: UUID | None = None
    context_manifest: list[dict[str, Any]] = field(default_factory=list)
    source_fingerprint: dict[str, Any] = field(default_factory=dict)
    request_model_override: AiModelSelection | None = None
    confirmed: bool = False
    parameters: dict[str, object] = field(default_factory=dict)
    # Лимит completion у рассуждающих моделей расходуется и на скрытые
    # рассуждения. Операция задаёт нижнюю границу для полезного JSON-ответа.
    minimum_output_tokens: int = 0
    # Заполняется, только когда вызов идёт из очереди фоновых операций
    # (`app.ai.jobs.process_ai_job`) — прямые вызовы (например, экзаменационный
    # чат) его не передают, и `AiRun.job_id` остаётся пустым.
    job_id: UUID | None = None


@dataclass(frozen=True)
class AiResult[T: BaseModel]:
    run_id: UUID
    value: T
    usage: AiUsage
    requested_model_id: str
    actual_model_id: str
    cached: bool


@dataclass(frozen=True)
class AiStreamEvent:
    kind: str
    delta: str = ""
    run_id: UUID | None = None
    usage: AiUsage | None = None


def _error_status(code: str) -> int:
    return {
        "ai_invalid_credentials": 401,
        "ai_rate_limited": 429,
        "ai_provider_unavailable": 503,
        "ai_timeout": 504,
        "ai_cancelled": 499,
        "ai_empty_response": 502,
    }.get(code, 422)


def _gateway_error(code: str, detail: str) -> AiGatewayError:
    return AiGatewayError(detail, code=code, status=_error_status(code))


def _sum_usage(first: ProviderUsage, second: ProviderUsage) -> ProviderUsage:
    cost = None
    if first.cost_usd is not None or second.cost_usd is not None:
        cost = (first.cost_usd or ZERO) + (second.cost_usd or ZERO)
    return ProviderUsage(
        input_tokens=first.input_tokens + second.input_tokens,
        output_tokens=first.output_tokens + second.output_tokens,
        reasoning_tokens=first.reasoning_tokens + second.reasoning_tokens,
        cached_tokens=first.cached_tokens + second.cached_tokens,
        cost_usd=cost,
    )


class ModelGateway:
    def __init__(
        self,
        session: Session,
        transport: OpenAICompatibleTransport | None = None,
        retry_backoff: Sequence[float] = RETRY_BACKOFF_SECONDS,
    ) -> None:
        self.session = session
        self.transport = transport
        # Паузы между повторами. Тесты передают пустую последовательность,
        # чтобы не ждать по-настоящему.
        self.retry_backoff = tuple(retry_backoff)

    async def preflight(self, request: AiTextRequest[Any]) -> AiPreflight:
        resolved = resolve_model(self.session, request.role, request.request_model_override)
        credential(self.session, resolved.provider.id)
        model = self._catalog_model(resolved)
        response_schema = self._response_schema(request)
        parameters = self._parameters(resolved, request.parameters)
        configured_output_tokens = int(parameters.get("max_output_tokens", 2000))
        output_tokens = max(configured_output_tokens, request.minimum_output_tokens)
        parameters = {**parameters, "max_output_tokens": output_tokens}
        input_tokens = self._estimate_input(request.messages, response_schema)
        request_hash = self._request_hash(request, resolved, parameters, response_schema)
        cached = bool(
            resolved.role.cache_policy != "none" and self.session.get(AiCacheEntry, request_hash)
        )
        estimated_usd = self._estimated_cost(model, input_tokens, output_tokens)
        settings = self.session.get(AiSettings, 1)
        assert settings is not None
        confirmation_reasons = []
        if estimated_usd is None:
            confirmation_reasons.append("unknown_price")
        if (
            estimated_usd is not None
            and settings.confirm_cost_usd is not None
            and estimated_usd >= settings.confirm_cost_usd
        ):
            confirmation_reasons.append("cost_threshold")
        if input_tokens > settings.confirm_input_tokens:
            confirmation_reasons.append("large_context")
        if not cached:
            self._check_limits(settings, estimated_usd)
        estimated_rub = (
            estimated_usd * settings.usd_rub_rate
            if estimated_usd is not None and settings.usd_rub_rate is not None
            else None
        )
        return AiPreflight(
            role=request.role,
            modality=resolved.role.modality,
            provider_id=resolved.provider.id,
            provider_label=resolved.provider.label,
            model_id=resolved.model_id,
            model_source=resolved.source,
            request_hash=request_hash,
            estimated_input_tokens=input_tokens,
            estimated_output_tokens=output_tokens,
            estimated_cost_usd=estimated_usd,
            estimated_cost_rub=estimated_rub,
            usd_rub_rate=settings.usd_rub_rate,
            usd_rub_rate_date=settings.usd_rub_rate_date,
            cached=cached,
            confirmation_required=bool(confirmation_reasons) and not cached,
            confirmation_reasons=confirmation_reasons,
            context_manifest=request.context_manifest,
        )

    async def preflight_confirmed(self, request: AiTextRequest[Any]) -> AiPreflight:
        """Предпросмотр с проверкой подтверждения — общий для `complete()`,
        `stream()` и постановки в очередь (`start()` у ролей ИИ, Ш4 плана):
        задача не должна попасть в очередь, если стоимость или контекст ещё не
        подтверждены, а не проваливаться на этом уже во время исполнения.
        """
        preflight = await self.preflight(request)
        if preflight.confirmation_required and not request.confirmed:
            raise AiGatewayError(
                "Перед вызовом нужно подтвердить стоимость или большой контекст",
                code="ai_confirmation_required",
                context={"reasons": preflight.confirmation_reasons},
            )
        return preflight

    async def complete[T: BaseModel](self, request: AiTextRequest[T]) -> AiResult[T]:
        if request.response_model is None:
            raise AiGatewayError(
                "Для complete нужна схема структурного ответа",
                code="ai_response_schema_missing",
            )
        preflight = await self.preflight_confirmed(request)
        resolved = resolve_model(self.session, request.role, request.request_model_override)
        cache = self.session.get(AiCacheEntry, preflight.request_hash)
        if cache is not None and resolved.role.cache_policy != "none":
            return self._cached_result(request, resolved, preflight, cache)
        transport = self.transport or production_transport(self.session, resolved.provider.id)
        run = self._start_run(request, resolved, preflight)
        started = time.monotonic()
        messages = [item.model_dump() for item in request.messages]
        response_schema = request.response_model.model_json_schema()
        parameters = self._parameters(resolved, {
            **request.parameters,
            "max_output_tokens": preflight.estimated_output_tokens,
        })
        combined_usage = ProviderUsage()
        # Временный сбой провайдера или один невалидный по схеме ответ не должен
        # ронять весь вызов: попытки повторяются с растущей паузой, и только
        # исчерпав их, мы сдаёмся и записываем неудачу. Схему модель
        # переписывает по замечанию, поэтому её попытка — последняя.
        attempts = len(self.retry_backoff) + 1
        for attempt in range(attempts):
            last_attempt = attempt == attempts - 1
            try:
                result = await transport.complete(
                    model=resolved.model_id,
                    messages=messages,
                    response_schema=response_schema,
                    max_output_tokens=preflight.estimated_output_tokens,
                    parameters=parameters,
                )
            except ProviderError as error:
                if not last_attempt and error.code in _RETRYABLE_PROVIDER_CODES:
                    await asyncio.sleep(self.retry_backoff[attempt])
                    continue
                self._fail_run(run.id, error.code, started)
                raise _gateway_error(error.code, error.detail) from error
            combined_usage = _sum_usage(combined_usage, result.usage)
            try:
                value = request.response_model.model_validate_json(result.content)
            except (ValidationError, ValueError, json.JSONDecodeError) as error:
                if not last_attempt:
                    messages = [
                        *messages,
                        {"role": "assistant", "content": result.content},
                        {
                            "role": "user",
                            "content": (
                                f"Ответ не прошёл проверку по схеме: {error}. Пришли только "
                                "исправленный JSON строго по той же схеме."
                            ),
                        },
                    ]
                    continue
                self._fail_run(run.id, "ai_invalid_structured_output", started)
                raise AiGatewayError(
                    "Ответ модели не прошёл структурную проверку",
                    code="ai_invalid_structured_output",
                ) from error
            usage = self._finish_run(
                run.id,
                value.model_dump(mode="json"),
                result.actual_model_id,
                result.request_id,
                combined_usage,
                started,
                resolved.role.cache_policy != "none",
            )
            return AiResult(
                run_id=run.id,
                value=value,
                usage=usage,
                requested_model_id=resolved.model_id,
                actual_model_id=result.actual_model_id,
                cached=False,
            )
        raise AssertionError("unreachable: loop always returns or raises")

    async def stream(self, request: AiTextRequest[Any]) -> AsyncIterator[AiStreamEvent]:
        preflight = await self.preflight_confirmed(request)
        resolved = resolve_model(self.session, request.role, request.request_model_override)
        transport = self.transport or production_transport(self.session, resolved.provider.id)
        run = self._start_run(request, resolved, preflight)
        started = time.monotonic()
        final_usage = ProviderUsage()
        actual_model = resolved.model_id
        request_id = None
        yield AiStreamEvent(kind="started", run_id=run.id)
        try:
            async for event in transport.stream(
                model=resolved.model_id,
                messages=[item.model_dump() for item in request.messages],
                max_output_tokens=preflight.estimated_output_tokens,
                parameters=self._parameters(resolved, {
                    **request.parameters,
                    "max_output_tokens": preflight.estimated_output_tokens,
                }),
            ):
                if event.usage is not None:
                    final_usage = event.usage
                actual_model = event.actual_model_id or actual_model
                request_id = event.request_id or request_id
                if event.delta:
                    yield AiStreamEvent(kind="delta", delta=event.delta, run_id=run.id)
        except asyncio.CancelledError:
            self._fail_run(run.id, "ai_cancelled", started, status="cancelled")
            raise
        except ProviderError as error:
            self._fail_run(run.id, error.code, started)
            raise _gateway_error(error.code, error.detail) from error
        usage = self._finish_run(
            run.id,
            {},
            actual_model,
            request_id,
            final_usage,
            started,
            cache=False,
        )
        yield AiStreamEvent(kind="completed", run_id=run.id, usage=usage)

    async def test_model(self, selection: AiModelSelection) -> AiModelTestRead:
        request = AiTextRequest(
            role="settings_model_test",
            messages=[AiMessage(role="user", content="Ответь одним словом: работает")],
            request_model_override=selection,
            confirmed=True,
        )
        preflight = await self.preflight(request)
        resolved = resolve_model(self.session, request.role, selection)
        transport = self.transport or production_transport(self.session, resolved.provider.id)
        run = self._start_run(request, resolved, preflight)
        started = time.monotonic()
        try:
            result = await transport.complete(
                model=resolved.model_id,
                messages=[item.model_dump() for item in request.messages],
                response_schema=None,
                max_output_tokens=preflight.estimated_output_tokens,
                parameters=self._parameters(resolved, {
                    **request.parameters,
                    "max_output_tokens": preflight.estimated_output_tokens,
                }),
            )
        except ProviderError as error:
            self._fail_run(run.id, error.code, started)
            raise _gateway_error(error.code, error.detail) from error
        self._finish_run(
            run.id,
            {},
            result.actual_model_id,
            result.request_id,
            result.usage,
            started,
            cache=False,
        )
        return AiModelTestRead(
            status="answered",
            run_id=run.id,
            duration_ms=round((time.monotonic() - started) * 1000),
            answer=result.content.strip()[:400],
            actual_model_id=result.actual_model_id,
            input_tokens=result.usage.input_tokens,
            output_tokens=result.usage.output_tokens,
        )

    async def transcribe(self, _request: object) -> None:
        raise AiGatewayError(
            "Распознавание речи появится вместе с диктовкой",
            code="ai_capability_unsupported",
        )

    def _catalog_model(self, resolved: ResolvedModel) -> AiModelCatalogEntry:
        row = resolved.model
        if not row.is_available:
            raise AiGatewayError(
                "Выбранной модели нет в актуальном локальном каталоге",
                code="ai_capability_unsupported",
                context={"model_id": resolved.model_id},
            )
        missing = resolved.role.required_capabilities - model_capabilities(row)
        if missing:
            labels = ", ".join(_CAPABILITY_LABELS.get(item, item) for item in sorted(missing))
            raise AiGatewayError(
                f"Модель «{resolved.model_id}» не поддерживает: {labels}. "
                "Выберите для этой функции другую модель или включите нужные "
                "возможности у модели в Параметрах ИИ.",
                code="ai_capability_unsupported",
                context={"model_id": resolved.model_id, "missing": sorted(missing)},
            )
        return row

    @staticmethod
    def _parameters(
        resolved: ResolvedModel, request_parameters: dict[str, object]
    ) -> dict[str, object]:
        return resolved.model.default_parameters | resolved.parameters | request_parameters

    @staticmethod
    def _response_schema(request: AiTextRequest[Any]) -> dict[str, Any] | None:
        return request.response_model.model_json_schema() if request.response_model else None

    @staticmethod
    def _estimate_input(messages: list[AiMessage], response_schema: dict[str, Any] | None) -> int:
        """Оценка входных токенов до вызова.

        Картинку нельзя мерить длиной её base64: страница весит около мегабайта,
        и по буквам получилось бы полмиллиона токенов вместо полутора тысяч —
        подтверждение стоимости срабатывало бы на каждой странице и врало бы в
        сотни раз. Поэтому текст считается по длине, картинки — по плиткам.
        """
        image_tokens = 0
        text_parts: list[Any] = []
        for message in messages:
            if isinstance(message.content, str):
                text_parts.append(message.content)
                continue
            for part in message.content:
                if isinstance(part, AiImagePart):
                    image_tokens += _image_tokens(part.image_url.url)
                else:
                    text_parts.append(part.text)
        payload = json.dumps(
            {"text": text_parts, "schema": response_schema},
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode()
        return max(1, image_tokens + math.ceil(len(payload) / 3))

    @staticmethod
    def _hashable_messages(messages: list[AiMessage]) -> list[dict[str, Any]]:
        """Сообщения для ключа кэша: картинка сворачивается в свой отпечаток.

        Ключ должен оставаться коротким и стабильным. Тот же вырез страницы,
        полученный при повторном разборе, даёт тот же sha256 — и тот же ключ.
        """
        result: list[dict[str, Any]] = []
        for message in messages:
            dumped = message.model_dump()
            content = dumped.get("content")
            if not isinstance(content, list):
                result.append(dumped)
                continue
            for part in content:
                if part.get("type") != "image_url":
                    continue
                url = str(part["image_url"]["url"])
                part["image_url"]["url"] = f"sha256:{hashlib.sha256(url.encode()).hexdigest()}"
            result.append(dumped)
        return result

    @staticmethod
    def _estimated_cost(
        model: AiModelCatalogEntry, input_tokens: int, output_tokens: int
    ) -> Decimal | None:
        if model.prompt_price_usd is None or model.completion_price_usd is None:
            return None
        return model.prompt_price_usd * input_tokens + model.completion_price_usd * output_tokens

    def _check_limits(self, settings: AiSettings, estimate: Decimal | None) -> None:
        if (
            estimate is not None
            and settings.operation_limit_usd is not None
            and estimate > settings.operation_limit_usd
        ):
            raise AiGatewayError(
                "Оценка превышает лимит одного вызова",
                code="ai_operation_limit",
                context={"estimated_cost_usd": str(estimate)},
            )
        if settings.daily_limit_usd is None:
            return
        start = datetime.combine(date.today(), day_time.min)
        spent = self.session.scalar(
            select(func.coalesce(func.sum(AiRun.actual_cost_usd), 0)).where(
                AiRun.status == "succeeded", AiRun.created_at >= start
            )
        )
        if estimate is not None and Decimal(spent or 0) + estimate > settings.daily_limit_usd:
            raise AiGatewayError(
                "Дневной лимит внешних моделей исчерпан",
                code="ai_daily_limit",
                context={"spent_usd": str(spent or 0)},
            )

    @staticmethod
    def _request_hash(
        request: AiTextRequest[Any],
        resolved: ResolvedModel,
        parameters: dict[str, object],
        response_schema: dict[str, Any] | None,
    ) -> str:
        canonical = json.dumps(
            {
                "role": request.role,
                "modality": resolved.role.modality,
                "provider_id": str(resolved.provider.id),
                "model": resolved.model_id,
                "parameters": parameters,
                "prompt_version": resolved.role.prompt_version,
                "response_schema": response_schema,
                "messages": ModelGateway._hashable_messages(request.messages),
                "project_id": str(request.project_id) if request.project_id else None,
                "context_manifest": request.context_manifest,
                "source_fingerprint": request.source_fingerprint,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(canonical.encode()).hexdigest()

    def _start_run(
        self, request: AiTextRequest[Any], resolved: ResolvedModel, preflight: AiPreflight
    ) -> AiRun:
        settings = self.session.get(AiSettings, 1)
        model = self.session.get(AiModelCatalogEntry, (resolved.provider.id, resolved.model_id))
        assert settings is not None and model is not None
        self.session.commit()
        with self.session.begin():
            run = AiRun(
                project_id=request.project_id,
                job_id=request.job_id,
                provider_id=resolved.provider.id,
                provider_label_snapshot=resolved.provider.label,
                role=request.role,
                modality=resolved.role.modality,
                status="running",
                requested_model_id=resolved.model_id,
                prompt_version=resolved.role.prompt_version,
                request_hash=preflight.request_hash,
                context_manifest=request.context_manifest,
                estimated_input_tokens=preflight.estimated_input_tokens,
                estimated_output_tokens=preflight.estimated_output_tokens,
                estimated_cost_usd=preflight.estimated_cost_usd,
                usd_rub_rate_snapshot=settings.usd_rub_rate,
                usd_rub_rate_date=settings.usd_rub_rate_date,
                pricing_snapshot_at=model.pricing_snapshot_at,
            )
            self.session.add(run)
            self.session.flush()
        return run

    def _cached_result[T: BaseModel](
        self,
        request: AiTextRequest[T],
        resolved: ResolvedModel,
        preflight: AiPreflight,
        cache: AiCacheEntry,
    ) -> AiResult[T]:
        assert request.response_model is not None
        value = request.response_model.model_validate(cache.response_payload)
        self.session.commit()
        with self.session.begin():
            cache.hit_count += 1
            cache.last_used_at = utc_now()
            run = AiRun(
                project_id=request.project_id,
                job_id=request.job_id,
                provider_id=resolved.provider.id,
                provider_label_snapshot=resolved.provider.label,
                role=request.role,
                modality=resolved.role.modality,
                status="cached",
                requested_model_id=resolved.model_id,
                actual_model_id=resolved.model_id,
                prompt_version=resolved.role.prompt_version,
                request_hash=preflight.request_hash,
                context_manifest=request.context_manifest,
                estimated_input_tokens=preflight.estimated_input_tokens,
                estimated_output_tokens=preflight.estimated_output_tokens,
                estimated_cost_usd=preflight.estimated_cost_usd,
                input_tokens=0,
                output_tokens=0,
                actual_cost_usd=ZERO,
                actual_cost_rub=ZERO,
                response_payload=cache.response_payload,
                cached_from_run_id=cache.source_run_id,
                completed_at=utc_now(),
            )
            self.session.add(run)
            self.session.flush()
        return AiResult(
            run.id,
            value,
            AiUsage(actual_cost_usd=ZERO, actual_cost_rub=ZERO),
            resolved.model_id,
            resolved.model_id,
            True,
        )

    def _finish_run(
        self,
        run_id: UUID,
        payload: dict[str, Any],
        actual_model: str,
        request_id: str | None,
        provider_usage: ProviderUsage,
        started: float,
        cache: bool,
    ) -> AiUsage:
        self.session.commit()
        with self.session.begin():
            run = self.session.get(AiRun, run_id)
            assert run is not None
            actual_usd = provider_usage.cost_usd
            actual_rub = (
                actual_usd * run.usd_rub_rate_snapshot
                if actual_usd is not None and run.usd_rub_rate_snapshot is not None
                else None
            )
            run.status = "succeeded"
            run.actual_model_id = actual_model
            run.provider_request_id = request_id
            run.input_tokens = provider_usage.input_tokens
            run.output_tokens = provider_usage.output_tokens
            run.reasoning_tokens = provider_usage.reasoning_tokens
            run.provider_cached_tokens = provider_usage.cached_tokens
            run.actual_cost_usd = actual_usd
            run.actual_cost_rub = actual_rub
            run.response_payload = payload
            run.duration_ms = round((time.monotonic() - started) * 1000)
            run.completed_at = utc_now()
            if cache:
                self.session.add(
                    AiCacheEntry(
                        request_hash=run.request_hash,
                        source_run_id=run.id,
                        project_id=run.project_id,
                        role=run.role,
                        response_payload=payload,
                    )
                )
        return AiUsage(
            input_tokens=provider_usage.input_tokens,
            output_tokens=provider_usage.output_tokens,
            reasoning_tokens=provider_usage.reasoning_tokens,
            provider_cached_tokens=provider_usage.cached_tokens,
            actual_cost_usd=actual_usd,
            actual_cost_rub=actual_rub,
        )

    def _fail_run(self, run_id: UUID, code: str, started: float, status: str = "failed") -> None:
        self.session.rollback()
        with self.session.begin():
            run = self.session.get(AiRun, run_id)
            assert run is not None
            run.status = status
            run.error_code = code
            run.duration_ms = round((time.monotonic() - started) * 1000)
            run.completed_at = utc_now()
