import type { ChatMessageRead, ChatModelOverride } from "./chat";
import { request } from "./projects";

/** Проектные чаты без темы устроены одинаково (`app/chat/project_sessions.py`)
 * и различаются только сегментом пути. */
export type ProjectChatChannel = "program-chat" | "source-search-chat";

export interface ProjectChatSessionSummary {
  id: string;
  project_id: string;
  title: string;
  updated_at: string;
  message_count: number;
}

export interface ProjectChatSessionDetail {
  id: string;
  project_id: string;
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
  count: number | null;
  reason: string | null;
  flag_key: string | null;
  label: string | null;
}

export interface ProjectChatContextPreview {
  session_id: string;
  manifest: ProjectChatManifestEntry[];
  fingerprint: string;
  total_bytes: number;
}

export interface ProjectChatContextPatch {
  section_scope_node_id?: string | null;
  context_flags?: Record<string, boolean>;
}

export interface ProjectChatSettingsPatch {
  model_override: ChatModelOverride | null;
  model_parameters: Record<string, unknown> | null;
}

/** Клиент одного проектного чата: история, черновик, контекст, модель и ход. */
export function projectChatApi(projectId: string, channel: ProjectChatChannel) {
  const sessions = `/api/projects/${encodeURIComponent(projectId)}/${channel}/sessions`;
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
  };
}
