/** Восстановление фонового распределения и черновика после ухода с экрана. */
import { useEffect, useState } from "react";
import { preparation, errorText, type Draft } from "../api/preparation";
import { getBackgroundJobResult } from "../api/backgroundJobs";
import { useBackgroundJob } from "./useBackgroundJob";

/** Ошибка чтения результата оставляет задачу доступной для повторной загрузки. */
export function usePreparationAi(projectId: string) {
  const jobKey = `tentex-preparation-job:${projectId}`;
  const draftKey = `tentex-preparation-draft:${projectId}`;
  const [jobId, setJobId] = useState<string | null>(() => localStorage.getItem(jobKey));
  const [draft, setDraft] = useState<Draft | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [retry, setRetry] = useState(0);
  const { job, error: jobError } = useBackgroundJob(jobId);

  useEffect(() => {
    if (jobId) localStorage.setItem(jobKey, jobId);
    else localStorage.removeItem(jobKey);
  }, [jobId, jobKey]);

  useEffect(() => {
    let active = true;
    const id = localStorage.getItem(draftKey);
    if (id) preparation.getDraft(projectId, id)
      .then(value => { if (active) setDraft(value); })
      .catch(caught => { if (active) setError(errorText(caught)); });
    return () => { active = false; };
  }, [projectId, draftKey]);

  useEffect(() => {
    if (job?.state === "failed" || job?.state === "cancelled") {
      setError(job.error ?? (job.state === "cancelled" ? "Запрос ИИ отменён." : "Не удалось распределить вопросы с ИИ."));
      setJobId(null);
    }
  }, [job]);

  useEffect(() => {
    if (job?.state !== "completed" || !jobId) return;
    let active = true;
    getBackgroundJobResult<Draft>(jobId).then(value => {
      if (!active) return;
      if (!value || !("items" in value)) throw new Error("ИИ не вернул черновик плана.");
      localStorage.setItem(draftKey, value.id);
      setDraft(value); setJobId(null); setError(null);
    }).catch(caught => { if (active) setError(errorText(caught)); });
    return () => { active = false; };
  }, [job?.state, jobId, draftKey, retry]);

  function clearDraft() { setDraft(null); localStorage.removeItem(draftKey); }
  function start(id: string) { setError(null); setJobId(id); }
  return { jobId, setJobId: start, job, draft, clearDraft, error: error ?? jobError,
    retry: () => { setError(null); setRetry(value => value + 1); } };
}
