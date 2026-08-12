from __future__ import annotations

from typing import Literal

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.ai.provider import (
    OpenAICompatibleTransport,
    OpenAITransport,
    ProviderError,
    ProviderModel,
)
from app.ai.schemas import AiConnectionTestRead, AiModelRead
from app.ai.settings import AiGatewayError, credential
from app.models import AiConnection, AiModelCatalogEntry, utc_now

Modality = Literal["text", "speech"]


def production_transport(session: Session, modality: Modality) -> OpenAITransport:
    connection = session.get(AiConnection, modality)
    if connection is None or not connection.base_url:
        raise AiGatewayError("Подключение не настроено", code="ai_connection_not_configured")
    return OpenAITransport(connection.base_url, credential(session, modality))


async def test_connection(
    session: Session,
    modality: Modality,
    transport: OpenAICompatibleTransport | None = None,
) -> AiConnectionTestRead:
    transport = transport or production_transport(session, modality)
    try:
        models = await transport.list_models()
    except ProviderError as error:
        _record_failure(session, modality, error.code)
        raise AiGatewayError(error.detail, code=error.code, status=_status(error.code)) from error
    now = utc_now()
    session.commit()
    with session.begin():
        connection = session.get(AiConnection, modality)
        assert connection is not None
        connection.last_test_status = "connected"
        connection.last_tested_at = now
    return AiConnectionTestRead(status="connected", model_count=len(models), tested_at=now)


async def refresh_catalog(
    session: Session,
    modality: Modality,
    transport: OpenAICompatibleTransport | None = None,
) -> list[AiModelRead]:
    transport = transport or production_transport(session, modality)
    try:
        models = await transport.list_models()
    except ProviderError as error:
        _record_failure(session, modality, error.code)
        raise AiGatewayError(error.detail, code=error.code, status=_status(error.code)) from error
    now = utc_now()
    session.commit()
    with session.begin():
        session.execute(
            update(AiModelCatalogEntry)
            .where(AiModelCatalogEntry.modality == modality)
            .values(is_available=False, catalog_snapshot_at=now)
        )
        for item in models:
            _upsert_model(session, modality, item, now)
        connection = session.get(AiConnection, modality)
        assert connection is not None
        connection.last_catalog_refresh_at = now
        connection.last_test_status = "connected"
        connection.last_tested_at = now
    return list(
        map(
            AiModelRead.model_validate,
            session.scalars(
                select(AiModelCatalogEntry)
                .where(AiModelCatalogEntry.modality == modality)
                .order_by(AiModelCatalogEntry.display_name)
            ),
        )
    )


def _upsert_model(session: Session, modality: Modality, item: ProviderModel, snapshot_at) -> None:
    row = session.get(AiModelCatalogEntry, (modality, item.model_id))
    favorite = row.is_favorite if row else False
    if row is None:
        row = AiModelCatalogEntry(modality=modality, model_id=item.model_id)
        session.add(row)
    row.display_name = item.display_name
    row.context_length = item.context_length
    row.supported_parameters = item.supported_parameters
    row.input_modalities = item.input_modalities
    row.output_modalities = item.output_modalities
    row.prompt_price_usd = item.prompt_price_usd
    row.completion_price_usd = item.completion_price_usd
    row.pricing_snapshot_at = snapshot_at
    row.catalog_snapshot_at = snapshot_at
    row.is_favorite = favorite
    row.is_available = True


def _status(code: str) -> int:
    return {
        "ai_invalid_credentials": 401,
        "ai_rate_limited": 429,
        "ai_provider_unavailable": 503,
        "ai_timeout": 504,
    }.get(code, 422)


def _record_failure(session: Session, modality: Modality, code: str) -> None:
    session.rollback()
    with session.begin():
        connection = session.get(AiConnection, modality)
        if connection is not None:
            connection.last_test_status = code
            connection.last_tested_at = utc_now()
