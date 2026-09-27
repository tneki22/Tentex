import type { Schema } from "./preparation";
import type { PageQuality } from "./materials";
import { ProjectApiError, request, type MaterialKindHint } from "./projects";

export type ChatMessageRole = "user" | "examiner" | "system" | "assistant";
export type ChatStreamState = "complete" | "stopped" | "failed";
export type ChatPayloadKind =
  | "none" | "answer_form" | "verdict" | "task" | "interactive" | "tool_result" | "program_diff";
export type ExaminerPersona = "calm_teacher" | "neutral_examiner" | "strict_reviewer";
export type ExaminerStrictness = "soft" | "normal" | "strict";
export type ChatMode = "exam" | "study" | "program" | "source_search";
export type ChatRetrievalScope = "linked_topic" | "topic_project" | "project" | "selected_materials";
export type ChatKnowledgePolicy = "sources_only" | "allow_model";
/** Что сделать с найденными местами; название операции не попадает в поисковый запрос. */
export type ChatOperation = "discuss" | "explain" | "find_evidence" | "compare_sources" | "find_discrepancies";

/** Параметры хода учебного чата: повтор после сбоя отправляет их без изменений. */
export interface ChatSendOptions {
  scope: ChatRetrievalScope;
  knowledgePolicy: ChatKnowledgePolicy;
  materialIds?: string[];
  operation?: ChatOperation;
}
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

export interface ProgramChatOperationView {
  op: "add" | "rename" | "move" | "change_type" | "set_goal" | "set_visibility" | "merge";
  rationale: string;
  title?: string | null;
  node_type?: string;
  node_id?: string;
  node_ids?: string[];
  parent_node_id?: string | null;
  new_parent_node_id?: string | null;
  after_node_id?: string | null;
  /** Поставить первым среди соседей; `after_node_id: null` без него значит «в конец». */
  at_start?: boolean;
  is_in_current_program?: boolean;
  goal_role?: string | null;
  target_level?: string | null;
  outline_ref?: { material_id: string; outline_item_key: string } | null;
  /** Подсказка поиска материала для темы без пункта оглавления (свободный проект). */
  search_queries?: string[];
  material_kind?: MaterialKindHint | null;
  children?: ProgramChatOperationView[];
}

export type ProgramChatOperationState = "pending" | "applied" | "conflicted";

export interface ProgramChatDiffPayload {
  summary: string;
  pros: string[];
  cons: string[];
  operations: ProgramChatOperationView[];
  operation_states: ProgramChatOperationState[];
  rejected: boolean;
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
  program_node_id: string | null;
  title: string;
  updated_at: string;
  message_count: number;
  last_outcome: string | null;
}

