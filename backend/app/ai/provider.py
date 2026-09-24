from __future__ import annotations

import base64
import json
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


_SPEECH_TO_TEXT_MARKERS = ("whisper", "transcribe")


def is_speech_to_text_id(model_id: str) -> bool:
    """Семейство распознавания речи по ID: whisper-*, *-transcribe.

    Такие модели говорят через `/audio/transcriptions`, а не через чат, поэтому
    проверка связи и вызов у них устроены иначе, чем у текстовых.
    """
    lowered = model_id.lower()
    return any(marker in lowered for marker in _SPEECH_TO_TEXT_MARKERS)


def _infer_modalities(
    model_id: str, input_modalities: list[str], output_modalities: list[str]
) -> tuple[list[str], list[str]]:
    """Достраивает модальности, которые провайдер не отдал в `/models`.

    OpenRouter присылает `architecture`, а Groq или OpenAI — нет: у них список
    только с ID. Без этого Whisper оказывается «без возможностей» и не попадает
    в выбор модели для речи. Догадываемся строго по ID семейства
    распознавания речи; остальное по-прежнему задаётся руками.
    """
    if input_modalities or not is_speech_to_text_id(model_id):
        return input_modalities, output_modalities
    return ["audio"], output_modalities or ["text"]


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
class TimedSegment:
    """Отрезок расшифровки: секунды от начала присланной записи и текст."""

    start: float
    end: float
    text: str


@dataclass(frozen=True)
class ProviderTranscription:
    text: str
    actual_model_id: str
    usage: ProviderUsage
    request_id: str | None = None
    # Пусто, если провайдер не отдаёт время фраз (чат-модели, gpt-4o-transcribe,
    # OpenRouter): тогда у расшифровки есть только сплошной текст.
    segments: tuple[TimedSegment, ...] = ()


@dataclass(frozen=True)
class ProviderEmbeddings:
    vectors: list[list[float]]
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

    async def embed(self, *, model: str, texts: list[str]) -> ProviderEmbeddings: ...

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

    async def transcribe(
        self,
        *,
        model: str,
        audio: bytes,
        audio_format: str,
        language: str,
        via_chat: bool = False,
        timestamps: bool = False,
    ) -> ProviderTranscription: ...


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


def _empty_response_error(choice: object, usage: object) -> ProviderError:
    """Пустой ответ бывает по разным причинам, и лечатся они по-разному."""
    finish_reason = getattr(choice, "finish_reason", None)
    message = getattr(choice, "message", None)
    reasoning = getattr(message, "reasoning", None) if message is not None else None
    reasoning_tokens = _usage(usage).reasoning_tokens
    if finish_reason == "length" or reasoning or reasoning_tokens:
        return ProviderError(
            "ai_empty_response",
            "Модель потратила весь лимит токенов на рассуждение и не успела ответить. "
            "Увеличьте максимум токенов ответа или выберите модель без рассуждения",
        )
    if finish_reason == "content_filter":
        return ProviderError(
            "ai_empty_response", "Провайдер заблокировал ответ фильтром содержимого"
        )
    return ProviderError("ai_empty_response", "Модель вернула пустой ответ")


def _provider_message(error: APIStatusError) -> str:
    """Объяснение провайдера: без него «Провайдер отклонил запрос» ничем не помогает."""
    body: object = getattr(error, "body", None)
    for _ in range(2):
        if isinstance(body, dict):
            message = body.get("message")
            if (
                isinstance(message, str)
                and message.strip()
                and message.strip() != "Provider returned error"
            ):
                return message.strip()
            metadata = body.get("metadata")
            raw = metadata.get("raw") if isinstance(metadata, dict) else None
            if isinstance(raw, str):
                try:
                    nested = json.loads(raw)
                except json.JSONDecodeError:
                    nested = None
                if isinstance(nested, dict):
                    nested_error = nested.get("error")
                    nested_message = (
                        nested_error.get("message") if isinstance(nested_error, dict) else None
                    )
                    if isinstance(nested_message, str) and nested_message.strip():
                        return nested_message.strip()
            body = body.get("error")
            continue
        break
    return ""


