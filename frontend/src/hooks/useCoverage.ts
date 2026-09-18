import { useCallback, useEffect, useState } from "react";
import {
  getCoverageIssues,
  getCoverageOverview,
  getCoverageRun,
  type CoverageBlock,
  type CoverageOverview,
  type CoverageRun,
} from "../api/coverage";

const ACTIVE_POLL_MS = 1800;
/** Список «Где нужна помощь» показывает первые строки и честный остаток, а не весь проект. */
const ISSUE_PAGE = 12;

/** Согласованный снимок Обзора и последнего запуска с экономным polling активной работы. */
export function useCoverage(projectId: string | undefined) {
  const [overview, setOverview] = useState<CoverageOverview | null>(null);
  const [run, setRun] = useState<CoverageRun | null>(null);
  const [issues, setIssues] = useState<CoverageBlock[]>([]);
  const [issueTotal, setIssueTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const refresh = useCallback(async (signal?: AbortSignal) => {
    if (!projectId) return;
    setError("");
    try {
      const nextOverview = await getCoverageOverview(projectId, signal);
      if (signal?.aborted) return;
      setOverview(nextOverview);
      const [nextRun, issuePage] = await Promise.all([
        nextOverview.latest_run_id
          ? getCoverageRun(projectId, nextOverview.latest_run_id, signal)
          : Promise.resolve(null),
        getCoverageIssues(projectId, ISSUE_PAGE, signal),
      ]);
      if (signal?.aborted) return;
      setRun(nextRun);
      setIssues(issuePage.items);
      setIssueTotal(issuePage.total);
    } catch (caught) {
      if (!signal?.aborted) setError(caught instanceof Error ? caught.message : "Не удалось загрузить покрытие");
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  }, [projectId]);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    void refresh(controller.signal);
    return () => controller.abort();
  }, [refresh]);

  useEffect(() => {
    if (!run || !["queued", "running"].includes(run.state)) return;
    const timer = window.setInterval(() => void refresh(), ACTIVE_POLL_MS);
    return () => window.clearInterval(timer);
  }, [run?.state, refresh]);

  return { overview, run, issues, issueTotal, loading, error, refresh };
}
