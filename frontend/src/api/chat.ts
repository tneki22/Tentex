import { ProjectApiError, request } from "./projects";

export type ChatMessageRole = "user" | "examiner" | "system";
export type ChatStreamState = "complete" | "stopped" | "failed";
export type ChatPayloadKind = "none" | "answer_form" | "verdict" | "task" | "interactive";
export type ExaminerPersona = "calm_teacher" | "neutral_examiner" | "strict_reviewer";
export type ExaminerStrictness = "soft" | "normal" | "strict";

export interface AnswerFormPayload {
  question: string;
  ordinal: number;
  submitted_at: string;
  text: string;
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
  ai_run_id: string | null;
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
  persona: ExaminerPersona;
  strictness: ExaminerStrictness;
  draft_text: string;
  created_at: string;
  updated_at: string;
  messages: ChatMessageRead[];
}

export interface ChatDraftRead {
  text: string;
  updated_at: string;
}

export interface ChatContextRead {
  node_id: string;
  question: string;
  reference_included: boolean;
  material_count: number;
  tail_limit: number;
}

export interface ChatAnswerResult {
  messages: ChatMessageRead[];
}

export type ChatStreamEvent =
  | { type: "started"; messageId: string; runId: string }
  | { type: "delta"; text: string }
  | { type: "completed"; messageId: string; usage: Record<string, unknown>; cached: boolean }
  | { type: "error"; code: string; detail: string };

const chatPath = (projectId: string): string =>
  `/api/projects/${encodeURIComponent(projectId)}/chat`;

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

export const getChatContext = (
  projectId: string,
  nodeId: string,
  signal?: AbortSignal,
): Promise<ChatContextRead> =>
  request(`${chatPath(projectId)}/context?node_id=${encodeURIComponent(nodeId)}`, { signal });

export const submitChatAnswer = (
  projectId: string,
  sessionId: string,
  text: string,
): Promise<ChatAnswerResult> => request(
  `${chatPath(projectId)}/sessions/${encodeURIComponent(sessionId)}/answer`,
  { method: "POST", body: JSON.stringify({ text }) },
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
