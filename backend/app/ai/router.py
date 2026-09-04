from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai import catalog, settings
from app.ai.gateway import ModelGateway
from app.ai.schemas import (
    AiCatalogModelRead,
    AiCatalogModelWrite,
    AiDefaultWrite,
    AiGlobalSettingsWrite,
    AiManualModelWrite,
    AiModelFavoritesWrite,
    AiModelSelection,
    AiModelTestRead,
    AiModelTestWrite,
    AiProviderFavoritesWrite,
    AiProviderTestRead,
    AiProviderWrite,
    AiRoleWrite,
    AiRunRead,
    AiSettingsRead,
    AiUsageGroup,
    AiUsageRead,
    Modality,
)
from app.db import get_session
from app.models import AiRun

SessionDependency = Annotated[Session, Depends(get_session)]
router = APIRouter(prefix="/api/settings/ai", tags=["ai-settings"])


@router.get("", response_model=AiSettingsRead)
def get_ai_settings(session: SessionDependency) -> AiSettingsRead:
    return settings.read_settings(session)


@router.put("", response_model=AiSettingsRead)
def put_ai_settings(command: AiGlobalSettingsWrite, session: SessionDependency) -> AiSettingsRead:
    return settings.update_global_settings(session, command)


@router.post("/providers", response_model=AiSettingsRead, status_code=status.HTTP_201_CREATED)
def post_ai_provider(command: AiProviderWrite, session: SessionDependency) -> AiSettingsRead:
    return settings.create_provider(session, command)


@router.put("/providers/{provider_id}", response_model=AiSettingsRead)
def put_ai_provider(
    provider_id: UUID, command: AiProviderWrite, session: SessionDependency
) -> AiSettingsRead:
    return settings.update_provider(session, provider_id, command)


@router.delete("/providers/{provider_id}", response_model=AiSettingsRead)
def delete_ai_provider(provider_id: UUID, session: SessionDependency) -> AiSettingsRead:
    return settings.delete_provider(session, provider_id)


