import { useEffect, useState } from "react";
import { useSearchParams } from "react-router";
import { listBackgroundJobs, type BackgroundJobKind } from "../api/backgroundJobs";

/** Каким задачам диалог уже показывали в этой вкладке. Не в localStorage:
 *  напоминание живёт до конца сеанса работы, а не вечно — новая вкладка
 *  начинает с чистого листа и предложение всплывает снова. */
const PROMPTED_KEY = "tentex-review-prompted";

function prompted(): string[] {
  try {
    const raw = sessionStorage.getItem(PROMPTED_KEY);
    return raw ? (JSON.parse(raw) as string[]) : [];
  } catch {
    return [];
  }
}

function markPrompted(jobId: string) {
  try {
    sessionStorage.setItem(PROMPTED_KEY, JSON.stringify([...prompted(), jobId]));
  } catch {
    // Приватный режим или переполненное хранилище: без памяти диалог просто
    // всплывёт ещё раз — это лучше, чем упасть на записи напоминания.
  }
}

/**
 * Задача этого вида, чьё предложение готово и ждёт человека, — чтобы экран
 * открыл свой диалог сразу, а не оставил пользователя гадать, что нажать.
 *
 * Две причины сработать, и обе нужны:
 * - `?job=<id>` в адресе — приход из панели фоновых задач. Всегда открывает,
 *   даже если это предложение уже показывали: пользователь пришёл именно за ним.
 * - просто заход на экран — тогда открывается один раз за сеанс на задачу,
 *   иначе закрытый диалог всплывал бы при каждом возврате на экран.
 *
 * Возвращает id задачи один раз; сам диалог забирает результат через
 * `findResumableBackgroundJob` — здесь только решение «пора показать».
 */
export function usePendingReviewJob(
  kind: BackgroundJobKind,
  filters: { projectId?: string; materialId?: string },
  enabled = true,
): string | null {
  const [jobId, setJobId] = useState<string | null>(null);
  const [searchParams] = useSearchParams();
  const requested = searchParams.get("job");
  const { projectId, materialId } = filters;

  useEffect(() => {
    if (!enabled) return;
    const controller = new AbortController();
    void listBackgroundJobs({ pendingReview: true, projectId, materialId }, controller.signal)
      .then((jobs) => {
        if (controller.signal.aborted) return;
        const asked = requested
          ? jobs.find((job) => job.id === requested && job.kind === kind)
          : undefined;
        const seen = prompted();
        const job = asked ?? jobs.find((item) => item.kind === kind && !seen.includes(item.id));
        if (!job) return;
        markPrompted(job.id);
        setJobId(job.id);
      })
      .catch(() => undefined);
    return () => controller.abort();
  }, [kind, projectId, materialId, requested, enabled]);

  return jobId;
}
