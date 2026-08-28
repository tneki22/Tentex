from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from app.bindings.schemas import AffectedProjectPreview
from app.models import (
    BlockClass,
    MaterialSourceKind,
    MaterialState,
    PageQuality,
    ParserMode,
    ProcessingStage,
    ProcessingTaskState,
    RecognitionSource,
    SourceRole,
)
from app.projects.schemas import ProgramChangeResult

NonBlank = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)


class MaterialPurpose(StrEnum):
    EXAM_STRUCTURE = "exam_structure"
    REFERENCE_ANSWERS = "reference_answers"
    STUDY_SOURCE = "study_source"


class ExamMaterialSlot(StrEnum):
    QUESTION_LIST = "question_list"
    QUESTION_ANSWERS = "question_answers"
    TASK_LIST = "task_list"
    TASK_ANSWERS = "task_answers"


class MaterialUpdate(ApiModel):
    display_name: NonBlank | None = None
    source_role: SourceRole | None = None
    priority: int | None = Field(default=None, ge=0)
    instruction: str | None = None
    purposes: list[MaterialPurpose] | None = None
    exam_slot: ExamMaterialSlot | None = None
    replace_reference_answers: bool = False

    @field_validator("purposes")
    @classmethod
    def unique_purposes(
        cls, purposes: list[MaterialPurpose] | None
    ) -> list[MaterialPurpose] | None:
        if purposes is None:
            return None
        return list(dict.fromkeys(purposes)) or [MaterialPurpose.STUDY_SOURCE]

    @model_validator(mode="after")
    def replacement_requires_answers_purpose(self) -> "MaterialUpdate":
        if self.replace_reference_answers and (
            self.purposes is None
            or MaterialPurpose.REFERENCE_ANSWERS not in self.purposes
        ):
            raise ValueError(
                "Подтверждение замены допустимо только для файла эталонных ответов"
            )
        return self


class TextMaterialCreate(ApiModel):
    name: NonBlank = "Вставленный текст.txt"
    text: NonBlank
    source_role: SourceRole = SourceRole.ADDITIONAL
    purposes: list[MaterialPurpose] = Field(default_factory=lambda: [MaterialPurpose.STUDY_SOURCE])
    exam_slot: ExamMaterialSlot | None = None


class ExternalMaterialCreate(ApiModel):
    kind: Literal["url", "youtube"]
    url: Annotated[str, StringConstraints(strip_whitespace=True, min_length=8, max_length=2048)]
    source_role: SourceRole = SourceRole.ADDITIONAL
    purposes: list[MaterialPurpose] = Field(default_factory=lambda: [MaterialPurpose.STUDY_SOURCE])
    exam_slot: ExamMaterialSlot | None = None


ProcessingScope = Literal["all", "needs_review", "range"]


class ProcessingStart(ApiModel):
    parser_mode: ParserMode = ParserMode.FAST
    scope: ProcessingScope = "all"
    page_from: int | None = Field(default=None, ge=1)
    page_to: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def range_is_complete(self) -> "ProcessingStart":
        if self.scope == "range":
            if self.page_from is None or self.page_to is None:
                raise ValueError("Для диапазона нужны первая и последняя страница")
            if self.page_from > self.page_to:
                raise ValueError("Первая страница диапазона больше последней")
        elif self.page_from is not None or self.page_to is not None:
            raise ValueError("Диапазон задаётся только вместе с областью «Диапазон»")
        return self


class ProcessingTaskRead(ApiModel):
    id: UUID
    state: ProcessingTaskState
    stage: ProcessingStage
    parser_mode: ParserMode
    done: int
    total: int
    diagnostics: list[str]
    error: str | None
    created_at: datetime
    updated_at: datetime


class MaterialRead(ApiModel):
    id: UUID
    original_name: str
    display_name: str
    media_type: str
    source_kind: MaterialSourceKind
    source_url: str | None
    retrieved_at: datetime | None
    size_bytes: int
    page_count: int | None
    source_role: SourceRole
    priority: int
    instruction: str | None
    purposes: list[MaterialPurpose]
    exam_slot: ExamMaterialSlot | None
    status: MaterialState
    parser_mode: ParserMode | None
    active_parse_revision: int
    scan_page_count: int
    ocr_low_page_count: int
    estimated_seconds: int | None
    outline: list[dict[str, object]]
    diagnostics: list[str]
    error: str | None
    task: ProcessingTaskRead | None
    attached_at: datetime
    created_at: datetime
    updated_at: datetime


class FragmentRead(ApiModel):
    id: UUID
    block_id: UUID
    sort_order: int
    text: str
    bbox: list[float]
    element_kind: str
    # Путь показывать наружу незачем, важен сам факт исходного выреза.
    has_asset: bool = False
    structure_level: int | None
    degraded_structure: bool
    quality: PageQuality
    recognition_source: RecognitionSource
    confidence: float | None = None
    # Границы сегмента у расшифровки аудио и субтитров; у остальных источников None.
    time_from: float | None = None
    time_to: float | None = None


class BlockRead(ApiModel):
    id: UUID
    sort_order: int
    title: str | None
    block_class: BlockClass
    service_reason: str | None
    page_from: int
    page_to: int


class PageRead(ApiModel):
    id: UUID
    page_number: int
    width: float
    height: float
    text: str
    markdown: str
    quality: PageQuality
    confidence: float | None
    reviewed_at: datetime | None
    diagnostics: list[str]
    fragments: list[FragmentRead]
    blocks: list[BlockRead]


