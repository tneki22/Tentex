from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models import (
    EmbeddingBackendKind,
    PageQuality,
    RetrievalIndexState,
    RetrievalPreset,
)
from app.retrieval.chunking import (
    DEFAULT_MAX_TOKENS,
    DEFAULT_OVERLAP_TOKENS,
    DEFAULT_TARGET_TOKENS,
)


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)


class SearchStrategy(StrEnum):
    LEXICAL = "lexical"
    SEMANTIC = "semantic"
    HYBRID = "hybrid"


class RetrievalScope(StrEnum):
    LINKED_TOPIC = "linked_topic"
    TOPIC_PROJECT = "topic_project"
    PROJECT = "project"
    SELECTED_MATERIALS = "selected_materials"
    # Вся готовая Библиотека; с project_id — кроме уже подключённых к проекту:
    # так подбираются материалы, которых в проекте ещё нет.
    LIBRARY = "library"


class RetrievalDepth(StrEnum):
    FAST = "fast"
    EXHAUSTIVE = "exhaustive"


class KnowledgePolicy(StrEnum):
    SOURCES_ONLY = "sources_only"
    ALLOW_MODEL = "allow_model"


class RetrievalSearchWrite(ApiModel):
    query: str = Field(min_length=1, max_length=2_000)
    strategy: SearchStrategy = SearchStrategy.HYBRID
    scope: RetrievalScope = RetrievalScope.PROJECT
    project_id: UUID | None = None
    node_id: UUID | None = None
    material_ids: list[UUID] = Field(default_factory=list, max_length=100)
    limit: Annotated[int, Field(ge=1, le=50)] = 10

    @model_validator(mode="after")
    def validate_scope(self):
        if self.scope == RetrievalScope.SELECTED_MATERIALS and not self.material_ids:
            raise ValueError("Для выбранных материалов нужен хотя бы один material_id")
        if (
            self.scope not in {RetrievalScope.SELECTED_MATERIALS, RetrievalScope.LIBRARY}
            and self.project_id is None
        ):
            raise ValueError("Для этой области нужен project_id")
        if (
            self.scope in {RetrievalScope.LINKED_TOPIC, RetrievalScope.TOPIC_PROJECT}
            and not self.node_id
        ):
            raise ValueError("Для области темы нужен node_id")
        return self


class RetrievalLocatorRead(ApiModel):
    chunk_id: UUID
    material_id: UUID
    material_name: str
    block_id: UUID | None
    block_title: str | None
    page_from: int | None
    page_to: int | None
    fragment_ids: list[UUID]
    typst_path: str | None = None
    line_from: int | None = None
    line_to: int | None = None


class RetrievalHitRead(ApiModel):
    locator: RetrievalLocatorRead
    text: str
    quality: PageQuality | None
    score: float
    signals: list[Literal["lexical", "semantic"]]
    warning: str | None = None


class RetrievalSearchRead(ApiModel):
    query: str
    strategy: SearchStrategy
    index_id: UUID | None
    degraded: bool
    degradation_reasons: list[str]
    results: list[RetrievalHitRead]


class EmbeddingProfileWrite(ApiModel):
    label: str = Field(min_length=1, max_length=100)
    backend_kind: EmbeddingBackendKind
    model_id: str = Field(min_length=1, max_length=300)
    model_revision: str | None = Field(default=None, max_length=100)
    provider_id: UUID | None = None
    batch_size: int = Field(default=32, ge=1, le=512)
    normalize: bool = True
    pooling: Literal["mean", "cls", "last_token"] = "mean"
    query_template: str = "{text}"
    document_template: str = "{text}"

    @model_validator(mode="after")
    def validate_backend(self):
        needs_provider = self.backend_kind == EmbeddingBackendKind.OPENAI_COMPATIBLE
        if needs_provider != (self.provider_id is not None):
            raise ValueError("provider_id нужен только OpenAI-совместимому профилю")
        if "{text}" not in self.query_template or "{text}" not in self.document_template:
            raise ValueError("Шаблоны должны содержать {text}")
        return self


class EmbeddingProfileRead(EmbeddingProfileWrite):
    id: UUID
    dimension: int | None
    installed: bool
    tested_at: datetime | None
    test_error: str | None
    created_at: datetime
    updated_at: datetime


