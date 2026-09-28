from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.background.schemas import BackgroundJobStartRead
from app.db import get_session
from app.lessons import (
    ai_build,
    ai_enrich,
    bulk,
    editing,
    from_search,
    progress,
    proposals,
    service,
)
from app.lessons.ai_schemas import (
    LessonAiBuildWrite,
    LessonAiOrder,
    LessonAiPreflightRead,
    LessonAiResumeWrite,
    LessonAiRunWrite,
    LessonEnrichOrder,
    LessonEnrichPreflightRead,
    LessonEnrichWrite,
    LessonProposalApplyWrite,
)
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


@router.post("/from-search", response_model=LessonChangeResult, status_code=201)
def create_lesson_from_search(
    project_id: UUID, command: from_search.LessonFromSearchWrite, session: SessionDependency
) -> LessonChangeResult:
    """Страницы, отмеченные в поиске, — новым черновиком или в конец урока."""
    return from_search.create_lesson_from_search(session, project_id, command)


@router.post("/bulk", response_model=LessonBulkResult, status_code=201)
def create_bulk_lessons(
    project_id: UUID, command: LessonBulkWrite, session: SessionDependency
) -> LessonBulkResult:
    return bulk.create_bulk_lessons(session, project_id, command)


@router.post("/ai/preflight", response_model=LessonAiPreflightRead)
async def lesson_ai_preflight(
    project_id: UUID, command: LessonAiOrder, session: SessionDependency
) -> LessonAiPreflightRead:
    """Материалы, кандидаты, паспорт урока и оценка уровней — без вызова модели."""
    return await ai_build.preflight(session, project_id, command)


@router.post("/ai/plan", response_model=BackgroundJobStartRead, status_code=202)
async def start_lesson_ai_plan(
    project_id: UUID, command: LessonAiRunWrite, session: SessionDependency
) -> BackgroundJobStartRead:
    """План урока «Обычный»/«Подробный» фоном; итог задачи — план для редактора."""
    return await ai_build.start_plan(session, project_id, command)


@router.post("/ai/build", response_model=BackgroundJobStartRead, status_code=202)
async def start_lesson_ai_build(
    project_id: UUID, command: LessonAiBuildWrite, session: SessionDependency
) -> BackgroundJobStartRead:
    """Сборка урока фоном; итог задачи — `{lesson_id, dropped, cost_usd}`."""
    return await ai_build.start(session, project_id, command)


@router.post("/ai/jobs/{job_id}/resume", response_model=BackgroundJobStartRead, status_code=202)
def resume_lesson_ai_build(
    project_id: UUID, job_id: UUID, command: LessonAiResumeWrite, session: SessionDependency
) -> BackgroundJobStartRead:
    """Продолжить упавшую сборку с места сбоя, при нужде с новым пределом расхода."""
    return ai_build.resume(session, project_id, job_id, command)


@router.post("/{lesson_id}/ai/enrich/preflight", response_model=LessonEnrichPreflightRead)
async def lesson_enrich_preflight(
    project_id: UUID, lesson_id: UUID, command: LessonEnrichOrder, session: SessionDependency
) -> LessonEnrichPreflightRead:
    """Сколько порций урока уйдёт в модель и во что это обойдётся — без вызова."""
    return await ai_enrich.preflight(session, project_id, lesson_id, command)


@router.post("/{lesson_id}/ai/enrich", response_model=BackgroundJobStartRead, status_code=202)
async def start_lesson_enrich(
    project_id: UUID, lesson_id: UUID, command: LessonEnrichWrite, session: SessionDependency
) -> BackgroundJobStartRead:
    """«Дополнить урок» фоном; итог задачи — предложение для решения человека."""
    return await ai_enrich.start(session, project_id, lesson_id, command)


@router.post(
    "/{lesson_id}/proposals/{job_id}/apply", response_model=proposals.LessonProposalApplyResult
)
def apply_lesson_proposal(
    project_id: UUID, lesson_id: UUID, job_id: UUID, command: LessonProposalApplyWrite,
    session: SessionDependency,
) -> proposals.LessonProposalApplyResult:
    """Применить выбранные изменения предложения одной записью с одной отменой."""
    return proposals.apply_proposal(session, project_id, lesson_id, job_id, command)


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


@router.delete("/{lesson_id}", status_code=204)
def delete_lesson(project_id: UUID, lesson_id: UUID, session: SessionDependency) -> None:
    service.delete_lesson(session, project_id, lesson_id)
