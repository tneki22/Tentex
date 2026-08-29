"""Pydantic-схемы входа и результата для каждого Tool.

Одна схема на Tool — вход валидируется до выполнения, результат до сохранения
(AI-CHATS.md §17.2). Здесь только реально реализованный `search_project_materials`;
у заблокированных specs (`registry.py`) схемы не нужны — обходом их не вызвать.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ToolApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MaterialSearchInput(ToolApiModel):
    query: str = Field(min_length=1, max_length=300)
    node_id: UUID | None = None
    limit: int = Field(default=10, ge=1, le=10)


class MaterialSearchResultItem(ToolApiModel):
    fragment_id: UUID
    material_id: UUID
    material_name: str
    block_title: str | None
    page_from: int
    page_to: int
    excerpt: str
    already_bound: bool


class MaterialSearchOutput(ToolApiModel):
    items: list[MaterialSearchResultItem]