def _with_reason(base: str, error: APIStatusError) -> str:
    message = _provider_message(error)
    return f"{base}: {message}" if message else base


def normalize_provider_error(error: Exception) -> ProviderError:
    if isinstance(error, AuthenticationError):
        return ProviderError(
            "ai_invalid_credentials", _with_reason("Провайдер отклонил ключ", error)
        )
    if isinstance(error, RateLimitError):
        return ProviderError(
            "ai_rate_limited", _with_reason("Провайдер временно ограничил запросы", error)
        )
    if isinstance(error, APITimeoutError):
        return ProviderError("ai_timeout", "Провайдер не ответил вовремя")
    if isinstance(error, APIConnectionError):
        return ProviderError("ai_provider_unavailable", "Не удалось подключиться к провайдеру")
    if isinstance(error, APIStatusError):
        if error.status_code >= 500:
            return ProviderError(
                "ai_provider_unavailable", _with_reason("Провайдер временно недоступен", error)
            )
        return ProviderError(
            "ai_provider_unavailable", _with_reason("Провайдер отклонил запрос", error)
        )
    if isinstance(error, ProviderError):
        return error
    return ProviderError("ai_provider_unavailable", "Вызов внешней модели завершился ошибкой")


def _transcription_usage(value: object) -> ProviderUsage:
    """Расход распознавания: токены есть у gpt-4o-transcribe, у Whisper — только секунды."""
    data = value.model_dump() if hasattr(value, "model_dump") else (value or {})
    if not isinstance(data, dict):
        return ProviderUsage()
    return ProviderUsage(
        input_tokens=data.get("input_tokens") or 0,
        output_tokens=data.get("output_tokens") or 0,
        cost_usd=_decimal(data.get("cost")),
    )


def _timed_segment(raw: object) -> TimedSegment | None:
    """Отрезок из ответа `verbose_json`: у SDK это объект, у сырого JSON — словарь."""
    if isinstance(raw, dict):
        start, end, text = raw.get("start"), raw.get("end"), raw.get("text")
    else:
        start, end, text = (getattr(raw, name, None) for name in ("start", "end", "text"))
    if not isinstance(text, str) or not text.strip():
        return None
    try:
        return TimedSegment(float(start), float(end), text.strip())  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