class RetrievalIndexBuildWrite(ApiModel):
    profile_id: UUID
    preset: RetrievalPreset = RetrievalPreset.BALANCED
    chunk_target_tokens: int = Field(default=DEFAULT_TARGET_TOKENS, ge=64, le=2_048)
    chunk_max_tokens: int = Field(default=DEFAULT_MAX_TOKENS, ge=64, le=4_096)
    chunk_overlap_tokens: int = Field(default=DEFAULT_OVERLAP_TOKENS, ge=0, le=512)
    material_ids: list[UUID] = Field(default_factory=list, max_length=500)
    cloud_consent: bool = False

    @model_validator(mode="after")
    def validate_chunking(self):
        if self.chunk_max_tokens < self.chunk_target_tokens:
            raise ValueError("Максимум куска не может быть меньше цели")
        if self.chunk_overlap_tokens >= self.chunk_target_tokens:
            raise ValueError("Перекрытие должно быть меньше целевого размера")
        return self


class RetrievalIndexRead(ApiModel):
    id: UUID
    profile_id: UUID
    state: RetrievalIndexState
    preset: RetrievalPreset
    chunk_target_tokens: int
    chunk_max_tokens: int
    chunk_overlap_tokens: int
    chunk_count: int
    indexed_material_count: int
    material_count: int
    corpus_manifest: list[dict]
    diagnostics: list[str]
    error: str | None
    created_at: datetime
    completed_at: datetime | None
    activated_at: datetime | None


class RetrievalIndexBuildRead(ApiModel):
    index: RetrievalIndexRead
    job_id: UUID


class RetrievalIndexMaterialsWrite(ApiModel):
    material_ids: list[UUID] = Field(min_length=1, max_length=500)
    cloud_consent: bool = False


class RetrievalIndexMaterialsRead(ApiModel):
    job_ids: list[UUID]


class RetrievalSettingsWrite(ApiModel):
    default_profile_id: UUID | None = None
    preset: RetrievalPreset = RetrievalPreset.BALANCED
    expert_parameters: dict[str, int | float | bool | str] = Field(default_factory=dict)


class RetrievalSettingsRead(ApiModel):
    default_profile_id: UUID | None
    preset: RetrievalPreset
    expert_parameters: dict
    active_index: RetrievalIndexRead | None
    profiles: list[EmbeddingProfileRead]
    ready_materials: int
    total_ready_materials: int
    degraded: bool
    degradation_reasons: list[str]


class LocalModelRead(ApiModel):
    model_id: str
    label: str
    role: Literal["embedding", "reranker"]
    installed: bool
    installing: bool = False
    recommended_for: str


class BenchmarkCaseWrite(ApiModel):
    query: str = Field(min_length=1, max_length=2_000)
    relevant_material_ids: list[UUID] = Field(default_factory=list)
    relevant_locator_ids: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)


class BenchmarkRunRead(ApiModel):
    id: UUID
    index_id: UUID
    metrics: dict[str, float | int]
    case_count: int
    created_at: datetime


class ExhaustiveRunWrite(ApiModel):
    query: str = Field(min_length=1, max_length=2_000)
    scope: RetrievalScope = RetrievalScope.PROJECT
    node_id: UUID | None = None
    material_ids: list[UUID] = Field(default_factory=list, max_length=100)
    confirmed: bool = False

    @model_validator(mode="after")
    def validate_scope(self):
        if self.scope == RetrievalScope.SELECTED_MATERIALS and not self.material_ids:
            raise ValueError("Для выбранных материалов нужен хотя бы один material_id")
        if (
            self.scope in {RetrievalScope.LINKED_TOPIC, RetrievalScope.TOPIC_PROJECT}
            and not self.node_id
        ):
            raise ValueError("Для области темы нужен node_id")
        return self


class ExhaustiveRunRead(ApiModel):
    id: UUID
    job_id: UUID
    project_id: UUID
    session_id: UUID
    user_message_id: UUID | None
    final_message_id: UUID | None
    query: str
    scope: str
    corpus_manifest: list[dict]
    result: dict
    created_at: datetime
    completed_at: datetime | None
