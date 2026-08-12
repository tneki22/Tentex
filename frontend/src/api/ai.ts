import { ProjectApiError, request } from "./projects";

export type AiModality = "text" | "speech";
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
  | "ai_role_not_found"
  | "ai_role_parameters_invalid"
  | "ai_model_override_forbidden"
  | "ai_secret_mismatch";

export type AiApiError = ProjectApiError & { readonly code: AiErrorCode };

const AI_ERROR_CODES = new Set<AiErrorCode>([
  "ai_disabled",
  "ai_role_disabled",
  "ai_credentials_missing",
  "ai_model_not_configured",
  "ai_capability_unsupported",
  "ai_confirmation_required",
  "ai_operation_limit",
  "ai_daily_limit",
  "ai_invalid_credentials",
  "ai_rate_limited",
  "ai_provider_unavailable",
  "ai_timeout",
  "ai_invalid_structured_output",
  "ai_cancelled",
  "ai_connection_not_configured",
  "ai_base_url_invalid",
  "ai_base_url_credentials_forbidden",
  "ai_fx_snapshot_incomplete",
  "ai_model_not_in_catalog",
  "ai_role_not_found",
  "ai_role_parameters_invalid",
  "ai_model_override_forbidden",
  "ai_secret_mismatch",
]);

export function isAiApiError(error: unknown): error is AiApiError {
  return error instanceof ProjectApiError
    && error.code !== null
    && AI_ERROR_CODES.has(error.code as AiErrorCode);
}

export interface AiConnectionRead {
  modality: AiModality;
  label: string;
  base_url: string;
  has_api_key: boolean;
  default_model_id: string | null;
  last_test_status: string | null;
  last_tested_at: string | null;
  last_catalog_refresh_at: string | null;
  updated_at: string;
}

export interface AiModelRead {
  modality: AiModality;
  model_id: string;
  display_name: string;
  context_length: number | null;
  supported_parameters: string[];
  input_modalities: string[];
  output_modalities: string[];
  prompt_price_usd: DecimalValue | null;
  completion_price_usd: DecimalValue | null;
  pricing_snapshot_at: string;
  catalog_snapshot_at: string;
  is_favorite: boolean;
  is_available: boolean;
}

export interface AiRoleRead {
  role: string;
  title: string;
  description: string;
  modality: AiModality;
  enabled: boolean;
  model_override: string | null;
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
  confirm_input_tokens: number;
  usd_rub_rate: DecimalValue | null;
  usd_rub_rate_date: string | null;
  connections: AiConnectionRead[];
  roles: AiRoleRead[];
  models: AiModelRead[];
  today_usage: AiTodayUsage;
}

export interface AiPreflight {
  role: string;
  modality: AiModality;
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

export interface AiConnectionTestRead {
  status: "connected";
  model_count: number;
  tested_at: string;
}

export interface AiRunRead {
  id: string;
  project_id: string | null;
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
  confirm_input_tokens: number;
  usd_rub_rate: DecimalValue | null;
  usd_rub_rate_date: string | null;
}

export interface AiConnectionWrite {
  label?: string | null;
  base_url?: string | null;
  api_key?: string | null;
  default_model_id?: string | null;
}

export interface AiRoleWrite {
  enabled: boolean;
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
  method: "PUT",
  body: JSON.stringify(command),
  signal,
});

export const updateAiConnection = (
  modality: AiModality,
  command: AiConnectionWrite,
  signal?: AbortSignal,
): Promise<AiConnectionRead> => request(`${AI_PATH}/connections/${modality}`, {
  method: "PUT",
  body: JSON.stringify(command),
  signal,
});

export const deleteAiCredential = (
  modality: AiModality,
  signal?: AbortSignal,
): Promise<void> => request(`${AI_PATH}/connections/${modality}/credential`, {
  method: "DELETE",
  signal,
});

export const testAiConnection = (
  modality: AiModality,
  signal?: AbortSignal,
): Promise<AiConnectionTestRead> => request(`${AI_PATH}/connections/${modality}/test`, {
  method: "POST",
  signal,
});

export const refreshAiModels = (
  modality: AiModality,
  signal?: AbortSignal,
): Promise<AiModelRead[]> => request(`${AI_PATH}/connections/${modality}/models/refresh`, {
  method: "POST",
  signal,
});

export const updateAiRole = (
  role: string,
  command: AiRoleWrite,
  signal?: AbortSignal,
): Promise<AiSettingsRead> => request(`${AI_PATH}/roles/${encodeURIComponent(role)}`, {
  method: "PUT",
  body: JSON.stringify(command),
  signal,
});

export const updateAiFavorites = (
  modelIds: string[],
  signal?: AbortSignal,
): Promise<AiSettingsRead> => request(`${AI_PATH}/favorites`, {
  method: "PUT",
  body: JSON.stringify({ model_ids: modelIds }),
  signal,
});

function filterQuery(filters: {
  projectId?: string;
  role?: string;
  from?: string;
  to?: string;
}): string {
  const query = new URLSearchParams();
  if (filters.projectId) query.set("project_id", filters.projectId);
  if (filters.role) query.set("role", filters.role);
  if (filters.from) query.set("from", filters.from);
  if (filters.to) query.set("to", filters.to);
  const value = query.toString();
  return value ? `?${value}` : "";
}

export const listAiRuns = (
  filters: { projectId?: string; role?: string; from?: string; to?: string } = {},
  signal?: AbortSignal,
): Promise<AiRunRead[]> => request(`${AI_PATH}/runs${filterQuery(filters)}`, { signal });

export const getAiUsage = (
  filters: { projectId?: string; from?: string; to?: string } = {},
  signal?: AbortSignal,
): Promise<AiUsageRead> => request(`${AI_PATH}/usage${filterQuery(filters)}`, { signal });
