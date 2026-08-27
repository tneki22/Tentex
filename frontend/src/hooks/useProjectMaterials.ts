import { useCallback, useEffect, useMemo, useState } from "react";
import {
  controlMaterialProcessing,
  createExternalMaterial,
  createTextMaterial,
  detachMaterial,
  listMaterials,
  startMaterialProcessing,
  updateMaterial,
  uploadMaterial,
} from "../api/materials";
import type {
  MaterialPurpose,
  MaterialRead,
  ParserMode,
  SourceRole,
} from "../api/materials";

export function useProjectMaterials(projectId: string | undefined) {
  const [materials, setMaterials] = useState<MaterialRead[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async (signal?: AbortSignal) => {
    if (!projectId) {
      setMaterials([]);
      setError(null);
      setLoading(false);
      return;
    }
    try {
      const result = await listMaterials(projectId, signal);
      setMaterials(result);
      setError(null);
    } catch (caught) {
      if (signal?.aborted) return;
      setError(caught instanceof Error ? caught.message : "Не удалось загрузить материалы");
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

  const hasActiveTask = useMemo(() => materials.some((material) =>
    material.task && ["queued", "running"].includes(material.task.state)), [materials]);

  useEffect(() => {
    if (!hasActiveTask) return;
    const timer = window.setInterval(() => void refresh(), 1200);
    return () => window.clearInterval(timer);
  }, [hasActiveTask, refresh]);

  const mutate = useCallback(async <T,>(operation: () => Promise<T>): Promise<T | null> => {
    setBusy(true);
    setError(null);
    try {
      const result = await operation();
      await refresh();
      return result;
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Действие не выполнено");
      return null;
    } finally {
      setBusy(false);
    }
  }, [refresh]);

  return {
    materials,
    loading,
    busy,
    error,
    refresh,
    upload: (file: File, sourceRole: SourceRole, purposes: MaterialPurpose[]) =>
      projectId ? mutate(() => uploadMaterial(projectId, file, sourceRole, purposes)) : null,
    createText: (command: {
      name: string;
      text: string;
      source_role: SourceRole;
      purposes: MaterialPurpose[];
    }) => projectId ? mutate(() => createTextMaterial(projectId, command)) : null,
    createExternal: (command: {
      kind: "url" | "youtube";
      url: string;
      source_role: SourceRole;
      purposes: MaterialPurpose[];
    }) => projectId ? mutate(() => createExternalMaterial(projectId, command)) : null,
    update: (materialId: string, command: Parameters<typeof updateMaterial>[2]) =>
      projectId ? mutate(() => updateMaterial(projectId, materialId, command)) : null,
    start: (materialId: string, mode: ParserMode = "fast") =>
      projectId ? mutate(() => startMaterialProcessing(projectId, materialId, mode)) : null,
    control: (materialId: string, action: "pause" | "resume" | "retry" | "cancel") =>
      projectId ? mutate(() => controlMaterialProcessing(projectId, materialId, action)) : null,
    detach: (materialId: string) =>
      projectId ? mutate(() => detachMaterial(projectId, materialId)) : null,
  };
}
