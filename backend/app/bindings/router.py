from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.bindings import answers_link, service
from app.bindings.schemas import (
    AnswersHeadingResolveWrite,
    AnswersLinkRead,
    BindingBulkRemoveWrite,
    BindingChangeResult,
    BindingCreateWrite,
    BindingFragmentRead,
    NodeBindingSummary,
    ReindexResult,
    SearchResultRead,
)
from app.db import get_session
from app.models import BindingStatus

SessionDependency = Annotated[Session, Depends(get_session)]
router = APIRouter(prefix="/api/projects/{project_id}", tags=["bindings"])


@router.get("/search", response_model=list[SearchResultRead])
def search_materials(
    project_id: UUID,
    session: SessionDependency,
    q: str = "",
    material_id: UUID | None = None,
    node_id: UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 50,
) -> list[SearchResultRead]:
    return service.search_project_materials(
        session, project_id, q, material_id=material_id, node_id=node_id, limit=limit
    )


@router.post("/materials/{material_id}/reindex", response_model=ReindexResult)
def reindex_material(
    project_id: UUID, material_id: UUID, session: SessionDependency
) -> ReindexResult:
    return service.reindex_material(session, project_id, material_id)


@router.post("/materials/{material_id}/link-answers", response_model=AnswersLinkRead)
def link_answers(
    project_id: UUID, material_id: UUID, session: SessionDependency
) -> AnswersLinkRead:
    with session.begin():
        result = answers_link.link_answers_material(session, project_id, material_id)
    return AnswersLinkRead.model_validate(result, from_attributes=True)


@router.post("/materials/{material_id}/link-answers/resolve", response_model=AnswersLinkRead)
def resolve_answers_heading(
    project_id: UUID,
    material_id: UUID,
    command: AnswersHeadingResolveWrite,
    session: SessionDependency,
) -> AnswersLinkRead:
    with session.begin():
        result = answers_link.resolve_answers_heading(
            session,
            project_id,
            material_id,
            command.anchor_fragment_id,
            command.program_node_id,
        )
    return AnswersLinkRead.model_validate(result, from_attributes=True)


@router.get("/bindings", response_model=list[BindingFragmentRead])
def list_bindings(
    project_id: UUID,
    session: SessionDependency,
    node_id: UUID | None = None,
    material_id: UUID | None = None,
    page: int | None = None,
    status: BindingStatus | None = None,
) -> list[BindingFragmentRead]:
    return service.list_bindings(
        session,
        project_id,
        node_id=node_id,
        material_id=material_id,
        page_number=page,
        status=status,
    )


@router.get("/bindings/summary", response_model=list[NodeBindingSummary])
def bindings_summary(project_id: UUID, session: SessionDependency) -> list[NodeBindingSummary]:
    return service.get_summary(session, project_id)


@router.post("/bindings", response_model=BindingChangeResult)
def create_bindings(
    project_id: UUID, command: BindingCreateWrite, session: SessionDependency
) -> BindingChangeResult:
    return service.create_bindings(session, project_id, command)


@router.post("/bindings/bulk-remove", response_model=BindingChangeResult)
def remove_bindings_bulk(
    project_id: UUID, command: BindingBulkRemoveWrite, session: SessionDependency
) -> BindingChangeResult:
    return service.remove_bindings_bulk(session, project_id, command)


@router.delete("/bindings/{binding_id}", response_model=BindingChangeResult)
def remove_binding(
    project_id: UUID, binding_id: UUID, session: SessionDependency
) -> BindingChangeResult:
    return service.remove_binding(session, project_id, binding_id)


@router.post("/bindings/{binding_id}/restore", response_model=BindingChangeResult)
def restore_binding(
    project_id: UUID, binding_id: UUID, session: SessionDependency
) -> BindingChangeResult:
    return service.restore_binding(session, project_id, binding_id)
