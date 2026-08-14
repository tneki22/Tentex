from __future__ import annotations

from collections import deque
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AsyncOpenAI,
    AuthenticationError,
    RateLimitError,
)

from app.config import settings


@dataclass(frozen=True)
class ProviderModel:
    model_id: str
    display_name: str
    context_length: int | None = None
    max_completion_tokens: int | None = None
    supported_parameters: list[str] = field(default_factory=list)
    input_modalities: list[str] = field(default_factory=list)
    output_modalities: list[str] = field(default_factory=list)
    reasoning: dict[str, Any] = field(default_factory=dict)
    default_parameters: dict[str, Any] = field(default_factory=dict)
    prompt_price_usd: Decimal | None = None
    completion_price_usd: Decimal | None = None
    knowledge_cutoff: str | None = None
    expiration_date: str | None = None


@dataclass(frozen=True)
class ProviderUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0
    cached_tokens: int = 0
    cost_usd: Decimal | None = None


@dataclass(frozen=True)
class ProviderCompletion:
    content: str
    actual_model_id: str
    usage: ProviderUsage
    request_id: str | None = None


@dataclass(frozen=True)
class ProviderStreamEvent:
    delta: str = ""
    usage: ProviderUsage | None = None
    actual_model_id: str | None = None
    request_id: str | None = None


class ProviderError(Exception):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


class OpenAICompatibleTransport(Protocol):
    async def list_models(self) -> list[ProviderModel]: ...

    async def complete(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        response_schema: dict[str, Any] | None,
        max_output_tokens: int,
        parameters: dict[str, object],
    ) -> ProviderCompletion: ...

    def stream(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        max_output_tokens: int,
        parameters: dict[str, object],
    ) -> AsyncIterator[ProviderStreamEvent]: ...


def _decimal(value: object) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _usage(value: object) -> ProviderUsage:
    data = value.model_dump() if hasattr(value, "model_dump") else (value or {})
    details = data.get("completion_tokens_details") or {}
    prompt_details = data.get("prompt_tokens_details") or {}
    return ProviderUsage(
        input_tokens=data.get("prompt_tokens") or 0,
        output_tokens=data.get("completion_tokens") or 0,
        reasoning_tokens=details.get("reasoning_tokens") or 0,
        cached_tokens=prompt_details.get("cached_tokens") or 0,
        cost_usd=_decimal(data.get("cost")),
    )


def normalize_provider_error(error: Exception) -> ProviderError:
    if isinstance(error, AuthenticationError):
        return ProviderError("ai_invalid_credentials", "Провайдер отклонил ключ")
    if isinstance(error, RateLimitError):
        return ProviderError("ai_rate_limited", "Провайдер временно ограничил запросы")
    if isinstance(error, APITimeoutError):
        return ProviderError("ai_timeout", "Провайдер не ответил вовремя")
    if isinstance(error, APIConnectionError):
        return ProviderError("ai_provider_unavailable", "Не удалось подключиться к провайдеру")
    if isinstance(error, APIStatusError):
        if error.status_code >= 500:
            return ProviderError("ai_provider_unavailable", "Провайдер временно недоступен")
        return ProviderError("ai_provider_unavailable", "Провайдер отклонил запрос")
    if isinstance(error, ProviderError):
        return error
    return ProviderError("ai_provider_unavailable", "Вызов внешней модели завершился ошибкой")


