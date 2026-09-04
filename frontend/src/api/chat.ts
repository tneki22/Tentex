import type { Schema } from "./preparation";
import type { PageQuality } from "./materials";
import { ProjectApiError, request } from "./projects";

export type ChatMessageRole = "user" | "examiner" | "system";
export type ChatStreamState = "complete" | "stopped" | "failed";
export type ChatPayloadKind = "none" | "answer_form" | "verdict" | "task" | "interactive" | "tool_result";
export type ExaminerPersona = "calm_teacher" | "neutral_examiner" | "strict_reviewer";
export type ExaminerStrictness = "soft" | "normal" | "strict";
export type ChatMode = "exam" | "study";
export type ChatToolRunState = "queued" | "running" | "succeeded" | "failed";
export type AttemptOutcome = "passed" | "partial" | "failed" | "unscored";
export type GradeMethod = "exact_match" | "key_terms" | "sql" | "semantic" | "ai_judge" | "self_assessment";

export const CONTEXT_FLAG_KEYS = [
  "profile",
  "reference",
  "fragments",
  "attempts",
  "section_memory",
] as const;
export type ContextFlagKey = (typeof CONTEXT_FLAG_KEYS)[number];
export type ChatContextFlags = Record<ContextFlagKey, boolean>;

export interface ChatModelOverride {
  provider_id: string;
  model_id: string;
}

export interface AnswerFormPayload {
  question: string;
  ordinal: number;
  submitted_at: string;
  text: string;
}

export interface RubricPointRead {
  point: string;
  quote: string | null;
  quote_start: number | null;
  quote_end: number | null;
}

export interface GradeUsageRead {
  input_tokens: number;
  output_tokens: number;
  reasoning_tokens: number;
  provider_cached_tokens: number;
  actual_cost_usd: string | number | null;
  actual_cost_rub: string | number | null;
}

export interface VerdictPayload {
  outcome: AttemptOutcome;
  method: GradeMethod | null;
  credited: RubricPointRead[];
  missed: RubricPointRead[];
  wrong: RubricPointRead[];
  summary: string;
  usage: GradeUsageRead;
  cached: boolean;
  actual_model_id: string | null;
  self_assessment: AttemptOutcome | null;
}

export interface AttemptRead {
  id: string;
  project_id: string;
  program_node_id: string;
  parent_attempt_id: string | null;
  ordinal: number;
  text: string;
  persona: ExaminerPersona;
  strictness: ExaminerStrictness;
  context_snapshot: Record<string, unknown>;
  created_at: string;
}

export interface GradeRead {
  attempt_id: string;
  outcome: AttemptOutcome;
  method: GradeMethod | null;
  credited_points: RubricPointRead[];
  missed_points: RubricPointRead[];
  wrong_points: RubricPointRead[];
  summary: string;
  self_assessment: AttemptOutcome | null;
  ai_run_id: string | null;
  actual_model_id: string | null;
  usage: GradeUsageRead;
  cached: boolean;
  created_at: string;
  updated_at: string;
}

export interface AttemptSummaryRead {
  id: string;
  ordinal: number;
  created_at: string;
  outcome: AttemptOutcome | null;
  method: GradeMethod | null;
  self_assessment: AttemptOutcome | null;
  text_preview: string;
}

export interface AttemptDetailRead {
  attempt: AttemptRead;
  grade: GradeRead | null;
}

