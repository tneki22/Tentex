import { useCallback, useEffect, useState } from "react";
import {
  createBindings,
  getBindingsSummary,
  listBindings,
  removeBinding,
  removeBindingsBulk,
  restoreBinding,
} from "../api/bindings";
import type {
  BindingCreateCommand,
  BindingFragmentRead,
  BindingStatus,
  NodeBindingSummary,
} from "../api/bindings";

export function useBindings(projectId: string | undefined) {
  const [summary, setSummary] = useState<NodeBindingSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refreshSummary = useCallback(async (signal?: AbortSignal) => {
    if (!projectId) {
      setSummary([]);
      setError(null);
      setLoading(false);
      return;
    }
    try {
      const result = await getBindingsSummary(projectId, signal);
      setSummary(result);
      setError(null);
    } catch (caught) {
      if (signal?.aborted) return;
      setError(caught instanceof Error ? caught.message : "Не удалось загрузить сводку привязок");
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  }, [projectId]);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    void refreshSummary(controller.signal);
    return () => controller.abort();
  }, [refreshSummary]);

  const mutate = useCallback(async <T,>(operation: () => Promise<T>): Promise<T | null> => {
    setBusy(true);
    setError(null);
    try {
      const result = await operation();
      await refreshSummary();
      return result;
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Действие не выполнено");
      return null;
    } finally {
      setBusy(false);
    }
  }, [refreshSummary]);

  return {
    summary,
    loading,
    busy,
    error,
    refreshSummary,
    forNode: (nodeId: string, signal?: AbortSignal): Promise<BindingFragmentRead[]> =>
      projectId ? listBindings(projectId, { nodeId }, signal) : Promise.resolve([]),
    forMaterialPage: (
      materialId: string,
      page: number | undefined,
      signal?: AbortSignal,
    ): Promise<BindingFragmentRead[]> =>
      projectId ? listBindings(projectId, { materialId, page }, signal) : Promise.resolve([]),
    orphanedForNode: (nodeId: string, signal?: AbortSignal): Promise<BindingFragmentRead[]> =>
      projectId
        ? listBindings(projectId, { nodeId, status: "orphaned" as BindingStatus }, signal)
        : Promise.resolve([]),
    bind: (command: BindingCreateCommand) =>
      projectId ? mutate(() => createBindings(projectId, command)) : null,
    unbind: (bindingId: string) =>
      projectId ? mutate(() => removeBinding(projectId, bindingId)) : null,
    removeAllForMaterial: (materialId: string, pageNumber?: number) =>
      projectId ? mutate(() => removeBindingsBulk(projectId, { materialId, pageNumber })) : null,
    restore: (bindingId: string) =>
      projectId ? mutate(() => restoreBinding(projectId, bindingId)) : null,
  };
}
