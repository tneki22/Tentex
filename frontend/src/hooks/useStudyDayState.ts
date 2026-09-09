/** Серверное состояние учебного дня общее для приглашения, таймера и старта. */
import { useCallback, useEffect, useState } from "react";
import { errorText, preparation, type Queue } from "../api/preparation";

const REFRESH_MS = 60_000;

/** Синхронизирует границу учебного дня при фокусе, событии старта и смене суток. */
export function useStudyDayState(projectId: string, enabled: boolean) {
  const [day, setDay] = useState<Queue | null>(null);
  const [loading, setLoading] = useState(enabled);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async (signal?: AbortSignal) => {
    if (!enabled) return null;
    try {
      const value = await preparation.queue(projectId, undefined, false, signal);
      if (!signal?.aborted) {
        setDay(value);
        setError(null);
        setLoading(false);
      }
      return value;
    } catch (caught) {
      if (!signal?.aborted) {
        setError(errorText(caught));
        setLoading(false);
      }
      return null;
    }
  }, [enabled, projectId]);

  useEffect(() => {
    if (!enabled) {
      setDay(null);
      setError(null);
      setLoading(false);
      return;
    }
    setLoading(true);
    const controller = new AbortController();
    const update = () => void refresh(controller.signal);
    update();
    window.addEventListener("focus", update);
    window.addEventListener("tentex-preparation-changed", update);
    const timer = window.setInterval(update, REFRESH_MS);
    return () => {
      controller.abort();
      window.clearInterval(timer);
      window.removeEventListener("focus", update);
      window.removeEventListener("tentex-preparation-changed", update);
    };
  }, [enabled, refresh]);

  const start = useCallback(async () => {
    try {
      const value = await preparation.queue(projectId, undefined, true);
      setDay(value);
      setError(null);
      window.dispatchEvent(new Event("tentex-preparation-changed"));
      return value;
    } catch (caught) {
      setError(errorText(caught));
      throw caught;
    }
  }, [projectId]);

  return { day, loading, error, refresh, start };
}
