from __future__ import annotations

from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.ai.provider import (
    OpenAICompatibleTransport,
    OpenAITransport,
    ProviderError,
    ProviderModel,
)
from app.ai.schemas import AiModelRead, AiProviderTestRead
from app.ai.settings import AiGatewayError, credential
from app.models import AiModelCatalogEntry, AiProviderConnection, utc_now


def production_transport(session: Session, provider_id: UUID) -> OpenAITransport:
    provider = session.get(AiProviderConnection, provider_id)
    if provider is None:
        raise AiGatewayError("Провайдер не найден", code="ai_provider_not_found", status=404)
    if not provider.base_url:
        raise AiGatewayError("Подключение не настроено", code="ai_connection_not_configured")
    return OpenAITransport(provider.base_url, credential(session, provider_id))


async def test_connection(
    session: Session,
    provider_id: UUID,
    transport: OpenAICompatibleTransport | None = None,
) -> AiProviderTestRead:
    transport = transport or production_transport(session, provider_id)
    try:
        models = await transport.list_models()
    except ProviderError as error:
        _record_failure(session, provider_id, error.code)
        raise AiGatewayError(error.detail, code=error.code, status=_status(error.code)) from error
    now = utc_now()
    session.commit()
    with session.begin():
        provider = session.get(AiProviderConnection, provider_id)
        if provider is None:
            raise AiGatewayError("Провайдер не найден", code="ai_provider_not_found", status=404)
        provider.last_test_status = "connected"
        provider.last_tested_at = now
    return AiProviderTestRead(status="connected", model_count=len(models), tested_at=now)


async def refresh_catalog(
    session: Session,
    provider_id: UUID,
    transport: OpenAICompatibleTransport | None = None,
) -> list[AiModelRead]:
    transport = transport or production_transport(session, provider_id)
    try:
        models = await transport.list_models()
    except ProviderError as error:
        _record_failure(session, provider_id, error.code)
        raise AiGatewayError(error.detail, code=error.code, status=_status(error.code)) from error
    now = utc_now()
    session.commit()
    with session.begin():
        provider = session.get(AiProviderConnection, provider_id)
        if provider is None:
            raise AiGatewayError("Провайдер не найден", code="ai_provider_not_found", status=404)
        session.execute(
            update(AiModelCatalogEntry)
            .where(AiModelCatalogEntry.provider_id == provider_id)
            .values(is_available=False, catalog_snapshot_at=now)
        )
        for item in models:
            _upsert_model(session, provider_id, item, now)
        provider.last_catalog_refresh_at = now
        provider.last_test_status = "connected"
        provider.last_tested_at = now
    return list(
        map(
            AiModelRead.model_validate,
            session.scalars(
                select(AiModelCatalogEntry)
                .where(AiModelCatalogEntry.provider_id == provider_id)
                .order_by(AiModelCatalogEntry.display_name)
            ),
        )
    )


def _upsert_model(session: Session, provider_id: UUID, item: ProviderModel, snapshot_at) -> None:
    row = session.get(AiModelCatalogEntry, (provider_id, item.model_id))
    manual = dict(row.manual_overrides) if row else {}
    favorite_order = row.favorite_order if row else None
    if row is None:
        row = AiModelCatalogEntry(provider_id=provider_id, model_id=item.model_id)
        session.add(row)
    row.display_name = item.display_name
    row.context_length = item.context_length
    row.max_completion_tokens = item.max_completion_tokens
    row.supported_parameters = item.supported_parameters
    row.input_modalities = item.input_modalities
    row.output_modalities = item.output_modalities
    row.reasoning = item.reasoning
    row.default_parameters = item.default_parameters
    row.prompt_price_usd = item.prompt_price_usd
    row.completion_price_usd = item.completion_price_usd
    row.knowledge_cutoff = item.knowledge_cutoff
    row.expiration_date = item.expiration_date
    row.pricing_snapshot_at = snapshot_at
    row.catalog_snapshot_at = snapshot_at
    row.is_available = True
    row.favorite_order = favorite_order
    row.manual_overrides = manual
    for field, value in manual.items():
        if hasattr(row, field):
            setattr(row, field, value)


def _status(code: str) -> int:
    return {
        "ai_invalid_credentials": 401,
        "ai_rate_limited": 429,
        "ai_provider_unavailable": 503,
        "ai_timeout": 504,
    }.get(code, 422)


def _record_failure(session: Session, provider_id: UUID, code: str) -> None:
    session.rollback()
    with session.begin():
        provider = session.get(AiProviderConnection, provider_id)
        if provider is not None:
            provider.last_test_status = code
            provider.last_tested_at = utc_now()
