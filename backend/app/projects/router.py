from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Query, Response, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.ai.dependencies import get_model_gateway
from app.ai.gateway import ModelGateway
from app.db import get_session
from app.projects import answers, program, program_ai, service
from app.projects.schemas import (
    ActionUndoResult,
    ActivateWizardDraft,
    CoverageMapRead,
    ExamImportResult,
    ExamImportWrite,
    ProgramChangeResult,
    ProgramMove,
    ProgramNodeCreate,
    ProgramNodeUpdate,
    ProgramRevisionCommand,
    ProgramSwap,
    ProgramTargetLevel,
    ProjectDetail,
    ProjectOrderWrite,
    ProjectSettingsResult,
    ProjectSettingsWrite,
    ProjectSummary,
    ReferenceAnswerAttachmentRead,
    ReferenceAnswerConfirm,
    ReferenceAnswerImportResult,
    ReferenceAnswerImportWrite,
    ReferenceAnswerSlot,
    ReferenceAnswerWrite,
    UndoProjectAction,
    WizardDraftCreate,
    WizardDraftDetail,
    WizardDraftSummary,
    WizardDraftWrite,
    WorkspaceStateRead,
    WorkspaceStateWrite,
)

SessionDependency = Annotated[Session, Depends(get_session)]
GatewayDependency = Annotated[ModelGateway, Depends(get_model_gateway)]

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


@drafts.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_draft(
    project_id: UUID,
    session: SessionDependency,
    expected_revision: Annotated[int, Query(ge=0)],
) -> Response:
    service.delete_wizard_draft(session, project_id, expected_revision)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@drafts.post("/{project_id}/exam-import", response_model=ExamImportResult)
def import_exam(
    project_id: UUID, command: ExamImportWrite, session: SessionDependency
) -> ExamImportResult:
    return service.import_exam_program(session, project_id, command)


@drafts.post("/{project_id}/activate", response_model=ProjectDetail)
def activate_draft(
    project_id: UUID, command: ActivateWizardDraft, session: SessionDependency
) -> ProjectDetail:
    return service.activate_wizard_draft(session, project_id, command.expected_revision)


@projects.get("", response_model=list[ProjectSummary])
def list_all_projects(session: SessionDependency) -> list[ProjectSummary]:
    return service.list_projects(session)


@projects.put("/order", response_model=list[ProjectSummary])
def save_order(command: ProjectOrderWrite, session: SessionDependency) -> list[ProjectSummary]:
    return service.save_project_order(session, command)


@projects.get("/{project_id}", response_model=ProjectDetail)
def get_one_project(project_id: UUID, session: SessionDependency) -> ProjectDetail:
    return service.get_project(session, project_id)


