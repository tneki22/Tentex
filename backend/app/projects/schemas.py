from datetime import date, datetime, time
from enum import StrEnum
from typing import Annotated, Literal, Self
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
    ReferenceAnswerMatchMethod,
    ReferenceAnswerOrigin,
    StartingLevel,
    StudyFormat,
    TargetOutcome,
    TemplateKey,
    WorkspaceVariant,
)

NonBlank = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)


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


def normalize_modules(modules: list[ModuleKey]) -> list[ModuleKey]:
    selected = set(modules)
    return [module for module in ModuleKey if module in selected]


class ProjectDraftWrite(ApiModel):
    name: NonBlank | None = None
    description: str | None = None
    icon: ProjectIcon | None = None
    color: int | None = Field(default=None, ge=1, le=8)
    deadline: date | None = None
    enabled_modules: list[ModuleKey] = Field(default_factory=list)

    @field_validator("enabled_modules")
    @classmethod
    def normalize_enabled_modules(cls, modules: list[ModuleKey]) -> list[ModuleKey]:
        return normalize_modules(modules)


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
    exam_time: time | None = None
    exam_procedure: str | None = None


class ProjectSettingsProjectWrite(ApiModel):
    name: NonBlank
    description: str | None = None
    icon: ProjectIcon | None = None
    color: int | None = Field(default=None, ge=1, le=8)
    deadline: date | None = None
    enabled_modules: list[ModuleKey] = Field(default_factory=list)

    @field_validator("enabled_modules")
    @classmethod
    def normalize_enabled_modules(cls, modules: list[ModuleKey]) -> list[ModuleKey]:
        return normalize_modules(modules)


class ProjectSettingsWrite(ApiModel):
    project: ProjectSettingsProjectWrite
    goal_passport: GoalPassportWrite


class WizardDraftCreate(ApiModel):
    template_key: TemplateKey


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
    expected_program_revision: int = Field(ge=0)
    parent_id: UUID | None = None
    position: int | None = Field(default=None, ge=0)
    node_type: NodeType
    exam_kind: ExamKind | None = None
    title: NonBlank
    section_purpose: str | None = None
    goal_role: GoalRole | None = None
    target_level: TargetOutcome | None = None
    needs_material: bool = False


class ProgramNodeUpdate(ApiModel):
    expected_program_revision: int = Field(ge=0)
    title: NonBlank | None = None
    node_type: NodeType | None = None
    exam_kind: ExamKind | None = None
    section_purpose: str | None = None
    goal_role: GoalRole | None = None
    needs_material: bool | None = None

    @model_validator(mode="after")
    def require_change(self) -> Self:
        if self.model_fields_set == {"expected_program_revision"}:
            raise ValueError("Нужно передать хотя бы одно изменяемое поле")
        return self


class ProgramMove(ApiModel):
    expected_program_revision: int = Field(ge=0)
    parent_id: UUID | None = None
    position: int | None = Field(default=None, ge=0)


class ProgramSwap(ApiModel):
    expected_program_revision: int = Field(ge=0)
    target_node_id: UUID


class ProgramTargetLevel(ApiModel):
    expected_program_revision: int = Field(ge=0)
    target_level: TargetOutcome
    include_descendants: bool = False


class ProgramRevisionCommand(ApiModel):
    expected_program_revision: int = Field(ge=0)


class UndoProjectAction(ApiModel):
    expected_action_sequence: int = Field(ge=1)


class ProjectOrderWrite(ApiModel):
    project_ids: list[UUID]


class ExamImportWrite(ApiModel):
    expected_revision: int = Field(ge=0)
    expected_program_revision: int = Field(ge=0)
    exam_format: Literal[ExamFormat.QUESTIONS, ExamFormat.QUESTIONS_TASKS, ExamFormat.TICKETS]
    raw_text: str = Field(min_length=1, max_length=1_000_000)
    dedupe_duplicates: bool = False


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
    tabs: list[WorkspaceTab] = Field(default_factory=list)
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
    icon: ProjectIcon | None
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


class ProgramNodeRead(ApiModel):
    id: UUID
    project_id: UUID
    parent_id: UUID | None
    node_type: NodeType
    exam_kind: ExamKind | None
    sort_order: int
    title: str
    section_purpose: str | None
    goal_role: GoalRole | None
    target_level: TargetOutcome | None
    is_in_current_program: bool
    needs_material: bool
    is_archived: bool
    origin_kind: OriginKind
    origin_note: str | None
    origin_material_id: UUID | None
    created_at: datetime
    updated_at: datetime


class ProgramState(ApiModel):
    nodes: list[ProgramNodeRead]
    revision: int


class ReferenceAnswerStatus(StrEnum):
    MISSING = "missing"
    AUTO_MATCHED = "auto_matched"
    CONFIRMED = "confirmed"
    NEEDS_REVIEW = "needs_review"
    MANUAL = "manual"


