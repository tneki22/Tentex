import type { PageQuality } from "./materials";
import { ProjectApiError, request, type LatestUndoableAction } from "./projects";

export type BindingStatus = "manual" | "confirmed" | "machine" | "removed" | "orphaned";
export type BindingMechanism = "manual" | "search" | "answers_file" | "pass_two";

export interface HeadingSuggestionCandidate {
  node_id: string;
  node_title: string;
  score: number;
}

export interface HeadingSuggestion {
  anchor_fragment_id: string;
  heading: string;
  preview: string | null;
  page_from: number;
  candidates: HeadingSuggestionCandidate[];
}

export interface AnswersLinkRead {
  linked_sections: number;
  linked_fragments: number;
  created_answers: number;
  updated_answers: number;
  restored_answers: number;
  unchanged_answers: number;
  preserved_answers: number;
  numbered_sections: number;
  extra_sections: number;
  ordinal_rejected_reason: string | null;
  fuzzy_headings: string[];
  unmatched_headings: string[];
  duplicate_headings: string[];
  suggestions: HeadingSuggestion[];
  expected_questions: number;
  matched_node_ids: string[];
  available_node_ids: string[];
  unavailable_node_ids: string[];
  missing_node_ids: string[];
  ambiguous_sections: string[];
  ambiguous_pages: number[];
  complete: boolean;
}

export type AnswerLinkPhase = "preparing" | "matching" | "binding" | "importing" | "verifying";

export interface AnswersLinkProgress {
  phase: AnswerLinkPhase;
  completed: number;
  total: number;
  phase_completed: number;
  phase_total: number;
}

export type AnswersLinkStreamEvent =
  | { type: "progress"; progress: AnswersLinkProgress }
  | { type: "completed"; result: AnswersLinkRead };

export interface BindingFragmentRead {
  id: string;
  project_id: string;
  program_node_id: string;
  node_title: string;
  fragment_id: string;
  material_id: string;
  material_name: string;
  block_id: string | null;
  page_number: number;
  text: string;
  bbox: number[];
  element_kind: string;
  asset_label: string | null;
  quality: PageQuality;
  status: BindingStatus;
  mechanism: BindingMechanism;
  created_at: string;
  updated_at: string;
}

export interface BindingChangeResult {
  bindings: BindingFragmentRead[];
  latest_undoable_action: LatestUndoableAction | null;
}

export interface NodeBindingSummary {
  program_node_id: string;
  fragment_count: number;
  material_count: number;
  worst_quality: PageQuality | null;
}

export interface BindingCreateCommand {
  program_node_id: string;
  fragment_ids?: string[];
  block_id?: string;
  mechanism?: BindingMechanism;
}

const bindingsPath = (projectId: string): string =>
  `/api/projects/${encodeURIComponent(projectId)}/bindings`;

export const listBindings = (
  projectId: string,
  filters: { nodeId?: string; materialId?: string; page?: number; status?: BindingStatus } = {},
  signal?: AbortSignal,
): Promise<BindingFragmentRead[]> => {
  const params = new URLSearchParams();
  if (filters.nodeId) params.set("node_id", filters.nodeId);
  if (filters.materialId) params.set("material_id", filters.materialId);
  if (filters.page) params.set("page", String(filters.page));
  if (filters.status) params.set("status", filters.status);
  const query = params.toString();
  return request(`${bindingsPath(projectId)}${query ? `?${query}` : ""}`, { signal });
};

export const getBindingsSummary = (
  projectId: string,
  signal?: AbortSignal,
): Promise<NodeBindingSummary[]> => request(`${bindingsPath(projectId)}/summary`, { signal });

export const createBindings = (
  projectId: string,
  command: BindingCreateCommand,
): Promise<BindingChangeResult> => request(bindingsPath(projectId), {
  method: "POST",
  body: JSON.stringify(command),
});

export const removeBinding = (
  projectId: string,
  bindingId: string,
): Promise<BindingChangeResult> => request(
  `${bindingsPath(projectId)}/${encodeURIComponent(bindingId)}`,
  { method: "DELETE" },
);

export const removeBindingsBulk = (
  projectId: string,
  command: { materialId: string; pageNumber?: number },
): Promise<BindingChangeResult> => request(`${bindingsPath(projectId)}/bulk-remove`, {
  method: "POST",
  body: JSON.stringify({ material_id: command.materialId, page_number: command.pageNumber ?? null }),
});

export const linkAnswersMaterial = (
  projectId: string,
  materialId: string,
): Promise<AnswersLinkRead> => request(
  `/api/projects/${encodeURIComponent(projectId)}/materials/${encodeURIComponent(materialId)}/link-answers`,
  { method: "POST" },
);

function parseAnswerLinkFrame(raw: string): AnswersLinkStreamEvent | null {
  let event = "";
  let data = "";
  for (const line of raw.split("\n")) {
    if (line.startsWith("event: ")) event = line.slice(7).trim();
    else if (line.startsWith("data: ")) data += line.slice(6);
  }
  if (!event || !data) return null;
  const payload = JSON.parse(data) as Record<string, unknown>;
  if (event === "progress") {
    return { type: "progress", progress: payload as unknown as AnswersLinkProgress };
  }
  if (event === "completed") {
    return { type: "completed", result: payload as unknown as AnswersLinkRead };
  }
  if (event === "error") {
    throw new ProjectApiError(
      409,
      String(payload.detail ?? "Не удалось сопоставить ответы"),
      String(payload.code ?? "answer_matching_failed"),
    );
  }
  return null;
}

export async function* streamAnswersLink(
  projectId: string,
  materialId: string,
  signal: AbortSignal,
): AsyncGenerator<AnswersLinkStreamEvent> {
  const response = await fetch(
    `/api/projects/${encodeURIComponent(projectId)}/materials/${encodeURIComponent(materialId)}/link-answers/stream`,
    { method: "POST", signal },
  );
  if (!response.ok || !response.body) {
    const payload = await response.json().catch(() => null) as { detail?: string; code?: string } | null;
    throw new ProjectApiError(
      response.status,
      payload?.detail ?? "Не удалось сопоставить ответы",
      payload?.code ?? null,
    );
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
      const event = parseAnswerLinkFrame(buffer.slice(0, split));
      if (event) yield event;
      buffer = buffer.slice(split + 2);
      split = buffer.indexOf("\n\n");
    }
  }
}

export const resolveAnswersHeading = (
  projectId: string,
  materialId: string,
  command: { anchorFragmentId: string; programNodeId: string },
): Promise<AnswersLinkRead> => request(
  `/api/projects/${encodeURIComponent(projectId)}/materials/${encodeURIComponent(materialId)}/link-answers/resolve`,
  {
    method: "POST",
    body: JSON.stringify({
      anchor_fragment_id: command.anchorFragmentId,
      program_node_id: command.programNodeId,
    }),
  },
);

export const restoreBinding = (
  projectId: string,
  bindingId: string,
): Promise<BindingChangeResult> => request(
  `${bindingsPath(projectId)}/${encodeURIComponent(bindingId)}/restore`,
  { method: "POST" },
);
