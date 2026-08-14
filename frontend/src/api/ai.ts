import { ProjectApiError, request } from "./projects";

export type AiModality = "text" | "speech";
export type AiCatalogProfile = "openrouter" | "openai_compatible";
export type AiModelSource = "request" | "role_override" | "text_default" | "speech_default";
export type DecimalValue = number | `${number}`;

export type AiErrorCode =
  | "ai_disabled"
  | "ai_role_disabled"
  | "ai_credentials_missing"
  | "ai_model_not_configured"
  | "ai_capability_unsupported"
  | "ai_confirmation_required"
  | "ai_operation_limit"
  | "ai_daily_limit"
  | "ai_invalid_credentials"
  | "ai_rate_limited"
  | "ai_provider_unavailable"
  | "ai_timeout"
  | "ai_invalid_structured_output"
  | "ai_cancelled"
  | "ai_connection_not_configured"
  | "ai_base_url_invalid"
  | "ai_base_url_credentials_forbidden"
  | "ai_fx_snapshot_incomplete"
  | "ai_model_not_in_catalog"
  | "ai_model_modality_unsupported"
  | "ai_provider_not_found"
  | "ai_provider_in_use"
  | "ai_provider_label_exists"
  | "ai_role_selection_incomplete"
  | "ai_role_not_found"
  | "ai_role_parameters_invalid"
  | "ai_model_override_forbidden"
  | "ai_secret_mismatch";

export type AiApiError = ProjectApiError & { readonly code: AiErrorCode };

const AI_ERROR_CODES = new Set<AiErrorCode>([
  "ai_disabled", "ai_role_disabled", "ai_credentials_missing", "ai_model_not_configured",
  "ai_capability_unsupported", "ai_confirmation_required", "ai_operation_limit",
  "ai_daily_limit", "ai_invalid_credentials", "ai_rate_limited", "ai_provider_unavailable",
  "ai_timeout", "ai_invalid_structured_output", "ai_cancelled",
  "ai_connection_not_configured", "ai_base_url_invalid", "ai_base_url_credentials_forbidden",
  "ai_fx_snapshot_incomplete", "ai_model_not_in_catalog", "ai_model_modality_unsupported",
  "ai_provider_not_found", "ai_provider_in_use", "ai_provider_label_exists",
  "ai_role_selection_incomplete", "ai_role_not_found", "ai_role_parameters_invalid",
  "ai_model_override_forbidden", "ai_secret_mismatch",
]);

export function isAiApiError(error: unknown): error is AiApiError {
  return error instanceof ProjectApiError
    && error.code !== null
    && AI_ERROR_CODES.has(error.code as AiErrorCode);
}

export interface AiModelSelection {
  provider_id: string;
  model_id: string;
}

export interface AiProviderRead {
  id: string;
  label: string;
  catalog_profile: AiCatalogProfile;
  base_url: string;
  has_api_key: boolean;
  is_favorite: boolean;
  model_count: number;
  last_test_status: string | null;
  last_tested_at: string | null;
  last_catalog_refresh_at: string | null;
  updated_at: string;
}

export interface AiModelRead {
  provider_id: string;
  model_id: string;
  display_name: string;
  context_length: number | null;
  max_completion_tokens: number | null;
  supported_parameters: string[];
  input_modalities: string[];
  output_modalities: string[];
  reasoning: Record<string, unknown>;
  default_parameters: Record<string, unknown>;
  manual_overrides: Record<string, unknown>;
  prompt_price_usd: DecimalValue | null;
  completion_price_usd: DecimalValue | null;
  knowledge_cutoff: string | null;
  expiration_date: string | null;
  pricing_snapshot_at: string;
  catalog_snapshot_at: string;
  is_manually_added: boolean;
  favorite_order: number | null;
  is_available: boolean;
}

export interface AiRoleRead {
  role: string;
  title: string;
  description: string;
  modality: AiModality;
  enabled: boolean;
  provider_override_id: string | null;
  model_override: string | null;
  resolved_provider_id: string | null;
  resolved_model: string | null;
  model_source: Exclude<AiModelSource, "request"> | null;
  required_capabilities: string[];
  parameters: Record<string, unknown>;
}

export interface AiTodayUsage {
  input_tokens: number;
  output_tokens: number;
  actual_cost_usd: DecimalValue;
  actual_cost_rub: DecimalValue;
  cache_hits: number;
}

