from datetime import datetime
from typing import Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models import BindingMechanism, BindingStatus, PageQuality
from app.projects.schemas import LatestUndoableAction


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)


class SearchHighlightRead(ApiModel):
    start: int
    end: int


class SearchResultRead(ApiModel):
    fragment_ids: list[UUID]
    material_id: UUID
    material_name: str
    block_id: UUID
    block_title: str | None
    page_from: int
    page_to: int
    quality: PageQuality
    text: str
    highlights: list[SearchHighlightRead]
    already_bound: bool = False


class HeadingSuggestionCandidateRead(ApiModel):
    node_id: UUID
    node_title: str
    score: float


class HeadingSuggestionRead(ApiModel):
    """Заголовок без уверенного вопроса: показываем кандидатов, решает пользователь."""

    anchor_fragment_id: UUID
    heading: str
    preview: str | None = None
    page_from: int
    candidates: list[HeadingSuggestionCandidateRead]


class AnswersLinkRead(ApiModel):
    """Отчёт автопривязки файла эталонных ответов: что легло, что не нашлось."""

    linked_sections: int
    linked_fragments: int
    created_answers: int
    updated_answers: int
    restored_answers: int
    unchanged_answers: int
    preserved_answers: int
    numbered_sections: int = 0
    extra_sections: int = 0
    ordinal_rejected_reason: str | None = None
    fuzzy_headings: list[str] = Field(default_factory=list)
    unmatched_headings: list[str]
    duplicate_headings: list[str]
    suggestions: list[HeadingSuggestionRead] = Field(default_factory=list)
    expected_questions: int = 0
    matched_node_ids: list[UUID] = Field(default_factory=list)
    available_node_ids: list[UUID] = Field(default_factory=list)
    unavailable_node_ids: list[UUID] = Field(default_factory=list)
    missing_node_ids: list[UUID] = Field(default_factory=list)
    ambiguous_sections: list[str] = Field(default_factory=list)
    ambiguous_pages: list[int] = Field(default_factory=list)
    complete: bool = False


class AnswersLinkProgressRead(ApiModel):
    phase: str
    completed: int
    total: int
    phase_completed: int = 0
    phase_total: int = 0


class AnswersHeadingResolveWrite(ApiModel):
    anchor_fragment_id: UUID
    program_node_id: UUID


class ReindexResult(ApiModel):
    material_id: UUID
    indexed_fragments: int


class BindingFragmentRead(ApiModel):
    id: UUID
    project_id: UUID
    program_node_id: UUID
    node_title: str
    fragment_id: UUID
    material_id: UUID
    material_name: str
    block_id: UUID | None
    page_number: int
    text: str
    bbox: list[float]
    element_kind: str
    asset_label: str | None = None
    quality: PageQuality
    status: BindingStatus
    mechanism: BindingMechanism
    created_at: datetime
    updated_at: datetime


class BindingBulkRemoveWrite(ApiModel):
    material_id: UUID
    page_number: int | None = None


class BindingCreateWrite(ApiModel):
    program_node_id: UUID
    fragment_ids: list[UUID] = Field(default_factory=list)
    block_id: UUID | None = None
    mechanism: BindingMechanism = BindingMechanism.MANUAL

    @model_validator(mode="after")
    def exactly_one_source(self) -> Self:
        has_fragments = len(self.fragment_ids) > 0
        has_block = self.block_id is not None
        if has_fragments == has_block:
            raise ValueError("Укажите либо fragment_ids, либо block_id, но не оба сразу")
        return self


class BindingChangeResult(ApiModel):
    bindings: list[BindingFragmentRead]
    latest_undoable_action: LatestUndoableAction | None


class NodeBindingSummary(ApiModel):
    program_node_id: UUID
    fragment_count: int
    material_count: int
    worst_quality: PageQuality | None


class AffectedProjectPreview(ApiModel):
    project_id: UUID
    project_name: str
    nodes_losing_material: list[str]


class MaterialBindingImpact(ApiModel):
    binding_count: int
    affected_projects: list[AffectedProjectPreview]


class PageCorrectionBindings(ApiModel):
    transferred: int
    orphaned: list[UUID]
