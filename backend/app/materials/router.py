from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Query, Response, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.ai.dependencies import get_model_gateway
from app.ai.gateway import ModelGateway
from app.db import get_session
from app.materials import ai_cleanup, library, service
from app.materials.schemas import (
    ExamProgramDraftImportWrite,
    ExamProgramImportWrite,
    ExamProgramPreview,
    ExternalMaterialCreate,
    LibraryMaterialAttachWrite,
    LibraryMaterialDetailRead,
    LibraryMaterialRead,
    LibrarySearchResult,
    MaterialAnswerImportResult,
    MaterialCapabilities,
    MaterialDeletePreview,
    MaterialPurpose,
    MaterialRead,
    MaterialRevisionRead,
    MaterialUpdate,
    PageCorrectionRead,
    PageRead,
    PageTextUpdate,
    ProcessingStart,
    SourceRefreshResult,
    TextMaterialCreate,
)
from app.models import SourceRole
from app.projects.errors import ProjectDomainError
from app.projects.schemas import ProgramChangeResult

SessionDependency = Annotated[Session, Depends(get_session)]
GatewayDependency = Annotated[ModelGateway, Depends(get_model_gateway)]
router = APIRouter(prefix="/api", tags=["materials"])


@router.get("/material-capabilities", response_model=MaterialCapabilities)
def get_capabilities() -> MaterialCapabilities:
    return service.capabilities()


# ── Глобальная Библиотека. Конкретные пути объявляются раньше `/{material_id}`,
# иначе «upload» и «text» уедут в разбор id материала.


@router.get("/materials", response_model=list[LibraryMaterialRead])
def list_library_materials(session: SessionDependency) -> list[LibraryMaterialRead]:
    return library.list_library_materials(session)


@router.post(
    "/materials/upload",
    response_model=LibraryMaterialDetailRead,
    status_code=status.HTTP_202_ACCEPTED,
)
async def upload_library_material(
    session: SessionDependency, file: Annotated[UploadFile, File()]
) -> LibraryMaterialDetailRead:
    return await library.create_library_upload(session, file)


@router.post(
    "/materials/text",
    response_model=LibraryMaterialDetailRead,
    status_code=status.HTTP_201_CREATED,
)
def create_library_text_material(
    command: TextMaterialCreate, session: SessionDependency
) -> LibraryMaterialDetailRead:
    return library.create_library_text(session, command)


@router.post(
    "/materials/external",
    response_model=LibraryMaterialDetailRead,
    status_code=status.HTTP_201_CREATED,
)
def create_library_external_material(
    command: ExternalMaterialCreate, session: SessionDependency
) -> LibraryMaterialDetailRead:
    return library.create_library_external(session, command)


@router.get("/materials/{material_id}/delete-preview", response_model=MaterialDeletePreview)
def preview_library_material_delete(
    material_id: UUID, session: SessionDependency
) -> MaterialDeletePreview:
    return library.material_delete_preview(session, material_id)


@router.get("/materials/{material_id}/revisions", response_model=list[MaterialRevisionRead])
def list_material_revisions(
    material_id: UUID, session: SessionDependency
) -> list[MaterialRevisionRead]:
    return library.list_library_revisions(session, material_id)


@router.post(
    "/materials/{material_id}/revisions/{revision}/restore",
    response_model=LibraryMaterialDetailRead,
)
def restore_material_revision(
    material_id: UUID, revision: int, session: SessionDependency
) -> LibraryMaterialDetailRead:
    return library.restore_revision(session, material_id, revision)