class ReferenceAnswerRead(ApiModel):
    project_id: UUID
    program_node_id: UUID
    text: str
    origin_kind: ReferenceAnswerOrigin
    match_method: ReferenceAnswerMatchMethod
    matched_title: str | None
    is_confirmed: bool
    is_active: bool
    revision: int
    source_label: str | None
    source_material_id: UUID | None
    source_page_from: int | None
    source_page_to: int | None
    source_only: bool = False
    created_at: datetime
    updated_at: datetime


class ReferenceAnswerAttachmentRead(ApiModel):
    id: UUID
    program_node_id: UUID
    file_name: str
    media_type: str
    size_bytes: int
    created_at: datetime


class ReferenceAnswerSlot(ApiModel):
    project_id: UUID
    node_id: UUID
    node_title: str
    status: ReferenceAnswerStatus
    answer: ReferenceAnswerRead | None


class ReferenceAnswerWrite(ApiModel):
    expected_revision: int | None = Field(default=None, ge=0)
    text: str = Field(min_length=1, max_length=1_000_000)
    source_label: str | None = Field(default=None, max_length=200)

    @field_validator("text")
    @classmethod
    def strip_answer_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Эталонный ответ не может быть пустым")
        return value

    @field_validator("source_label")
    @classmethod
    def strip_source_label(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None


class ReferenceAnswerConfirm(ApiModel):
    expected_revision: int = Field(ge=0)


class ReferenceAnswerImportWrite(ApiModel):
    raw_text: str = Field(min_length=1, max_length=1_000_000)
    source_label: str | None = Field(default=None, max_length=200)

    @field_validator("raw_text")
    @classmethod
    def strip_import_text(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Вставьте текст эталонных ответов")
        return stripped

    @field_validator("source_label")
    @classmethod
    def strip_import_source_label(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None


class ReferenceAnswerImportIssue(ApiModel):
    heading: str
    preview: str | None = None
    candidate_node_ids: list[UUID] = Field(default_factory=list)


class CoverageMapRow(ApiModel):
    node_id: UUID
    parent_id: UUID | None
    node_type: NodeType
    exam_kind: ExamKind | None
    title: str
    sort_order: int
    is_in_current_program: bool
    target_level: TargetOutcome | None
    answer_status: ReferenceAnswerStatus | None
    answer_preview: str | None
    answer_revision: int | None


class CoverageMapTotals(ApiModel):
    study_nodes: int
    with_answer: int
    confirmed: int
    needs_review: int
    missing: int


class CoverageMapRead(ApiModel):
    project_id: UUID
    program_revision: int
    rows: list[CoverageMapRow]
    totals: CoverageMapTotals


class ReferenceAnswerImportResult(ApiModel):
    created: int
    skipped_existing: list[UUID]
    ambiguous: list[ReferenceAnswerImportIssue]
    unmatched_sections: list[ReferenceAnswerImportIssue]
    empty_sections: list[str]
    coverage_map: CoverageMapRead


class LatestUndoableAction(ApiModel):
    sequence: int
    action_type: str
    target_title: str
    created_at: datetime


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
    program: ProgramState
    latest_undoable_action: LatestUndoableAction | None


class ProjectSummary(ApiModel):
    id: UUID
    template_key: TemplateKey
    workspace_variant: WorkspaceVariant
    status: ProjectStatus
    name: str
    description: str | None
    icon: ProjectIcon | None
    color: int | None
    sort_order: int
    deadline: date | None
    status_changed_at: datetime | None
    updated_at: datetime


class ProjectStats(ApiModel):
    """Сводка для карточки проекта на главном экране.

    `None` означает «метрика не считается для этого типа проекта»: по FR-P3 она
    не показывается и не подменяется нулём. Ноль здесь — настоящий ноль.
    """

    project_id: UUID
    program_nodes: int | None
    reference_answers: int | None
    materials: int
    material_pages: int | None
    last_activity_at: datetime | None


class ProjectDetail(ApiModel):
    project: ProjectRead
    goal_passport: GoalPassportRead | None
    program: ProgramState
    workspace_state: WorkspaceStateRead | None
    latest_undoable_action: LatestUndoableAction | None


class ProjectSettingsResult(ApiModel):
    project: ProjectRead
    goal_passport: GoalPassportRead


class ProgramChangeResult(ApiModel):
    changed_node: ProgramNodeRead | None
    program: ProgramState
    latest_undoable_action: LatestUndoableAction | None
    draft_revision: int | None


class ActionUndoResult(ApiModel):
    undone_action_type: str
    program: ProgramState | None
    draft_revision: int | None
    latest_undoable_action: LatestUndoableAction | None


class ExamImportCounts(ApiModel):
    tickets: int = 0
    questions: int = 0
    tasks: int = 0


class ExamImportResult(ApiModel):
    revision: int
    counts: ExamImportCounts
    warnings: list[str]
    has_duplicates: bool
    program: ProgramState
    latest_undoable_action: LatestUndoableAction | None
