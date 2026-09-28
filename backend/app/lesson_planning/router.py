"""HTTP-маршруты небольшого учебникового календаря."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_session
from app.lesson_planning import service
from app.lesson_planning.schemas import (
    DistributionRead,
    DistributionWrite,
    LessonPlanningRead,
    LessonTimeBatch,
    LessonTimeResult,
    PlanWrite,
)

router = APIRouter(prefix="/api/projects/{project_id}/lesson-planning", tags=["lesson-planning"])
SessionDependency = Annotated[Session, Depends(get_session)]


@router.get("", response_model=LessonPlanningRead)
def overview(project_id: UUID, session: SessionDependency) -> LessonPlanningRead:
    return service.overview(session, project_id)


@router.post("/preview", response_model=DistributionRead)
def preview(
    project_id: UUID, command: DistributionWrite, session: SessionDependency
) -> DistributionRead:
    return service.preview(session, project_id, command)


@router.put("/plan", response_model=LessonPlanningRead)
def save_plan(
    project_id: UUID, command: PlanWrite, session: SessionDependency
) -> LessonPlanningRead:
    return service.save_plan(session, project_id, command)


@router.post("/time", response_model=LessonTimeResult)
def time_batch(
    project_id: UUID, command: LessonTimeBatch, session: SessionDependency
) -> LessonTimeResult:
    return service.add_intervals(session, project_id, command)
