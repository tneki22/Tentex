import { useCallback, useEffect, useState } from "react";

interface RecentEntry {
  nodeId: string;
  savedAt: number;
}

const STORAGE_PREFIX = "tentex:recent-answers:";
const LIMIT = 20;

function read(projectId: string): RecentEntry[] {
  try {
    const raw = window.localStorage.getItem(STORAGE_PREFIX + projectId);
    return raw ? JSON.parse(raw) : [];
  } catch {
    return [];
  }
}

/**
 * История последних изменённых ответов для левой панели экрана «Ответы».
 * Сервер не хранит момент правки отдельно от ревизии, поэтому список — это
 * то, что сохраняли из этой вкладки браузера, а не полная серверная история.
 */
export function useRecentAnswers(projectId: string) {
  const [entries, setEntries] = useState<RecentEntry[]>(() => read(projectId));

  useEffect(() => {
    setEntries(read(projectId));
  }, [projectId]);

  const recordSave = useCallback((nodeId: string) => {
    setEntries((current) => {
      const next = [{ nodeId, savedAt: Date.now() }, ...current.filter((entry) => entry.nodeId !== nodeId)].slice(0, LIMIT);
      try {
        window.localStorage.setItem(STORAGE_PREFIX + projectId, JSON.stringify(next));
      } catch {
        // хранилище недоступно — история останется только в памяти вкладки
      }
      return next;
    });
  }, [projectId]);

  return { recent: entries.map((entry) => entry.nodeId), recordSave };
}