class OpenAITransport:
    def __init__(self, base_url: str, api_key: str) -> None:
        self.client = AsyncOpenAI(
            base_url=base_url,
            api_key=api_key,
            timeout=settings.ai_timeout_seconds,
            max_retries=0,
        )

    async def list_models(self) -> list[ProviderModel]:
        try:
            result = await self.client.models.list()
        except Exception as error:
            raise normalize_provider_error(error) from error
        models = []
        for item in result.data:
            data = item.model_dump()
            pricing = data.get("pricing") or {}
            architecture = data.get("architecture") or {}
            models.append(
                ProviderModel(
                    model_id=item.id,
                    display_name=data.get("name") or item.id,
                    context_length=data.get("context_length"),
                    max_completion_tokens=(data.get("top_provider") or {}).get(
                        "max_completion_tokens"
                    ),
                    supported_parameters=data.get("supported_parameters") or [],
                    input_modalities=architecture.get("input_modalities") or [],
                    output_modalities=architecture.get("output_modalities") or [],
                    reasoning=data.get("reasoning") or {},
                    default_parameters=data.get("default_parameters") or {},
                    prompt_price_usd=_decimal(pricing.get("prompt")),
                    completion_price_usd=_decimal(pricing.get("completion")),
                    knowledge_cutoff=data.get("knowledge_cutoff"),
                    expiration_date=data.get("expiration_date"),
                )
            )
        return models

    async def complete(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        response_schema: dict[str, Any] | None,
        max_output_tokens: int,
        parameters: dict[str, object],
    ) -> ProviderCompletion:
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": max_output_tokens,
            "extra_body": {"usage": {"include": True}},
        }
        self._apply_parameters(kwargs, parameters)
        if response_schema is not None:
            kwargs["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "tentex_result",
                    "strict": True,
                    "schema": response_schema,
                },
            }
            kwargs["extra_body"]["provider"] = {"require_parameters": True}
        try:
            result = await self.client.chat.completions.create(**kwargs)
        except Exception as error:
            raise normalize_provider_error(error) from error
        content = result.choices[0].message.content if result.choices else None
        if not isinstance(content, str):
            raise ProviderError("ai_invalid_structured_output", "Модель вернула пустой ответ")
        return ProviderCompletion(
            content=content,
            actual_model_id=result.model,
            usage=_usage(result.usage),
            request_id=getattr(result, "id", None),
        )

    async def stream(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        max_output_tokens: int,
        parameters: dict[str, object],
    ) -> AsyncIterator[ProviderStreamEvent]:
        try:
            kwargs: dict[str, Any] = {
                "model": model,
                "messages": messages,
                "max_tokens": max_output_tokens,
                "stream": True,
                "stream_options": {"include_usage": True},
            }
            self._apply_parameters(kwargs, parameters)
            result = await self.client.chat.completions.create(**kwargs)
            async for item in result:
                delta = item.choices[0].delta.content if item.choices else ""
                yield ProviderStreamEvent(
                    delta=delta or "",
                    usage=_usage(item.usage) if item.usage else None,
                    actual_model_id=item.model,
                    request_id=getattr(item, "id", None),
                )
        except Exception as error:
            raise normalize_provider_error(error) from error

    @staticmethod
    def _apply_parameters(kwargs: dict[str, Any], parameters: dict[str, object]) -> None:
        direct = {
            "temperature",
            "top_p",
            "seed",
            "frequency_penalty",
            "presence_penalty",
            "stop",
        }
        extra = dict(kwargs.get("extra_body") or {})
        for key, value in parameters.items():
            if key == "max_output_tokens":
                continue
            if key in direct:
                kwargs[key] = value
            else:
                extra[key] = value
        if extra:
            kwargs["extra_body"] = extra


class FakeTransport:
    def __init__(
        self,
        *,
        models: Sequence[ProviderModel] = (),
        completions: Sequence[ProviderCompletion | Exception] = (),
        streams: Sequence[Sequence[ProviderStreamEvent] | Exception] = (),
    ) -> None:
        self.models = list(models)
        self.completions = deque(completions)
        self.streams = deque(streams)
        self.list_calls = 0
        self.complete_calls = 0
        self.stream_calls = 0
        self.complete_requests: list[dict[str, object]] = []

    async def list_models(self) -> list[ProviderModel]:
        self.list_calls += 1
        return list(self.models)

    async def complete(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        response_schema: dict[str, Any] | None,
        max_output_tokens: int,
        parameters: dict[str, object],
    ) -> ProviderCompletion:
        self.complete_calls += 1
        self.complete_requests.append(
            {
                "model": model,
                "messages": messages,
                "response_schema": response_schema,
                "max_output_tokens": max_output_tokens,
                "parameters": parameters,
            }
        )
        if not self.completions:
            raise ProviderError("ai_provider_unavailable", "Fake response queue is empty")
        result = self.completions.popleft()
        if isinstance(result, Exception):
            raise result
        return result

    async def stream(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        max_output_tokens: int,
        parameters: dict[str, object],
    ) -> AsyncIterator[ProviderStreamEvent]:
        del model, messages, max_output_tokens, parameters
        self.stream_calls += 1
        if not self.streams:
            raise ProviderError("ai_provider_unavailable", "Fake stream queue is empty")
        result = self.streams.popleft()
        if isinstance(result, Exception):
            raise result
        for item in result:
            yield item
