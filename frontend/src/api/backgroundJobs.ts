import { request } from "./projects";
import type { ParserMode } from "./materials";

/** Виды фоновых операций (Ш1 плана): одна очередь на разбор материалов и все
 *  вызовы ИИ. Держать в синхроне с `BackgroundJobKind` в `backend/app/models.py`. */
export type BackgroundJobKind =
  | "parse"
  | "typst_compile"
  | "ai_grouping"
  | "ai_import_repair"
  | "ai_preparation"
  | "ai_cleanup"
  | "link_answers"
  | "ai_answer_sections";

export type BackgroundJobState =
  | "queued"
  | "running"
  | "paused"
  | "cancelled"
  | "failed"
  | "completed";

/** Осмысленны только у `kind === "parse"`: у ролей ИИ и `link_answers` пустые. */
export type BackgroundJobStage = "queued" | "extract" | "segment" | "complete";

export interface BackgroundJobRead {
  id: string;
  kind: BackgroundJobKind;
  state: BackgroundJobState;
  material_id: string | null;
  project_id: string | null;
  /** Имя файла или проекта, над которым идёт работа. Пустая строка — ни того, ни другого. */
  subject: string;
  /** Чем читается материал: локальный движок или внешняя модель. У ролей ИИ пусто. */
  model_label: string;
  /** Задача досчиталась, но её предложение ещё никто не принял и не убрал.
   *  Считает сервер (`registry._needs_review`) — по виду задачи и `reviewed_at`. */
  needs_review: boolean;
  stage: BackgroundJobStage | null;
  parser_mode: ParserMode | null;
  done: number;
  total: number;
  diagnostics: string[];
  error: string | null;
  pause_requested: boolean;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
  reviewed_at: string | null;
}

/** Ответ постановки в очередь: долгие операции больше не держат HTTP-запрос —
 *  эндпоинт сразу отвечает 202 и id задачи, а результат приходит через опрос. */
export interface BackgroundJobStartRead {
  job_id: string;
}

export const ACTIVE_JOB_STATES: ReadonlySet<BackgroundJobState> = new Set([
  "queued",
  "running",
  "paused",
]);

const BACKGROUND_JOBS_PATH = "/api/background-jobs";

export const listBackgroundJobs = (
  filters: {
    activeOnly?: boolean;
    /** Вместе с `activeOnly` — объединение корзин, а не пересечение. */
    pendingReview?: boolean;
    projectId?: string;
    materialId?: string;
  } = {},
  signal?: AbortSignal,
): Promise<BackgroundJobRead[]> => {
  const params = new URLSearchParams();
  if (filters.activeOnly) params.set("active_only", "true");
  if (filters.pendingReview) params.set("pending_review", "true");
  if (filters.projectId) params.set("project_id", filters.projectId);
  if (filters.materialId) params.set("material_id", filters.materialId);
  const query = params.toString();
  return request(`${BACKGROUND_JOBS_PATH}${query ? `?${query}` : ""}`, { signal });
};

export const getBackgroundJob = (jobId: string, signal?: AbortSignal): Promise<BackgroundJobRead> =>
  request(`${BACKGROUND_JOBS_PATH}/${encodeURIComponent(jobId)}`, { signal });

/** Разобранный ответ завершившейся задачи — ровно то, что вернул бы синхронный
 *  вызов. Отдельным запросом, а не полем в `BackgroundJobRead`: реестр
 *  опрашивается раз в секунду, и таскать в каждом ответе целое предложение
 *  модели незачем. Доступен только у задачи в состоянии `completed`. */
export const getBackgroundJobResult = <T>(jobId: string, signal?: AbortSignal): Promise<T> =>
  request(`${BACKGROUND_JOBS_PATH}/${encodeURIComponent(jobId)}/result`, { signal });

/** Снять задачу с корзины «ждут проверки». Зовётся после применения плана и
 *  когда результат убирают из панели не глядя; повторный вызов безвреден. */
export const resolveBackgroundJob = (jobId: string): Promise<BackgroundJobRead> =>
  request(`${BACKGROUND_JOBS_PATH}/${encodeURIComponent(jobId)}/resolve`, { method: "POST" });

export const cancelBackgroundJob = (jobId: string): Promise<BackgroundJobRead> =>
  request(`${BACKGROUND_JOBS_PATH}/${encodeURIComponent(jobId)}/cancel`, { method: "POST" });

/** Задача нужного вида, к которой диалогу есть смысл вернуться при открытии:
 *  идущая сейчас либо уже досчитавшаяся, но с неразобранным предложением.
 *
 *  Второй случай и есть починка потерянного результата: уход с экрана больше не
 *  выбрасывает готовый план — открыв диалог заново, пользователь видит его,
 *  а не платит модели второй раз за тот же вопрос. Самая свежая задача идёт
 *  первой: список отсортирован по убыванию `created_at`.
 */
export async function findResumableBackgroundJob(
  kind: BackgroundJobKind,
  filters: { projectId?: string; materialId?: string },
  signal?: AbortSignal,
): Promise<BackgroundJobRead | null> {
  const jobs = await listBackgroundJobs(
    { activeOnly: true, pendingReview: true, ...filters },
    signal,
  );
  return jobs.find((job) => job.kind === kind) ?? null;
}
