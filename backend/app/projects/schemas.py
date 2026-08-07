from datetime import date, datetime
from enum import StrEnum
from typing import Annotated, Self
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    StringConstraints,
    field_validator,
    model_validator,
)

from app.models import (
    ExamFormat,
    ExamKind,
    GoalPurpose,
    GoalRole,
    GoalScope,
    ModuleKey,
    NodeType,
    OriginKind,
    ProjectStatus,
    StartingLevel,
    StudyFormat,
    TargetOutcome,
    TemplateKey,
    WorkspaceVariant,
)

NonBlank = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)


class ProjectDraftWrite(ApiModel):
    name: NonBlank | None = None
    description: str | None = None
    icon: str | None = None
    color: int | None = Field(default=None, ge=1, le=8)
    sort_order: int = Field(default=0, ge=0)
    deadline: date | None = None
    enabled_modules: list[ModuleKey] = Field(default_factory=list)


class GoalPassportWrite(ApiModel):
    subject: NonBlank | None = None
    purpose: GoalPurpose | None = None
    scope: GoalScope | None = None
    starting_level: StartingLevel | None = None
    current_knowledge: str | None = None
    target_outcome: TargetOutcome | None = None
    goal: str | None = None
    success_criterion: str | None = None
    important: str | None = None
    excluded: str | None = None
    study_format: StudyFormat | None = None
    minutes_per_day: int | None = Field(default=None, gt=0)
    days_per_week: int | None = Field(default=None, ge=1, le=7)
    session_minutes: int | None = Field(default=None, gt=0)
    exam_format: ExamFormat | None = None
    expected_item_count: int | None = Field(default=None, gt=0)
    instructor_requirements: str | None = None


class ProjectIcon(StrEnum):
    GRADUATION_CAP = "graduation-cap"
    BOOK_OPEN = "book-open"
    DATABASE = "database"
    SIGMA = "sigma"
    ATOM = "atom"
    CODE = "code"
    GLOBE = "globe"
    SCALE = "scale"
    FLASK = "flask"


class ProjectSettingsProjectWrite(ApiModel):
    name: NonBlank
    description: str | None = None
    icon: ProjectIcon | None = None
    color: int | None = Field(default=None, ge=1, le=8)
    deadline: date | None = None
    enabled_modules: list[ModuleKey] = Field(default_factory=list)

    @field_validator("enabled_modules")
    @classmethod
    def normalize_modules(cls, modules: list[ModuleKey]) -> list[ModuleKey]:
        selected = set(modules)
        return [module for module in ModuleKey if module in selected]


class ProjectSettingsWrite(ApiModel):
    project: ProjectSettingsProjectWrite
    goal_passport: GoalPassportWrite


class WizardDraftCreate(ApiModel):
    template_key: TemplateKey
    workspace_variant: WorkspaceVariant


class WizardDraftWrite(ApiModel):
    expected_revision: int = Field(ge=0)
    current_step: int = Field(ge=1, le=5)
    max_completed_step: int = Field(ge=1, le=5)
    schema_version: int = Field(ge=1)
    project: ProjectDraftWrite
    goal_passport: GoalPassportWrite | None = None
    state: dict[str, JsonValue] = Field(default_factory=dict)


class ActivateWizardDraft(ApiModel):
    expected_revision: int = Field(ge=0)


class ProgramNodeCreate(ApiModel):
    parent_id: UUID | None = None
    node_type: NodeType
    exam_kind: ExamKind | None = None
    sort_order: int = Field(default=0, ge=0)
    title: NonBlank
    section_purpose: str | None = None
    goal_role: GoalRole | None = None
    target_level: TargetOutcome | None = None
    is_in_current_program: bool = True
    needs_material: bool = False
    is_archived: bool = False
    origin_kind: OriginKind = OriginKind.MANUAL
    origin_note: str | None = None