export interface ChatSessionDetail {
  id: string;
  project_id: string;
  program_node_id: string | null;
  section_scope_node_id: string | null;
  title: string;
  mode: ChatMode;
  persona: ExaminerPersona;
  strictness: ExaminerStrictness;
  model_override: ChatModelOverride | null;
  model_parameters: Record<string, unknown>;
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
  /** Ездят вместе с моделью: врозь это «рассуждение от прошлой модели». */
  model_parameters?: Record<string, unknown> | null;
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
  node_id: string | null;
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

export type WebSourceKind =
  | "textbook" | "lecture" | "article" | "video" | "course" | "problems" | "catalog" | "other";

/** Объём найденного источника — из прочитанной страницы или выдачи, не от модели. */
export interface WebSourceVolume {
  kind: "html" | "pdf" | "text" | "video" | null;
  words?: number | null;
  minutes?: number | null;
  pages?: number | null;
  size_bytes?: number | null;
  file_links?: number;
  duration?: string | null;
}

export interface WebSourceItem {
  url: string;
  title: string;
  host: string;
  kind: WebSourceKind;
  why: string;
  gist: string;
  level: "beginner" | "intermediate" | "advanced" | null;
  volume: WebSourceVolume;
  author: string | null;
  node_ids: string[];
  priority_reason?: string | null;
  use_advice?: string | null;
  time_fit?: string | null;
}

export interface WebSearchRun {
  query: string;
  category: "general" | "videos" | "science";
  language: "ru" | "en" | "all";
  node_ids: string[];
  found: number;
}

/** Ход чата «Поиск в интернете» (`app/projects/source_search_chat.py`). */
/** Страница из выдачи поиска — для блока «Процесс поиска». */
export interface WebCandidateLink {
  url: string;
  title: string;
  host: string;
  /** Страницу открыли, чтобы узнать объём и начало текста. */
  opened: boolean;
}

export interface SourceSearchResult {
  summary: string;
  /** Что модель решила искать; у ходов до потока этапов поля нет. */
  plan_reply?: string;
  searches: WebSearchRun[];
  items: WebSourceItem[];
  candidates?: WebCandidateLink[];
  candidate_count: number;
  hidden_attached: number;
  hidden_seen: number;
  unresponsive_engines: string[];
  follow_ups: string[];
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
      output_kind: "source_search_results";
      state: "succeeded" | "failed";
      query: string;
      result: SourceSearchResult;
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

/**
 * Источник ответа из `context_snapshot.retrieval_sources` и кадра `started`.
 * Поля после `text` появились 27.09.2026 — в старых сообщениях их нет.
 */
export interface ChatRetrievalSource {
  id: string;
  material: string;
  material_id: string;
  locator: string;
  page: number | null;
  text: string;
  page_to?: number | null;
  typst_path?: string | null;
  line_from?: number | null;
  line_to?: number | null;
  block_title?: string | null;
  quality?: string | null;
  warning?: string | null;
  /** Тот же текст есть и в этих материалах — одно место вместо повтора. */
  also_in?: string[];
}

export type ChatStreamEvent =
  | {
      type: "started";
      messageId: string;
      userMessageId: string | null;
      runId: string;
      sources: ChatRetrievalSource[];
    }
  | { type: "delta"; text: string }
  | { type: "reset"; reason: string }
  | {
      type: "completed";
      messageId: string;
      message: ChatMessageRead;
      usage: Record<string, unknown>;
      cached: boolean;
    }
  | { type: "error"; code: string; detail: string; context: Record<string, unknown> };

const chatPath = (projectId: string): string =>
  `/api/projects/${encodeURIComponent(projectId)}/chat`;
const attemptsPath = (projectId: string): string =>
  `/api/projects/${encodeURIComponent(projectId)}/attempts`;

export const listChatSessions = (
  projectId: string,
  nodeId: string | null,
  signal?: AbortSignal,
): Promise<ChatSessionSummary[]> =>
  request(`${chatPath(projectId)}/sessions${nodeId ? `?node_id=${encodeURIComponent(nodeId)}` : ""}`, { signal });

export const createChatSession = (
  projectId: string,
  nodeId: string | null,
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
  nodeId: string | null,
  signal?: AbortSignal,
): Promise<ChatCapabilities> =>
  request(`${chatPath(projectId)}/capabilities${nodeId ? `?node_id=${encodeURIComponent(nodeId)}` : ""}`, { signal });

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
    return {
      type: "started",
      messageId: String(payload.message_id),
      userMessageId: payload.user_message_id ? String(payload.user_message_id) : null,
      runId: String(payload.run_id),
      sources: Array.isArray(payload.sources) ? (payload.sources as ChatRetrievalSource[]) : [],
    };
  }
  if (event === "delta") return { type: "delta", text: String(payload.text ?? "") };
  if (event === "reset") return { type: "reset", reason: String(payload.reason ?? "") };
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
    return {
      type: "error",
      code: String(payload.code ?? "unknown"),
      detail: String(payload.detail ?? ""),
      context: (payload.context as Record<string, unknown> | undefined) ?? {},
    };
  }
  return null;
}

export async function* streamMessage(
  projectId: string,
  sessionId: string,
  text: string,
  signal: AbortSignal,
  retrieval: ChatSendOptions = { scope: "topic_project", knowledgePolicy: "sources_only" },
): AsyncGenerator<ChatStreamEvent> {
  const response = await fetch(
    `${chatPath(projectId)}/sessions/${encodeURIComponent(sessionId)}/messages`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        text,
        retrieval_scope: retrieval.scope,
        retrieval_material_ids: retrieval.materialIds ?? [],
        knowledge_policy: retrieval.knowledgePolicy,
        operation: retrieval.operation ?? "discuss",
      }),
      signal,
    },
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
