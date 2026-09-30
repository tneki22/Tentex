import type { MaterialPresentationKind, PageQuality } from "./materials";
import { request } from "./projects";

export interface SearchHighlightRead {
  start: number;
  end: number;
}

/** Одна страница попадания: свои фрагменты и своё превью.
 *  Блок тянется через несколько страниц, поэтому текст лучшего фрагмента блока
 *  не годится карточке каждой страницы. */
export interface SearchResultPageRead {
  page_number: number;
  fragment_ids: string[];
  quality: PageQuality;
  text: string;
  highlights: SearchHighlightRead[];
  already_bound: boolean;
}

export interface SearchResultRead {
  fragment_ids: string[];
  material_id: string;
  material_name: string;
  /** Есть ли у материала растр страницы: предпросмотр выбирает картинку или
   *  подготовленный текст заранее, а не по ошибке 422. */
  presentation_kind: MaterialPresentationKind;
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
  pages: SearchResultPageRead[];
  retrieval_score?: number | null;
  signals?: Array<"lexical" | "semantic">;
  warning?: string | null;
}

export interface SearchResponse {
  /** Леммы, по которым искали: длинная формулировка сводится к ключевым словам. */
  terms: string[];
  prefix: string | null;
  results: SearchResultRead[];
  strategy?: "lexical" | "semantic" | "hybrid";
  index_id?: string | null;
  degraded?: boolean;
  degradation_reasons?: string[];
}

export interface ReindexResult {
  material_id: string;
  indexed_fragments: number;
}

const projectPath = (projectId: string): string => `/api/projects/${encodeURIComponent(projectId)}`;

export const searchProjectMaterials = (
  projectId: string,
  query: string,
  options: {
    materialId?: string;
    nodeId?: string;
    limit?: number;
    strategy?: "lexical" | "semantic" | "hybrid";
    scope?: "linked_topic" | "topic_project" | "project";
  } = {},
  signal?: AbortSignal,
): Promise<SearchResponse> => {
  const params = new URLSearchParams({ q: query });
  if (options.materialId) params.set("material_id", options.materialId);
  if (options.nodeId) params.set("node_id", options.nodeId);
  if (options.limit) params.set("limit", String(options.limit));
  params.set("strategy", options.strategy ?? "hybrid");
  if (options.scope) params.set("scope", options.scope);
  return request(`${projectPath(projectId)}/search?${params.toString()}`, { signal });
};

export const reindexMaterial = (projectId: string, materialId: string): Promise<ReindexResult> =>
  request(`${projectPath(projectId)}/materials/${encodeURIComponent(materialId)}/reindex`, {
    method: "POST",
  });
