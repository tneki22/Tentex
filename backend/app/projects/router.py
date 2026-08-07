from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.db import get_session
from app.projects import service
from app.projects.schemas import (
    ActivateWizardDraft,
    ProgramNodeCreate,
    ProgramNodeRead,
    ProgramNodeUpdate,
    ProjectDetail,
    ProjectSettingsWrite,
    ProjectSummary,
    WizardDraftCreate,
    WizardDraftDetail,
    WizardDraftSummary,
    WizardDraftWrite,
    WorkspaceStateRead,
    WorkspaceStateWrite,
)

SessionDependency = Annotated[Session, Depends(get_session)]

router = APIRouter(prefix="/api")
drafts = APIRouter(prefix="/wizard-drafts", tags=["wizard-drafts"])
projects = APIRouter(prefix="/projects", tags=["projects"])


@drafts.post("", response_model=WizardDraftDetail, status_code=status.HTTP_201_CREATED)
def create_draft(command: WizardDraftCreate, session: SessionDependency) -> WizardDraftDetail:
    return service.create_wizard_draft(session, command)


@drafts.get("", response_model=list[WizardDraftSummary])
def list_drafts(session: SessionDependency) -> list[WizardDraftSummary]:
    return service.list_wizard_drafts(session)


@drafts.get("/{project_id}", response_model=WizardDraftDetail)
def get_draft(project_id: UUID, session: SessionDependency) -> WizardDraftDetail:
    return service.get_wizard_draft(session, project_id)


@drafts.put("/{project_id}", response_model=WizardDraftDetail)
def save_draft(
    project_id: UUID, command: WizardDraftWrite, session: SessionDependency
) -> WizardDraftDetail:
    return service.save_wizard_draft(session, project_id, command)


@drafts.post("/{project_id}/activate", response_model=ProjectDetail)
def activate_draft(
    project_id: UUID, command: ActivateWizardDraft, session: SessionDependency
) -> ProjectDetail:
    return service.activate_wizard_draft(session, project_id, command.expected_revision)


@projects.get("", response_model=list[ProjectSummary])
def list_all_projects(session: SessionDependency) -> list[ProjectSummary]:
    return service.list_projects(session)


@projects.get("/{project_id}", response_model=ProjectDetail)
def get_one_project(project_id: UUID, session: SessionDependency) -> ProjectDetail:
    return service.get_project(session, project_id)


@projects.put("/{project_id}/settings", response_model=ProjectDetail)
def save_project_settings(
    project_id: UUID, command: ProjectSettingsWrite, session: SessionDependency
) -> ProjectDetail:
    return service.update_project_settings(session, project_id, command)


@projects.post(
    "/{project_id}/program-nodes",
    response_model=ProgramNodeRead,
    status_code=status.HTTP_201_CREATED,
)
def create_node(
    project_id: UUID, command: ProgramNodeCreate, session: SessionDependency
) -> ProgramNodeRead:
    return service.create_program_node(session, project_id, command)


@projects.patch(
    "/{project_id}/program-nodes/{node_id}", response_model=ProgramNodeRead
)
def update_node(
    project_id: UUID,
    node_id: UUID,
    command: ProgramNodeUpdate,
    session: SessionDependency,
) -> ProgramNodeRead:
    return service.update_program_node(session, project_id, node_id, command)


@projects.put("/{project_id}/workspace-state", response_model=WorkspaceStateRead)
def save_layout(
    project_id: UUID, command: WorkspaceStateWrite, session: SessionDependency
) -> WorkspaceStateRead:
    return service.save_workspace_state(session, project_id, command)


router.include_router(drafts)
router.include_router(projects)
