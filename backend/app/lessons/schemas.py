from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.models import (
    LessonBasis,
    LessonBlockKind,
    LessonBlockOrigin,
    LessonNoteVariant,
    LessonRefRole,
    LessonStatus,
    SourceRole,
)
from app.projects.schemas import LatestUndoableAction


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)


class LessonSummaryRead(ApiModel):
    id: UUID
    title: str
    status: LessonStatus
    duration_minutes: int | None
    program_node_ids: list[UUID]
    needs_review: bool
    updated_at: datetime


class LessonsOverviewRead(ApiModel):
    lessons: list[LessonSummaryRead]


class LessonSourceRangeRead(ApiModel):
    """Диапазон темы в одном источнике: из оглавления и после уточнения границ."""

    material_id: UUID
    source_name: str
    source_role: SourceRole
    priority: int
    is_parsed: bool
    outline_page_from: int
    outline_page_to: int
    page_from: int
    page_to: int
    starts_at_heading: bool
    ends_mid_page: bool
    default_selected: bool


class LessonTopicSourcesRead(ApiModel):
    program_node_id: UUID
    ranges: list[LessonSourceRangeRead]


class LessonQuickWrite(ApiModel):
    program_node_id: UUID
    # Пусто — «Быстрый урок» по первому основному источнику; список — «Из источников».
    material_ids: list[UUID] | None = None


class LessonManualWrite(ApiModel):
    program_node_id: UUID


class LessonBlockWrite(ApiModel):
    expected_revision: int = Field(ge=1)
    operation: str
    block_id: UUID | None = None
    after_block_id: UUID | None = None
    material_id: UUID | None = None
    page_from: int | None = Field(default=None, ge=1)
    page_to: int | None = Field(default=None, ge=1)
    variant: LessonNoteVariant = LessonNoteVariant.TEXT


class LessonNoteWrite(ApiModel):
    expected_revision: int = Field(ge=1)
    body_md: str = Field(max_length=100_000)
    variant: LessonNoteVariant | None = None


class LessonUpdateWrite(ApiModel):
    title: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)
    ] | None = None
    status: LessonStatus | None = None
    expected_revision: int = Field(ge=1)


class LessonRefRead(ApiModel):
    id: UUID
    role: LessonRefRole
    material_id: UUID | None
    source_name: str
    source_role: SourceRole | None
    material_revision: int | None
    page_from: int
    page_to: int
    from_fragment_id: UUID | None
    to_fragment_id: UUID | None
    region_bbox: list[float] | None
    always_pages: bool
    is_available: bool
    is_parsed: bool
    low_quality_pages: list[int]


class LessonBlockRead(ApiModel):
    id: UUID
    sort_order: int
    kind: LessonBlockKind
    variant: LessonNoteVariant | None
    body_md: str | None
    origin: LessonBlockOrigin
    basis: LessonBasis | None
    bound_program_node_id: UUID | None
    refs: list[LessonRefRead]


class LessonTopicRead(ApiModel):
    program_node_id: UUID
    title_snapshot: str
    current_title: str | None
    needs_review: bool


class LessonRead(ApiModel):
    id: UUID
    project_id: UUID
    title: str
    goal: str | None
    status: LessonStatus
    duration_minutes: int | None
    revision: int
    needs_review: bool
    # Последнее действие журнала — создание именно этого урока: «Отменить» доступно.
    undo_sequence: int | None
    topics: list[LessonTopicRead]
    blocks: list[LessonBlockRead]
    created_at: datetime
    updated_at: datetime


class LessonChangeResult(ApiModel):
    lesson: LessonRead
    latest_undoable_action: LatestUndoableAction | None
