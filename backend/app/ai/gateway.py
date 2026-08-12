from __future__ import annotations

import asyncio
import hashlib
import json
import math
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import date, datetime
from datetime import time as day_time
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai.catalog import production_transport
from app.ai.provider import (
    OpenAICompatibleTransport,
    ProviderError,
    ProviderUsage,
)
from app.ai.schemas import AiMessage, AiPreflight, AiUsage
from app.ai.settings import AiGatewayError, ResolvedModel, credential, resolve_model
from app.models import (
    AiCacheEntry,
    AiModelCatalogEntry,
    AiRun,
    AiSettings,
    utc_now,
)

ZERO = Decimal("0")


@dataclass(frozen=True)
class AiTextRequest[T: BaseModel]:
    role: str
    messages: list[AiMessage]
    response_model: type[T] | None = None
    project_id: UUID | None = None
    context_manifest: list[dict[str, Any]] = field(default_factory=list)
    source_fingerprint: dict[str, Any] = field(default_factory=dict)
    request_model_override: str | None = None
    confirmed: bool = False
    parameters: dict[str, object] = field(default_factory=dict)


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
    }.get(code, 422)


def _gateway_error(code: str, detail: str) -> AiGatewayError:
    return AiGatewayError(detail, code=code, status=_error_status(code))


class ModelGateway:
    def __init__(
        self,
        session: Session,
        transport: OpenAICompatibleTransport | None = None,
    ) -> None:
        self.session = session
        self.transport = transport

    async def preflight(self, request: AiTextRequest[Any]) -> AiPreflight:
        resolved = resolve_model(self.session, request.role, request.request_model_override)
        credential(self.session, resolved.role.modality)
        model = self._catalog_model(resolved)
        response_schema = self._response_schema(request)
        parameters = resolved.parameters | request.parameters
        input_tokens = self._estimate_input(request.messages, response_schema)
        output_tokens = int(parameters.get("max_output_tokens", 2000))
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

    async def complete[T: BaseModel](self, request: AiTextRequest[T]) -> AiResult[T]:
        if request.response_model is None:
            raise AiGatewayError(
                "Для complete нужна схема структурного ответа",
                code="ai_response_schema_missing",
            )
        preflight = await self.preflight(request)
        if preflight.confirmation_required and not request.confirmed:
            raise AiGatewayError(
                "Перед вызовом нужно подтвердить стоимость или большой контекст",
                code="ai_confirmation_required",
                context={"reasons": preflight.confirmation_reasons},
            )
        resolved = resolve_model(self.session, request.role, request.request_model_override)
        cache = self.session.get(AiCacheEntry, preflight.request_hash)
        if cache is not None and resolved.role.cache_policy != "none":
            return self._cached_result(request, resolved, preflight, cache)
        transport = self.transport or production_transport(self.session, resolved.role.modality)
        run = self._start_run(request, resolved, preflight)
        started = time.monotonic()
        try:
            result = await transport.complete(
                model=resolved.model_id,
                messages=[item.model_dump() for item in request.messages],
                response_schema=request.response_model.model_json_schema(),
                max_output_tokens=preflight.estimated_output_tokens,
            )
            value = request.response_model.model_validate_json(result.content)
        except (ValidationError, ValueError, json.JSONDecodeError) as error:
            self._fail_run(run.id, "ai_invalid_structured_output", started)
            raise AiGatewayError(
                "Ответ модели не прошёл структурную проверку",
                code="ai_invalid_structured_output",
            ) from error
        except ProviderError as error:
            self._fail_run(run.id, error.code, started)
            raise _gateway_error(error.code, error.detail) from error
        usage = self._finish_run(
            run.id,
            value.model_dump(mode="json"),
            result.actual_model_id,
            result.request_id,
            result.usage,
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

    async def stream(self, request: AiTextRequest[Any]) -> AsyncIterator[AiStreamEvent]:
        preflight = await self.preflight(request)
        if preflight.confirmation_required and not request.confirmed:
            raise AiGatewayError(
                "Перед вызовом нужно подтвердить стоимость или большой контекст",
                code="ai_confirmation_required",
                context={"reasons": preflight.confirmation_reasons},
            )
        resolved = resolve_model(self.session, request.role, request.request_model_override)
        transport = self.transport or production_transport(self.session, resolved.role.modality)
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

    async def transcribe(self, _request: object) -> None:
        raise AiGatewayError(
            "Распознавание речи появится вместе с диктовкой",
            code="ai_capability_unsupported",
        )

    def _catalog_model(self, resolved: ResolvedModel) -> AiModelCatalogEntry:
        row = self.session.get(AiModelCatalogEntry, (resolved.role.modality, resolved.model_id))
        if row is None or not row.is_available:
            raise AiGatewayError(
                "Выбранной модели нет в актуальном локальном каталоге",
                code="ai_capability_unsupported",
                context={"model_id": resolved.model_id},
            )
        capabilities = set()
        if "response_format" in row.supported_parameters:
            capabilities.add("structured_output")
        capabilities.add("streaming")
        if "audio" in row.input_modalities:
            capabilities.add("audio_transcription")
        missing = resolved.role.required_capabilities - capabilities
        if missing:
            raise AiGatewayError(
                "Модель не поддерживает возможности этой функции",
                code="ai_capability_unsupported",
                context={"model_id": resolved.model_id, "missing": sorted(missing)},
            )
        return row

    @staticmethod
    def _response_schema(request: AiTextRequest[Any]) -> dict[str, Any] | None:
        return request.response_model.model_json_schema() if request.response_model else None

    @staticmethod
    def _estimate_input(messages: list[AiMessage], response_schema: dict[str, Any] | None) -> int:
        payload = json.dumps(
            {
                "messages": [item.model_dump() for item in messages],
                "schema": response_schema,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode()
        return max(1, math.ceil(len(payload) / 3))

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
                "model": resolved.model_id,
                "parameters": parameters,
                "prompt_version": resolved.role.prompt_version,
                "response_schema": response_schema,
                "messages": [item.model_dump() for item in request.messages],
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
        model = self.session.get(AiModelCatalogEntry, (resolved.role.modality, resolved.model_id))
        assert settings is not None and model is not None
        self.session.commit()
        with self.session.begin():
            run = AiRun(
                project_id=request.project_id,
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
