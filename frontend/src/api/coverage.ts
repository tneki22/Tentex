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

/** Пустые вызовы и токены означают «выведи из области запуска», а не «без предела». */
export interface CoverageLimits {
  max_calls?: number | null;
  max_total_tokens?: number | null;
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
  packets_at_least: number;
  prompt_overhead_tokens: number;
  packet_input_tokens: number;
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
  limits: { max_calls: number; max_total_tokens: number; max_cost_usd: number | null };
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
  in_latest_run: boolean;
  /** Когда закончился последний запуск, в область которого входил источник. */
  researched_at: string | null;
  /** Состояние последнего запуска, если источник в его области. */
  run_state: CoverageRun["state"] | null;
}

export interface CoverageOverview {
  coverage_revision: number;
  program_revision: number;
  source_revisions: Record<string, number>;
  partial: boolean;
  total: number;
  distribution: Record<CoverageBucket, number>;
  topics: { total: number; with_content: number; reading_basis: number; legacy: number };
  content_titles: string[];
  reading_titles: string[];
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
  coverage_revision: number;
  items: CoverageBlock[];
  total: number;
  next_offset: number | null;
  distribution: Partial<Record<CoverageBucket, number>>;
}

export type CoverageView = "readable" | "gaps" | "outside_program" | "needs_action";

export interface CoverageTopic {
  node_id: string;
  title: string;
  parent_title: string | null;
  evidence_count: number;
  mention_count: number;
  hidden_count: number;
  legacy_count: number;
  best_evidence_id: string | null;
}

export interface CoverageTopicPage {
  coverage_revision: number;
  items: CoverageTopic[];
  total: number;
  next_offset: number | null;
}

/**
 * Кусок чтения: подряд идущие опоры темы одного материала. `id` — адрес первой опоры,
 * `member_ids` — всех; `from_fragment_id…to_fragment_id` включают заголовок, номера
 * страниц и рисунки между опорами и целиком вставляются в урок.
 */
export interface EvidenceSummary {
  id: string;
  binding_id: string;
  binding_ids: string[];
  member_ids: string[];
  topic_id: string;
  material_id: string;
  material_name: string;
  title: string;
  page_from: number;
  page_to: number;
  from_fragment_id: string;
  to_fragment_id: string;
  fragment_ids: string[];
  fragment_count: number;
  quote: string;
  description: string;
  roles: string[];
  semantic_kind: string | null;
  status: string;
  mechanism: string;
  quality: "native" | "ocr" | "ocr_low";
  available: boolean;
  stale: boolean;
  hidden: boolean;
  preferred: boolean;
  legacy: boolean;
}

export interface TopicEvidence {
  coverage_revision: number;
  topic_id: string;
  topic_title: string;
  best_evidence_id: string | null;
  starter: EvidenceSummary[];
  explanations: EvidenceSummary[];
  practice: EvidenceSummary[];
  depth: EvidenceSummary[];
  mentions: EvidenceSummary[];
  hidden: EvidenceSummary[];
  legacy: EvidenceSummary[];
}

export interface EvidenceDetail extends EvidenceSummary {
  key: string;
  ref: string;
  repair: string;
  start: number | null;
  end: number | null;
  original_ref: string | null;
  origin: string | null;
  applied: boolean;
  locator: Record<string, unknown>;
  topic_title: string;
  text: string;
  linked_topics: Array<{ topic_id: string; title: string }>;
}

export type CoverageDecisionAction =
  | "confirm" | "remove" | "restore" | "reassign" | "change_role"
  | "hide" | "show" | "prefer" | "clear_prefer" | "service" | "outside_goal";

export interface CoverageDecisionCommand {
  request_key: string;
  expected_coverage_revision: number;
  action: CoverageDecisionAction;
  binding_id?: string;
  /** Все привязки куска: одна команда и одна отмена. */
  binding_ids?: string[];
  evidence_id?: string;
  block_id?: string;
  topic_ids?: string[];
  role?: "definition" | "explanation" | "example" | "exercise" | "reference";
  semantic_kind?: "content" | "mention" | "context";
}

export interface CoverageDecisionReceipt {
  request_key: string;
  action: CoverageDecisionAction;
  coverage_revision: number;
  action_sequence: number;
  binding_ids: string[];
  message: string;
}

/** Нерешённые, сбойные и устаревшие блоки всех источников: одна страница вместо всего проекта. */
export const getCoverageIssues = (
  projectId: string,
  limit = 12,
  signal?: AbortSignal,
): Promise<CoverageBlockPage> => request(`${path(projectId)}/issues?offset=0&limit=${limit}`, { signal });

export const getCoverageTopics = (
  projectId: string,
  view: "readable" | "gaps",
  offset = 0,
  limit = 30,
  signal?: AbortSignal,
): Promise<CoverageTopicPage> => request(
  `${path(projectId)}/topics?view=${view}&offset=${offset}&limit=${limit}`,
  { signal },
);

export const getCoverageBlocks = (
  projectId: string,
  view: "outside_program" | "needs_action",
  offset = 0,
  limit = 30,
  signal?: AbortSignal,
): Promise<CoverageBlockPage> => request(
  `${path(projectId)}/blocks?view=${view}&offset=${offset}&limit=${limit}`,
  { signal },
);

export const getTopicEvidence = (
  projectId: string,
  nodeId: string,
  signal?: AbortSignal,
): Promise<TopicEvidence> => request(
  `${path(projectId)}/topics/${encodeURIComponent(nodeId)}/evidence`,
  { signal },
);

export const getEvidence = (
  projectId: string,
  evidenceId: string,
  signal?: AbortSignal,
): Promise<EvidenceDetail> => request(
  `${path(projectId)}/evidence/${encodeURIComponent(evidenceId)}`,
  { signal },
);

export const decideCoverage = (
  projectId: string,
  command: CoverageDecisionCommand,
): Promise<CoverageDecisionReceipt> => request(`${path(projectId)}/decisions`, {
  method: "POST",
  body: JSON.stringify(command),
});

export const controlCoverageRun = (
  projectId: string,
  run: CoverageRun,
  action: "pause" | "resume" | "cancel",
  limits?: CoverageLimits,
): Promise<CoverageRun> => request(`${path(projectId)}/runs/${encodeURIComponent(run.id)}/control`, {
  method: "POST",
  body: JSON.stringify({ action, expected_generation: run.execution_generation, limits }),
});