export interface AiSettingsRead {
  external_models_enabled: boolean;
  daily_limit_usd: DecimalValue | null;
  operation_limit_usd: DecimalValue | null;
  confirm_cost_usd: DecimalValue | null;
  confirm_input_tokens: number;
  usd_rub_rate: DecimalValue | null;
  usd_rub_rate_date: string | null;
  default_text: AiModelSelection | null;
  default_speech: AiModelSelection | null;
  providers: AiProviderRead[];
  roles: AiRoleRead[];
  models: AiModelRead[];
  today_usage: AiTodayUsage;
}

export interface AiPreflight {
  role: string;
  modality: AiModality;
  provider_id: string;
  provider_label: string;
  model_id: string;
  model_source: AiModelSource;
  request_hash: string;
  estimated_input_tokens: number;
  estimated_output_tokens: number;
  estimated_cost_usd: DecimalValue | null;
  estimated_cost_rub: DecimalValue | null;
  usd_rub_rate: DecimalValue | null;
  usd_rub_rate_date: string | null;
  cached: boolean;
  confirmation_required: boolean;
  confirmation_reasons: string[];
  context_manifest: Array<Record<string, unknown>>;
}

export interface AiUsage {
  input_tokens: number;
  output_tokens: number;
  reasoning_tokens: number;
  provider_cached_tokens: number;
  actual_cost_usd: DecimalValue | null;
  actual_cost_rub: DecimalValue | null;
}

export interface AiProviderTestRead {
  status: "connected";
  model_count: number;
  tested_at: string;
}

export interface AiModelTestRead {
  status: "answered";
  run_id: string;
  duration_ms: number;
}

export interface AiRunRead {
  id: string;
  project_id: string | null;
  provider_id: string | null;
  provider_label_snapshot: string;
  role: string;
  modality: string;
  status: string;
  requested_model_id: string;
  actual_model_id: string | null;
  prompt_version: string;
  request_hash: string;
  context_manifest: Array<Record<string, unknown>>;
  estimated_input_tokens: number;
  estimated_output_tokens: number;
  estimated_cost_usd: DecimalValue | null;
  input_tokens: number | null;
  output_tokens: number | null;
  reasoning_tokens: number | null;
  provider_cached_tokens: number | null;
  actual_cost_usd: DecimalValue | null;
  actual_cost_rub: DecimalValue | null;
  usd_rub_rate_snapshot: DecimalValue | null;
  usd_rub_rate_date: string | null;
  provider_request_id: string | null;
  cached_from_run_id: string | null;
  duration_ms: number | null;
  error_code: string | null;
  created_at: string;
  completed_at: string | null;
}

export interface AiUsageRead {
  groups: Array<{
    key: string;
    runs: number;
    cache_hits: number;
    input_tokens: number;
    output_tokens: number;
    actual_cost_usd: DecimalValue;
    actual_cost_rub: DecimalValue;
  }>;
}

export interface AiGlobalSettingsWrite {
  external_models_enabled: boolean;
  daily_limit_usd: DecimalValue | null;
  operation_limit_usd: DecimalValue | null;
  confirm_cost_usd: DecimalValue | null;
  confirm_input_tokens: number;
  usd_rub_rate: DecimalValue | null;
  usd_rub_rate_date: string | null;
}

export interface AiProviderWrite {
  label: string;
  catalog_profile: AiCatalogProfile;
  base_url: string;
  api_key?: string | null;
}

export interface AiManualModelWrite {
  model_id: string;
  display_name: string;
  context_length: number | null;
  max_completion_tokens: number | null;
  supported_parameters: string[];
  input_modalities: string[];
  output_modalities: string[];
  reasoning: Record<string, unknown>;
  default_parameters: Record<string, unknown>;
  prompt_price_usd: DecimalValue | null;
  completion_price_usd: DecimalValue | null;
  knowledge_cutoff: string | null;
  expiration_date: string | null;
}

export type AiCatalogModelWrite = AiManualModelWrite;

export interface AiCatalogModelRead extends AiCatalogModelWrite {
  is_added: boolean;
}

export interface AiRoleWrite {
  enabled: boolean;
  provider_override_id: string | null;
  model_override: string | null;
  parameters: Record<string, unknown>;
}

const AI_PATH = "/api/settings/ai";

export const getAiSettings = (signal?: AbortSignal): Promise<AiSettingsRead> =>
  request(AI_PATH, { signal });

export const updateAiSettings = (
  command: AiGlobalSettingsWrite,
  signal?: AbortSignal,
): Promise<AiSettingsRead> => request(AI_PATH, {
  method: "PUT", body: JSON.stringify(command), signal,
});

