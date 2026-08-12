from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai import catalog, settings
from app.ai.schemas import (
    AiConnectionRead,
    AiConnectionTestRead,
    AiConnectionWrite,
    AiFavoritesWrite,
    AiGlobalSettingsWrite,
    AiModelRead,
    AiRoleWrite,
    AiRunRead,
    AiSettingsRead,
    AiUsageGroup,
    AiUsageRead,
)
from app.db import get_session
from app.models import AiRun

SessionDependency = Annotated[Session, Depends(get_session)]
Modality = Literal["text", "speech"]
router = APIRouter(prefix="/api/settings/ai", tags=["ai-settings"])


@router.get("", response_model=AiSettingsRead)
def get_ai_settings(session: SessionDependency) -> AiSettingsRead:
    return settings.read_settings(session)


@router.put("", response_model=AiSettingsRead)
def put_ai_settings(command: AiGlobalSettingsWrite, session: SessionDependency) -> AiSettingsRead:
    return settings.update_global_settings(session, command)


@router.put("/connections/{modality}", response_model=AiConnectionRead)
def put_ai_connection(
    modality: Modality,
    command: AiConnectionWrite,
    session: SessionDependency,
) -> AiConnectionRead:
    return settings.update_connection(session, modality, command)


@router.delete("/connections/{modality}/credential", status_code=status.HTTP_204_NO_CONTENT)
def delete_ai_credential(modality: Modality, session: SessionDependency) -> Response:
    settings.delete_credential(session, modality)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/connections/{modality}/test", response_model=AiConnectionTestRead)
async def test_ai_connection(
    modality: Modality, session: SessionDependency
) -> AiConnectionTestRead:
    return await catalog.test_connection(session, modality)


@router.post("/connections/{modality}/models/refresh", response_model=list[AiModelRead])
async def refresh_ai_models(modality: Modality, session: SessionDependency) -> list[AiModelRead]:
    return await catalog.refresh_catalog(session, modality)


@router.put("/roles/{role}", response_model=AiSettingsRead)
def put_ai_role(role: str, command: AiRoleWrite, session: SessionDependency) -> AiSettingsRead:
    return settings.update_role(session, role, command)


@router.put("/favorites", response_model=AiSettingsRead)
def put_ai_favorites(command: AiFavoritesWrite, session: SessionDependency) -> AiSettingsRead:
    return settings.update_favorites(session, command)


def _filtered_runs(
    session: Session,
    project_id: UUID | None,
    role: str | None,
    from_: datetime | None,
    to: datetime | None,
    limit: int | None = None,
) -> list[AiRun]:
    query = select(AiRun).order_by(AiRun.created_at.desc())
    if project_id is not None:
        query = query.where(AiRun.project_id == project_id)
    if role is not None:
        query = query.where(AiRun.role == role)
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
    role: str | None = None,
    from_: Annotated[datetime | None, Query(alias="from")] = None,
    to: datetime | None = None,
) -> list[AiRunRead]:
    return [
        AiRunRead.model_validate(row)
        for row in _filtered_runs(session, project_id, role, from_, to, limit=1000)
    ]


@router.get("/usage", response_model=AiUsageRead)
def get_ai_usage(
    session: SessionDependency,
    project_id: UUID | None = None,
    from_: Annotated[datetime | None, Query(alias="from")] = None,
    to: datetime | None = None,
    group_by: Literal["role"] = "role",
) -> AiUsageRead:
    del group_by
    rows = _filtered_runs(session, project_id, None, from_, to)
    groups: dict[str, AiUsageGroup] = {}
    for row in rows:
        group = groups.setdefault(
            row.role,
            AiUsageGroup(
                key=row.role,
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
