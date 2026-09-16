from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.db import get_session
from app.lessons import bulk, editing, progress, service
from app.lessons.schemas import (
    LessonBlockWrite,
    LessonBulkResult,
    LessonBulkWrite,
    LessonChangeResult,
    LessonCompletionWrite,
    LessonConfirmWrite,
    LessonManualWrite,
    LessonNoteWrite,
    LessonProgressWrite,
    LessonQuickWrite,
    LessonRead,
    LessonsOverviewRead,
    LessonTopicSourcesRead,
    LessonUnbindWrite,
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


@router.post("/manual", response_model=LessonChangeResult, status_code=201)
def create_manual_lesson(
    project_id: UUID, command: LessonManualWrite, session: SessionDependency
) -> LessonChangeResult:
    return service.create_manual_lesson(session, project_id, command)


@router.post("/bulk", response_model=LessonBulkResult, status_code=201)
def create_bulk_lessons(
    project_id: UUID, command: LessonBulkWrite, session: SessionDependency
) -> LessonBulkResult:
    return bulk.create_bulk_lessons(session, project_id, command)


@router.post("/{lesson_id}/blocks", response_model=LessonChangeResult)
def edit_lesson_blocks(
    project_id: UUID, lesson_id: UUID, command: LessonBlockWrite, session: SessionDependency
) -> LessonChangeResult:
    return editing.edit_lesson_blocks(session, project_id, lesson_id, command)


@router.patch("/{lesson_id}/blocks/{block_id}", response_model=LessonChangeResult)
def update_lesson_note(
    project_id: UUID, lesson_id: UUID, block_id: UUID,
    command: LessonNoteWrite, session: SessionDependency,
) -> LessonChangeResult:
    return editing.update_lesson_note(session, project_id, lesson_id, block_id, command)


@router.post("/{lesson_id}/media", response_model=LessonChangeResult)
async def add_lesson_image(
    project_id: UUID,
    lesson_id: UUID,
    session: SessionDependency,
    file: Annotated[UploadFile, File()],
    expected_revision: Annotated[int, Form(ge=1)],
    after_block_id: Annotated[UUID | None, Form()] = None,
    caption: Annotated[str | None, Form(max_length=2000)] = None,
) -> LessonChangeResult:
    return await editing.add_lesson_image(
        session, project_id, lesson_id, file, expected_revision, after_block_id, caption
    )


@router.get("/{lesson_id}/media/{block_id}", response_class=FileResponse)
def lesson_image(
    project_id: UUID, lesson_id: UUID, block_id: UUID, session: SessionDependency
) -> FileResponse:
    path, media_type = editing.lesson_image(session, project_id, lesson_id, block_id)
    return FileResponse(path, media_type=media_type)


@router.post("/{lesson_id}/confirm", response_model=LessonChangeResult)
def confirm_lesson(
    project_id: UUID, lesson_id: UUID, command: LessonConfirmWrite, session: SessionDependency
) -> LessonChangeResult:
    return editing.confirm_lesson(session, project_id, lesson_id, command)


@router.post("/{lesson_id}/progress", response_model=LessonChangeResult)
def save_lesson_position(
    project_id: UUID, lesson_id: UUID, command: LessonProgressWrite, session: SessionDependency
) -> LessonChangeResult:
    return progress.save_position(session, project_id, lesson_id, command)


@router.post("/{lesson_id}/completion", response_model=LessonChangeResult)
def set_lesson_completed(
    project_id: UUID, lesson_id: UUID, command: LessonCompletionWrite, session: SessionDependency
) -> LessonChangeResult:
    return progress.set_completed(session, project_id, lesson_id, command)


@router.post("/{lesson_id}/unbind", response_model=LessonChangeResult)
def unbind_lesson_bindings(
    project_id: UUID, lesson_id: UUID, command: LessonUnbindWrite, session: SessionDependency
) -> LessonChangeResult:
    return editing.unbind_lesson_bindings(session, project_id, lesson_id, command)


@router.get("/{lesson_id}", response_model=LessonRead)
def get_lesson(project_id: UUID, lesson_id: UUID, session: SessionDependency) -> LessonRead:
    return service.get_lesson(session, project_id, lesson_id)


@router.patch("/{lesson_id}", response_model=LessonChangeResult)
def update_lesson(
    project_id: UUID, lesson_id: UUID, command: LessonUpdateWrite, session: SessionDependency
) -> LessonChangeResult:
    return service.update_lesson(session, project_id, lesson_id, command)
