import {
  Archive,
  Check,
  CheckCircle2,
  Copy,
  Download,
  FolderArchive,
  HardDrive,
  RefreshCw,
  ShieldCheck,
  Trash2,
  Upload,
} from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { ACTIVE_JOB_STATES, getBackgroundJobResult } from "../api/backgroundJobs";
import { listProjects, type ProjectSummary } from "../api/projects";
import {
  backupDownloadUrl,
  cleanupStorage,
  createBackup,
  deleteBackup,
  exportProject,
  getRestoreStatus,
  getStorage,
  importProject,
  listBackups,
  restoreBackup,
  restoreManagedBackup,
  saveBackupPolicy,
  transferDownloadUrl,
  uploadTransfer,
  verifyStorage,
  type BackupArchive,
  type MaintenanceResult,
  type StorageSnapshot,
  type TransferPreview,
} from "../api/storage";
import { useBackgroundJob } from "../hooks/useBackgroundJob";
import {
  Button,
  ConfirmDialog,
  Dialog,
  ErrorState,
  Field,
  LoadingState,
  Select,
  StatusBadge,
  Switch,
} from "../components/ui";
import type { StorageSettingsSubsection } from "./Setup";

const SUBSECTIONS = ["overview", "backups", "projects", "maintenance"] as const;

type WatchedAction = "backup" | "export" | "import" | "verify" | "cleanup";

const BACKUP_KIND: Record<BackupArchive["kind"], string> = {
  manual: "Вручную",
  automatic: "Автоматически",
  pre_restore: "Перед восстановлением",
};

const BACKUP_STATE: Record<BackupArchive["state"], { label: string; tone: "neutral" | "info" | "success" | "danger" }> = {
  queued: { label: "В очереди", tone: "neutral" },
  creating: { label: "Создаётся", tone: "info" },
  ready: { label: "Проверена", tone: "success" },
  failed: { label: "Ошибка", tone: "danger" },
};

function bytes(value: number | null): string {
  if (value === null) return "—";
  if (value < 1024) return `${value} Б`;
  const units = ["КБ", "МБ", "ГБ", "ТБ"];
  let amount = value / 1024;
  let unit = units[0];
  for (let index = 1; index < units.length && amount >= 1024; index += 1) {
    amount /= 1024;
    unit = units[index];
  }
  return `${amount.toLocaleString("ru-RU", { maximumFractionDigits: amount >= 10 ? 1 : 2 })} ${unit}`;
}

function dateTime(value: string | null): string {
  return value ? new Date(value).toLocaleString("ru-RU", { dateStyle: "medium", timeStyle: "short" }) : "Ещё не создавалась";
}

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : "Не удалось выполнить действие";
}

/** Причина падения фоновой задачи — техническая строка исключения, не для
 *  пользователя. Понятный смысл уже виден по действию, которое не удалось. */
const WATCHED_ACTION_FAILURE: Record<WatchedAction, string> = {
  backup: "Не удалось создать резервную копию.",
  export: "Не удалось подготовить пакет проекта.",
  import: "Не удалось импортировать пакет проекта.",
  verify: "Не удалось проверить хранилище.",
  cleanup: "Не удалось очистить временные файлы.",
};

