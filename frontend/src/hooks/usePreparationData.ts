/** Один снимок экрана и полный журнал ответов обновляются вместе. */
import { useCallback, useEffect, useState } from "react";
import { preparation, errorText, type Overview, type Activity } from "../api/preparation";
import { getProject, type ModuleKey } from "../api/projects";

/** Минутный опрос замечает смену учебного дня без перезагрузки страницы. */
const REFRESH_INTERVAL = 60_000;

/** Отмена запроса не позволяет старому проекту заменить текущие данные. */
export function usePreparationData(projectId: string) {
  const [overview, setOverview] = useState<Overview | null>(null);
  const [answers, setAnswers] = useState<Activity[]>([]);
  const [modules, setModules] = useState<ModuleKey[] | undefined>();
  const [error, setError] = useState<string | null>(null);
  const [version, setVersion] = useState(0);
  const refresh = useCallback(() => setVersion(value => value + 1), []);

  useEffect(() => {
    const controller = new AbortController();
    async function load() {
      const snapshot = await preparation.overview(projectId, undefined, undefined, controller.signal);
      if (controller.signal.aborted) return;
      setOverview(snapshot);
      const query = new URLSearchParams({
        kind: "answer", date_from: snapshot.days[0]?.date ?? snapshot.today,
        date_to: snapshot.today, limit: "200",
      });
      const items: Activity[] = [];
      let total = 1;
      while (items.length < total && !controller.signal.aborted) {
        query.set("offset", String(items.length));
        const page = await preparation.history(projectId, query, controller.signal);
        items.push(...page.items);
        total = page.total;
        if (!page.items.length) break;
      }
      if (!controller.signal.aborted) { setAnswers(items); setError(null); }
    }
    void load().catch(caught => { if (!controller.signal.aborted) setError(errorText(caught)); });
    return () => controller.abort();
  }, [projectId, version]);

  useEffect(() => {
    const controller = new AbortController();
    getProject(projectId, controller.signal)
      .then(detail => { if (!controller.signal.aborted) setModules(detail.project.enabled_modules); })
      .catch(caught => { if (!controller.signal.aborted) setError(errorText(caught)); });
    return () => controller.abort();
  }, [projectId]);

  useEffect(() => {
    window.addEventListener("focus", refresh);
    const timer = window.setInterval(refresh, REFRESH_INTERVAL);
    return () => { window.removeEventListener("focus", refresh); window.clearInterval(timer); };
  }, [refresh]);
  return { overview, setOverview, answers, modules, error, refresh };
}
