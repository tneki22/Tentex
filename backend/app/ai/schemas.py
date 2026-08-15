from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

NonBlank = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
Modality = Literal["text", "speech"]
CatalogProfile = Literal["openrouter", "openai_compatible"]


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)


class AiModelSelection(ApiModel):
    provider_id: UUID
    model_id: NonBlank


class AiGlobalSettingsWrite(ApiModel):
    external_models_enabled: bool
    daily_limit_usd: Decimal | None = Field(default=None, ge=0)
    operation_limit_usd: Decimal | None = Field(default=None, ge=0)
    confirm_cost_usd: Decimal | None = Field(default=None, ge=0)
    confirm_input_tokens: int = Field(ge=0, le=10_000_000)
    usd_rub_rate: Decimal | None = Field(default=None, gt=0)
    usd_rub_rate_date: date | None = None


class AiProviderWrite(ApiModel):
    label: NonBlank
    catalog_profile: CatalogProfile = "openai_compatible"
    base_url: NonBlank
    api_key: str | None = Field(default=None, max_length=20_000)


class AiDefaultWrite(ApiModel):
    selection: AiModelSelection | None = None


class AiRoleWrite(ApiModel):
    enabled: bool
    provider_override_id: UUID | None = None
    model_override: str | None = Field(default=None, max_length=500)
    parameters: dict[str, object] = Field(default_factory=dict)


class AiProviderFavoritesWrite(ApiModel):
    provider_ids: list[UUID] = Field(max_length=100)


class AiModelFavoritesWrite(ApiModel):
    models: list[AiModelSelection] = Field(max_length=100)


class AiManualModelWrite(ApiModel):
    model_id: NonBlank
    display_name: NonBlank
    context_length: int | None = Field(default=None, gt=0)
    max_completion_tokens: int | None = Field(default=None, gt=0)
    supported_parameters: list[str] = Field(default_factory=list)
    input_modalities: list[str] = Field(default_factory=lambda: ["text"])
    output_modalities: list[str] = Field(default_factory=lambda: ["text"])
    reasoning: dict[str, object] = Field(default_factory=dict)
    default_parameters: dict[str, object] = Field(default_factory=dict)
    prompt_price_usd: Decimal | None = Field(default=None, ge=0)
    completion_price_usd: Decimal | None = Field(default=None, ge=0)
    knowledge_cutoff: str | None = None
    expiration_date: str | None = None


class AiCatalogModelWrite(ApiModel):
    model_id: NonBlank
    display_name: NonBlank
    context_length: int | None = Field(default=None, gt=0)
    max_completion_tokens: int | None = Field(default=None, gt=0)
    supported_parameters: list[str] = Field(default_factory=list)
    input_modalities: list[str] = Field(default_factory=list)
    output_modalities: list[str] = Field(default_factory=list)
    reasoning: dict[str, object] = Field(default_factory=dict)
    default_parameters: dict[str, object] = Field(default_factory=dict)
    prompt_price_usd: Decimal | None = Field(default=None, ge=0)
    completion_price_usd: Decimal | None = Field(default=None, ge=0)
    knowledge_cutoff: str | None = None
    expiration_date: str | None = None


class AiCatalogModelRead(AiCatalogModelWrite):
    is_added: bool


class AiProviderRead(ApiModel):
    id: UUID
    label: str
    catalog_profile: CatalogProfile
    base_url: str
    has_api_key: bool
    is_favorite: bool
    model_count: int
    last_test_status: str | None
    last_tested_at: datetime | None
    last_catalog_refresh_at: datetime | None
    updated_at: datetime


