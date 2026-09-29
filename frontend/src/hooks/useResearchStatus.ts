import { useCallback, useEffect, useState } from "react";
import { getCoverageOverview } from "../api/coverage";
import { researchState, type ResearchState } from "../components/domain/researchStatus";

/** Пока исследование идёт, строка «34 из 80 блоков» обновляется сама. */
const POLL_MS = 8000;

/**
 * Состояние исследования каждого материала проекта. Сводка покрытия тяжелее списка
 * материалов, поэтому грузится отдельно и не задерживает таблицу: без неё строка
 * просто остаётся без подписи.
 */
export function useResearchStatus(projectId: string, enabled: boolean, reloadKey = "") {
  const [states, setStates] = useState<Map<string, ResearchState>>(new Map());

  const load = useCallback(async (signal?: AbortSignal) => {
    const overview = await getCoverageOverview(projectId, signal);
    if (signal?.aborted) return;
    const next = new Map<string, ResearchState>();
    for (const source of overview.sources) {
      const state = researchState(source);
      if (state) next.set(source.id, state);
    }
    setStates(next);
  }, [projectId]);

  useEffect(() => {
    if (!enabled) {
      setStates(new Map());
      return;
    }
    const controller = new AbortController();
    load(controller.signal).catch(() => undefined);
    return () => controller.abort();
  }, [enabled, load, reloadKey]);

  const running = [...states.values()].some((state) => state.action === "progress");
  useEffect(() => {
    if (!enabled || !running) return;
    const timer = window.setInterval(() => { load().catch(() => undefined); }, POLL_MS);
    return () => window.clearInterval(timer);
  }, [enabled, running, load]);

  return states;
}
