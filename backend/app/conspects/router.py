from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.conspects import service
from app.conspects.schemas import (
    ConspectImageRead,
    ConspectRead,
    ConspectSummaryRead,
    ConspectWrite,
)
from app.db import get_session

SessionDependency = Annotated[Session, Depends(get_session)]
router = APIRouter(prefix="/api/projects/{project_id}", tags=["conspects"])


@router.get("/conspects", response_model=ConspectSummaryRead)
def list_conspects(project_id: UUID, session: SessionDependency) -> ConspectSummaryRead:
    return service.list_conspect_summary(session, project_id)


@router.get("/conspects/{node_id}", response_model=ConspectRead)
def get_conspect(project_id: UUID, node_id: UUID, session: SessionDependency) -> ConspectRead:
    return service.get_conspect(session, project_id, node_id)


@router.put("/conspects/{node_id}", response_model=ConspectRead)
def save_conspect(
    project_id: UUID, node_id: UUID, command: ConspectWrite, session: SessionDependency
) -> ConspectRead:
    return service.save_conspect(session, project_id, node_id, command)


@router.post("/conspects/{node_id}/images", response_model=ConspectImageRead)
async def upload_conspect_image(
    project_id: UUID,
    node_id: UUID,
    session: SessionDependency,
    file: Annotated[UploadFile, File()],
) -> ConspectImageRead:
    return await service.add_conspect_image(session, project_id, node_id, file)


@router.get("/conspect-images/{image_id}/file", response_class=FileResponse)
def conspect_image_file(
    project_id: UUID, image_id: UUID, session: SessionDependency
) -> FileResponse:
    return FileResponse(service.conspect_image_path(session, project_id, image_id))


@router.delete("/conspect-images/{image_id}", status_code=204)
def delete_conspect_image(project_id: UUID, image_id: UUID, session: SessionDependency) -> None:
    service.delete_conspect_image(session, project_id, image_id)