class AiModelRead(ApiModel):
    provider_id: UUID
    model_id: str
    display_name: str
    context_length: int | None
    max_completion_tokens: int | None
    supported_parameters: list[str]
    input_modalities: list[str]
    output_modalities: list[str]
    reasoning: dict[str, object]
    default_parameters: dict[str, object]
    manual_overrides: dict[str, object]
    prompt_price_usd: Decimal | None
    completion_price_usd: Decimal | None
    knowledge_cutoff: str | None
    expiration_date: str | None
    pricing_snapshot_at: datetime
    catalog_snapshot_at: datetime
    is_manually_added: bool
    favorite_order: int | None
    is_available: bool


class AiRoleRead(ApiModel):
    role: str
    title: str
    description: str
    modality: Modality
    enabled: bool
    provider_override_id: UUID | None
    model_override: str | None
    resolved_provider_id: UUID | None
    resolved_model: str | None
    model_source: str | None
    required_capabilities: list[str]
    parameters: dict[str, object]


class AiTodayUsage(ApiModel):
    input_tokens: int = 0
    output_tokens: int = 0
    actual_cost_usd: Decimal = Decimal("0")
    actual_cost_rub: Decimal = Decimal("0")
    cache_hits: int = 0


class AiSettingsRead(ApiModel):
    external_models_enabled: bool
    daily_limit_usd: Decimal | None
    operation_limit_usd: Decimal | None
    confirm_cost_usd: Decimal | None
    confirm_input_tokens: int
    usd_rub_rate: Decimal | None
    usd_rub_rate_date: date | None
    default_text: AiModelSelection | None
    default_speech: AiModelSelection | None
    providers: list[AiProviderRead]
    roles: list[AiRoleRead]
    models: list[AiModelRead]
    today_usage: AiTodayUsage


class AiProviderTestRead(ApiModel):
    status: Literal["connected"]
    model_count: int
    tested_at: datetime


class AiModelTestWrite(ApiModel):
    model_id: NonBlank


class AiModelTestRead(ApiModel):
    status: Literal["answered"]
    run_id: UUID
    duration_ms: int
    answer: str
    actual_model_id: str
    input_tokens: int
    output_tokens: int


class AiMessage(ApiModel):
    role: Literal["system", "user", "assistant"]
    content: str


class AiPreflight(ApiModel):
    role: str
    modality: Modality
    provider_id: UUID
    provider_label: str
    model_id: str
    model_source: str
    request_hash: str
    estimated_input_tokens: int
    estimated_output_tokens: int
    estimated_cost_usd: Decimal | None
    estimated_cost_rub: Decimal | None
    usd_rub_rate: Decimal | None
    usd_rub_rate_date: date | None
    cached: bool
    confirmation_required: bool
    confirmation_reasons: list[str]
    context_manifest: list[dict[str, Any]]


class AiUsage(ApiModel):
    input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0
    provider_cached_tokens: int = 0
    actual_cost_usd: Decimal | None = None
    actual_cost_rub: Decimal | None = None


class AiRunRead(ApiModel):
    id: UUID
    project_id: UUID | None
    provider_id: UUID | None
    provider_label_snapshot: str
    role: str
    modality: str
    status: str
    requested_model_id: str
    actual_model_id: str | None
    prompt_version: str
    request_hash: str
    context_manifest: list[dict[str, Any]]
    estimated_input_tokens: int
    estimated_output_tokens: int
    estimated_cost_usd: Decimal | None
    input_tokens: int | None
    output_tokens: int | None
    reasoning_tokens: int | None
    provider_cached_tokens: int | None
    actual_cost_usd: Decimal | None
    actual_cost_rub: Decimal | None
    usd_rub_rate_snapshot: Decimal | None
    usd_rub_rate_date: date | None
    provider_request_id: str | None
    cached_from_run_id: UUID | None
    duration_ms: int | None
    error_code: str | None
    created_at: datetime
    completed_at: datetime | None


class AiUsageGroup(ApiModel):
    key: str
    runs: int
    cache_hits: int
    input_tokens: int
    output_tokens: int
    actual_cost_usd: Decimal
    actual_cost_rub: Decimal


class AiUsageRead(ApiModel):
    groups: list[AiUsageGroup]
