import type { PageQuality } from "./materials";
import { request } from "./projects";

export interface SearchHighlightRead {
  start: number;
  end: number;
}

export interface SearchResultRead {
  fragment_ids: string[];
  material_id: string;
  material_name: string;
  block_id: string;
  block_title: string | null;
  page_from: number;
  page_to: number;
  quality: PageQuality;
  text: string;
  highlights: SearchHighlightRead[];
  /** Словоформы из текста, совпавшие с запросом, — для подсветки на клиенте. */
  matched_forms: string[];
  already_bound: boolean;
}

export interface SearchResponse {
  /** Леммы, по которым искали: длинная формулировка сводится к ключевым словам. */
  terms: string[];
  prefix: string | null;
  results: SearchResultRead[];
}

export interface ReindexResult {
  material_id: string;
  indexed_fragments: number;
}

const projectPath = (projectId: string): string => `/api/projects/${encodeURIComponent(projectId)}`;

export const searchProjectMaterials = (
  projectId: string,
  query: string,
  options: { materialId?: string; nodeId?: string; limit?: number } = {},
  signal?: AbortSignal,
): Promise<SearchResponse> => {
  const params = new URLSearchParams({ q: query });
  if (options.materialId) params.set("material_id", options.materialId);
  if (options.nodeId) params.set("node_id", options.nodeId);
  if (options.limit) params.set("limit", String(options.limit));
  return request(`${projectPath(projectId)}/search?${params.toString()}`, { signal });
};

export const reindexMaterial = (projectId: string, materialId: string): Promise<ReindexResult> =>
  request(`${projectPath(projectId)}/materials/${encodeURIComponent(materialId)}/reindex`, {
    method: "POST",
  });
