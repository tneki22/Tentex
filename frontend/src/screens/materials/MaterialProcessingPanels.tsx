import { useCallback, useEffect, useState } from "react";
import {
  confirmLibraryPageReview,
  controlLibraryProcessing,
  getLibraryMaterial,
  listMaterialRevisions,
  restoreMaterialRevision,
  startLibraryProcessing,
  type LibraryMaterialDetailRead,
  type MaterialPageRead,
  type MaterialRevisionRead,
  type ParserMode,
  type ProcessingScope,
} from "../../api/materials";
import { LoadingState } from "../../components/ui";
import { LibraryProcessingPanel } from "../library/LibraryProcessingPanel";
import { MaterialRevisionPanel } from "../library/MaterialRevisionPanel";

const POLL_MS = 1200;

interface MaterialProcessingPanelsProps {
  materialId: string;
  /** Текущая страница проекта: панель по ней включает правку и подтверждение OCR. */
  page: MaterialPageRead | null;
  onEditPage: () => void;
  onCleanupPage: () => void;
  /** После запуска разбора и восстановления версии — обновить проектный список и просмотрщик. */
  onChanged: () => void;
  onError: (message: string) => void;
}

/**
 * Обработка и версии материала внутри проекта. Обработка общая для всех проектов
 * с этим файлом, поэтому карточка, версии и запуск читаются проектонезависимыми
 * ручками (`/api/materials/...`), а панели — те же, что в Библиотеке, вместе с их
 * предупреждением «файл используется в N проектах». Сравнение версий бок-о-бок,
 * скачивание исходника и полное удаление остаются в Библиотеке.
 */
export function MaterialProcessingPanels({
  materialId,
  page,
  onEditPage,
  onCleanupPage,
  onChanged,
  onError,
}: MaterialProcessingPanelsProps) {
  const [detail, setDetail] = useState<LibraryMaterialDetailRead | null>(null);
  const [revisions, setRevisions] = useState<MaterialRevisionRead[]>([]);
  const [busy, setBusy] = useState(false);
  const [selectedRevision, setSelectedRevision] = useState<number | null>(null);

  const refresh = useCallback(async (signal?: AbortSignal) => {
    try {
      const [next, history] = await Promise.all([
        getLibraryMaterial(materialId, signal),
        listMaterialRevisions(materialId, signal),
      ]);
      if (signal?.aborted) return;
      setDetail(next);
      setRevisions(history);
    } catch (caught) {
      if (signal?.aborted) return;
      onError(caught instanceof Error ? caught.message : "Не удалось загрузить обработку файла");
    }
  }, [materialId, onError]);

  useEffect(() => {
    const controller = new AbortController();
    setDetail(null);
    setRevisions([]);
    setSelectedRevision(null);
    void refresh(controller.signal);
    return () => controller.abort();
  }, [refresh]);

  /** Пока идёт разбор — карточка обновляется сама: прогресс без перезагрузки экрана. */
  const taskState = detail?.task?.state;
  const taskDone = detail?.task?.done;
  useEffect(() => {
    if (taskState !== "queued" && taskState !== "running") return;
    const timer = window.setInterval(() => void refresh(), POLL_MS);
    return () => window.clearInterval(timer);
  }, [taskState, taskDone, refresh]);

  const run = useCallback(async (action: () => Promise<unknown>) => {
    setBusy(true);
    try {
      await action();
      await refresh();
      onChanged();
    } catch (caught) {
      onError(caught instanceof Error ? caught.message : "Действие не выполнилось");
      // Конфликт версий значит, что карточка устарела: перечитываем её.
      await refresh();
    } finally {
      setBusy(false);
    }
  }, [refresh, onChanged, onError]);

  const start = (command: {
    parser_mode: ParserMode;
    scope: ProcessingScope;
    page_from?: number;
    page_to?: number;
  }) => void run(() => startLibraryProcessing(materialId, command));

  const control = (action: "pause" | "resume" | "retry" | "cancel") =>
    void run(() => controlLibraryProcessing(materialId, action));

  const restore = (revision: number) => {
    setSelectedRevision(null);
    void run(() => restoreMaterialRevision(materialId, revision));
  };

  const confirmReview = () => {
    if (!page) return;
    void run(() => confirmLibraryPageReview(materialId, page.page_number));
  };

  if (!detail) return <LoadingState label="Загружаем обработку файла" />;

  return (
    <>
      <LibraryProcessingPanel
        material={detail}
        page={page}
        busy={busy}
        readOnly={false}
        onStart={start}
        onControl={control}
        onEditPage={onEditPage}
        onCleanupPage={onCleanupPage}
        onConfirmPageReview={confirmReview}
      />
      <MaterialRevisionPanel
        material={detail}
        revisions={revisions}
        selected={selectedRevision}
        busy={busy}
        onSelect={setSelectedRevision}
        onRestore={restore}
      />
    </>
  );
}
