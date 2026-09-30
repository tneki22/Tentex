import { useCallback, useEffect, useState } from "react";

export type LessonViewMode = "pages" | "text";

const STORAGE_PREFIX = "tentex:lesson-view:";
/** Раздел «Уроки» и вкладка «Урок» могут быть открыты одновременно: режим у них общий. */
const CHANGE_EVENT = "tentex:lesson-view-change";

function read(projectId: string): LessonViewMode {
  try {
    return window.localStorage.getItem(STORAGE_PREFIX + projectId) === "text" ? "text" : "pages";
  } catch {
    return "pages";
  }
}

/** Как показывать урок: страницами оригинала или распознанным текстом. Один выбор на проект. */
export function useLessonViewMode(projectId: string) {
  const [mode, setMode] = useState<LessonViewMode>(() => read(projectId));

  useEffect(() => {
    const sync = () => setMode(read(projectId));
    sync();
    window.addEventListener(CHANGE_EVENT, sync);
    window.addEventListener("storage", sync);
    return () => {
      window.removeEventListener(CHANGE_EVENT, sync);
      window.removeEventListener("storage", sync);
    };
  }, [projectId]);

  const change = useCallback((next: LessonViewMode) => {
    setMode(next);
    try {
      window.localStorage.setItem(STORAGE_PREFIX + projectId, next);
    } catch {
      // хранилище недоступно — режим останется только в памяти вкладки
    }
    window.dispatchEvent(new Event(CHANGE_EVENT));
  }, [projectId]);

  return { mode, setMode: change };
}
