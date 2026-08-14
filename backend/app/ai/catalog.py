from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.provider import (
    OpenAICompatibleTransport,
    OpenAITransport,
    ProviderError,
    ProviderModel,
)
from app.ai.schemas import (
    AiCatalogModelRead,
    AiCatalogModelWrite,
    AiProviderTestRead,
    AiSettingsRead,
)
from app.ai.settings import AiGatewayError, credential, read_settings
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


async def search_catalog(
    session: Session,
    provider_id: UUID,
    transport: OpenAICompatibleTransport | None = None,
) -> list[AiCatalogModelRead]:
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
        provider.last_catalog_refresh_at = now
        provider.last_test_status = "connected"
        provider.last_tested_at = now
    added = set(
        session.scalars(
            select(AiModelCatalogEntry.model_id).where(
                AiModelCatalogEntry.provider_id == provider_id
            )
        )
    )
    return sorted(
        (_catalog_read(item, item.model_id in added) for item in models),
        key=lambda item: item.display_name.casefold(),
    )


def add_catalog_model(
    session: Session,
    provider_id: UUID,
    command: AiCatalogModelWrite,
) -> AiSettingsRead:
    now = utc_now()
    session.commit()
    with session.begin():
        provider = session.get(AiProviderConnection, provider_id)
        if provider is None:
            raise AiGatewayError("Провайдер не найден", code="ai_provider_not_found", status=404)
        _upsert_model(session, provider_id, ProviderModel(**command.model_dump()), now)
    return read_settings(session)


def _catalog_read(item: ProviderModel, is_added: bool) -> AiCatalogModelRead:
    data = dict(item.__dict__)
    # OpenRouter uses -1 for routers whose final price depends on the selected
    # downstream model. It is not a real negative price, so expose it as unknown.
    for field in ("prompt_price_usd", "completion_price_usd"):
        value = data[field]
        if value is not None and value < 0:
            data[field] = None
    return AiCatalogModelRead(**data, is_added=is_added)


def _upsert_model(session: Session, provider_id: UUID, item: ProviderModel, snapshot_at) -> None:
    row = session.get(AiModelCatalogEntry, (provider_id, item.model_id))
    manual = dict(row.manual_overrides) if row else {}
    favorite_order = row.favorite_order if row else None
    if row is None:
        row = AiModelCatalogEntry(
            provider_id=provider_id,
            model_id=item.model_id,
            is_manually_added=False,
        )
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
