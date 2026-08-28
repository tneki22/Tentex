import { useCallback, useEffect, useState } from "react";

export type AnswerViewMode = "text" | "scans";

const STORAGE_PREFIX = "tentex:answer-view:";
/** Одно событие на вкладку: два экрана проекта могут жить в разных панелях. */
const CHANGE_EVENT = "tentex:answer-view-change";

function read(projectId: string): AnswerViewMode {
  try {
    return window.localStorage.getItem(STORAGE_PREFIX + projectId) === "scans" ? "scans" : "text";
  } catch {
    return "text";
  }
}

/**
 * Как показывать эталонный ответ: распознанным текстом или страницами документа.
 *
 * Выбор один на проект и общий для вкладки «Ответы» и панели ответа Рабочей
 * области: пользователь переключается один раз, а не в каждом месте заново.
 */
export function useAnswerViewMode(projectId: string) {
  const [mode, setMode] = useState<AnswerViewMode>(() => read(projectId));

  useEffect(() => {
    setMode(read(projectId));
  }, [projectId]);

  useEffect(() => {
    const sync = () => setMode(read(projectId));
    window.addEventListener(CHANGE_EVENT, sync);
    window.addEventListener("storage", sync);
    return () => {
      window.removeEventListener(CHANGE_EVENT, sync);
      window.removeEventListener("storage", sync);
    };
  }, [projectId]);

  const change = useCallback((next: AnswerViewMode) => {
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

export type AnswerFileMode = "preview" | "list";

const FILE_MODE_KEY = "tentex:answer-files";

/** Как показывать список файлов ответа: миниатюрами или строками со ссылками. */
export function useAnswerFileMode() {
  const [mode, setMode] = useState<AnswerFileMode>(() => {
    try {
      return window.localStorage.getItem(FILE_MODE_KEY) === "list" ? "list" : "preview";
    } catch {
      return "preview";
    }
  });

  const change = useCallback((next: AnswerFileMode) => {
    setMode(next);
    try {
      window.localStorage.setItem(FILE_MODE_KEY, next);
    } catch {
      // хранилище недоступно — вид останется только в памяти вкладки
    }
  }, []);

  return { mode, setMode: change };
}
