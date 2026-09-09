import { useCallback, useEffect, useState } from "react";
import {
  listCards,
  type CardFilters,
  type CardListRead,
} from "../api/cards";

export function useCardBank(projectId: string, filters: CardFilters) {
  const [data, setData] = useState<CardListRead | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [refreshKey, setRefreshKey] = useState(0);
  const refresh = useCallback(() => setRefreshKey((value) => value + 1), []);

  useEffect(() => {
    const controller = new AbortController();
    const timeout = window.setTimeout(() => {
      setLoading(true);
      setError("");
      void listCards(projectId, filters, controller.signal)
        .then((result) => {
          if (!controller.signal.aborted) setData(result);
        })
        .catch((reason: unknown) => {
          if (!controller.signal.aborted) {
            setError(reason instanceof Error ? reason.message : "Не удалось загрузить Банк");
          }
        })
        .finally(() => {
          if (!controller.signal.aborted) setLoading(false);
        });
    }, filters.query ? 180 : 0);
    return () => {
      controller.abort();
      window.clearTimeout(timeout);
    };
  }, [
    filters.includeDeleted,
    filters.query,
    filters.rating,
    filters.source,
    filters.state,
    filters.unitId,
    projectId,
    refreshKey,
  ]);

  return { data, loading, error, refresh };
}
