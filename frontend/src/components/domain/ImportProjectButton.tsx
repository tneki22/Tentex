import { useEffect, useRef, useState } from "react";
import { Upload } from "lucide-react";
import { Button, ConfirmDialog } from "../ui";
import { ACTIVE_JOB_STATES } from "../../api/backgroundJobs";
import { importProject, uploadTransfer, type TransferPreview } from "../../api/storage";
import { useBackgroundJob } from "../../hooks/useBackgroundJob";

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : "Не удалось импортировать проект";
}

/**
 * Перенос пакета проекта тем же механизмом, что и раздел «Хранилище»
 * (`StorageSettingsSection`): загрузка → проверенный предпросмотр → импорт в
 * очереди. Ветка восстановления резервной копии сюда не взята — отсюда
 * переносят только один проект, а не заменяют всю установку.
 */
export function ImportProjectButton({ className }: { className?: string }) {
  const fileInput = useRef<HTMLInputElement>(null);
  const [preview, setPreview] = useState<TransferPreview | null>(null);
  const [uploadError, setUploadError] = useState("");
  const [confirmError, setConfirmError] = useState("");
  const [status, setStatus] = useState("");
  const [watchedJobId, setWatchedJobId] = useState<string | null>(null);
  const watchedJob = useBackgroundJob(watchedJobId);

  useEffect(() => {
    const job = watchedJob.job;
    if (!watchedJobId || !job || ACTIVE_JOB_STATES.has(job.state)) return;
    setWatchedJobId(null);
    setStatus(job.state === "completed"
      ? "Проект импортирован — он появится в списке проектов."
      : "Не удалось импортировать пакет проекта.");
  }, [watchedJob.job, watchedJobId]);

  async function chooseFile(file: File | undefined) {
    if (!file) return;
    setUploadError("");
    setStatus("");
    try {
      setPreview(await uploadTransfer(file));
    } catch (error) {
      setUploadError(errorText(error));
    } finally {
      if (fileInput.current) fileInput.current.value = "";
    }
  }

  const counts = preview?.manifest.counts as Record<string, number> | undefined;

  return (
    <>
      <input
        ref={fileInput}
        hidden
        type="file"
        accept=".tentex-project"
        onChange={(event) => void chooseFile(event.target.files?.[0])}
      />
      <Button variant="secondary" className={className} onClick={() => fileInput.current?.click()}>
        <Upload size={15} aria-hidden="true" />Импортировать проект
      </Button>
      {uploadError && <p className="inline-error" role="alert">{uploadError}</p>}
      {status && <p role="status">{status}</p>}
      <ConfirmDialog
        open={preview !== null}
        onOpenChange={(open) => { if (!open) setPreview(null); }}
        title="Импортировать проект?"
        confirmLabel="Импортировать"
        confirmDisabled={preview?.kind !== "project"}
        onConfirm={async () => {
          if (!preview) return;
          setConfirmError("");
          try {
            const result = await importProject(preview.id, preview.repeated);
            setStatus("Импортируем пакет проекта…");
            setWatchedJobId(result.job_id);
          } catch (error) {
            setConfirmError(errorText(error));
            throw error;
          }
        }}
      >
        {preview && <>
          <p>
            Файл «{preview.file_name}»
            {typeof counts?.projects === "number" ? `, проектов: ${counts.projects}` : ""}
            {typeof counts?.materials === "number" ? `, материалов: ${counts.materials}` : ""}.
          </p>
          {preview.kind !== "project" && (
            <p className="inline-error" role="alert">Это не пакет проекта — выберите файл .tentex-project.</p>
          )}
          {preview.repeated && <p>Этот пакет уже импортировался. Будет создана ещё одна копия проекта.</p>}
          {confirmError && <p className="inline-error" role="alert">{confirmError}</p>}
        </>}
      </ConfirmDialog>
    </>
  );
}
