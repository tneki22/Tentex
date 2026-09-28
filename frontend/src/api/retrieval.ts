import type { BackgroundJobRead, BackgroundJobStartRead } from "./backgroundJobs";
import { request } from "./projects";

export type EmbeddingBackendKind = "local_hf" | "openai_compatible";
export type RetrievalPreset = "fast" | "balanced" | "accurate";
export type RetrievalIndexState = "building" | "ready" | "active" | "failed";
export type SearchStrategy = "lexical" | "semantic" | "hybrid";
export type RetrievalScope = "linked_topic" | "topic_project" | "project" | "selected_materials";
/** Что Tentex знает о модели: `verified` — прогнана на контрольных запросах. */
export type ModelSupport = "verified" | "recipe" | "short_window" | "not_embedding" | "unknown";

export interface EmbeddingProfileRead {
  id: string;
  label: string;
  backend_kind: EmbeddingBackendKind;
  model_id: string;
  model_revision: string | null;
  provider_id: string | null;
  dimension: number | null;
  batch_size: number;
  normalize: boolean;
  pooling: "mean" | "cls" | "last_token";
  query_template: string;
  document_template: string;
  installed: boolean;
  tested_at: string | null;
  test_error: string | null;
  created_at: string;
  updated_at: string;
  support: ModelSupport;
}

export interface RetrievalIndexRead {
  id: string;
  profile_id: string;
  state: RetrievalIndexState;
  preset: RetrievalPreset;
  chunk_target_tokens: number;
  chunk_max_tokens: number;
  chunk_overlap_tokens: number;
  chunk_count: number;
  indexed_material_count: number;
  material_count: number;
  corpus_manifest: Array<{ material_id: string; name: string; revision: number; size_bytes: number }>;
  diagnostics: string[];
  error: string | null;
  created_at: string;
  completed_at: string | null;
  activated_at: string | null;
}

export interface RetrievalSettingsRead {
  default_profile_id: string | null;
  preset: RetrievalPreset;
  expert_parameters: Record<string, number | boolean | string>;
  active_index: RetrievalIndexRead | null;
  profiles: EmbeddingProfileRead[];
  ready_materials: number;
  total_ready_materials: number;
  degraded: boolean;
  degradation_reasons: string[];
}

export interface LocalModelRead {
  model_id: string;
  label: string;
  role: "embedding" | "reranker";
  installed: boolean;
  installing: boolean;
  recommended_for: string;
  support: ModelSupport;
}

export interface RetrievalHitRead {
  locator: {
    chunk_id: string;
    material_id: string;
    material_name: string;
    block_id: string | null;
    block_title: string | null;
    page_from: number | null;
    page_to: number | null;
    fragment_ids: string[];
    typst_path: string | null;
    line_from: number | null;
    line_to: number | null;
  };
  text: string;
  quality: "native" | "ocr" | "ocr_low" | null;
  score: number;
  signals: Array<"lexical" | "semantic">;
  warning: string | null;
  also_in: string[];
}

export interface RetrievalSearchRead {
  query: string;
  strategy: SearchStrategy;
  index_id: string | null;
  degraded: boolean;
  degradation_reasons: string[];
  no_relevant_match: boolean;
  /** Имена и термины запроса, которых нет ни в одном фрагменте выбранных материалов. */
  missing_terms: string[];
  results: RetrievalHitRead[];
}

export interface BenchmarkRunRead {
  id: string;
  index_id: string;
  metrics: Record<string, number>;
  case_count: number;
  created_at: string;
}

export interface ExhaustiveRunRead {
  id: string;
  job_id: string;
  project_id: string;
  session_id: string;
  user_message_id: string | null;
  final_message_id: string | null;
  query: string;
  scope: RetrievalScope;
  corpus_manifest: Array<{ material_id: string; name: string; revision: number; size_bytes: number }>;
  result: Record<string, unknown>;
  created_at: string;
  completed_at: string | null;
}

export const getRetrievalSettings = (signal?: AbortSignal): Promise<RetrievalSettingsRead> =>
  request("/api/settings/retrieval", { signal });

export const updateRetrievalSettings = (
  command: Pick<RetrievalSettingsRead, "default_profile_id" | "preset" | "expert_parameters">,
): Promise<RetrievalSettingsRead> => request("/api/settings/retrieval", {
  method: "PUT",
  body: JSON.stringify(command),
});