@router.get("/materials/{material_id}/search", response_model=LibrarySearchResult)
def search_material(
    material_id: UUID,
    session: SessionDependency,
    q: str = "",
    revision: int | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> LibrarySearchResult:
    return library.search_library_material(
        session, material_id, q, revision=revision, limit=limit
    )


@router.get("/materials/{material_id}/source")
def get_material_source(
    material_id: UUID, session: SessionDependency, revision: int | None = None
) -> FileResponse:
    source = library.library_source(session, material_id, revision=revision)
    # inline: исходник открывается и проигрывается в просмотрщике, а «Скачать»
    # остаётся отдельным действием интерфейса.
    return FileResponse(
        source.path,
        media_type=source.media_type,
        filename=source.filename,
        content_disposition_type="inline",
    )


@router.post("/materials/{material_id}/source/refresh", response_model=SourceRefreshResult)
def refresh_material_source(material_id: UUID, session: SessionDependency) -> SourceRefreshResult:
    return library.refresh_source(session, material_id)


@router.get("/materials/{material_id}/pages/{page_number}", response_model=PageRead)
def get_library_page(
    material_id: UUID,
    page_number: int,
    session: SessionDependency,
    revision: int | None = None,
    task_id: UUID | None = None,
) -> PageRead:
    return library.read_library_page(
        session, material_id, page_number, revision=revision, task_id=task_id
    )


@router.get("/materials/{material_id}/pages/{page_number}/image")
def get_library_page_image(
    material_id: UUID, page_number: int, session: SessionDependency
) -> FileResponse:
    return FileResponse(library.library_page_image_path(session, material_id, page_number))


@router.put("/materials/{material_id}/pages/{page_number}", response_model=PageCorrectionRead)
def update_library_page_text(
    material_id: UUID,
    page_number: int,
    command: PageTextUpdate,
    session: SessionDependency,
) -> PageCorrectionRead:
    return library.update_library_page_text(session, material_id, page_number, command)


@router.post(
    "/materials/{material_id}/pages/{page_number}/ai-cleanup/preflight",
    response_model=ai_cleanup.CleanupPreflightRead,
)
async def preflight_library_page_cleanup(
    material_id: UUID,
    page_number: int,
    command: ai_cleanup.CleanupPreflightWrite,
    session: SessionDependency,
    gateway: GatewayDependency,
) -> ai_cleanup.CleanupPreflightRead:
    return await ai_cleanup.preflight(session, gateway, None, material_id, page_number, command)


@router.post(
    "/materials/{material_id}/pages/{page_number}/ai-cleanup",
    response_model=ai_cleanup.CleanupRunRead,
)
async def run_library_page_cleanup(
    material_id: UUID,
    page_number: int,
    command: ai_cleanup.CleanupRunWrite,
    session: SessionDependency,
    gateway: GatewayDependency,
) -> ai_cleanup.CleanupRunRead:
    return await ai_cleanup.run(session, gateway, None, material_id, page_number, command)


@router.post(
    "/materials/{material_id}/pages/{page_number}/ai-cleanup/apply",
    response_model=PageCorrectionRead,
)
def apply_library_page_cleanup(
    material_id: UUID,
    page_number: int,
    command: ai_cleanup.CleanupApplyWrite,
    session: SessionDependency,
) -> PageCorrectionRead:
    return ai_cleanup.apply(session, None, material_id, page_number, command)


@router.get(
    "/materials/{material_id}/fragments/{fragment_id}/asset", response_class=FileResponse
)
def get_library_fragment_asset(
    material_id: UUID, fragment_id: UUID, session: SessionDependency
) -> FileResponse:
    return FileResponse(library.library_fragment_asset_path(session, material_id, fragment_id))


@router.post("/materials/{material_id}/processing", response_model=LibraryMaterialDetailRead)
def start_library_processing(
    material_id: UUID, command: ProcessingStart, session: SessionDependency
) -> LibraryMaterialDetailRead:
    return library.start_library_processing(session, material_id, command)


@router.post(
    "/materials/{material_id}/processing/{action}", response_model=LibraryMaterialDetailRead
)
def control_library_processing(
    material_id: UUID, action: str, session: SessionDependency
) -> LibraryMaterialDetailRead:
    return library.control_library_task(session, material_id, action)


@router.post(
    "/materials/{material_id}/project-links",
    response_model=LibraryMaterialDetailRead,
    status_code=status.HTTP_201_CREATED,
)
def attach_library_material(
    material_id: UUID, command: LibraryMaterialAttachWrite, session: SessionDependency
) -> LibraryMaterialDetailRead:
    return library.attach_material_to_project(session, material_id, command)


@router.get("/materials/{material_id}", response_model=LibraryMaterialDetailRead)
def get_library_material(
    material_id: UUID, session: SessionDependency
) -> LibraryMaterialDetailRead:
    return library.read_library_material(session, material_id)


@router.delete("/materials/{material_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_library_material(material_id: UUID, session: SessionDependency) -> Response:
    library.delete_library_material(session, material_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/projects/{project_id}/materials", response_model=list[MaterialRead])
def list_project_materials(project_id: UUID, session: SessionDependency) -> list[MaterialRead]:
    return service.list_materials(session, project_id)


@router.post(
    "/projects/{project_id}/materials",
    response_model=MaterialRead,
    status_code=status.HTTP_202_ACCEPTED,
)
async def upload_project_material(
    project_id: UUID,
    session: SessionDependency,
    file: Annotated[UploadFile, File()],
    source_role: Annotated[SourceRole, Form()] = SourceRole.ADDITIONAL,
    purposes: Annotated[str, Form()] = MaterialPurpose.STUDY_SOURCE.value,
) -> MaterialRead:
    try:
        parsed_purposes = [
            MaterialPurpose(value.strip()) for value in purposes.split(",") if value.strip()
        ]
    except ValueError as error:
        raise ProjectDomainError(
            "Неизвестное назначение материала",
            status=422,
            code="material_purpose_invalid",
        ) from error
    return await service.upload_material(session, project_id, file, source_role, parsed_purposes)


@router.post(
    "/projects/{project_id}/materials/text",
    response_model=MaterialRead,
    status_code=status.HTTP_201_CREATED,
)
def create_project_text_material(
    project_id: UUID, command: TextMaterialCreate, session: SessionDependency
) -> MaterialRead:
    return service.create_text_material(session, project_id, command)


@router.post(
    "/projects/{project_id}/materials/external",
    response_model=MaterialRead,
    status_code=status.HTTP_201_CREATED,
)
def create_project_external_material(
    project_id: UUID, command: ExternalMaterialCreate, session: SessionDependency
) -> MaterialRead:
    return service.create_external_material(session, project_id, command)


@router.get("/projects/{project_id}/materials/{material_id}", response_model=MaterialRead)
def get_project_material(
    project_id: UUID, material_id: UUID, session: SessionDependency
) -> MaterialRead:
    return service.get_material(session, project_id, material_id)


@router.patch("/projects/{project_id}/materials/{material_id}", response_model=MaterialRead)
def update_project_material(
    project_id: UUID,
    material_id: UUID,
    command: MaterialUpdate,
    session: SessionDependency,
) -> MaterialRead:
    return service.update_material(session, project_id, material_id, command)


@router.delete(
    "/projects/{project_id}/materials/{material_id}", status_code=status.HTTP_204_NO_CONTENT
)
def detach_project_material(
    project_id: UUID, material_id: UUID, session: SessionDependency
) -> Response:
    service.detach_material(session, project_id, material_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/projects/{project_id}/materials/{material_id}/processing", response_model=MaterialRead
)
def start_material_processing(
    project_id: UUID,
    material_id: UUID,
    command: ProcessingStart,
    session: SessionDependency,
) -> MaterialRead:
    return service.start_processing(session, project_id, material_id, command)


@router.post(
    "/projects/{project_id}/materials/{material_id}/processing/{action}",
    response_model=MaterialRead,
)
def control_material_processing(
    project_id: UUID,
    material_id: UUID,
    action: str,
    session: SessionDependency,
) -> MaterialRead:
    return service.control_task(session, project_id, material_id, action)


@router.get(
    "/projects/{project_id}/materials/{material_id}/pages/{page_number}",
    response_model=PageRead,
)
def get_material_page(
    project_id: UUID,
    material_id: UUID,
    page_number: int,
    session: SessionDependency,
) -> PageRead:
    return service.get_page(session, project_id, material_id, page_number)


@router.post(
    "/projects/{project_id}/materials/{material_id}/pages/{page_number}/ai-cleanup/preflight",
    response_model=ai_cleanup.CleanupPreflightRead,
)
async def preflight_material_page_cleanup(
    project_id: UUID,
    material_id: UUID,
    page_number: int,
    command: ai_cleanup.CleanupPreflightWrite,
    session: SessionDependency,
    gateway: GatewayDependency,
) -> ai_cleanup.CleanupPreflightRead:
    return await ai_cleanup.preflight(
        session, gateway, project_id, material_id, page_number, command
    )


@router.post(
    "/projects/{project_id}/materials/{material_id}/pages/{page_number}/ai-cleanup",
    response_model=ai_cleanup.CleanupRunRead,
)
async def run_material_page_cleanup(
    project_id: UUID,
    material_id: UUID,
    page_number: int,
    command: ai_cleanup.CleanupRunWrite,
    session: SessionDependency,
    gateway: GatewayDependency,
) -> ai_cleanup.CleanupRunRead:
    return await ai_cleanup.run(session, gateway, project_id, material_id, page_number, command)


@router.post(
    "/projects/{project_id}/materials/{material_id}/pages/{page_number}/ai-cleanup/apply",
    response_model=PageCorrectionRead,
)
def apply_material_page_cleanup(
    project_id: UUID,
    material_id: UUID,
    page_number: int,
    command: ai_cleanup.CleanupApplyWrite,
    session: SessionDependency,
) -> PageCorrectionRead:
    return ai_cleanup.apply(session, project_id, material_id, page_number, command)


@router.put(
    "/projects/{project_id}/materials/{material_id}/pages/{page_number}",
    response_model=PageCorrectionRead,
)
def update_material_page_text(
    project_id: UUID,
    material_id: UUID,
    page_number: int,
    command: PageTextUpdate,
    session: SessionDependency,
) -> PageCorrectionRead:
    return service.update_page_text(session, project_id, material_id, page_number, command)


@router.get("/projects/{project_id}/materials/{material_id}/pages/{page_number}/image")
def get_material_page_image(
    project_id: UUID,
    material_id: UUID,
    page_number: int,
    session: SessionDependency,
) -> FileResponse:
    return FileResponse(service.page_image_path(session, project_id, material_id, page_number))


@router.get(
    "/projects/{project_id}/materials/{material_id}/fragments/{fragment_id}/asset",
    response_class=FileResponse,
)
def get_fragment_asset(
    project_id: UUID,
    material_id: UUID,
    fragment_id: UUID,
    session: SessionDependency,
) -> FileResponse:
    return FileResponse(service.fragment_asset_path(session, project_id, material_id, fragment_id))


@router.post(
    "/projects/{project_id}/materials/{material_id}/reference-answer-import",
    response_model=MaterialAnswerImportResult,
)
def import_material_reference_answers(
    project_id: UUID, material_id: UUID, session: SessionDependency
) -> MaterialAnswerImportResult:
    return service.import_answers_from_material(session, project_id, material_id)


@router.get(
    "/projects/{project_id}/materials/{material_id}/exam-program-preview",
    response_model=ExamProgramPreview,
)
def preview_exam_program(
    project_id: UUID, material_id: UUID, session: SessionDependency
) -> ExamProgramPreview:
    return service.preview_exam_program(session, project_id, material_id)


@router.post(
    "/projects/{project_id}/materials/{material_id}/exam-program-import",
    response_model=ProgramChangeResult,
)
def import_exam_program(
    project_id: UUID,
    material_id: UUID,
    command: ExamProgramImportWrite,
    session: SessionDependency,
) -> ProgramChangeResult:
    return service.import_exam_program_from_material(session, project_id, material_id, command)


@router.post(
    "/projects/{project_id}/materials/{material_id}/exam-draft-import",
    response_model=ProgramChangeResult,
)
def import_exam_draft_program(
    project_id: UUID,
    material_id: UUID,
    command: ExamProgramDraftImportWrite,
    session: SessionDependency,
) -> ProgramChangeResult:
    return service.import_exam_draft_from_material(session, project_id, material_id, command)