class ProgramNodeUpdate(ApiModel):
    parent_id: UUID | None = None
    node_type: NodeType | None = None
    exam_kind: ExamKind | None = None
    sort_order: int | None = Field(default=None, ge=0)
    title: NonBlank | None = None
    section_purpose: str | None = None
    goal_role: GoalRole | None = None
    target_level: TargetOutcome | None = None
    is_in_current_program: bool | None = None
    needs_material: bool | None = None
    is_archived: bool | None = None
    origin_kind: OriginKind | None = None
    origin_note: str | None = None


class WorkspaceTab(StrEnum):
    ANSWER = "answer"
    SOURCE = "source"
    LESSON = "lesson"
    CONSPECT = "conspect"
    HISTORY = "history"
    CHAT = "chat"
    SUMMARY = "summary"


class WorkspaceGroup(ApiModel):
    id: NonBlank
    tabs: list[WorkspaceTab] = Field(min_length=1)
    active_tab: WorkspaceTab | None = None

    @model_validator(mode="after")
    def validate_tabs(self) -> Self:
        if len(self.tabs) != len(set(self.tabs)):
            raise ValueError("В группе не должно быть повторяющихся вкладок")
        if self.active_tab is not None and self.active_tab not in self.tabs:
            raise ValueError("Активная вкладка должна входить в список вкладок группы")
        return self


class WorkspaceLayout(ApiModel):
    selected_node_id: UUID | None = None
    expanded_node_ids: list[UUID] = Field(default_factory=list)
    tree_width: int = Field(default=320, ge=260, le=460)
    groups: list[WorkspaceGroup] = Field(min_length=1, max_length=3)
    group_weights: list[float]

    @model_validator(mode="after")
    def validate_groups(self) -> Self:
        if len(self.groups) != len(self.group_weights):
            raise ValueError("Число групп и их весов должно совпадать")
        if any(weight <= 0 for weight in self.group_weights):
            raise ValueError("Вес каждой группы должен быть положительным")
        group_ids = [group.id for group in self.groups]
        if len(group_ids) != len(set(group_ids)):
            raise ValueError("Идентификаторы групп не должны повторяться")
        return self


class WorkspaceStateWrite(ApiModel):
    schema_version: Annotated[int, Field(strict=True, ge=1, le=1)]
    layout: WorkspaceLayout


class ProjectRead(ApiModel):
    id: UUID
    template_key: TemplateKey
    workspace_variant: WorkspaceVariant
    status: ProjectStatus
    name: str | None
    description: str | None
    icon: str | None
    color: int | None
    sort_order: int
    deadline: date | None
    enabled_modules: list[ModuleKey]
    status_changed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class WizardDraftRead(ApiModel):
    project_id: UUID
    current_step: int
    max_completed_step: int
    revision: int
    schema_version: int
    state: dict[str, JsonValue]
    updated_at: datetime


class GoalPassportRead(GoalPassportWrite):
    project_id: UUID
    updated_at: datetime


class ProgramNodeRead(ProgramNodeCreate):
    id: UUID
    project_id: UUID
    created_at: datetime
    updated_at: datetime


class WorkspaceStateRead(WorkspaceStateWrite):
    project_id: UUID
    updated_at: datetime


class WizardDraftSummary(ApiModel):
    project_id: UUID
    template_key: TemplateKey
    workspace_variant: WorkspaceVariant
    name: str | None
    current_step: int
    max_completed_step: int
    revision: int
    updated_at: datetime


class WizardDraftDetail(ApiModel):
    project: ProjectRead
    draft: WizardDraftRead
    goal_passport: GoalPassportRead | None
    program_nodes: list[ProgramNodeRead]


class ProjectSummary(ApiModel):
    id: UUID
    template_key: TemplateKey
    workspace_variant: WorkspaceVariant
    status: ProjectStatus
    name: str
    description: str | None
    icon: str | None
    color: int | None
    sort_order: int
    deadline: date | None
    updated_at: datetime


class ProjectDetail(ApiModel):
    project: ProjectRead
    goal_passport: GoalPassportRead | None
    program_nodes: list[ProgramNodeRead]
    workspace_state: WorkspaceStateRead | None
