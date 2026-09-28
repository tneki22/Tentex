import type { ChatMessageRead, ChatModelOverride } from "./chat";
import { ProjectApiError, request } from "./projects";

/** Проектные чаты без темы устроены одинаково (`app/chat/project_sessions.py`)
 * и различаются только сегментом пути. */
export type ProjectChatChannel = "program-chat" | "source-search-chat";

export interface ProjectChatSessionSummary {
  id: string;
  project_id: string | null;
  title: string;
  updated_at: string;
  message_count: number;
}

export interface ProjectChatSessionDetail {
  id: string;
  project_id: string | null;
  section_scope_node_id: string | null;
  title: string;
  model_override: ChatModelOverride | null;
  model_parameters: Record<string, unknown>;
  context_flags: Record<string, boolean>;
  draft_text: string;
  created_at: string;
  updated_at: string;
  messages: ChatMessageRead[];
}

export interface ProjectChatManifestEntry {
  kind: string;
  id: string | null;
  included: boolean;
  truncated: boolean;
  bytes: number;
  chars: number;
  count: number | null;
  reason: string | null;
  flag_key: string | null;
  label: string | null;
  preview: string[];
}

export interface ProjectChatContextPreview {
  session_id: string;
  manifest: ProjectChatManifestEntry[];
  fingerprint: string;
  total_bytes: number;
}

export interface ProjectChatContextPatch {
  context_flags?: Record<string, boolean>;
}

/** Кадр потокового хода: этап с его данными, готовый ответ или ошибка. */
export type ProjectChatStreamEvent =
  | { type: "progress"; data: { stage: string } & Record<string, unknown> }
  | { type: "completed"; message: ChatMessageRead }
  | { type: "error"; code: string; detail: string };

function parseStreamFrame(raw: string): ProjectChatStreamEvent | null {
  let event = "";
  let data = "";
  for (const line of raw.split("\n")) {
    if (line.startsWith("event: ")) event = line.slice(7).trim();
    else if (line.startsWith("data: ")) data += line.slice(6);
  }
  if (!event || !data) return null;
  const payload = JSON.parse(data) as Record<string, unknown>;
  if (event === "progress") return { type: "progress", data: payload as { stage: string } };
  if (event === "completed") return { type: "completed", message: payload.message as ChatMessageRead };
  if (event === "error") {
    return { type: "error", code: String(payload.code ?? "unknown"), detail: String(payload.detail ?? "") };
  }
  return null;
}

async function* readStream(url: string, text: string, signal: AbortSignal): AsyncGenerator<ProjectChatStreamEvent> {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
    signal,
  });
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
      const frame = parseStreamFrame(buffer.slice(0, split));
      if (frame) yield frame;
      buffer = buffer.slice(split + 2);
      split = buffer.indexOf("\n\n");
    }
  }
}

export interface ProjectChatSettingsPatch {
  model_override: ChatModelOverride | null;
  model_parameters: Record<string, unknown> | null;
}

/** Клиент одного проектного чата: история, черновик, контекст, модель и ход. */
export function projectChatApi(projectId: string | null, channel: ProjectChatChannel) {
  const sessions = projectId === null
    ? "/api/library/source-search-chat/sessions"
    : `/api/projects/${encodeURIComponent(projectId)}/${channel}/sessions`;
  const session = (sessionId: string) => `${sessions}/${encodeURIComponent(sessionId)}`;
  return {
    list: (signal?: AbortSignal): Promise<ProjectChatSessionSummary[]> =>
      request(sessions, { signal }),
    create: (): Promise<ProjectChatSessionDetail> => request(sessions, { method: "POST" }),
    get: (sessionId: string, signal?: AbortSignal): Promise<ProjectChatSessionDetail> =>
      request(session(sessionId), { signal }),
    saveDraft: (sessionId: string, text: string): Promise<ProjectChatSessionDetail> =>
      request(`${session(sessionId)}/draft`, { method: "PUT", body: JSON.stringify({ text }) }),
    getContext: (sessionId: string, signal?: AbortSignal): Promise<ProjectChatContextPreview> =>
      request(`${session(sessionId)}/context`, { signal }),
    updateContext: (sessionId: string, patch: ProjectChatContextPatch): Promise<ProjectChatSessionDetail> =>
      request(`${session(sessionId)}/context`, { method: "PUT", body: JSON.stringify(patch) }),
    updateSettings: (sessionId: string, patch: ProjectChatSettingsPatch): Promise<ProjectChatSessionDetail> =>
      request(`${session(sessionId)}/settings`, { method: "PUT", body: JSON.stringify(patch) }),
    send: (sessionId: string, text: string): Promise<ChatMessageRead> =>
      request(`${session(sessionId)}/messages`, { method: "POST", body: JSON.stringify({ text }) }),
    /** Ход с этапами; есть только у поиска в интернете. Отмена `signal` — остановка хода. */
    stream: (sessionId: string, text: string, signal: AbortSignal) =>
      readStream(`${session(sessionId)}/messages/stream`, text, signal),
  };
}