class OpenAITransport:
    def __init__(
        self, base_url: str, api_key: str, catalog_profile: str = "openai_compatible"
    ) -> None:
        self.catalog_profile = catalog_profile
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
            input_modalities, output_modalities = _infer_modalities(
                item.id,
                architecture.get("input_modalities") or [],
                architecture.get("output_modalities") or [],
            )
            models.append(
                ProviderModel(
                    model_id=item.id,
                    display_name=data.get("name") or item.id,
                    context_length=data.get("context_length"),
                    max_completion_tokens=(data.get("top_provider") or {}).get(
                        "max_completion_tokens"
                    ),
                    supported_parameters=data.get("supported_parameters") or [],
                    input_modalities=input_modalities,
                    output_modalities=output_modalities,
                    reasoning=data.get("reasoning") or {},
                    default_parameters=data.get("default_parameters") or {},
                    prompt_price_usd=_decimal(pricing.get("prompt")),
                    completion_price_usd=_decimal(pricing.get("completion")),
                    knowledge_cutoff=data.get("knowledge_cutoff"),
                    expiration_date=data.get("expiration_date"),
                )
            )
        return models

    async def embed(self, *, model: str, texts: list[str]) -> ProviderEmbeddings:
        """Вызвать общий OpenAI-compatible `/embeddings` без провайдерных веток."""
        try:
            result = await self.client.embeddings.create(model=model, input=texts)
        except Exception as error:
            raise normalize_provider_error(error) from error
        vectors = [item.embedding for item in sorted(result.data, key=lambda item: item.index)]
        usage = getattr(result, "usage", None)
        return ProviderEmbeddings(
            vectors=vectors,
            actual_model_id=result.model,
            usage=ProviderUsage(input_tokens=getattr(usage, "prompt_tokens", 0) or 0),
            request_id=getattr(result, "id", None),
        )

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
        }
        # `usage.include` — расширение OpenRouter, из него приходит стоимость. Groq
        # и прочие OpenAI-совместимые API отвечают на незнакомое поле отказом,
        # а токены у них и так возвращаются в обычном `usage`.
        if self.catalog_profile == "openrouter":
            kwargs["extra_body"] = {"usage": {"include": True}}
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
        try:
            result = await self.client.chat.completions.create(**kwargs)
        except Exception as error:
            raise normalize_provider_error(error) from error
        choice = result.choices[0] if result.choices else None
        content = choice.message.content if choice is not None else None
        if not isinstance(content, str) or not content.strip():
            raise _empty_response_error(choice, result.usage)
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

    async def transcribe(
        self,
        *,
        model: str,
        audio: bytes,
        audio_format: str,
        language: str,
        via_chat: bool = False,
        timestamps: bool = False,
    ) -> ProviderTranscription:
        if via_chat:
            return await self._transcribe_via_chat(model, audio, audio_format, language)
        if timestamps and self.catalog_profile != "openrouter" and is_speech_to_text_id(model):
            timed = await self._transcribe_timed(model, audio, audio_format, language)
            if timed is not None:
                return timed
        try:
            if self.catalog_profile == "openrouter":
                # У OpenRouter собственный JSON-протокол: аудио уходит base64 в теле,
                # а не файлом multipart, как у OpenAI и Groq.
                data = await self.client.post(
                    "/audio/transcriptions",
                    body={
                        "model": model,
                        "input_audio": {
                            "data": base64.b64encode(audio).decode("ascii"),
                            "format": audio_format,
                        },
                        "language": language,
                    },
                    cast_to=object,
                )
                return ProviderTranscription(
                    text=str(data.get("text") or ""),
                    actual_model_id=model,
                    usage=_transcription_usage(data.get("usage")),
                )
            result = await self.client.audio.transcriptions.create(
                model=model,
                file=(f"dictation.{audio_format}", audio),
                language=language,
                response_format="json",
            )
        except Exception as error:
            raise normalize_provider_error(error) from error
        return ProviderTranscription(
            text=result.text or "",
            actual_model_id=model,
            usage=_transcription_usage(getattr(result, "usage", None)),
        )

    async def _transcribe_timed(
        self, model: str, audio: bytes, audio_format: str, language: str
    ) -> ProviderTranscription | None:
        """Расшифровка с временем фраз (`verbose_json`), как отдают Whisper у Groq и OpenAI.

        `None` — провайдер формат не принял, и вызывающий повторяет запрос
        обычным `json`: без времени фраз расшифровка всё равно лучше, чем отказ.
        Не принятым считается только отказ по самому запросу; ключ, лимиты и
        сеть пробрасываются как есть — повтор их не вылечит.
        """
        try:
            result = await self.client.audio.transcriptions.create(
                model=model,
                file=(f"audio.{audio_format}", audio),
                language=language,
                response_format="verbose_json",
            )
        except Exception as error:
            normalized = normalize_provider_error(error)
            if getattr(error, "status_code", None) in (400, 404, 415, 422):
                return None
            raise normalized from error
        segments = tuple(
            segment
            for raw in getattr(result, "segments", None) or ()
            if (segment := _timed_segment(raw)) is not None
        )
        return ProviderTranscription(
            text=getattr(result, "text", "") or "",
            actual_model_id=model,
            usage=_transcription_usage(getattr(result, "usage", None)),
            segments=segments,
        )

    async def _transcribe_via_chat(
        self, model: str, audio: bytes, audio_format: str, language: str
    ) -> ProviderTranscription:
        """Мультимодальная чат-модель (Gemini и подобные): аудио идёт частью сообщения.

        У таких моделей нет `/audio/transcriptions` — провайдер отвечает, что
        модели не существует, поэтому расшифровку просим обычным запросом.
        """
        kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": 4000,
            "temperature": 0,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                f"Дословно расшифруй речь из записи (язык: {language}). "
                                "Верни только текст расшифровки без комментариев и кавычек. "
                                "Если в записи нет речи, верни пустой ответ."
                            ),
                        },
                        {
                            "type": "input_audio",
                            "input_audio": {
                                "data": base64.b64encode(audio).decode("ascii"),
                                "format": audio_format,
                            },
                        },
                    ],
                }
            ],
        }
        if self.catalog_profile == "openrouter":
            kwargs["extra_body"] = {"usage": {"include": True}}
        try:
            result = await self.client.chat.completions.create(**kwargs)
        except Exception as error:
            raise normalize_provider_error(error) from error
        choice = result.choices[0] if result.choices else None
        content = choice.message.content if choice is not None else None
        return ProviderTranscription(
            # Пустой ответ здесь — не сбой, а «речи нет».
            text=content if isinstance(content, str) else "",
            actual_model_id=result.model,
            usage=_usage(result.usage),
            request_id=getattr(result, "id", None),
        )

    def _apply_parameters(self, kwargs: dict[str, Any], parameters: dict[str, object]) -> None:
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
            if key == "reasoning_effort":
                self._apply_reasoning(kwargs, extra, value)
            elif key in direct:
                kwargs[key] = value
            else:
                extra[key] = value
        if extra:
            kwargs["extra_body"] = extra

    def _apply_reasoning(
        self, kwargs: dict[str, Any], extra: dict[str, Any], value: object
    ) -> None:
        """Один параметр — два разных поля запроса, по профилю провайдера.

        У OpenRouter это объект `reasoning`, и только он умеет сказать «не
        рассуждай» (`enabled: false`). У OpenAI-совместимых API это плоский
        `reasoning_effort`, выключения в нём нет — там «off» значит просто не
        слать поле и оставить поведение модели по умолчанию.
        """
        if value is None:
            return
        if self.catalog_profile == "openrouter":
            extra["reasoning"] = {"enabled": False} if value == "off" else {"effort": value}
            return
        if value != "off":
            kwargs["reasoning_effort"] = value


