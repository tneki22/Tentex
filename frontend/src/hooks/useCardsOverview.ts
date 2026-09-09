import { useCallback, useEffect, useState } from "react";
import {
  getCardsOverview,
  type CardOverviewRead,
} from "../api/cards";

export function useCardsOverview(projectId: string, period: 7 | 30) {
  const [data, setData] = useState<CardOverviewRead | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [refreshKey, setRefreshKey] = useState(0);
  const refresh = useCallback(() => setRefreshKey((value) => value + 1), []);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError("");
    void getCardsOverview(projectId, period, controller.signal)
      .then((result) => {
        if (!controller.signal.aborted) setData(result);
      })
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) {
          setError(reason instanceof Error ? reason.message : "Не удалось загрузить карточки");
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [period, projectId, refreshKey]);

  return { data, loading, error, refresh };
}
