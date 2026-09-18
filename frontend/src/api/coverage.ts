import { request } from "./projects";

export type CoverageBucket =
  | "linked"
  | "outside_program"
  | "service"
  | "mixed_resolved"
  | "unresolved"
  | "pending"
  | "processing"
  | "error"
  | "stale";

export interface CoverageLimits {
  max_calls: number;
  max_total_tokens: number;
  max_cost_usd?: number | null;
}

export interface CoveragePlan {
  material_ids: string[];
  context_material_ids: string[];
  mode: "initial" | "incremental";
  expected_program_revision: number;
  limits: CoverageLimits;
  roles?: Record<string, { provider_id: string; model_id: string }>;
}

export interface CoveragePreflight {
  fingerprint: string;
  snapshot: {
    sources: Array<{
      id: string;
      name: string;
      source_role: string;
      revision: number;
      diagnostics: Record<string, unknown>;
    }>;
    context_sources: Array<{ id: string; name: string; revision: number }>;
  };
  blocks: number;
  execution_available: boolean;
  execution_issue: string | null;
  model_roles: Record<string, {
    provider_id: string;
    model_id: string;
    model_source: string;
    context_length: number | null;
    prompt_version: string;
  }>;
  limits: CoverageLimits;
}

export interface CoverageRun {
  id: string;
  job_id: string;
  state: "queued" | "running" | "paused" | "failed" | "completed" | "cancelled";
  execution_generation: number;
  stop_reason: string | null;
  snapshot: CoveragePreflight["snapshot"];
  stale: boolean;
  primary: { total: number; pending: number; processing: number; inspected: number; error: number };
  outcomes: Record<"linked" | "outside_program" | "service" | "mixed_resolved" | "unresolved", number>;
  research: { discovered: number; finished: number };
  pending_synthesis: number;
  costs: { calls: number; tokens: number; cost_usd: number; uncertain_calls: number };
  pause_requested: boolean;
}

export interface CoverageSourceOverview {
  id: string;
  name: string;
  revision: number;
  total: number;
  distribution: Record<CoverageBucket, number>;
  diagnostics: Record<string, unknown>;
  known_limits: string[];
}

export interface CoverageOverview {
  coverage_revision: number;
  program_revision: number;
  source_revisions: Record<string, number>;
  partial: boolean;
  total: number;
  distribution: Record<CoverageBucket, number>;
  topics: { total: number; with_content: number; reading_basis: number; legacy: number };
  material_ratio: {
    numerator: number;
    denominator: number;
    value: number | null;
    label: string;
    mixed: number;
  };
  findings: number;
  latest_run_id: string | null;
  latest_run_state: CoverageRun["state"] | null;
  sources: CoverageSourceOverview[];
}

export interface CoverageBlock {
  block_id: string;
  material_id: string;
  revision: number;
  bucket: CoverageBucket;
  has_content: boolean;
  result_id: string | null;
  title: string | null;
  page_from: number;
  page_to: number;
  material_name: string;
  reason: string | null;
}

const path = (projectId: string): string =>
  `/api/projects/${encodeURIComponent(projectId)}/coverage`;

export const preflightCoverage = (
  projectId: string,
  plan: CoveragePlan,
  signal?: AbortSignal,
): Promise<CoveragePreflight> => request(`${path(projectId)}/preflight`, {
  method: "POST",
  body: JSON.stringify(plan),
  signal,
});

export const startCoverage = (
  projectId: string,
  plan: CoveragePlan,
  preflightFingerprint: string,
  requestKey: string,
): Promise<CoverageRun> => request(`${path(projectId)}/runs`, {
  method: "POST",
  body: JSON.stringify({
    ...plan,
    preflight_fingerprint: preflightFingerprint,
    request_key: requestKey,
  }),
});

export const getCoverageOverview = (
  projectId: string,
  signal?: AbortSignal,
): Promise<CoverageOverview> => request(`${path(projectId)}/overview`, { signal });

export const getCoverageRun = (
  projectId: string,
  runId: string,
  signal?: AbortSignal,
): Promise<CoverageRun> => request(`${path(projectId)}/runs/${encodeURIComponent(runId)}`, { signal });

export interface CoverageBlockPage {
  items: CoverageBlock[];
  total: number;
  next_offset: number | null;
}

/** Нерешённые, сбойные и устаревшие блоки всех источников: одна страница вместо всего проекта. */
export const getCoverageIssues = (
  projectId: string,
  limit = 12,
  signal?: AbortSignal,
): Promise<CoverageBlockPage> => request(`${path(projectId)}/issues?offset=0&limit=${limit}`, { signal });

export const controlCoverageRun = (
  projectId: string,
  run: CoverageRun,
  action: "pause" | "resume" | "cancel",
): Promise<CoverageRun> => request(`${path(projectId)}/runs/${encodeURIComponent(run.id)}/control`, {
  method: "POST",
  body: JSON.stringify({ action, expected_generation: run.execution_generation }),
});