@router.delete(
    "/providers/{provider_id}/credential", status_code=status.HTTP_204_NO_CONTENT
)
def delete_ai_credential(provider_id: UUID, session: SessionDependency) -> Response:
    settings.delete_credential(session, provider_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/providers/{provider_id}/test", response_model=AiProviderTestRead)
async def test_ai_provider(
    provider_id: UUID, session: SessionDependency
) -> AiProviderTestRead:
    return await catalog.test_connection(session, provider_id)


@router.post("/providers/{provider_id}/models/search", response_model=list[AiCatalogModelRead])
async def search_ai_models(
    provider_id: UUID, session: SessionDependency
) -> list[AiCatalogModelRead]:
    return await catalog.search_catalog(session, provider_id)


@router.post("/providers/{provider_id}/models", response_model=AiSettingsRead)
def add_ai_catalog_model(
    provider_id: UUID,
    command: AiCatalogModelWrite,
    session: SessionDependency,
) -> AiSettingsRead:
    return catalog.add_catalog_model(session, provider_id, command)


@router.put("/providers/{provider_id}/models/manual", response_model=AiSettingsRead)
def put_manual_ai_model(
    provider_id: UUID,
    command: AiManualModelWrite,
    session: SessionDependency,
) -> AiSettingsRead:
    return settings.upsert_manual_model(session, provider_id, command)


@router.delete("/providers/{provider_id}/models", response_model=AiSettingsRead)
def delete_ai_model(
    provider_id: UUID,
    # ID модели содержит «/», поэтому он приходит параметром запроса, а не частью пути.
    model_id: Annotated[str, Query(min_length=1)],
    session: SessionDependency,
) -> AiSettingsRead:
    return settings.delete_model(session, provider_id, model_id)


@router.post("/providers/{provider_id}/models/test", response_model=AiModelTestRead)
async def test_ai_model(
    provider_id: UUID,
    command: AiModelTestWrite,
    session: SessionDependency,
) -> AiModelTestRead:
    return await ModelGateway(session).test_model(
        AiModelSelection(provider_id=provider_id, model_id=command.model_id)
    )


@router.put("/provider-favorites", response_model=AiSettingsRead)
def put_ai_provider_favorites(
    command: AiProviderFavoritesWrite, session: SessionDependency
) -> AiSettingsRead:
    return settings.update_provider_favorites(session, command)


@router.put("/model-favorites", response_model=AiSettingsRead)
def put_ai_model_favorites(
    command: AiModelFavoritesWrite, session: SessionDependency
) -> AiSettingsRead:
    return settings.update_model_favorites(session, command)


@router.put("/defaults/{modality}", response_model=AiSettingsRead)
def put_ai_default(
    modality: Modality, command: AiDefaultWrite, session: SessionDependency
) -> AiSettingsRead:
    return settings.set_default(session, modality, command)


@router.put("/roles/{role}", response_model=AiSettingsRead)
def put_ai_role(role: str, command: AiRoleWrite, session: SessionDependency) -> AiSettingsRead:
    return settings.update_role(session, role, command)


def _filtered_runs(
    session: Session,
    project_id: UUID | None,
    provider_id: UUID | None,
    model_id: str | None,
    role: str | None,
    run_status: str | None,
    from_: datetime | None,
    to: datetime | None,
    limit: int | None = None,
    job_id: UUID | None = None,
) -> list[AiRun]:
    query = select(AiRun).order_by(AiRun.created_at.desc())
    if project_id is not None:
        query = query.where(AiRun.project_id == project_id)
    if job_id is not None:
        query = query.where(AiRun.job_id == job_id)
    if provider_id is not None:
        query = query.where(AiRun.provider_id == provider_id)
    if model_id is not None:
        query = query.where(AiRun.requested_model_id == model_id)
    if role is not None:
        query = query.where(AiRun.role == role)
    if run_status is not None:
        query = query.where(AiRun.status == run_status)
    if from_ is not None:
        query = query.where(AiRun.created_at >= from_)
    if to is not None:
        query = query.where(AiRun.created_at <= to)
    if limit is not None:
        query = query.limit(limit)
    return list(session.scalars(query))


@router.get("/runs", response_model=list[AiRunRead])
def list_ai_runs(
    session: SessionDependency,
    project_id: UUID | None = None,
    provider_id: UUID | None = None,
    model_id: str | None = None,
    role: str | None = None,
    run_status: Annotated[str | None, Query(alias="status")] = None,
    from_: Annotated[datetime | None, Query(alias="from")] = None,
    to: datetime | None = None,
    job_id: UUID | None = None,
) -> list[AiRunRead]:
    rows = _filtered_runs(
        session,
        project_id,
        provider_id,
        model_id,
        role,
        run_status,
        from_,
        to,
        limit=1000,
        job_id=job_id,
    )
    return [AiRunRead.model_validate(row) for row in rows]


@router.get("/usage", response_model=AiUsageRead)
def get_ai_usage(
    session: SessionDependency,
    project_id: UUID | None = None,
    provider_id: UUID | None = None,
    model_id: str | None = None,
    from_: Annotated[datetime | None, Query(alias="from")] = None,
    to: datetime | None = None,
    group_by: Literal["role", "provider", "model"] = "role",
) -> AiUsageRead:
    rows = _filtered_runs(
        session, project_id, provider_id, model_id, None, None, from_, to
    )
    groups: dict[str, AiUsageGroup] = {}
    for row in rows:
        key = {
            "role": row.role,
            "provider": row.provider_label_snapshot,
            "model": row.requested_model_id,
        }[group_by]
        group = groups.setdefault(
            key,
            AiUsageGroup(
                key=key,
                runs=0,
                cache_hits=0,
                input_tokens=0,
                output_tokens=0,
                actual_cost_usd=Decimal("0"),
                actual_cost_rub=Decimal("0"),
            ),
        )
        group.runs += 1
        group.cache_hits += row.status == "cached"
        if row.status == "succeeded":
            group.input_tokens += row.input_tokens or 0
            group.output_tokens += row.output_tokens or 0
            group.actual_cost_usd += row.actual_cost_usd or Decimal("0")
            group.actual_cost_rub += row.actual_cost_rub or Decimal("0")
    return AiUsageRead(groups=sorted(groups.values(), key=lambda item: item.key))
