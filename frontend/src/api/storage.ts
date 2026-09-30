import { request } from "./projects";
import type { BackgroundJobStartRead } from "./backgroundJobs";

export interface BackupPolicy {
  automatic_enabled: boolean;
  daily_time: string;
  retention_days: number;
  backup_directory: string | null;
  last_automatic_date: string | null;
}

export interface StorageSnapshot {
  data_directory: string;
  backup_directory: string;
  same_disk_warning: boolean;
  used_bytes: number;
  free_bytes: number;
  breakdown: {
    database: number;
    files: number;
    models: number;
    backups: number;
    temporary: number;
  };
  policy: BackupPolicy;
  last_backup_at: string | null;
  maintenance: boolean;
}

export interface BackupArchive {
  id: string;
  kind: "manual" | "automatic" | "pre_restore";
  state: "queued" | "creating" | "ready" | "failed";
  job_id: string | null;
  file_name: string | null;
  size_bytes: number | null;
  sha256: string | null;
  manifest: Record<string, unknown>;
  error: string | null;
  created_at: string;
  completed_at: string | null;
}

export interface TransferPreview {
  id: string;
  kind: "backup" | "project";
  file_name: string;
  size_bytes: number;
  manifest: Record<string, unknown>;
  repeated: boolean;
}

export interface MaintenanceResult {
  ok: boolean;
  detail: string;
  checked_files: number;
  missing_files: string[];
  freed_bytes: number;
}

export const getStorage = (signal?: AbortSignal): Promise<StorageSnapshot> =>
  request("/api/settings/storage", { signal });

export const saveBackupPolicy = (policy: Omit<BackupPolicy, "last_automatic_date">): Promise<BackupPolicy> =>
  request("/api/settings/storage/backup-policy", { method: "PUT", body: JSON.stringify(policy) });

export const listBackups = (signal?: AbortSignal): Promise<BackupArchive[]> =>
  request("/api/backups", { signal });

export const createBackup = (): Promise<{ backup_id: string; job_id: string }> =>
  request("/api/backups", { method: "POST" });

export const deleteBackup = (id: string): Promise<void> =>
  request(`/api/backups/${encodeURIComponent(id)}`, { method: "DELETE" });

export const backupDownloadUrl = (id: string): string =>
  `/api/backups/${encodeURIComponent(id)}/file`;

export async function uploadTransfer(file: File): Promise<TransferPreview> {
  const body = new FormData();
  body.append("file", file);
  return request("/api/storage/transfers", { method: "POST", body });
}

export const restoreBackup = (id: string): Promise<{ operation_id: string; state: string }> =>
  request(`/api/storage/transfers/${encodeURIComponent(id)}/restore`, { method: "POST" });

export const restoreManagedBackup = (id: string): Promise<{ operation_id: string; state: string }> =>
  request(`/api/backups/${encodeURIComponent(id)}/restore`, { method: "POST" });

export const getRestoreStatus = (id: string): Promise<{
  operation_id: string;
  state: "waiting" | "running" | "completed" | "failed" | "rolled_back";
  detail: string;
}> => request(`/api/storage/restores/${encodeURIComponent(id)}`);

export const exportProject = (
  projectId: string,
  profile: "personal" | "share",
): Promise<{ artifact_id: string; job_id: string }> => request(
  `/api/projects/${encodeURIComponent(projectId)}/exports`,
  { method: "POST", body: JSON.stringify({ profile }) },
);

export const transferDownloadUrl = (id: string): string =>
  `/api/storage/transfers/${encodeURIComponent(id)}/file`;

export const importProject = (
  id: string,
  allowDuplicate: boolean,
): Promise<{ artifact_id: string; job_id: string }> => request(
  `/api/storage/transfers/${encodeURIComponent(id)}/import-project`,
  { method: "POST", body: JSON.stringify({ allow_duplicate: allowDuplicate }) },
);

/** Проверка сканирует всю SQLite: на медленном диске это минуты, поэтому
 *  эндпоинт ставит задачу в очередь (202) вместо синхронного ответа. */
export const verifyStorage = (): Promise<BackgroundJobStartRead> =>
  request("/api/storage/verify", { method: "POST" });

export const cleanupStorage = (): Promise<BackgroundJobStartRead> =>
  request("/api/storage/cleanup", { method: "POST" });
