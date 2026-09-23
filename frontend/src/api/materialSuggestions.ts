import { request } from "./projects";

/** Материал Библиотеки, найденный под цель или тему проекта (без модели). */
export interface MaterialSuggestion {
  material_id: string;
  display_name: string;
  subject: string | null;
  page_count: number | null;
  has_outline: boolean;
  subject_match: boolean;
  hit_count: number;
  signals: Array<"lexical" | "semantic">;
  block_title: string | null;
  page_from: number | null;
  page_to: number | null;
  excerpt: string;
}

export interface MaterialSuggestions {
  query: string;
  items: MaterialSuggestion[];
  /** Активного индекса нет — подбор шёл только по словам. */
  words_only: boolean;
}

export interface MaterialSuggestionsResult {
  by_query: MaterialSuggestions | null;
  by_node: Record<string, MaterialSuggestions>;
}

const path = (projectId: string) =>
  `/api/projects/${encodeURIComponent(projectId)}/material-suggestions`;

export const suggestMaterialsForQuery = (
  projectId: string,
  query: string,
  signal?: AbortSignal,
): Promise<MaterialSuggestionsResult> => request(path(projectId), {
  method: "POST",
  body: JSON.stringify({ query }),
  signal,
});

export const suggestMaterialsForNodes = (
  projectId: string,
  nodeIds: string[],
  signal?: AbortSignal,
): Promise<MaterialSuggestionsResult> => request(path(projectId), {
  method: "POST",
  body: JSON.stringify({ node_ids: nodeIds, limit: 3 }),
  signal,
});
