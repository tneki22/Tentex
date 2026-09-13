import type { ChatMessageRead } from "./chat";
import type { ProgramChangeResult } from "./projects";
import { request } from "./projects";

export interface ProgramChatSessionSummary {
  id: string;
  project_id: string;
  title: string;
  updated_at: string;
  message_count: number;
}

export interface ProgramChatSessionDetail {
  id: string;
  project_id: string;
  section_scope_node_id: string | null;
  title: string;
  context_flags: Record<string, boolean>;
  draft_text: string;
  created_at: string;
  updated_at: string;
  messages: ChatMessageRead[];
}

export interface ProgramChatManifestEntry {
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

export interface ProgramChatContextPreview {
  session_id: string;
  manifest: ProgramChatManifestEntry[];
  fingerprint: string;
  total_bytes: number;
}

export interface ProgramChatContextPatch {
  section_scope_node_id?: string | null;
  context_flags?: Record<string, boolean>;
}

const programChatPath = (projectId: string): string =>
  `/api/projects/${encodeURIComponent(projectId)}/program-chat`;

export const listProgramChatSessions = (
  projectId: string,
  signal?: AbortSignal,
): Promise<ProgramChatSessionSummary[]> =>
  request(`${programChatPath(projectId)}/sessions`, { signal });

export const createProgramChatSession = (
  projectId: string,
): Promise<ProgramChatSessionDetail> =>
  request(`${programChatPath(projectId)}/sessions`, { method: "POST" });

export const getProgramChatSession = (
  projectId: string,
  sessionId: string,
  signal?: AbortSignal,
): Promise<ProgramChatSessionDetail> =>
  request(`${programChatPath(projectId)}/sessions/${encodeURIComponent(sessionId)}`, { signal });

export const saveProgramChatDraft = (
  projectId: string,
  sessionId: string,
  text: string,
): Promise<ProgramChatSessionDetail> => request(
  `${programChatPath(projectId)}/sessions/${encodeURIComponent(sessionId)}/draft`,
  { method: "PUT", body: JSON.stringify({ text }) },
);

export const getProgramChatContext = (
  projectId: string,
  sessionId: string,
  signal?: AbortSignal,
): Promise<ProgramChatContextPreview> =>
  request(`${programChatPath(projectId)}/sessions/${encodeURIComponent(sessionId)}/context`, { signal });

export const updateProgramChatContext = (
  projectId: string,
  sessionId: string,
  patch: ProgramChatContextPatch,
): Promise<ProgramChatSessionDetail> => request(
  `${programChatPath(projectId)}/sessions/${encodeURIComponent(sessionId)}/context`,
  { method: "PUT", body: JSON.stringify(patch) },
);

export const sendProgramChatMessage = (
  projectId: string,
  sessionId: string,
  text: string,
): Promise<ChatMessageRead> => request(
  `${programChatPath(projectId)}/sessions/${encodeURIComponent(sessionId)}/messages`,
  { method: "POST", body: JSON.stringify({ text }) },
);

export const applyProgramChatProposal = (
  projectId: string,
  messageId: string,
  selected: number[],
  expectedProgramRevision: number,
): Promise<ProgramChangeResult> => request(
  `${programChatPath(projectId)}/proposals/${encodeURIComponent(messageId)}/apply`,
  {
    method: "POST",
    body: JSON.stringify({ selected, expected_program_revision: expectedProgramRevision }),
  },
);

export const rejectProgramChatProposal = (
  projectId: string,
  messageId: string,
): Promise<ChatMessageRead> => request(
  `${programChatPath(projectId)}/proposals/${encodeURIComponent(messageId)}/reject`,
  { method: "POST" },
);
