from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db import get_session
from app.lessons import service
from app.lessons.schemas import (
    LessonChangeResult,
    LessonQuickWrite,
    LessonRead,
    LessonsOverviewRead,
    LessonTopicSourcesRead,
    LessonUpdateWrite,
)

SessionDependency = Annotated[Session, Depends(get_session)]
router = APIRouter(prefix="/api/projects/{project_id}/lessons", tags=["lessons"])


@router.get("/overview", response_model=LessonsOverviewRead)
def lessons_overview(project_id: UUID, session: SessionDependency) -> LessonsOverviewRead:
    return service.lessons_overview(session, project_id)


@router.get("/sources", response_model=LessonTopicSourcesRead)
def topic_sources(
    project_id: UUID, session: SessionDependency, program_node_id: Annotated[UUID, Query()]
) -> LessonTopicSourcesRead:
    return service.topic_sources(session, project_id, program_node_id)


@router.post("/quick", response_model=LessonChangeResult, status_code=201)
def create_quick_lesson(
    project_id: UUID, command: LessonQuickWrite, session: SessionDependency
) -> LessonChangeResult:
    return service.create_quick_lesson(session, project_id, command)


@router.get("/{lesson_id}", response_model=LessonRead)
def get_lesson(project_id: UUID, lesson_id: UUID, session: SessionDependency) -> LessonRead:
    return service.get_lesson(session, project_id, lesson_id)


@router.patch("/{lesson_id}", response_model=LessonChangeResult)
def update_lesson(
    project_id: UUID, lesson_id: UUID, command: LessonUpdateWrite, session: SessionDependency
) -> LessonChangeResult:
    return service.update_lesson(session, project_id, lesson_id, command)
