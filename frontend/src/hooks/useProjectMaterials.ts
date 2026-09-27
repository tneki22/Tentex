import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  controlMaterialProcessing,
  createExternalMaterial,
  createTextMaterial,
  detachMaterial,
  listMaterials,
  reorderMaterials,
  startMaterialProcessing,
  updateMaterial,
  uploadMaterial,
} from "../api/materials";
import type {
  ExamMaterialSlot,
  MaterialPurpose,
  MaterialRead,
  ParserMode,
  SourceRole,
} from "../api/materials";

export function useProjectMaterials(projectId: string | undefined) {
  const [materials, setMaterials] = useState<MaterialRead[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [uploadStatus, setUploadStatus] = useState<{ name: string; progress: number } | null>(null);
  const [error, setError] = useState<string | null>(null);
  // Опрос раз в 1200 мс и явные refresh() (после привязки из Библиотеки и
  // т.п.) могут завершиться не в том порядке, в котором были запущены:
  // ответ на устаревший запрос не должен переписывать более свежий список.
  const requestIdRef = useRef(0);

  const refresh = useCallback(async (signal?: AbortSignal) => {
    if (!projectId) {
      setMaterials([]);
      setError(null);
      setLoading(false);
      return;
    }
    const requestId = ++requestIdRef.current;
    try {
      const result = await listMaterials(projectId, signal);
      if (requestId !== requestIdRef.current) return;
      setMaterials(result);
      setError(null);
    } catch (caught) {
      if (signal?.aborted || requestId !== requestIdRef.current) return;
      setError(caught instanceof Error ? caught.message : "Не удалось загрузить материалы");
    } finally {
      if (!signal?.aborted && requestId === requestIdRef.current) setLoading(false);
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
    uploadStatus,
    error,
    refresh,
    upload: (
      file: File,
      sourceRole: SourceRole,
      purposes: MaterialPurpose[],
      examSlot?: ExamMaterialSlot | null,
    ) => {
      if (!projectId) return null;
      setUploadStatus({ name: file.name, progress: 0 });
      return mutate(() => uploadMaterial(projectId, file, sourceRole, purposes, examSlot,
        (progress) => setUploadStatus({ name: file.name, progress })))
        .finally(() => setUploadStatus(null));
    },
    createText: (command: {
      name: string;
      text: string;
      source_role: SourceRole;
      purposes: MaterialPurpose[];
      exam_slot?: ExamMaterialSlot | null;
    }) => projectId ? mutate(() => createTextMaterial(projectId, command)) : null,
    createExternal: (command: {
      kind: "url" | "youtube";
      url: string;
      source_role: SourceRole;
      purposes: MaterialPurpose[];
      exam_slot?: ExamMaterialSlot | null;
    }) => projectId ? mutate(() => createExternalMaterial(projectId, command)) : null,
    // Отдельно от mutate(): PATCH уже возвращает свежую запись, полный
    // повторный GET не нужен, а глобальный busy не должен гасить кнопки
    // остальных карточек ради сохранения одной. Ошибка ловится тут же —
    // вызывающая сторона получает null и может показать её сама.
    update: async (materialId: string, command: Parameters<typeof updateMaterial>[2]) => {
      if (!projectId) return null;
      try {
        const updated = await updateMaterial(projectId, materialId, command);
        setMaterials((current) => current.map((item) => (item.id === materialId ? updated : item)));
        setError(null);
        return updated;
      } catch (caught) {
        setError(caught instanceof Error ? caught.message : "Действие не выполнено");
        return null;
      }
    },
    start: (materialId: string, mode: ParserMode = "fast") =>
      projectId ? mutate(() => startMaterialProcessing(projectId, materialId, mode)) : null,
    control: (materialId: string, action: "pause" | "resume" | "retry" | "cancel") =>
      projectId ? mutate(() => controlMaterialProcessing(projectId, materialId, action)) : null,
    // Порядок меняется сразу, сервер его только подтверждает: перетаскивание
    // не должно ждать ответа. Ошибка возвращает серверный список.
    reorder: async (materialIds: string[]) => {
      if (!projectId) return;
      const position = new Map(materialIds.map((id, index) => [id, index]));
      requestIdRef.current += 1;
      setMaterials((current) => [...current]
        .sort((left, right) => (position.get(left.id) ?? 0) - (position.get(right.id) ?? 0))
        .map((item) => ({ ...item, priority: position.get(item.id) ?? item.priority })));
      try {
        const saved = await reorderMaterials(projectId, materialIds);
        // Опрос, начатый до записи, мог прочитать старый порядок — гасим его.
        requestIdRef.current += 1;
        setMaterials(saved);
        setError(null);
      } catch (caught) {
        setError(caught instanceof Error ? caught.message : "Не удалось сохранить порядок");
        await refresh();
      }
    },
    detach: (materialId: string) =>
      projectId ? mutate(() => detachMaterial(projectId, materialId)) : null,
  };
}