export const createAiProvider = (
  command: AiProviderWrite, signal?: AbortSignal,
): Promise<AiSettingsRead> => request(`${AI_PATH}/providers`, {
  method: "POST", body: JSON.stringify(command), signal,
});

export const updateAiProvider = (
  providerId: string, command: AiProviderWrite, signal?: AbortSignal,
): Promise<AiSettingsRead> => request(`${AI_PATH}/providers/${providerId}`, {
  method: "PUT", body: JSON.stringify(command), signal,
});

export const deleteAiProvider = (
  providerId: string, signal?: AbortSignal,
): Promise<AiSettingsRead> => request(`${AI_PATH}/providers/${providerId}`, {
  method: "DELETE", signal,
});

export const deleteAiCredential = (
  providerId: string, signal?: AbortSignal,
): Promise<void> => request(`${AI_PATH}/providers/${providerId}/credential`, {
  method: "DELETE", signal,
});

export const testAiProvider = (
  providerId: string, signal?: AbortSignal,
): Promise<AiProviderTestRead> => request(`${AI_PATH}/providers/${providerId}/test`, {
  method: "POST", signal,
});

export const searchAiModels = (
  providerId: string, signal?: AbortSignal,
): Promise<AiCatalogModelRead[]> => request(`${AI_PATH}/providers/${providerId}/models/search`, {
  method: "POST", signal,
});

export const addAiCatalogModel = (
  providerId: string, command: AiCatalogModelWrite, signal?: AbortSignal,
): Promise<AiSettingsRead> => request(`${AI_PATH}/providers/${providerId}/models`, {
  method: "POST", body: JSON.stringify(command), signal,
});

export const upsertManualAiModel = (
  providerId: string, command: AiManualModelWrite, signal?: AbortSignal,
): Promise<AiSettingsRead> => request(`${AI_PATH}/providers/${providerId}/models/manual`, {
  method: "PUT", body: JSON.stringify(command), signal,
});

export const testAiModel = (
  selection: AiModelSelection, signal?: AbortSignal,
): Promise<AiModelTestRead> => request(
  `${AI_PATH}/providers/${selection.provider_id}/models/test`,
  { method: "POST", body: JSON.stringify({ model_id: selection.model_id }), signal },
);

export const updateAiProviderFavorites = (
  providerIds: string[], signal?: AbortSignal,
): Promise<AiSettingsRead> => request(`${AI_PATH}/provider-favorites`, {
  method: "PUT", body: JSON.stringify({ provider_ids: providerIds }), signal,
});

export const updateAiModelFavorites = (
  models: AiModelSelection[], signal?: AbortSignal,
): Promise<AiSettingsRead> => request(`${AI_PATH}/model-favorites`, {
  method: "PUT", body: JSON.stringify({ models }), signal,
});

export const updateAiDefault = (
  modality: AiModality, selection: AiModelSelection | null, signal?: AbortSignal,
): Promise<AiSettingsRead> => request(`${AI_PATH}/defaults/${modality}`, {
  method: "PUT", body: JSON.stringify({ selection }), signal,
});

export const updateAiRole = (
  role: string, command: AiRoleWrite, signal?: AbortSignal,
): Promise<AiSettingsRead> => request(`${AI_PATH}/roles/${encodeURIComponent(role)}`, {
  method: "PUT", body: JSON.stringify(command), signal,
});

function filterQuery(filters: {
  projectId?: string;
  providerId?: string;
  modelId?: string;
  role?: string;
  status?: string;
  from?: string;
  to?: string;
  groupBy?: "role" | "provider" | "model";
}): string {
  const query = new URLSearchParams();
  if (filters.projectId) query.set("project_id", filters.projectId);
  if (filters.providerId) query.set("provider_id", filters.providerId);
  if (filters.modelId) query.set("model_id", filters.modelId);
  if (filters.role) query.set("role", filters.role);
  if (filters.status) query.set("status", filters.status);
  if (filters.from) query.set("from", filters.from);
  if (filters.to) query.set("to", filters.to);
  if (filters.groupBy) query.set("group_by", filters.groupBy);
  const value = query.toString();
  return value ? `?${value}` : "";
}

export const listAiRuns = (
  filters: Parameters<typeof filterQuery>[0] = {}, signal?: AbortSignal,
): Promise<AiRunRead[]> => request(`${AI_PATH}/runs${filterQuery(filters)}`, { signal });

export const getAiUsage = (
  filters: Parameters<typeof filterQuery>[0] = {}, signal?: AbortSignal,
): Promise<AiUsageRead> => request(`${AI_PATH}/usage${filterQuery(filters)}`, { signal });
