import { useCallback, useEffect, useState } from "react";

export type PersonalMark = "done" | "today" | "review";

const STORAGE_PREFIX = "tentex:marks:";

function readMarks(projectId: string): Record<string, PersonalMark> {
  try {
    const raw = window.localStorage.getItem(STORAGE_PREFIX + projectId);
    return raw ? JSON.parse(raw) : {};
  } catch {
    return {};
  }
}

/**
 * Личные пометки вопросов в дереве — «прошёл», «на сегодня», «повторить».
 * Хранятся только в localStorage этого браузера, не в базе: это черновая
 * разметка для себя, а не статус темы из §11.4 (тот считается на этапе 9
 * из реальных попыток и SM-2, и знает про этот хук ещё меньше, чем наоборот).
 */
export function usePersonalMarks(projectId: string) {
  const [marks, setMarks] = useState<Record<string, PersonalMark>>(() => readMarks(projectId));

  useEffect(() => {
    setMarks(readMarks(projectId));
  }, [projectId]);

  const setMark = useCallback((nodeId: string, mark: PersonalMark | null) => {
    setMarks((current) => {
      const next = { ...current };
      if (mark) next[nodeId] = mark; else delete next[nodeId];
      try {
        window.localStorage.setItem(STORAGE_PREFIX + projectId, JSON.stringify(next));
      } catch {
        // хранилище недоступно — пометка останется только в памяти вкладки
      }
      return next;
    });
  }, [projectId]);

  return { marks, setMark };
}
