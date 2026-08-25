import type { PageQuality } from "./materials";
import { request, type LatestUndoableAction } from "./projects";

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
  kept_answers: number;
  numbered_sections: number;
  extra_sections: number;
  ordinal_rejected_reason: string | null;
  fuzzy_headings: string[];
  unmatched_headings: string[];
  duplicate_headings: string[];
  suggestions: HeadingSuggestion[];
  expected_questions: number;
  linked_node_ids: string[];
  missing_node_ids: string[];
  ambiguous_sections: string[];
  ambiguous_pages: number[];
}

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
