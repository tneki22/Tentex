import { request } from "./projects";
import type { ParserMode } from "./materials";

export type OcrEngineRuntime = "worker" | "gpu_service" | "cloud";

/** Машинное состояние движка. Заголовок и цвет подбираются на экране. */
export type OcrReadiness =
  | "ready"
  | "downloading"
  | "needs_models"
  | "needs_service"
  | "starting"
  | "error"
  | "unavailable";

export type OcrJobState = "running" | "done" | "failed" | "cancelled";

export type OcrServiceState =
  | "running"
  | "starting"
  | "stopped"
  | "failed"
  | "absent"
  | "unavailable";

export interface OcrModelRead {
  key: string;
  engine: string;
  title: string;
  summary: string;
  good_for: string;
  source_title: string;
  source_url: string;
  repos: string[];
  license_title: string;
  license_url: string;
  size_bytes: number;
  device: "cpu" | "gpu";
  languages: string;
  min_vram_mb: number | null;
  recommended_vram_mb: number | null;
  min_ram_mb: number;
  notes: string[];
  recommended: boolean;
  installed: boolean;
  installed_bytes: number;
  /** `null` — проверить не удалось. Это не «не подойдёт». */
  fits: boolean | null;
  fits_note: string;
  job_state: OcrJobState | null;
  job_cancel_requested: boolean;
  job_done_bytes: number;
  job_total_bytes: number;
  job_current: string;
  job_error: string;
}

export interface OcrGpuRead {
  name: string;
  vram_mb: number | null;
  driver: string | null;
  source: string;
}

export interface OcrHardwareRead {
  cpu_cores: number | null;
  ram_mb: number | null;
  free_disk_mb: number | null;
  gpu: OcrGpuRead | null;
  gpu_reason: string;
  notes: string[];
}

export interface OcrServiceRead {
  state: OcrServiceState;
  summary: string;
  detail: string;
  can_start: boolean;
  can_stop: boolean;
}

export interface OcrEngineRead {
  mode: string;
  title: string;
  description: string;
  trade_off: string;
  runtime: OcrEngineRuntime;
  configurable: boolean;
  enabled: boolean;
  available: boolean;
  readiness: OcrReadiness;
  status_detail: string;
  active_label: string;
  restart_required: boolean;
  model_id: string | null;
  device: string | null;
  language: string | null;
  executor: string | null;
  extra: Record<string, unknown>;
  updated_at: string | null;
  models: OcrModelRead[];
  service: OcrServiceRead | null;
}

export interface OcrSettingsRead {
  default_mode: ParserMode;
  quality_threshold: number;
  raster_scale: number;
  hardware: OcrHardwareRead;
  engines: OcrEngineRead[];
}

export interface OcrGlobalSettingsWrite {
  default_mode: ParserMode;
  quality_threshold: number;
  raster_scale: number;
}

export interface OcrEngineWrite {
  model_id: string | null;
  device: string | null;
  language: string | null;
  executor: string | null;
  extra: Record<string, unknown>;
}

const BASE_PATH = "/api/settings/ocr";

export const getOcrSettings = (
  signal?: AbortSignal,
  options?: { refresh?: boolean }
): Promise<OcrSettingsRead> =>
  request(options?.refresh ? `${BASE_PATH}?refresh=true` : BASE_PATH, { signal });

export const updateOcrSettings = (
  command: OcrGlobalSettingsWrite
): Promise<OcrSettingsRead> =>
  request(BASE_PATH, { method: "PUT", body: JSON.stringify(command) });

export const updateOcrEngine = (
  mode: string,
  command: OcrEngineWrite
): Promise<OcrSettingsRead> =>
  request(`${BASE_PATH}/engines/${encodeURIComponent(mode)}`, {
    method: "PUT",
    body: JSON.stringify(command),
  });

/** Отвечает сразу: загрузка идёт в фоне, прогресс приезжает следующим GET. */
export const installOcrModel = (key: string): Promise<OcrSettingsRead> =>
  request(`${BASE_PATH}/models/${encodeURIComponent(key)}/install`, { method: "POST" });

export const cancelOcrModel = (key: string): Promise<OcrSettingsRead> =>
  request(`${BASE_PATH}/models/${encodeURIComponent(key)}/cancel`, { method: "POST" });

export const removeOcrModel = (key: string): Promise<OcrSettingsRead> =>
  request(`${BASE_PATH}/models/${encodeURIComponent(key)}`, { method: "DELETE" });

export const startOcrService = (): Promise<OcrSettingsRead> =>
  request(`${BASE_PATH}/service/start`, { method: "POST" });

export const stopOcrService = (): Promise<OcrSettingsRead> =>
  request(`${BASE_PATH}/service/stop`, { method: "POST" });
