/** Приглашение общее для всех разделов; начало дня хранится на сервере. */
import { useEffect, useState } from "react";
import { preparation } from "../api/preparation";

/** Перечитывает состояние после начала дня, возврата в окно и смены учебных суток. */
export function usePreparationInvitation(projectId: string, enabled: boolean) {
  const [invite, setInvite] = useState(false);
  useEffect(() => {
    if (!enabled) { setInvite(false); return; }
    const controller = new AbortController();
    const refresh = () => {
      void preparation.queue(projectId, undefined, false, controller.signal)
        .then(day => { if (!controller.signal.aborted) setInvite(day.has_plan && !day.started); })
        .catch(() => { if (!controller.signal.aborted) setInvite(false); });
    };
    refresh();
    window.addEventListener("focus", refresh);
    window.addEventListener("tentex-preparation-changed", refresh);
    const timer = window.setInterval(refresh, 60_000);
    return () => { controller.abort(); window.clearInterval(timer); window.removeEventListener("focus", refresh); window.removeEventListener("tentex-preparation-changed", refresh); };
  }, [projectId, enabled]);
  return invite;
}