class FakeTransport:
    def __init__(
        self,
        *,
        models: Sequence[ProviderModel] = (),
        completions: Sequence[ProviderCompletion | Exception] = (),
        streams: Sequence[Sequence[ProviderStreamEvent] | Exception] = (),
        transcriptions: Sequence[ProviderTranscription | Exception] = (),
        embeddings: Sequence[ProviderEmbeddings | Exception] = (),
    ) -> None:
        self.models = list(models)
        self.completions = deque(completions)
        self.streams = deque(streams)
        self.transcriptions = deque(transcriptions)
        self.embeddings = deque(embeddings)
        self.list_calls = 0
        self.complete_calls = 0
        self.stream_calls = 0
        self.complete_requests: list[dict[str, object]] = []
        self.transcribe_requests: list[dict[str, object]] = []
        self.embed_requests: list[dict[str, object]] = []

    async def list_models(self) -> list[ProviderModel]:
        self.list_calls += 1
        return list(self.models)

    async def embed(self, *, model: str, texts: list[str]) -> ProviderEmbeddings:
        self.embed_requests.append({"model": model, "texts": texts})
        if not self.embeddings:
            raise ProviderError("ai_provider_unavailable", "Fake embedding queue is empty")
        result = self.embeddings.popleft()
        if isinstance(result, Exception):
            raise result
        return result

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

    async def transcribe(
        self,
        *,
        model: str,
        audio: bytes,
        audio_format: str,
        language: str,
        via_chat: bool = False,
        timestamps: bool = False,
    ) -> ProviderTranscription:
        self.transcribe_requests.append(
            {
                "model": model,
                "bytes": len(audio),
                "format": audio_format,
                "language": language,
                "via_chat": via_chat,
                # Ключ появляется только у запросов со временем фраз: диктовка его
                # не просит, и её проверки на точное совпадение словаря не трогаем.
                **({"timestamps": True} if timestamps else {}),
            }
        )
        if not self.transcriptions:
            raise ProviderError("ai_provider_unavailable", "Fake transcription queue is empty")
        result = self.transcriptions.popleft()
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
