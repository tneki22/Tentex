import { request } from "./projects";

export type SourceKind = "article" | "video" | "pdf" | "course" | "book" | "other";

/** Страница из выдачи поиска в сети, которую модель предложила как материал. */
export interface SourceCandidate {
  url: string;
  title: string;
  kind: SourceKind;
  why: string;
  /** Фрагмент найденной страницы из выдачи, а не пересказ модели. */
  snippet: string;
  /** Ссылка и YouTube добавляются сразу; PDF по ссылке — только скачанным файлом. */
  import_kind: "url" | "youtube" | "pdf_manual";
}

/** Результат задачи `ai_source_search` — `GET /background-jobs/{id}/result`. */
export interface SourceSearchResult {
  query: string;
  program_node_id: string | null;
  candidates: SourceCandidate[];
  /** Адреса не из выдачи поиска: модель их придумала, сервер отбросил. */
  unverified_count: number;
  already_attached_count: number;
  run_id: string;
  actual_model_id: string;
}

/** Поставить поиск в очередь; нажатие «Найти» и есть подтверждение платного вызова. */
export const startSourceSearch = (
  projectId: string,
  command: { query: string; program_node_id?: string | null },
): Promise<{ job_id: string }> => request(`/api/projects/${encodeURIComponent(projectId)}/source-search`, {
  method: "POST",
  body: JSON.stringify({ ...command, confirmed: true }),
});