export const createEmbeddingProfile = (command: {
  label: string;
  backend_kind: EmbeddingBackendKind;
  model_id: string;
  model_revision?: string | null;
  provider_id?: string | null;
  batch_size?: number;
  normalize?: boolean;
  pooling?: "mean" | "cls" | "last_token";
  query_template?: string;
  document_template?: string;
}): Promise<EmbeddingProfileRead> => request("/api/settings/retrieval/profiles", {
  method: "POST",
  body: JSON.stringify(command),
});

export const testEmbeddingProfile = (profileId: string): Promise<EmbeddingProfileRead> =>
  request(`/api/settings/retrieval/profiles/${encodeURIComponent(profileId)}/test`, { method: "POST" });

export const listLocalEmbeddingModels = (): Promise<LocalModelRead[]> =>
  request("/api/settings/retrieval/local-models");

export const installLocalEmbeddingModel = (modelId: string): Promise<BackgroundJobStartRead> =>
  request("/api/settings/retrieval/local-models/install", {
    method: "POST",
    body: JSON.stringify({ model_id: modelId, revision: null }),
  });

export const deleteLocalEmbeddingModel = (modelId: string): Promise<void> =>
  request(`/api/settings/retrieval/local-models?model_id=${encodeURIComponent(modelId)}`, {
    method: "DELETE",
  });

export const listRetrievalIndexes = (): Promise<RetrievalIndexRead[]> =>
  request("/api/retrieval/indexes");

export const addRetrievalIndexMaterials = (
  indexId: string,
  materialIds: string[],
  cloudConsent: boolean,
): Promise<{ job_ids: string[] }> => request(
  `/api/retrieval/indexes/${encodeURIComponent(indexId)}/materials`,
  {
    method: "POST",
    body: JSON.stringify({ material_ids: materialIds, cloud_consent: cloudConsent }),
  },
);

export const buildRetrievalIndex = (command: {
  profile_id: string;
  preset: RetrievalPreset;
  cloud_consent: boolean;
  material_ids?: string[];
}): Promise<{ index: RetrievalIndexRead; job_id: string }> => request("/api/retrieval/indexes", {
  method: "POST",
  // Размеры кусков не передаются: их задаёт сервер под окно модели
  // (retrieval/chunking.py), и старые 384/480 здесь перекрывали его значения.
  body: JSON.stringify({ ...command, material_ids: command.material_ids ?? [] }),
});

export const pauseRetrievalIndexBuild = (jobId: string): Promise<BackgroundJobRead> => request(
  `/api/retrieval/indexes/jobs/${encodeURIComponent(jobId)}/pause`, { method: "POST" },
);

export const resumeRetrievalIndexBuild = (jobId: string): Promise<BackgroundJobRead> => request(
  `/api/retrieval/indexes/jobs/${encodeURIComponent(jobId)}/resume`, { method: "POST" },
);

export const indexLibraryMaterial = (materialId: string): Promise<BackgroundJobStartRead> => request(
  `/api/retrieval/indexes/materials/${encodeURIComponent(materialId)}`,
  { method: "POST" },
);

export const activateRetrievalIndex = (indexId: string): Promise<RetrievalIndexRead> =>
  request(`/api/retrieval/indexes/${encodeURIComponent(indexId)}/activate`, { method: "POST" });

export const deleteRetrievalIndex = (indexId: string): Promise<void> =>
  request(`/api/retrieval/indexes/${encodeURIComponent(indexId)}`, { method: "DELETE" });

export const listRetrievalBenchmarks = (): Promise<BenchmarkRunRead[]> =>
  request("/api/retrieval/benchmarks");

export const runRetrievalBenchmark = (indexId: string): Promise<BenchmarkRunRead> =>
  request(`/api/retrieval/benchmarks/${encodeURIComponent(indexId)}`, { method: "POST" });

export const searchLibraryContent = (
  query: string,
  materialIds: string[],
  strategy: SearchStrategy,
  signal?: AbortSignal,
): Promise<RetrievalSearchRead> => request("/api/library/search", {
  method: "POST",
  body: JSON.stringify({
    query,
    strategy,
    scope: "selected_materials",
    material_ids: materialIds,
    limit: 20,
  }),
  signal,
});

export const startExhaustiveReview = (
  projectId: string,
  sessionId: string,
  command: {
    query: string;
    scope: RetrievalScope;
    node_id?: string | null;
    material_ids?: string[];
    knowledge_policy: "sources_only" | "allow_model";
    confirmed: boolean;
  },
): Promise<ExhaustiveRunRead> => request(
  `/api/projects/${encodeURIComponent(projectId)}/chat/sessions/${encodeURIComponent(sessionId)}/exhaustive`,
  { method: "POST", body: JSON.stringify(command) },
);
