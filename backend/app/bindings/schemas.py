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


class AnswersLinkRead(ApiModel):
    """Отчёт автопривязки файла эталонных ответов: что легло, что не нашлось."""

    linked_sections: int
    linked_fragments: int
    created_answers: int
    updated_answers: int
    kept_answers: int
    unmatched_headings: list[str]
    duplicate_headings: list[str]


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
    quality: PageQuality
    status: BindingStatus
    mechanism: BindingMechanism
    created_at: datetime
    updated_at: datetime


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
