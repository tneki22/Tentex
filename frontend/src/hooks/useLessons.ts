import { useCallback, useEffect, useState } from "react";
import {
  getLesson,
  getLessonsOverview,
  type LessonRead,
  type LessonsOverviewRead,
} from "../api/lessons";

interface Loadable<T> {
  data: T | null;
  loading: boolean;
  error: unknown;
  refresh: () => void;
}

/** Общий каркас загрузки: отмена по смене ключа, повтор через `refresh`. */
function useLoadable<T>(key: string | null, load: (signal: AbortSignal) => Promise<T>): Loadable<T> {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(Boolean(key));
  const [error, setError] = useState<unknown>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    if (!key) {
      setData(null);
      setLoading(false);
      return;
    }
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    load(controller.signal)
      .then((next) => { if (!controller.signal.aborted) setData(next); })
      .catch((caught: unknown) => { if (!controller.signal.aborted) setError(caught); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
    // `load` зависит только от `key`: ключ и есть идентичность запроса.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, attempt]);

  const refresh = useCallback(() => setAttempt((value) => value + 1), []);
  return { data, loading, error, refresh };
}

export function useLessonsOverview(projectId: string, enabled = true) {
  return useLoadable<LessonsOverviewRead>(
    enabled && projectId ? projectId : null,
    (signal) => getLessonsOverview(projectId, signal),
  );
}

export function useLesson(projectId: string, lessonId: string | null) {
  const result = useLoadable<LessonRead>(
    projectId && lessonId ? `${projectId}:${lessonId}` : null,
    (signal) => getLesson(projectId, lessonId ?? "", signal),
  );
  return result;
}