export interface ChatMessageRead {
  id: string;
  session_id: string;
  sequence: number;
  role: ChatMessageRole;
  text: string;
  stream_state: ChatStreamState;
  payload_kind: ChatPayloadKind;
  payload: Record<string, unknown>;
  context_snapshot: Record<string, unknown>;
  skill: string | null;
  ai_run_id: string | null;
  attempt_id: string | null;
  grade_attempt_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface ChatSessionSummary {
  id: string;
  project_id: string;
  program_node_id: string;
  title: string;
  updated_at: string;
  message_count: number;
  last_outcome: string | null;
}

export interface ChatSessionDetail {
  id: string;
  project_id: string;
  program_node_id: string;
  section_scope_node_id: string | null;
  title: string;
  mode: ChatMode;
  persona: ExaminerPersona;
  strictness: ExaminerStrictness;
  model_override: ChatModelOverride | null;
  context_flags: ChatContextFlags;
  draft_text: string;
  created_at: string;
  updated_at: string;
  messages: ChatMessageRead[];
}

export interface ChatSettingsPatch {
  mode?: ChatMode;
  persona?: ExaminerPersona;
  strictness?: ExaminerStrictness;
  model_override?: ChatModelOverride | null;
  context_flags?: Partial<ChatContextFlags>;
}

export interface ChatDraftRead {
  text: string;
  updated_at: string;
}

export interface ManifestEntry {
  kind: string;
  id: string | null;
  included: boolean;
  truncated: boolean;
  bytes: number;
  count: number | null;
  reason: string | null;
}

export interface ChatContextPreview {
  session_id: string;
  node_id: string;
  question: string;
  persona: ExaminerPersona;
  strictness: ExaminerStrictness;
  model_source: "auto" | "override";
  model_id: string | null;
  manifest: ManifestEntry[];
  fingerprint: string;
  total_bytes: number;
}

export interface ChatCapability {
  key: string;
  title: string;
  available: boolean;
  unavailable_reason: string | null;
}

export interface ChatCapabilities {
  modes: ChatCapability[];
  skills: ChatCapability[];
  tools: ChatCapability[];
}

export interface ChatToolRun {
  id: string;
  session_id: string;
  tool_key: string;
  state: ChatToolRunState;
  result: Record<string, unknown> | null;
  error_code: string | null;
  message_id: string | null;
  created_at: string;
  completed_at: string | null;
}

export interface MaterialSearchResultItem {
  fragment_id: string;
  material_id: string;
  material_name: string;
  block_title: string | null;
  page_from: number;
  page_to: number;
  excerpt: string;
  quality: PageQuality;
  already_bound: boolean;
}

export type ToolResultPayload =
  | {
      tool_key: string;
      output_kind: "material_search_results";
      state: "succeeded" | "failed";
      query: string;
      result: { items: MaterialSearchResultItem[] };
    }
  | {
      tool_key: string;
      output_kind: string;
      state: "succeeded" | "failed";
      query: string;
      result: Record<string, unknown>;
    };

export interface ChatAnswerResult {
  messages: ChatMessageRead[];
  attempt: AttemptRead;
  grade: GradeRead;
}

export type ChatStreamEvent =
  | { type: "started"; messageId: string; runId: string }
  | { type: "delta"; text: string }
  | {
      type: "completed";
      messageId: string;
      message: ChatMessageRead;
      usage: Record<string, unknown>;
      cached: boolean;
    }
  | { type: "error"; code: string; detail: string };

const chatPath = (projectId: string): string =>
  `/api/projects/${encodeURIComponent(projectId)}/chat`;
const attemptsPath = (projectId: string): string =>
  `/api/projects/${encodeURIComponent(projectId)}/attempts`;

export const listChatSessions = (
  projectId: string,
  nodeId: string,
  signal?: AbortSignal,
): Promise<ChatSessionSummary[]> =>
  request(`${chatPath(projectId)}/sessions?node_id=${encodeURIComponent(nodeId)}`, { signal });

export const createChatSession = (
  projectId: string,
  nodeId: string,
): Promise<ChatSessionDetail> => request(`${chatPath(projectId)}/sessions`, {
  method: "POST",
  body: JSON.stringify({ program_node_id: nodeId }),
});

export const getChatSession = (
  projectId: string,
  sessionId: string,
  signal?: AbortSignal,
): Promise<ChatSessionDetail> =>
  request(`${chatPath(projectId)}/sessions/${encodeURIComponent(sessionId)}`, { signal });

export const saveChatDraft = (
  projectId: string,
  sessionId: string,
  text: string,
): Promise<ChatDraftRead> => request(
  `${chatPath(projectId)}/sessions/${encodeURIComponent(sessionId)}/draft`,
  { method: "PUT", body: JSON.stringify({ text }) },
);

export const updateChatSettings = (
  projectId: string,
  sessionId: string,
  patch: ChatSettingsPatch,
): Promise<ChatSessionDetail> => request(
  `${chatPath(projectId)}/sessions/${encodeURIComponent(sessionId)}/settings`,
  { method: "PUT", body: JSON.stringify(patch) },
);

export const getChatContextPreview = (
  projectId: string,
  sessionId: string,
  signal?: AbortSignal,
): Promise<ChatContextPreview> =>
  request(`${chatPath(projectId)}/sessions/${encodeURIComponent(sessionId)}/context`, { signal });

export const getChatCapabilities = (
  projectId: string,
  nodeId: string,
  signal?: AbortSignal,
): Promise<ChatCapabilities> =>
  request(`${chatPath(projectId)}/capabilities?node_id=${encodeURIComponent(nodeId)}`, { signal });

export const runChatTool = (
  projectId: string,
  sessionId: string,
  toolKey: string,
  input: Record<string, unknown>,
): Promise<ChatToolRun> => request(
  `${chatPath(projectId)}/sessions/${encodeURIComponent(sessionId)}/tools/${encodeURIComponent(toolKey)}/runs`,
  { method: "POST", body: JSON.stringify({ input }) },
);

export const submitChatAnswer = (
  projectId: string,
  sessionId: string,
  text: string,
  tracking?: Pick<Schema["ChatAnswerWrite"], "answer_mode" | "active_seconds">,
): Promise<ChatAnswerResult> => request(
  `${chatPath(projectId)}/sessions/${encodeURIComponent(sessionId)}/answer`,
  { method: "POST", body: JSON.stringify({ text, ...tracking }) },
);

export const listAttempts = (
  projectId: string,
  nodeId: string,
  signal?: AbortSignal,
): Promise<AttemptSummaryRead[]> => request(
  `${attemptsPath(projectId)}?node_id=${encodeURIComponent(nodeId)}`,
  { signal },
);

export const getAttempt = (
  projectId: string,
  attemptId: string,
  signal?: AbortSignal,
): Promise<AttemptDetailRead> => request(
  `${attemptsPath(projectId)}/${encodeURIComponent(attemptId)}`,
  { signal },
);

export const checkAttempt = (
  projectId: string,
  attemptId: string,
): Promise<GradeRead> => request(
  `${attemptsPath(projectId)}/${encodeURIComponent(attemptId)}/check`,
  { method: "POST" },
);

export const setAttemptSelfAssessment = (
  projectId: string,
  attemptId: string,
  outcome: Exclude<AttemptOutcome, "unscored">,
): Promise<GradeRead> => request(
  `${attemptsPath(projectId)}/${encodeURIComponent(attemptId)}/self-assessment`,
  { method: "PUT", body: JSON.stringify({ outcome }) },
);

function parseFrame(raw: string): ChatStreamEvent | null {
  let event = "";
  let data = "";
  for (const line of raw.split("\n")) {
    if (line.startsWith("event: ")) event = line.slice(7).trim();
    else if (line.startsWith("data: ")) data += line.slice(6);
  }
  if (!event || !data) return null;
  const payload = JSON.parse(data) as Record<string, unknown>;
  if (event === "started") {
    return { type: "started", messageId: String(payload.message_id), runId: String(payload.run_id) };
  }
  if (event === "delta") return { type: "delta", text: String(payload.text ?? "") };
  if (event === "completed") {
    return {
      type: "completed",
      messageId: String(payload.message_id),
      message: payload.message as ChatMessageRead,
      usage: (payload.usage as Record<string, unknown>) ?? {},
      cached: Boolean(payload.cached),
    };
  }
  if (event === "error") {
    return { type: "error", code: String(payload.code ?? "unknown"), detail: String(payload.detail ?? "") };
  }
  return null;
}

export async function* streamMessage(
  projectId: string,
  sessionId: string,
  text: string,
  signal: AbortSignal,
): AsyncGenerator<ChatStreamEvent> {
  const response = await fetch(
    `${chatPath(projectId)}/sessions/${encodeURIComponent(sessionId)}/messages`,
    { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text }), signal },
  );
  if (!response.ok || !response.body) {
    const payload = await response.json().catch(() => null) as { detail?: string; code?: string } | null;
    throw new ProjectApiError(response.status, payload?.detail ?? "Ответ не получен", payload?.code ?? null);
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let split = buffer.indexOf("\n\n");
    while (split >= 0) {
      const frame = parseFrame(buffer.slice(0, split));
      if (frame) yield frame;
      buffer = buffer.slice(split + 2);
      split = buffer.indexOf("\n\n");
    }
  }
}