/** Единый живой раздел хранения: настройки, архивы и проектные пакеты. */
export function StorageSettingsSection({
  subsection,
  onActiveSubsection,
}: {
  subsection: StorageSettingsSubsection;
  onActiveSubsection: (value: string) => void;
}) {
  const [snapshot, setSnapshot] = useState<StorageSnapshot | null>(null);
  const [backups, setBackups] = useState<BackupArchive[]>([]);
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");
  const [feedback, setFeedback] = useState("");
  const [watched, setWatched] = useState<{ jobId: string; artifactId?: string; action: WatchedAction } | null>(null);
  const [copiedPath, setCopiedPath] = useState<string | null>(null);
  const watchedJob = useBackgroundJob(watched?.jobId ?? null);
  const [preview, setPreview] = useState<TransferPreview | null>(null);
  const [restoreConfirm, setRestoreConfirm] = useState(false);
  const [restoreManaged, setRestoreManaged] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<BackupArchive | null>(null);
  const [projectId, setProjectId] = useState<string | null>(null);
  const [profile, setProfile] = useState<"personal" | "share">("share");
  const [maintenanceResult, setMaintenanceResult] = useState<MaintenanceResult | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const initialSubsection = useRef(subsection);
  const initialScrollDone = useRef(false);

  const load = useCallback(async (signal?: AbortSignal) => {
    try {
      const [nextSnapshot, nextBackups, nextProjects] = await Promise.all([
        getStorage(signal),
        listBackups(signal),
        listProjects(signal),
      ]);
      setSnapshot(nextSnapshot);
      setBackups(nextBackups);
      setProjects(nextProjects);
      setProjectId((current) => current ?? nextProjects[0]?.id ?? null);
      setError("");
    } catch (caught) {
      if (!signal?.aborted) setError(errorText(caught));
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load]);

  useEffect(() => {
    onActiveSubsection(subsection);
  }, [onActiveSubsection, subsection]);

  useEffect(() => {
    if (!snapshot || initialScrollDone.current || initialSubsection.current === "overview") return;
    initialScrollDone.current = true;
    window.requestAnimationFrame(() => {
      document.getElementById(`storage-${initialSubsection.current}`)?.scrollIntoView({ block: "start" });
    });
  }, [snapshot]);

  useEffect(() => {
    if (!snapshot) return;
    const sections = SUBSECTIONS
      .map((id) => document.getElementById(`storage-${id}`))
      .filter((section): section is HTMLElement => section !== null);
    const observer = new IntersectionObserver((entries) => {
      const active = entries
        .filter((entry) => entry.isIntersecting)
        .sort((left, right) => left.boundingClientRect.top - right.boundingClientRect.top)[0];
      if (active) onActiveSubsection(active.target.id.replace("storage-", ""));
    }, { rootMargin: "-12% 0px -72% 0px" });
    sections.forEach((section) => observer.observe(section));
    return () => observer.disconnect();
  }, [onActiveSubsection, snapshot]);

  useEffect(() => {
    const job = watchedJob.job;
    if (!watched || !job || ACTIVE_JOB_STATES.has(job.state)) return;
    if (job.state === "completed") {
      if (watched.action === "export" && watched.artifactId) {
        window.location.assign(transferDownloadUrl(watched.artifactId));
        setFeedback("Пакет проекта готов и скачивается.");
      } else if (watched.action === "import") {
        setFeedback("Проект импортирован рядом с существующими проектами.");
      } else if (watched.action === "verify" || watched.action === "cleanup") {
        void getBackgroundJobResult<MaintenanceResult>(watched.jobId).then(setMaintenanceResult);
        if (watched.action === "cleanup") void load();
      } else {
        setFeedback("Резервная копия готова.");
      }
      if (watched.action !== "verify" && watched.action !== "cleanup") void load();
    } else if (job.state === "failed") {
      setError(WATCHED_ACTION_FAILURE[watched.action]);
    }
    setWatched(null);
  }, [load, watched, watchedJob.job]);

  if (!snapshot && !error) return <LoadingState label="Собираем сведения о хранилище…" />;
  if (!snapshot) return <ErrorState title="Хранилище недоступно" message={error}><Button variant="secondary" onClick={() => void load()}>Повторить</Button></ErrorState>;

  async function run(key: string, action: () => Promise<void>) {
    setBusy(key);
    setError("");
    setFeedback("");
    try {
      await action();
    } catch (caught) {
      setError(errorText(caught));
    } finally {
      setBusy("");
    }
  }

  async function updatePolicy(patch: Partial<StorageSnapshot["policy"]>) {
    const next = { ...snapshot!.policy, ...patch };
    const saved = await saveBackupPolicy({
      automatic_enabled: next.automatic_enabled,
      daily_time: next.daily_time,
      retention_days: next.retention_days,
      backup_directory: next.backup_directory,
    });
    setSnapshot((current) => current ? { ...current, policy: saved } : current);
    setFeedback("Настройки резервного копирования сохранены.");
  }

  async function copyPath(path: string) {
    try {
      await navigator.clipboard.writeText(path);
      setCopiedPath(path);
      window.setTimeout(() => setCopiedPath((current) => (current === path ? null : current)), 1500);
    } catch {
      setError("Не удалось скопировать путь: браузер отклонил доступ к буферу обмена.");
    }
  }

  async function chooseFile(file: File | undefined) {
    if (!file) return;
    await run("upload", async () => {
      setPreview(await uploadTransfer(file));
    });
    if (fileInput.current) fileInput.current.value = "";
  }

  const counts = preview?.manifest.counts as Record<string, number> | undefined;

  return (
    <div className="storage-settings">
      {error && <div className="storage-notice is-danger" role="alert">{error}</div>}
      {feedback && <div className="storage-notice" role="status">{feedback}</div>}

      <section className="ai-anchor-section" id="storage-overview">
        <div className="ai-settings-group is-first">
          <header className="ai-group-head">
            <div><h2>Хранилище</h2><p>Рабочие данные, переносимые копии и место на этом компьютере.</p></div>
            <div className="storage-actions">
              <Button variant="secondary" disabled={Boolean(busy)} onClick={() => fileInput.current?.click()}><Upload size={15} />Восстановить из файла</Button>
              <Button disabled={Boolean(busy)} onClick={() => void run("backup", async () => {
                const result = await createBackup();
                setWatched({ jobId: result.job_id, action: "backup" });
                await load();
              })}><FolderArchive size={15} />Создать копию</Button>
            </div>
          </header>
          <input ref={fileInput} hidden type="file" accept=".tentex-backup,.tentex-project" onChange={(event) => void chooseFile(event.target.files?.[0])} />
          <div className="storage-summary-grid">
            <div><span>Занято Tentex</span><strong>{bytes(snapshot.used_bytes)}</strong></div>
            <div><span>Свободно на диске</span><strong>{bytes(snapshot.free_bytes)}</strong></div>
            <div><span>Последняя копия</span><strong>{dateTime(snapshot.last_backup_at)}</strong></div>
          </div>
          <div className="storage-paths">
            <div>
              <span>Рабочие данные</span>
              <button type="button" className="storage-path-copy" title="Скопировать путь" onClick={() => void copyPath(snapshot.data_directory)}>
                <code>{snapshot.data_directory}</code>
                {copiedPath === snapshot.data_directory ? <Check size={13} /> : <Copy size={13} />}
              </button>
            </div>
            <div>
              <span>Резервные копии</span>
              <button type="button" className="storage-path-copy" title="Скопировать путь" onClick={() => void copyPath(snapshot.backup_directory)}>
                <code>{snapshot.backup_directory}</code>
                {copiedPath === snapshot.backup_directory ? <Check size={13} /> : <Copy size={13} />}
              </button>
            </div>
          </div>
          {snapshot.same_disk_warning && <div className="storage-notice is-warning">Копии находятся на том же диске, что и рабочие данные. Для защиты от поломки диска выберите другой накопитель.</div>}
          <div className="storage-breakdown" aria-label="Использование места">
            {Object.entries({ database: "База и индексы", files: "Материалы и производные", models: "Локальные модели", backups: "Копии", temporary: "Временные файлы" }).map(([key, label]) => (
              <div key={key}><span>{label}</span><strong>{bytes(snapshot.breakdown[key as keyof typeof snapshot.breakdown])}</strong></div>
            ))}
          </div>
        </div>
      </section>

      <section className="ai-anchor-section" id="storage-backups">
        <div className="ai-settings-group is-first">
          <header className="ai-group-head"><div><h2>Резервные копии</h2><p>Автоматические копии выключены, пока вы сами их не включите.</p></div></header>
          <Switch
            checked={snapshot.policy.automatic_enabled}
            onCheckedChange={(value) => void run("policy", () => updatePolicy({ automatic_enabled: value }))}
            label="Ежедневные копии"
            hint="Пропущенный запуск выполнится при первом простое после выбранного времени."
            disabled={busy === "policy"}
          />
          <div className="storage-form-grid">
            <Field label="Время запуска" hint="Локальное время этого компьютера">
              <input type="time" value={snapshot.policy.daily_time} onChange={(event) => setSnapshot({ ...snapshot, policy: { ...snapshot.policy, daily_time: event.target.value } })} onBlur={() => void run("policy", () => updatePolicy({ daily_time: snapshot.policy.daily_time }))} />
            </Field>
            <Field label="Хранить автоматические копии" hint="Ручные копии не удаляются автоматически">
              <input type="number" min={1} max={365} value={snapshot.policy.retention_days} onChange={(event) => setSnapshot({ ...snapshot, policy: { ...snapshot.policy, retention_days: Number(event.target.value) } })} onBlur={() => void run("policy", () => updatePolicy({ retention_days: snapshot.policy.retention_days }))} />
            </Field>
          </div>
          <Field label="Папка резервных копий" hint="Оставьте пустой, чтобы использовать data/backups">
            <input value={snapshot.policy.backup_directory ?? ""} onChange={(event) => setSnapshot({ ...snapshot, policy: { ...snapshot.policy, backup_directory: event.target.value || null } })} onBlur={() => void run("policy", () => updatePolicy({ backup_directory: snapshot.policy.backup_directory }))} />
          </Field>

          <div className="storage-list">
            {backups.length === 0 ? <p className="ai-muted">Управляемых копий ещё нет. Старые отдельные SQLite-файлы сюда намеренно не попадают.</p> : backups.map((backup) => {
              const state = BACKUP_STATE[backup.state];
              return <article className="storage-list-row" key={backup.id}>
                <div className="storage-row-icon"><Archive size={17} /></div>
                <div><strong>{BACKUP_KIND[backup.kind]}</strong><small>{dateTime(backup.completed_at ?? backup.created_at)} · {bytes(backup.size_bytes)}</small>{backup.error && <small className="is-danger">{backup.error}</small>}</div>
                <StatusBadge tone={state.tone}>{state.label}</StatusBadge>
                <div className="storage-row-actions">
                  {backup.state === "ready" && <>
                    <a className="secondary-button" href={backupDownloadUrl(backup.id)} download><Download size={15} />Скачать</a>
                    <Button variant="ghost" onClick={() => {
                      setRestoreManaged(true);
                      setPreview({ id: backup.id, kind: "backup", file_name: backup.file_name ?? "Резервная копия", size_bytes: backup.size_bytes ?? 0, manifest: backup.manifest, repeated: false });
                    }}>Восстановить</Button>
                  </>}
                  <Button variant="ghost" disabled={backup.state === "creating"} aria-label="Удалить копию" onClick={() => setDeleteTarget(backup)}><Trash2 size={15} /></Button>
                </div>
              </article>;
            })}
          </div>
        </div>
      </section>

      <section className="ai-anchor-section" id="storage-projects">
        <div className="ai-settings-group is-first">
          <header className="ai-group-head"><div><h2>Перенос проектов</h2><p>Добавьте проект на другой установке, не заменяя её данные.</p></div></header>
          <div className="storage-project-form">
            <Field label="Проект">
              <Select value={projectId} options={projects.map((project) => ({ value: project.id, label: project.name }))} onValueChange={setProjectId} ariaLabel="Проект для экспорта" placeholder="Выберите проект" />
            </Field>
            <Field label="Состав пакета">
              <Select value={profile} options={[
                { value: "share", label: "Поделиться", description: "Без ответов, активности, чатов и личного прогресса" },
                { value: "personal", label: "Для себя", description: "С прогрессом, историей и рабочим состоянием" },
              ]} onValueChange={(value) => setProfile((value ?? "share") as "personal" | "share")} ariaLabel="Профиль экспорта" />
            </Field>
            <Button disabled={!projectId || Boolean(busy) || Boolean(watched)} onClick={() => void run("export", async () => {
              const result = await exportProject(projectId!, profile);
              setWatched({ jobId: result.job_id, artifactId: result.artifact_id, action: "export" });
            })}><Download size={15} />Экспортировать проект</Button>
          </div>
          <div className="storage-notice">В пакет входят файлы материалов и результаты их разбора — текст страниц, блоки, привязки к программе. Глобальный смысловой (dense) индекс не переносится: на другом компьютере поиск сразу работает по обычному текстовому индексу (BM25), а смысловой можно пересобрать отдельно в любой момент.</div>
          <Button variant="secondary" onClick={() => fileInput.current?.click()}><Upload size={15} />Импортировать пакет проекта</Button>
        </div>
      </section>

      <section className="ai-anchor-section" id="storage-maintenance">
        <div className="ai-settings-group is-first">
          <header className="ai-group-head"><div><h2>Обслуживание</h2><p>Проверка сверяет базу и файлы материалов, ничего не меняя. Очистка удаляет только временное: черновой кэш разбора и просроченные пакеты экспорта/импорта — Tentex создаёт их по ходу работы и в любой момент может пересобрать заново. Материалы и резервные копии не затрагиваются. Проверка большой базы может занять несколько минут — она идёт в фоне.</p></div></header>
          <div className="storage-maintenance-actions">
            <Button variant="secondary" disabled={Boolean(busy) || Boolean(watched)} onClick={() => void run("verify", async () => {
              const result = await verifyStorage();
              setMaintenanceResult(null);
              setWatched({ jobId: result.job_id, action: "verify" });
            })}><ShieldCheck size={15} />Проверить хранилище</Button>
            <Button variant="secondary" disabled={Boolean(busy) || Boolean(watched)} onClick={() => void run("cleanup", async () => {
              const result = await cleanupStorage();
              setMaintenanceResult(null);
              setWatched({ jobId: result.job_id, action: "cleanup" });
            })}><Trash2 size={15} />Очистить временное</Button>
          </div>
          {maintenanceResult && <div className={`storage-notice ${maintenanceResult.ok ? "" : "is-danger"}`}><strong>{maintenanceResult.detail}</strong>{maintenanceResult.checked_files > 0 && <span>Проверено файлов: {maintenanceResult.checked_files}.</span>}{maintenanceResult.freed_bytes > 0 && <span>Освобождено {bytes(maintenanceResult.freed_bytes)}.</span>}</div>}
          <div className="storage-links"><a href="/setup?section=search&subsection=models">Управление embedding-моделями</a><a href="/setup?section=search&subsection=index">Управление индексами</a><a href="/setup?section=ocr&subsection=models">Установка OCR-моделей</a></div>
        </div>
      </section>

      <Dialog
        open={preview !== null && !restoreConfirm}
        onOpenChange={(open) => { if (!open) { setPreview(null); setRestoreManaged(false); } }}
        title={preview?.kind === "backup" ? "Проверенная резервная копия" : "Пакет проекта"}
        description="Tentex проверил формат, безопасные пути и контрольные суммы."
        footer={<><Button variant="ghost" onClick={() => setPreview(null)}>Отменить</Button><Button onClick={() => {
          if (preview?.kind === "backup") setRestoreConfirm(true);
          else if (preview) void run("import", async () => {
            const result = await importProject(preview.id, preview.repeated);
            setWatched({ jobId: result.job_id, artifactId: preview.id, action: "import" });
            setPreview(null);
          });
        }}>{preview?.kind === "backup" ? "Продолжить" : "Импортировать как новый проект"}</Button></>}
      >
        {preview && <div className="storage-preview">
          <div><span>Файл</span><strong>{preview.file_name}</strong></div>
          <div><span>Размер</span><strong>{bytes(preview.size_bytes)}</strong></div>
          <div><span>Проекты</span><strong>{counts?.projects ?? (preview.kind === "project" ? 1 : "—")}</strong></div>
          <div><span>Материалы</span><strong>{counts?.materials ?? "—"}</strong></div>
          {preview.kind === "backup" && <>
            <div><span>Версия</span><strong>{String(preview.manifest.app_version ?? "—")} · Alembic {String(preview.manifest.alembic_revision ?? "—")}</strong></div>
            <div><span>Индексы</span><strong>{counts?.indexes ?? "—"}</strong></div>
            <div className="storage-preview-exclusions"><span>Не входит</span><strong>{Array.isArray(preview.manifest.excluded) ? preview.manifest.excluded.join(", ") : "Секреты и локальные модели"}</strong></div>
          </>}
          {preview.repeated && <div className="storage-notice is-warning">Этот пакет уже загружали или импортировали. Будет создана ещё одна копия проекта.</div>}
        </div>}
      </Dialog>

      <ConfirmDialog open={restoreConfirm} onOpenChange={setRestoreConfirm} title="Заменить текущую установку?" confirmLabel="Создать страховочную копию и восстановить" destructive pendingLabel="Запускаем…" onConfirm={async () => {
        if (!preview) return;
        const result = await (restoreManaged ? restoreManagedBackup(preview.id) : restoreBackup(preview.id));
        setRestoreConfirm(false);
        setPreview(null);
        setRestoreManaged(false);
        setFeedback("Восстановление запущено. Tentex дождётся фоновых задач и перезагрузит данные.");
        const timer = window.setInterval(async () => {
          try {
            const state = await getRestoreStatus(result.operation_id);
            setFeedback(state.detail);
            if (["completed", "failed", "rolled_back"].includes(state.state)) {
              window.clearInterval(timer);
              if (state.state === "completed") window.location.reload();
              else setError(state.detail);
            }
          } catch { /* API может кратко перезапускать соединения при замене базы. */ }
        }, 1500);
      }}>
        <p>Текущая база, проекты, Библиотека, файлы и индексы будут заменены содержимым архива. Перед заменой Tentex автоматически создаст страховочную копию.</p>
        <p>API-ключи и локальные модели из архива не восстанавливаются.</p>
      </ConfirmDialog>

      <ConfirmDialog open={deleteTarget !== null} onOpenChange={(open) => { if (!open) setDeleteTarget(null); }} title="Удалить резервную копию?" confirmLabel="Удалить копию" destructive onConfirm={async () => {
        if (!deleteTarget) return;
        await deleteBackup(deleteTarget.id);
        setDeleteTarget(null);
        await load();
      }}><p>Файл {deleteTarget?.file_name ?? "копии"} будет удалён с диска без возможности восстановления.</p></ConfirmDialog>

      {watched && watchedJob.job && ACTIVE_JOB_STATES.has(watchedJob.job.state) && <div className="storage-running" role="status"><RefreshCw size={15} className="is-spinning" /><span>{watchedJob.job.model_label || "Фоновая операция"}{watchedJob.job.total > 0 ? `: ${watchedJob.job.done} из ${watchedJob.job.total}` : ""}</span></div>}
      {snapshot.maintenance && <div className="storage-running"><HardDrive size={15} /><span>Хранилище работает в режиме обслуживания.</span></div>}
      {feedback && feedback.includes("готов") && <CheckCircle2 className="storage-feedback-icon" size={16} aria-hidden="true" />}
    </div>
  );
}
