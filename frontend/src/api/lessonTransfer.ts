import type { LessonSummaryRead } from "./lessons";
import { ProjectApiError, request, type LatestUndoableAction } from "./projects";

/**
 * Экспорт уроков одним файлом и перенос уроков файлом `.tentex-lessons`.
 * Контракт — `docs/architecture/lessons.md`, «Экспорт и перенос уроков».
 */

export type LessonExportFormat = "pdf" | "latex" | "markdown" | "tentex";
/** Кусок материала в файле: текстом фрагментов, листами страниц или строкой-ссылкой. */
export type LessonExportSources = "text" | "pages" | "reference";

export interface LessonExportCommand {
  lesson_ids: string[];
  format: LessonExportFormat;
  sources: LessonExportSources;
  answers: boolean;
}

export interface DownloadedFile {
  blob: Blob;
  filename: string;
}

const lessonsPath = (projectId: string): string =>
  `/api/projects/${encodeURIComponent(projectId)}/lessons`;

/** Имя из `Content-Disposition`: у русских названий оно приходит в `filename*=utf-8''…`. */
function dispositionName(header: string | null, fallback: string): string {
  if (!header) return fallback;
  const encoded = /filename\*=(?:UTF-8|utf-8)''([^;]+)/.exec(header);
  if (encoded) {
    try { return decodeURIComponent(encoded[1]); } catch { /* ниже — обычное имя */ }
  }
  const plain = /filename="?([^";]+)"?/.exec(header);
  return plain ? plain[1] : fallback;
}

/** Файл собирается в запросе: PDF с формулами — секунды, с листами страниц — дольше. */
export async function exportLessons(
  projectId: string, command: LessonExportCommand, signal?: AbortSignal,
): Promise<DownloadedFile> {
  const response = await fetch(`${lessonsPath(projectId)}/export`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(command),
    signal,
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => null) as { detail?: unknown; code?: unknown } | null;
    const message = typeof payload?.detail === "string" ? payload.detail : "Файл не собрался";
    throw new ProjectApiError(response.status, message, typeof payload?.code === "string" ? payload.code : null);
  }
  return { blob: await response.blob(), filename: dispositionName(response.headers.get("Content-Disposition"), "уроки") };
}

/** Сохранить полученный файл: браузер спрашивает место или кладёт в «Загрузки». */
export function saveFile({ blob, filename }: DownloadedFile): void {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.append(link);
  link.click();
  link.remove();
  // Ссылка нужна до начала загрузки; отзывать сразу — Firefox не успевает её прочитать.
  window.setTimeout(() => URL.revokeObjectURL(url), 30_000);
}

export type LessonImportMaterialStatus = "project" | "library" | "missing";

export interface LessonImportMaterialRead {
  key: string;
  name: string;
  status: LessonImportMaterialStatus;
  material_id: string | null;
  pieces: number;
}

export interface LessonImportLessonRead {
  key: string;
  title: string;
  topic_titles: string[];
  blocks: number;
  pieces: number;
  tasks: number;
  /** Тема этого проекта с той же формулировкой; `null` — выбрать вручную. */
  program_node_id: string | null;
}

export interface LessonImportPreviewRead {
  source_project: string;
  exported_at: string | null;
  lessons: LessonImportLessonRead[];
  materials: LessonImportMaterialRead[];
}

export interface LessonImportOptions {
  lessons: Array<{ key: string; program_node_id: string }>;
  /** Ключ материала файла → материал этой установки; `null` — кусок останется снимком текста. */
  materials: Record<string, string | null>;
}

export interface LessonImportResult {
  lessons: LessonSummaryRead[];
  latest_undoable_action: LatestUndoableAction | null;
  linked_pieces: number;
  snapshot_pieces: number;
  attached_materials: number;
}

export const LESSON_PACKAGE_SUFFIX = ".tentex-lessons";

export function previewLessonImport(projectId: string, file: File): Promise<LessonImportPreviewRead> {
  const body = new FormData();
  body.append("file", file);
  return request(`${lessonsPath(projectId)}/import/preview`, { method: "POST", body });
}

export function importLessons(projectId: string, file: File, options: LessonImportOptions): Promise<LessonImportResult> {
  const body = new FormData();
  body.append("file", file);
  body.append("options", JSON.stringify(options));
  return request(`${lessonsPath(projectId)}/import`, { method: "POST", body });
}
