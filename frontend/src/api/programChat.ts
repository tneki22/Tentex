import type { ChatMessageRead } from "./chat";
import type { ProgramChangeResult } from "./projects";
import { request } from "./projects";

const programChatPath = (projectId: string): string =>
  `/api/projects/${encodeURIComponent(projectId)}/program-chat`;

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