class PageTextUpdate(ApiModel):
    text: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2_000_000)
    ]
    expected_revision: int | None = Field(default=None, ge=1)
    expected_source_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class LibraryUsageRead(ApiModel):
    project_id: UUID
    project_name: str
    project_status: str
    display_name: str
    source_role: SourceRole
    purposes: list[MaterialPurpose]
    exam_slot: ExamMaterialSlot | None


class LibraryMaterialRead(ApiModel):
    id: UUID
    original_name: str
    media_type: str
    source_kind: MaterialSourceKind
    source_url: str | None
    size_bytes: int
    page_count: int | None
    status: MaterialState
    parser_mode: ParserMode | None
    native_page_count: int
    ocr_page_count: int
    ocr_low_page_count: int
    block_count: int
    fragment_count: int
    sha256: str
    created_at: datetime
    usage: list[LibraryUsageRead]


MaterialPresentationKind = Literal[
    "pdf", "image", "document", "plain_text", "web", "youtube", "audio"
]
OutlineSource = Literal["embedded", "recognized", "none"]


class LibraryMaterialCapabilities(ApiModel):
    """Что можно делать с этим материалом. Выводится из вида источника и данных,
    а не хранится отдельными флагами: иначе они разъезжаются с реальностью."""

    can_compare: bool
    can_view_original: bool
    can_edit_text: bool
    can_run_ocr: bool
    can_refresh_source: bool
    has_outline: bool
    has_timeline: bool


class OutlineItem(ApiModel):
    level: int
    title: str
    page: int


class PageStateRead(ApiModel):
    page_number: int
    quality: PageQuality
    reviewed_at: datetime | None


class MaterialRevisionRead(ApiModel):
    revision: int
    origin: Literal[
        "imported", "parse", "manual_edit", "ai_cleanup", "source_refresh", "restore"
    ]
    parser_mode: ParserMode | None
    parent_revision: int | None
    scope: dict[str, object]
    summary: dict[str, object]
    created_at: datetime
    is_current: bool


class LibraryMaterialDetailRead(LibraryMaterialRead):
    presentation_kind: MaterialPresentationKind
    capabilities: LibraryMaterialCapabilities
    outline: list[OutlineItem]
    outline_source: OutlineSource
    page_states: list[PageStateRead]
    active_parse_revision: int
    parser_mode: ParserMode | None
    scan_page_count: int
    estimated_seconds: int | None
    diagnostics: list[str]
    error: str | None
    task: ProcessingTaskRead | None
    retrieved_at: datetime | None
    updated_at: datetime


class LibraryMaterialAttachWrite(ApiModel):
    project_id: UUID
    display_name: NonBlank | None = None
    source_role: SourceRole = SourceRole.ADDITIONAL
    purposes: list[MaterialPurpose] = Field(
        default_factory=lambda: [MaterialPurpose.STUDY_SOURCE]
    )
    exam_slot: ExamMaterialSlot | None = None


class LibrarySearchHit(ApiModel):
    fragment_id: UUID
    page_number: int
    block_title: str | None
    bbox: list[float]
    text: str
    rank: float


class LibrarySearchResult(ApiModel):
    query: str
    revision: int
    hits: list[LibrarySearchHit]


class SourceRefreshResult(ApiModel):
    material: LibraryMaterialDetailRead
    revision: int
    changed: bool


class MaterialDeletePreview(ApiModel):
    material: LibraryMaterialRead
    active_task: bool
    reference_answer_count: int
    binding_count: int
    affected_projects: list[AffectedProjectPreview]


class PageCorrectionRead(ApiModel):
    page: PageRead
    transferred_bindings: int
    orphaned_binding_ids: list[UUID]


class ExamProgramPreviewNode(ApiModel):
    node_type: str
    exam_kind: str
    title: str
    depth: int


class ExamProgramPreview(ApiModel):
    material_id: UUID
    material_name: str
    counts: dict[str, int]
    warnings: list[str]
    has_duplicates: bool
    nodes: list[ExamProgramPreviewNode]


class ExamProgramImportWrite(ApiModel):
    expected_program_revision: int = Field(ge=0)
    dedupe_duplicates: bool = False


class ExamProgramDraftImportWrite(ApiModel):
    expected_draft_revision: int = Field(ge=0)
    expected_program_revision: int = Field(ge=0)
    dedupe_duplicates: bool = False


class ExamCompositeDraftImportWrite(ApiModel):
    """Атомарный импорт из независимых слотов «список вопросов» / «список задач»:

    один или оба сразу. Ревизия Программы увеличивается один раз на весь вызов.
    """

    expected_draft_revision: int = Field(ge=0)
    expected_program_revision: int = Field(ge=0)
    question_material_id: UUID | None = None
    task_material_id: UUID | None = None
    dedupe_duplicates: bool = False

    @model_validator(mode="after")
    def at_least_one_material(self) -> "ExamCompositeDraftImportWrite":
        if self.question_material_id is None and self.task_material_id is None:
            raise ValueError("Нужен хотя бы один список: вопросов или задач")
        return self


class ExamCompositeDraftImportResult(ApiModel):
    change: ProgramChangeResult
    counts: dict[str, int]
    warnings: list[str]


class MaterialAnswerImportResult(ApiModel):
    created: int
    skipped_existing: int
    unmatched_sections: list[str]
    ambiguous_sections: list[str]
    empty_sections: list[str]
