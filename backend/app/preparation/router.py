"""HTTP-контракт подготовки; транзакции остаются внутри доменных операций."""

from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from app.ai.dependencies import get_model_gateway
from app.ai.gateway import ModelGateway
from app.db import get_session, project_write_transaction
from app.models import Attempt
from app.preparation import activity, ai, planner, queue, reporting
from app.preparation.ai_schemas import PreparationAiPreflightRead
from app.preparation.data import require_project
from app.preparation.evidence import synchronize_review
from app.preparation.models import ReviewQuality
from app.preparation.schemas import (
    ActivityRead,
    AiStartRead,
    ApplyDraftWrite,
    DraftRead,
    DraftWrite,
    HistoryRead,
    ManualActivityWrite,
    OverviewRead,
    PlanRead,
    PreparationAiWrite,
    QualityWrite,
    QueuePositionWrite,
    QueueRead,
    RevisionWrite,
    SettingsRead,
    SettingsWrite,
    TimeBatchRead,
    TimeBatchWrite,
    UnderstoodWrite,
)
from app.projects.errors import ProjectDomainError

SessionDependency = Annotated[Session, Depends(get_session)]
GatewayDependency = Annotated[ModelGateway, Depends(get_model_gateway)]
router = APIRouter(prefix="/api/projects/{project_id}/preparation", tags=["preparation"])


@router.post("/ai/preflight", response_model=PreparationAiPreflightRead)
async def ai_preflight(
    project_id: UUID,
    command: PreparationAiWrite,
    session: SessionDependency,
    gateway: GatewayDependency,
):
    return await ai.preflight(session, gateway, project_id, command)


@router.post("/ai", response_model=AiStartRead, status_code=202)
async def ai_start(
    project_id: UUID,
    command: PreparationAiWrite,
    session: SessionDependency,
    gateway: GatewayDependency,
):
    return await ai.start(session, gateway, project_id, command)


@router.get("", response_model=OverviewRead)
def overview(
    project_id: UUID, session: SessionDependency, start: date | None = None, end: date | None = None
) -> OverviewRead:
    return reporting.overview(session, project_id, start=start, end=end)


@router.put("/settings", response_model=SettingsRead)
def settings(project_id: UUID, command: SettingsWrite, session: SessionDependency) -> SettingsRead:
    return planner.save_settings(session, project_id, command)


@router.post("/time", response_model=TimeBatchRead)
def time_batch(
    project_id: UUID, command: TimeBatchWrite, session: SessionDependency
) -> TimeBatchRead:
    return activity.add_intervals(session, project_id, command)


@router.put("/activities/{activity_id}", response_model=ActivityRead)
def save_activity(
    project_id: UUID, activity_id: UUID, command: ManualActivityWrite, session: SessionDependency
) -> ActivityRead:
    if activity_id != command.id:
        raise ProjectDomainError(
            "Идентификаторы занятия не совпадают", status=422, code="study_activity_id_mismatch"
        )
    return activity.save_manual(session, project_id, command)


@router.delete("/activities/{activity_id}", status_code=204)
def remove_activity(project_id: UUID, activity_id: UUID, session: SessionDependency) -> Response:
    activity.delete_manual(session, project_id, activity_id)
    return Response(status_code=204)


@router.post("/understood", status_code=204)
def understood(project_id: UUID, command: UnderstoodWrite, session: SessionDependency) -> Response:
    activity.mark_understood(session, project_id, command)
    return Response(status_code=204)


@router.put("/attempts/{attempt_id}/quality", status_code=204)
def quality(
    project_id: UUID, attempt_id: UUID, command: QualityWrite, session: SessionDependency
) -> Response:
    with project_write_transaction(session, project_id):
        require_project(session, project_id, writable=True)
        attempt = session.get(Attempt, attempt_id)
        if attempt is None or attempt.project_id != project_id:
            raise ProjectDomainError("Попытка не найдена", status=404, code="attempt_not_found")
        row = session.get(ReviewQuality, attempt_id)
        if row is None:
            session.add(ReviewQuality(attempt_id=attempt_id, quality=command.quality))
        else:
            row.quality = command.quality
        session.flush()
        synchronize_review(session, attempt)
    return Response(status_code=204)


@router.get("/history", response_model=HistoryRead)
def history(
    project_id: UUID,
    session: SessionDependency,
    date_from: date | None = None,
    date_to: date | None = None,
    node_id: UUID | None = None,
    section_id: UUID | None = None,
    kind: str | None = None,
    outcome: str | None = None,
    method: str | None = None,
    answer_mode: str | None = None,
    disputed: bool = False,
    q: str = "",
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
) -> HistoryRead:
    return activity.history(
        session,
        project_id,
        date_from=date_from,
        date_to=date_to,
        node_id=node_id,
        section_id=section_id,
        kind=kind,
        outcome=outcome,
        method=method,
        answer_mode=answer_mode,
        disputed=disputed,
        q=q,
        offset=offset,
        limit=limit,
    )


@router.post("/drafts", response_model=DraftRead)
def draft(project_id: UUID, command: DraftWrite, session: SessionDependency) -> DraftRead:
    return planner.create_draft(session, project_id, command)


@router.get("/drafts/{draft_id}", response_model=DraftRead)
def read_draft(project_id: UUID, draft_id: UUID, session: SessionDependency) -> DraftRead:
    return planner.get_draft(session, project_id, draft_id)


@router.post("/drafts/{draft_id}/apply", response_model=PlanRead)
def apply(
    project_id: UUID, draft_id: UUID, command: ApplyDraftWrite, session: SessionDependency
) -> PlanRead:
    return planner.apply_draft(session, project_id, draft_id, command)


@router.post("/undo", response_model=PlanRead)
def undo(project_id: UUID, command: RevisionWrite, session: SessionDependency) -> PlanRead:
    return planner.undo(session, project_id, command)


@router.get("/queue", response_model=QueueRead)
def read_queue(
    project_id: UUID, session: SessionDependency, on_date: date | None = None
) -> QueueRead:
    return queue.get_queue(session, project_id, on_date)


@router.post("/queue", response_model=QueueRead)
def start_queue(
    project_id: UUID, session: SessionDependency, on_date: date | None = None
) -> QueueRead:
    return queue.start_queue(session, project_id, on_date)


@router.put("/queue", response_model=QueueRead)
def move_queue(
    project_id: UUID,
    command: QueuePositionWrite,
    session: SessionDependency,
    on_date: date | None = None,
) -> QueueRead:
    return queue.move_queue(session, project_id, command, on_date)
