import { useCallback, useEffect, useRef, useState } from "react";
import { ACTIVE_JOB_STATES, getBackgroundJob, type BackgroundJobRead } from "../api/backgroundJobs";

const POLL_MS = 1200;

/**
 * Подписка на фоновую задачу вместо ожидания HTTP-ответа (Ш5 плана). Долгие
 * операции (разбор, вызовы ИИ) идут в отдельном контейнере воркера и не держат
 * запрос: эндпоинт отвечает 202 сразу, а прогресс и результат нужно опрашивать
 * из реестра. SSE тут не подошёл бы — воркер и api разделены, живого канала
 * между ними нет, а опрос базы всё равно остался бы под SSE тем же способом.
 *
 * Приём опроса — как в `useLibraryMaterial` (строки ~73–82): `setInterval` на
 * `POLL_MS`, пока задача в очереди, идёт или на паузе; остановка задачи никак
 * не связана с этим хуком — размонтирование компонента просто прекращает
 * опрос, сама задача продолжает жить в очереди независимо от того, смотрит на
 * неё кто-то или нет.
 */
export function useBackgroundJob(jobId: string | null) {
  const [job, setJob] = useState<BackgroundJobRead | null>(null);
  const [error, setError] = useState<string | null>(null);
  const generation = useRef(0);

  const refresh = useCallback(async () => {
    if (!jobId) return;
    const mine = generation.current;
    try {
      const next = await getBackgroundJob(jobId);
      if (mine !== generation.current) return;
      setJob(next);
      setError(null);
    } catch (caught) {
      if (mine !== generation.current) return;
      setError(caught instanceof Error ? caught.message : "Не удалось получить статус задачи");
    }
  }, [jobId]);

  useEffect(() => {
    generation.current += 1;
    setJob(null);
    setError(null);
    if (jobId) void refresh();
  }, [jobId, refresh]);

  useEffect(() => {
    if (!job || !ACTIVE_JOB_STATES.has(job.state)) return;
    const timer = window.setInterval(() => { void refresh(); }, POLL_MS);
    return () => window.clearInterval(timer);
  }, [job?.state, job?.done, refresh]);

  return { job, error, refresh };
}
