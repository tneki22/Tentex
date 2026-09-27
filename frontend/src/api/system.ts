import { ProjectApiError, request } from "./projects";

/** Схемы — `backend/app/system/schemas.py`. */
export type StatusLevel = "danger" | "warning" | "unknown" | "info" | "ok";
export type StatusSection = "attention" | "storage" | "capabilities";
export type StatusOverall = "attention" | "warning" | "ok";
export type StatusCommand = "probe_database" | "create_backup" | "verify_storage" | "open_background_jobs";

export interface SystemStatusTarget {
  kind: "link" | "command";
  label: string;
  href: string | null;
  command: StatusCommand | null;
}

export interface SystemStatusItem {
  code: string;
  level: StatusLevel;
  section: StatusSection;
  title: string;
  action: string | null;
  target: SystemStatusTarget | null;
  last_failure_at: string | null;
  occurrences: number | null;
}

export interface SystemStorage {
  used_bytes: number | null;
  free_bytes: number;
  total_bytes: number;
  last_backup_at: string | null;
  backup_in_progress: boolean;
  automatic_enabled: boolean | null;
  daily_time: string | null;
  retention_days: number | null;
}

export interface SystemStatus {
  checked_at: string;
  overall: StatusOverall;
  attention_count: number;
  items: SystemStatusItem[];
  storage: SystemStorage | null;
}

export interface SystemProbe {
  ok: boolean;
  status: SystemStatus;
}

/** Локальный сервер не ответил вовсе: Vite-прокси отдал 502–504 без тела или
 *  сам браузер не достучался. Отличается от ответа сервера с ошибкой. */
export class ApiUnreachableError extends Error {
  constructor() {
    super("Нет связи с локальным сервером");
    this.name = "ApiUnreachableError";
  }
}

/* `request()` повторяет GET при старте API до ~11 с — сводке это вредно: пока
   идут повторы, кнопка молчит о том, что сервер не отвечает. Здесь одна
   короткая пауза на перезапуск uvicorn с --reload и честный ответ. */
const UNREACHABLE_STATUSES = new Set([502, 503, 504]);
const RETRY_DELAY_MS = 1200;

async function fetchStatusOnce(signal?: AbortSignal): Promise<SystemStatus> {
  let response: Response;
  try {
    response = await fetch("/api/system/status", { headers: { Accept: "application/json" }, signal });
  } catch (error) {
    if (signal?.aborted) throw error;
    throw new ApiUnreachableError();
  }
  const payload: unknown = await response.json().catch(() => null);
  if (response.ok && payload) return payload as SystemStatus;
  if (payload === null && UNREACHABLE_STATUSES.has(response.status)) throw new ApiUnreachableError();
  const record = (payload ?? {}) as { detail?: unknown; code?: unknown };
  throw new ProjectApiError(
    response.status,
    typeof record.detail === "string" ? record.detail : "Сводка не загрузилась",
    typeof record.code === "string" ? record.code : null,
  );
}

export async function getSystemStatus(signal?: AbortSignal): Promise<SystemStatus> {
  try {
    return await fetchStatusOnce(signal);
  } catch (error) {
    if (!(error instanceof ApiUnreachableError)) throw error;
    await new Promise((resolve) => setTimeout(resolve, RETRY_DELAY_MS));
    if (signal?.aborted) throw error;
    return fetchStatusOnce(signal);
  }
}

/** «Проверить»: короткая проба записи без изменений и свежая сводка. */
export const probeWriteAccess = (): Promise<SystemProbe> =>
  request("/api/system/write-probe", { method: "POST" });
