import { useCallback, useEffect, useRef, useState } from "react";
import { getConspect, listConspects, saveConspect } from "../api/conspects";
import type { ConspectImageRead, ConspectSummaryEntry } from "../api/conspects";
import { ProjectApiError } from "../api/projects";

export type ConspectStatus = "loading" | "ready" | "saving" | "saved" | "error" | "conflict";

export interface ConspectController {
  content: string;
  revision: number;
  images: ConspectImageRead[];
  hydrationVersion: number;
  status: ConspectStatus;
  error: Error | null;
  scheduleSave: (markdown: string, retainedImageIds: string[]) => void;
  flush: () => Promise<void>;
  reload: () => Promise<void>;
}

const AUTOSAVE_DELAY_MS = 800;

interface PendingSave {
  markdown: string;
  retainedImageIds: string[];
}

interface ConspectIdentity {
  projectId: string;
  nodeId: string;
}

/**
 * Личный конспект темы с надёжным автосохранением.
 *
 * Очередь сохранений последовательная (`queueRef`), а не «последний ответ
 * победил»: параллельные PUT на одну тему могли бы прийти в обратном порядке
 * и откатить текст. `identityRef` отсекает ответы уже покинутого узла — если
 * пользователь успел переключиться, они не должны трогать состояние нового.
 */
export function useConspect(projectId: string, nodeId: string): ConspectController {
  const [content, setContent] = useState("");
  const [revision, setRevision] = useState(0);
  const [images, setImages] = useState<ConspectImageRead[]>([]);
  const [hydrationVersion, setHydrationVersion] = useState(0);
  const [status, setStatus] = useState<ConspectStatus>("loading");
  const [error, setError] = useState<Error | null>(null);

  const identityRef = useRef<ConspectIdentity>({ projectId, nodeId });
  const revisionRef = useRef(0);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pendingRef = useRef<PendingSave | null>(null);
  const queueRef = useRef<Promise<void>>(Promise.resolve());
  const conflictRef = useRef(false);

  const load = useCallback(async (signal?: AbortSignal) => {
    setStatus("loading");
    setError(null);
    try {
      const result = await getConspect(projectId, nodeId, signal);
      if (signal?.aborted) return;
      setContent(result.content_markdown);
      setRevision(result.revision);
      revisionRef.current = result.revision;
      setImages(result.images);
      setHydrationVersion((version) => version + 1);
      setStatus("ready");
    } catch (caught) {
      if (signal?.aborted) return;
      setError(caught instanceof Error ? caught : new Error("Не удалось загрузить конспект"));
      setStatus("error");
    }
  }, [projectId, nodeId]);

  const runSave = useCallback((
    identity: ConspectIdentity,
    expectedRevision: number,
    markdown: string,
    retainedImageIds: string[],
  ): Promise<void> => {
    const isCurrent = () => identityRef.current.projectId === identity.projectId
      && identityRef.current.nodeId === identity.nodeId;
    return saveConspect(identity.projectId, identity.nodeId, {
      content_markdown: markdown,
      expected_revision: expectedRevision,
      retained_image_ids: retainedImageIds,
    }).then(
      (result) => {
        if (!isCurrent()) return;
        revisionRef.current = result.revision;
        setRevision(result.revision);
        setContent(result.content_markdown);
        setImages(result.images);
        setStatus("saved");
      },
      (caught: unknown) => {
        if (!isCurrent()) return;
        if (caught instanceof ProjectApiError && caught.code === "stale_conspect_revision") {
          conflictRef.current = true;
          pendingRef.current = null;
          setError(caught);
          setStatus("conflict");
          return;
        }
        setError(caught instanceof Error ? caught : new Error("Не удалось сохранить конспект"));
        setStatus("error");
      },
    );
  }, []);

  const flush = useCallback((): Promise<void> => {
    if (debounceRef.current) {
      clearTimeout(debounceRef.current);
      debounceRef.current = null;
    }
    const pending = pendingRef.current;
    if (!pending || conflictRef.current) return queueRef.current;
    pendingRef.current = null;
    const identity = identityRef.current;
    const expectedRevision = revisionRef.current;
    setStatus("saving");
    queueRef.current = queueRef.current.then(
      () => runSave(identity, expectedRevision, pending.markdown, pending.retainedImageIds),
    );
    return queueRef.current;
  }, [runSave]);

  const scheduleSave = useCallback((markdown: string, retainedImageIds: string[]) => {
    if (conflictRef.current) return;
    pendingRef.current = { markdown, retainedImageIds };
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => {
      debounceRef.current = null;
      void flush();
    }, AUTOSAVE_DELAY_MS);
  }, [flush]);

  useEffect(() => {
    identityRef.current = { projectId, nodeId };
    revisionRef.current = 0;
    conflictRef.current = false;
    pendingRef.current = null;
    if (debounceRef.current) {
      clearTimeout(debounceRef.current);
      debounceRef.current = null;
    }
    const controller = new AbortController();
    void load(controller.signal);

    return () => {
      controller.abort();
      if (debounceRef.current) {
        clearTimeout(debounceRef.current);
        debounceRef.current = null;
      }
      // Debounce отменяется, но последний неотправленный снимок не теряется:
      // ставим его в очередь немедленно, под уходящей темой/проектом.
      const pending = pendingRef.current;
      if (pending && !conflictRef.current) {
        pendingRef.current = null;
        const outgoing: ConspectIdentity = { projectId, nodeId };
        const expectedRevision = revisionRef.current;
        queueRef.current = queueRef.current.then(
          () => runSave(outgoing, expectedRevision, pending.markdown, pending.retainedImageIds),
        );
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId, nodeId, load, runSave]);

  useEffect(() => {
    const handleBeforeUnload = (event: BeforeUnloadEvent) => {
      if (pendingRef.current !== null || status === "saving") {
        event.preventDefault();
      }
    };
    window.addEventListener("beforeunload", handleBeforeUnload);
    return () => window.removeEventListener("beforeunload", handleBeforeUnload);
  }, [status]);

  const reload = useCallback(async () => {
    if (debounceRef.current) {
      clearTimeout(debounceRef.current);
      debounceRef.current = null;
    }
    pendingRef.current = null;
    conflictRef.current = false;
    await load();
  }, [load]);

  return { content, revision, images, hydrationVersion, status, error, scheduleSave, flush, reload };
}

export interface ConspectSummaryController {
  entries: ConspectSummaryEntry[];
  loading: boolean;
  error: Error | null;
  reload: () => Promise<void>;
}

/**
 * Сводный конспект проекта. `refreshKey` меняется снаружи (открытый рядом
 * редактор сообщает об очередном сохранении через `onSaved`) — без него
 * сводка не узнала бы, что появился новый текст, до следующего перехода.
 */
export function useConspectSummary(projectId: string, refreshKey = 0): ConspectSummaryController {
  const [entries, setEntries] = useState<ConspectSummaryEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);

  const load = useCallback(async (signal?: AbortSignal) => {
    setLoading(true);
    setError(null);
    try {
      const result = await listConspects(projectId, signal);
      if (signal?.aborted) return;
      setEntries(result.entries);
    } catch (caught) {
      if (signal?.aborted) return;
      setError(caught instanceof Error ? caught : new Error("Не удалось загрузить сводный конспект"));
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  }, [projectId]);

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [load, refreshKey]);

  return { entries, loading, error, reload: () => load() };
}
