import { useCallback, useEffect, useRef, useState } from "react";
import {
  controlLibraryProcessing,
  getLibraryMaterial,
  getLibraryPage,
  listMaterialRevisions,
  startLibraryProcessing,
  type LibraryMaterialDetailRead,
  type MaterialPageRead,
  type MaterialRevisionRead,
  type ParserMode,
  type ProcessingScope,
} from "../api/materials";

const POLL_MS = 1200;

interface LoadOptions {
  page: number;
  /** null — активная версия; число — зарегистрированная историческая. */
  revision: number | null;
}

/**
 * Владелец состояния рабочей области материала: карточка, страница, версии и
 * фоновая задача. Визуальные ширины и полный экран сюда не относятся — они
 * живут в самом экране и не должны переживать смену материала.
 */
export function useLibraryMaterial(materialId: string, { page, revision }: LoadOptions) {
  const [detail, setDetail] = useState<LibraryMaterialDetailRead | null>(null);
  const [revisions, setRevisions] = useState<MaterialRevisionRead[]>([]);
  const [pageData, setPageData] = useState<MaterialPageRead | null>(null);
  const [loading, setLoading] = useState(true);
  const [pageLoading, setPageLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pageError, setPageError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [notFound, setNotFound] = useState(false);
  const generation = useRef(0);

  const refreshDetail = useCallback(async (signal?: AbortSignal) => {
    try {
      const [next, history] = await Promise.all([
        getLibraryMaterial(materialId, signal),
        listMaterialRevisions(materialId, signal),
      ]);
      if (signal?.aborted) return null;
      setDetail(next);
      setRevisions(history);
      setError(null);
      setNotFound(false);
      return next;
    } catch (caught) {
      if (signal?.aborted) return null;
      const message = caught instanceof Error ? caught.message : "Материал не загрузился";
      const status = (caught as { status?: number }).status;
      if (status === 404) setNotFound(true);
      setError(message);
      return null;
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  }, [materialId]);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setDetail(null);
    setPageData(null);
    void refreshDetail(controller.signal);
    return () => controller.abort();
  }, [refreshDetail]);

  /** Пока идёт разбор, карточка обновляется сама: прогресс без перезагрузки. */
  useEffect(() => {
    const task = detail?.task;
    const active = task && (task.state === "queued" || task.state === "running");
    if (!active) return;
    const timer = window.setInterval(() => {
      void refreshDetail();
    }, POLL_MS);
    return () => window.clearInterval(timer);
  }, [detail?.task?.state, detail?.task?.done, refreshDetail]);

  const activeTaskId = detail?.task
    && (detail.task.state === "running" || detail.task.state === "queued" || detail.task.state === "paused")
    ? detail.task.id
    : undefined;
  const activeRevision = detail?.active_parse_revision ?? 0;
  const hasReadyRevision = activeRevision > 0;
  const previewTaskId = !hasReadyRevision ? activeTaskId : undefined;

  const detailLoaded = detail !== null;
  useEffect(() => {
    if (!detailLoaded) return;
    if (!hasReadyRevision && !previewTaskId) {
      setPageData(null);
      setPageError(null);
      return;
    }
    const controller = new AbortController();
    const mine = ++generation.current;
    setPageLoading(true);
    setPageError(null);
    void getLibraryPage(materialId, page, {
      revision: revision ?? undefined,
      taskId: previewTaskId,
      signal: controller.signal,
    })
      .then((next) => {
        if (controller.signal.aborted || mine !== generation.current) return;
        setPageData(next);
      })
      .catch((caught: unknown) => {
        if (controller.signal.aborted || mine !== generation.current) return;
        setPageData(null);
        setPageError(caught instanceof Error ? caught.message : "Страница не загрузилась");
      })
      .finally(() => {
        if (!controller.signal.aborted && mine === generation.current) setPageLoading(false);
      });
    return () => controller.abort();
    // Активная версия в зависимостях не случайно: после обработки, правки и
    // восстановления страницу нужно перечитать, а на каждый тик опроса — нет.
  }, [materialId, page, revision, detailLoaded, activeRevision, hasReadyRevision, previewTaskId]);

  const run = useCallback(async <T,>(action: () => Promise<T>): Promise<T | null> => {
    setBusy(true);
    try {
      const result = await action();
      await refreshDetail();
      return result;
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Действие не выполнилось");
      // Конфликт версий значит, что карточка устарела: перечитываем её,
      // чтобы следующая попытка шла от настоящего состояния.
      await refreshDetail();
      return null;
    } finally {
      setBusy(false);
    }
  }, [refreshDetail]);

  const startProcessing = useCallback((command: {
    parser_mode: ParserMode;
    scope: ProcessingScope;
    page_from?: number | null;
    page_to?: number | null;
  }) => run(() => startLibraryProcessing(materialId, command)), [materialId, run]);

  const controlProcessing = useCallback((action: "pause" | "resume" | "retry") =>
    run(() => controlLibraryProcessing(materialId, action)), [materialId, run]);

  return {
    detail,
    revisions,
    page: pageData,
    loading,
    pageLoading,
    error,
    pageError,
    busy,
    notFound,
    setError,
    refreshDetail,
    startProcessing,
    controlProcessing,
    run,
  };
}