@projects.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project(project_id: UUID, session: SessionDependency) -> Response:
    service.delete_project(session, project_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@projects.get("/{project_id}/coverage-map", response_model=CoverageMapRead)
def get_coverage_map(project_id: UUID, session: SessionDependency) -> CoverageMapRead:
    return answers.get_coverage_map(session, project_id)


@projects.get(
    "/{project_id}/program-nodes/{node_id}/reference-answer",
    response_model=ReferenceAnswerSlot,
)
def get_reference_answer(
    project_id: UUID,
    node_id: UUID,
    session: SessionDependency,
) -> ReferenceAnswerSlot:
    return answers.get_reference_answer(session, project_id, node_id)


@projects.put(
    "/{project_id}/program-nodes/{node_id}/reference-answer",
    response_model=ReferenceAnswerSlot,
)
def put_reference_answer(
    project_id: UUID,
    node_id: UUID,
    command: ReferenceAnswerWrite,
    session: SessionDependency,
) -> ReferenceAnswerSlot:
    return answers.put_reference_answer(session, project_id, node_id, command)


@projects.post(
    "/{project_id}/program-nodes/{node_id}/reference-answer/confirm",
    response_model=ReferenceAnswerSlot,
)
def confirm_reference_answer(
    project_id: UUID,
    node_id: UUID,
    command: ReferenceAnswerConfirm,
    session: SessionDependency,
) -> ReferenceAnswerSlot:
    return answers.confirm_reference_answer(session, project_id, node_id, command)


@projects.delete(
    "/{project_id}/program-nodes/{node_id}/reference-answer",
    response_model=ReferenceAnswerSlot,
)
def delete_reference_answer(
    project_id: UUID,
    node_id: UUID,
    session: SessionDependency,
    expected_revision: Annotated[int, Query(ge=0)],
) -> ReferenceAnswerSlot:
    return answers.delete_reference_answer(
        session,
        project_id,
        node_id,
        expected_revision,
    )


@projects.get(
    "/{project_id}/reference-answers/{node_id}/attachments",
    response_model=list[ReferenceAnswerAttachmentRead],
)
def list_answer_attachments(
    project_id: UUID, node_id: UUID, session: SessionDependency
) -> list[ReferenceAnswerAttachmentRead]:
    return answers.list_attachments(session, project_id, node_id)


@projects.post(
    "/{project_id}/reference-answers/{node_id}/attachments",
    response_model=ReferenceAnswerAttachmentRead,
)
async def add_answer_attachment(
    project_id: UUID,
    node_id: UUID,
    session: SessionDependency,
    file: Annotated[UploadFile, File()],
) -> ReferenceAnswerAttachmentRead:
    return await answers.add_attachment(session, project_id, node_id, file)


@projects.get(
    "/{project_id}/attachments/{attachment_id}/file",
    response_class=FileResponse,
)
def download_answer_attachment(
    project_id: UUID, attachment_id: UUID, session: SessionDependency
) -> FileResponse:
    return FileResponse(answers.attachment_path(session, project_id, attachment_id))


@projects.delete("/{project_id}/attachments/{attachment_id}", status_code=204)
def remove_answer_attachment(
    project_id: UUID, attachment_id: UUID, session: SessionDependency
) -> None:
    answers.delete_attachment(session, project_id, attachment_id)


@projects.post(
    "/{project_id}/reference-answers/import",
    response_model=ReferenceAnswerImportResult,
)
def import_reference_answers(
    project_id: UUID,
    command: ReferenceAnswerImportWrite,
    session: SessionDependency,
) -> ReferenceAnswerImportResult:
    return answers.import_reference_answers(session, project_id, command)


@projects.put("/{project_id}/settings", response_model=ProjectSettingsResult)
def save_project_settings(
    project_id: UUID, command: ProjectSettingsWrite, session: SessionDependency
) -> ProjectSettingsResult:
    return service.update_project_settings(session, project_id, command)


@projects.post("/{project_id}/archive", response_model=ProjectSummary)
def archive_project(project_id: UUID, session: SessionDependency) -> ProjectSummary:
    return service.archive_project(session, project_id)


@projects.post("/{project_id}/restore", response_model=ProjectSummary)
def restore_project(project_id: UUID, session: SessionDependency) -> ProjectSummary:
    return service.restore_project(session, project_id)


@projects.post(
    "/{project_id}/program-nodes",
    response_model=ProgramChangeResult,
    status_code=status.HTTP_201_CREATED,
)
def create_node(
    project_id: UUID, command: ProgramNodeCreate, session: SessionDependency
) -> ProgramChangeResult:
    return program.create_program_node(session, project_id, command)


@projects.post(
    "/{project_id}/program/ai-grouping/preflight",
    response_model=program_ai.ProgramGroupingPreflightRead,
)
async def preflight_program_grouping(
    project_id: UUID,
    command: program_ai.ProgramGroupingPreflightWrite,
    session: SessionDependency,
    gateway: GatewayDependency,
) -> program_ai.ProgramGroupingPreflightRead:
    del command
    return await program_ai.preflight(session, gateway, project_id)


@projects.post(
    "/{project_id}/program/ai-grouping",
    response_model=program_ai.ProgramGroupingRunRead,
)
async def run_program_grouping(
    project_id: UUID,
    command: program_ai.ProgramGroupingRunWrite,
    session: SessionDependency,
    gateway: GatewayDependency,
) -> program_ai.ProgramGroupingRunRead:
    return await program_ai.run(session, gateway, project_id, command)


@projects.post(
    "/{project_id}/program/ai-grouping/apply",
    response_model=ProgramChangeResult,
)
def apply_program_grouping(
    project_id: UUID,
    command: program_ai.ProgramGroupingApplyWrite,
    session: SessionDependency,
) -> ProgramChangeResult:
    return program_ai.apply(session, project_id, command)


@projects.patch("/{project_id}/program-nodes/{node_id}", response_model=ProgramChangeResult)
def update_node(
    project_id: UUID,
    node_id: UUID,
    command: ProgramNodeUpdate,
    session: SessionDependency,
) -> ProgramChangeResult:
    return program.update_program_node(session, project_id, node_id, command)


@projects.post("/{project_id}/program-nodes/{node_id}/move", response_model=ProgramChangeResult)
def move_node(
    project_id: UUID, node_id: UUID, command: ProgramMove, session: SessionDependency
) -> ProgramChangeResult:
    return program.move_program_node(session, project_id, node_id, command)


@projects.post("/{project_id}/program-nodes/{node_id}/swap", response_model=ProgramChangeResult)
def swap_node(
    project_id: UUID, node_id: UUID, command: ProgramSwap, session: SessionDependency
) -> ProgramChangeResult:
    return program.swap_program_nodes(session, project_id, node_id, command)


@projects.post(
    "/{project_id}/program-nodes/{node_id}/target-level",
    response_model=ProgramChangeResult,
)
def set_node_target(
    project_id: UUID,
    node_id: UUID,
    command: ProgramTargetLevel,
    session: SessionDependency,
) -> ProgramChangeResult:
    return program.set_target_level(session, project_id, node_id, command)


@projects.post("/{project_id}/program-nodes/{node_id}/remove", response_model=ProgramChangeResult)
def remove_node(
    project_id: UUID,
    node_id: UUID,
    command: ProgramRevisionCommand,
    session: SessionDependency,
) -> ProgramChangeResult:
    return program.remove_program_node(session, project_id, node_id, command)


@projects.post("/{project_id}/program-nodes/{node_id}/restore", response_model=ProgramChangeResult)
def restore_node(
    project_id: UUID,
    node_id: UUID,
    command: ProgramRevisionCommand,
    session: SessionDependency,
) -> ProgramChangeResult:
    return program.restore_program_node(session, project_id, node_id, command)


@projects.post("/{project_id}/actions/undo", response_model=ActionUndoResult)
def undo_action(
    project_id: UUID, command: UndoProjectAction, session: SessionDependency
) -> ActionUndoResult:
    return program.undo_last_project_action(session, project_id, command.expected_action_sequence)


@projects.put("/{project_id}/workspace-state", response_model=WorkspaceStateRead)
def save_layout(
    project_id: UUID, command: WorkspaceStateWrite, session: SessionDependency
) -> WorkspaceStateRead:
    return service.save_workspace_state(session, project_id, command)


router.include_router(drafts)
router.include_router(projects)
