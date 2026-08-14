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
    SourceRole,
)

NonBlank = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)


class MaterialPurpose(StrEnum):
    EXAM_STRUCTURE = "exam_structure"
    REFERENCE_ANSWERS = "reference_answers"
    STUDY_SOURCE = "study_source"


class MaterialUpdate(ApiModel):
    display_name: NonBlank | None = None
    source_role: SourceRole | None = None
    priority: int | None = Field(default=None, ge=0)
    instruction: str | None = None
    purposes: list[MaterialPurpose] | None = None
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


class ExternalMaterialCreate(ApiModel):
    kind: Literal["url", "youtube"]
    url: Annotated[str, StringConstraints(strip_whitespace=True, min_length=8, max_length=2048)]
    source_role: SourceRole = SourceRole.ADDITIONAL
    purposes: list[MaterialPurpose] = Field(default_factory=lambda: [MaterialPurpose.STUDY_SOURCE])


class ProcessingStart(ApiModel):
    parser_mode: ParserMode = ParserMode.FAST


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
    # Только у element_kind == "image": путь показывать наружу незачем, важен сам факт.
    has_asset: bool = False
    structure_level: int | None
    degraded_structure: bool
    quality: PageQuality


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


class LibraryMaterialRead(ApiModel):
    id: UUID
    original_name: str
    media_type: str
    source_kind: MaterialSourceKind
    source_url: str | None
    size_bytes: int
    page_count: int | None
    status: MaterialState
    native_page_count: int
    ocr_page_count: int
    ocr_low_page_count: int
    block_count: int
    fragment_count: int
    sha256: str
    created_at: datetime
    usage: list[LibraryUsageRead]


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
    nodes: list[ExamProgramPreviewNode]


class ExamProgramImportWrite(ApiModel):
    expected_program_revision: int = Field(ge=0)


class ExamProgramDraftImportWrite(ApiModel):
    expected_draft_revision: int = Field(ge=0)
    expected_program_revision: int = Field(ge=0)


class MaterialCapabilities(ApiModel):
    fast_available: bool
    fast_label: str
    textbook_available: bool
    textbook_reason: str
    cloud_reason: str = "Облачные режимы появятся на этапе 7"


class MaterialAnswerImportResult(ApiModel):
    created: int
    skipped_existing: int
    unmatched_sections: list[str]
    ambiguous_sections: list[str]
    empty_sections: list[str]
