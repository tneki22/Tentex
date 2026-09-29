import shutil
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask

from app.ai.dependencies import get_model_gateway
from app.ai.gateway import ModelGateway
from app.background.schemas import BackgroundJobStartRead
from app.db import get_session
from app.lessons import (
    ai_build,
    ai_bulk,
    ai_enrich,
    ai_practice,
    bulk,
    editing,
    from_search,
    progress,
    proposals,
    service,
    tasks,
)
from app.lessons.ai_schemas import (
    LessonAiBuildWrite,
    LessonAiBulkOrder,
    LessonAiBulkPreflightRead,
    LessonAiBulkWrite,
    LessonAiOrder,
    LessonAiPreflightRead,
    LessonAiResumeWrite,
    LessonAiRunWrite,
    LessonEnrichOrder,
    LessonEnrichPreflightRead,
    LessonEnrichWrite,
    LessonProposalApplyWrite,
)
from app.lessons.export import importer as lesson_import
from app.lessons.export import service as lesson_export
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
from app.lessons.task_schemas import (
    LessonPracticeOrder,
    LessonPracticeWrite,
    StudyTaskAttemptRead,
    StudyTaskAttemptWrite,
)

SessionDependency = Annotated[Session, Depends(get_session)]
GatewayDependency = Annotated[ModelGateway, Depends(get_model_gateway)]
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


@router.post("/export")
def export_lessons(
    project_id: UUID, command: lesson_export.LessonExportWrite, session: SessionDependency
) -> FileResponse:
    """Выбранные уроки одним файлом: PDF, LaTeX, Markdown или `.tentex-lessons`."""
    result = lesson_export.export_lessons(session, project_id, command)
    return FileResponse(
        result.path, filename=result.filename, media_type=result.media_type,
        background=BackgroundTask(shutil.rmtree, result.workdir, ignore_errors=True),
    )


async def _package(file: UploadFile) -> lesson_import.Package:
    raw = await file.read(lesson_import.MAX_PACKAGE_BYTES + 1)
    await file.close()
    return lesson_import.read_package(raw)


@router.post("/import/preview", response_model=lesson_import.LessonImportPreviewRead)
async def preview_lesson_import(
    project_id: UUID, session: SessionDependency, file: Annotated[UploadFile, File()]
) -> lesson_import.LessonImportPreviewRead:
    """Что в файле уроков и куда он ляжет: темы проекта и найденные материалы."""
    package = await _package(file)
    return lesson_import.preview_package(session, project_id, package)


@router.post("/import", response_model=lesson_import.LessonImportResult, status_code=201)
async def import_lessons(
    project_id: UUID,
    session: SessionDependency,
    file: Annotated[UploadFile, File()],
    options: Annotated[str, Form()],
) -> lesson_import.LessonImportResult:
    """Уроки из файла — в выбранные темы; одна запись «Отменить» на весь импорт."""
    package = await _package(file)
    command = lesson_import.parse_options(options)
    return lesson_import.import_package(session, project_id, package, command)


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


@router.post("/ai/bulk/preflight", response_model=LessonAiBulkPreflightRead)
async def lesson_ai_bulk_preflight(
    project_id: UUID, command: LessonAiBulkOrder, session: SessionDependency
) -> LessonAiBulkPreflightRead:
    """Куски каждой темы списка и общая оценка черновиков — без вызова модели."""
    return await ai_bulk.preflight(session, project_id, command)


@router.post("/ai/bulk", response_model=BackgroundJobStartRead, status_code=202)
async def start_lesson_ai_bulk(
    project_id: UUID, command: LessonAiBulkWrite, session: SessionDependency
) -> BackgroundJobStartRead:
    """Черновики по списку тем одной задачей в порядке программы."""
    return await ai_bulk.start(session, project_id, command)


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


@router.post("/{lesson_id}/ai/practice/preflight", response_model=LessonEnrichPreflightRead)
async def lesson_practice_preflight(
    project_id: UUID, lesson_id: UUID, command: LessonPracticeOrder, session: SessionDependency
) -> LessonEnrichPreflightRead:
    """Во что обойдутся задания к уроку — без вызова модели."""
    return await ai_practice.preflight(session, project_id, lesson_id, command)


@router.post("/{lesson_id}/ai/practice", response_model=BackgroundJobStartRead, status_code=202)
async def start_lesson_practice(
    project_id: UUID, lesson_id: UUID, command: LessonPracticeWrite, session: SessionDependency
) -> BackgroundJobStartRead:
    """«Добавить практику» фоном; итог задачи — задания предложением."""
    return await ai_practice.start(session, project_id, lesson_id, command)


@router.post(
    "/{lesson_id}/tasks/{activity_id}/attempts", response_model=StudyTaskAttemptRead
)
async def submit_study_task_attempt(
    project_id: UUID, lesson_id: UUID, activity_id: UUID, command: StudyTaskAttemptWrite,
    session: SessionDependency, gateway: GatewayDependency,
) -> StudyTaskAttemptRead:
    """Ответ на задание: ключ проверяет сразу, открытый ответ — модель или позже."""
    return await tasks.submit_attempt(session, gateway, project_id, lesson_id, activity_id,
                                      command)


@router.get(
    "/{lesson_id}/tasks/{activity_id}/attempts", response_model=list[StudyTaskAttemptRead]
)
def list_study_task_attempts(
    project_id: UUID, lesson_id: UUID, activity_id: UUID, session: SessionDependency
) -> list[StudyTaskAttemptRead]:
    return tasks.list_attempts(session, project_id, lesson_id, activity_id)


@router.post(
    "/{lesson_id}/tasks/{activity_id}/attempts/{attempt_id}/check",
    response_model=StudyTaskAttemptRead,
)
async def check_study_task_attempt(
    project_id: UUID, lesson_id: UUID, activity_id: UUID, attempt_id: UUID,
    session: SessionDependency, gateway: GatewayDependency,
) -> StudyTaskAttemptRead:
    """Проверить открытый ответ, сохранённый без моделей."""
    return await tasks.check_pending(session, gateway, project_id, lesson_id, activity_id,
                                     attempt_id)


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
