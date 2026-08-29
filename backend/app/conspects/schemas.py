from datetime import datetime
from typing import Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

MAX_CONTENT_MARKDOWN_BYTES = 1_048_576


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)


class ConspectImageRead(ApiModel):
    id: UUID
    file_name: str
    media_type: str
    size_bytes: int
    created_at: datetime


class ConspectRead(ApiModel):
    project_id: UUID
    node_id: UUID
    content_markdown: str
    revision: int
    updated_at: datetime | None
    images: list[ConspectImageRead]


class ConspectWrite(ApiModel):
    content_markdown: str
    expected_revision: int = Field(ge=0)
    retained_image_ids: list[UUID] = Field(default_factory=list)

    @field_validator("content_markdown")
    @classmethod
    def _within_size_limit(cls, value: str) -> str:
        if len(value.encode("utf-8")) > MAX_CONTENT_MARKDOWN_BYTES:
            raise ValueError("Конспект больше 1 МиБ")
        return value

    @model_validator(mode="after")
    def _dedupe_retained_image_ids(self) -> Self:
        self.retained_image_ids = list(dict.fromkeys(self.retained_image_ids))
        return self


class ConspectSummaryEntry(ApiModel):
    node_id: UUID
    position: int
    title: str
    content_markdown: str
    revision: int
    updated_at: datetime


class ConspectSummaryRead(ApiModel):
    entries: list[ConspectSummaryEntry]
