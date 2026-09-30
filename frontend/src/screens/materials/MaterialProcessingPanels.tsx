import { useCallback, useEffect, useRef, useState } from "react";
import {
  addTypstFiles,
  buildTypstMaterial,
  confirmLibraryPageReview,
  controlLibraryProcessing,
  getLibraryMaterial,
  listMaterialRevisions,
  restoreMaterialRevision,
  startLibraryProcessing,
  type LibraryMaterialDetailRead,
  type MaterialPageRead,
  type MaterialRevisionRead,
  type LibraryProcessingCommand,
} from "../../api/materials";
import { indexLibraryMaterial } from "../../api/retrieval";
import { Button, ErrorState, LoadingState } from "../../components/ui";
import { LibraryProcessingPanel } from "../library/LibraryProcessingPanel";
import { MaterialRevisionPanel } from "../library/MaterialRevisionPanel";
import { HeaderFooterDialog } from "../HeaderFooterDialog";

const POLL_MS = 1200;

interface MaterialProcessingPanelsProps {
  projectId: string;
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
  projectId,
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
  const [loadError, setLoadError] = useState<string | null>(null);
  const [headerFooterOpen, setHeaderFooterOpen] = useState(false);

  /** Родитель пересоздаёт onError на каждый свой рендер (листание страниц и т.п.) —
   * держим актуальный колбэк в ref, чтобы это не меняло identity refresh и не гоняло
   * эффекты ниже заново на каждый чих родителя. */
  const onErrorRef = useRef(onError);
  onErrorRef.current = onError;

  const refresh = useCallback(async (signal?: AbortSignal) => {
    setLoadError(null);
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
      const message = caught instanceof Error ? caught.message : "Не удалось загрузить обработку файла";
      setLoadError(message);
      onErrorRef.current(message);
    }
  }, [materialId]);

  useEffect(() => {
    const controller = new AbortController();
    setDetail(null);
    setRevisions([]);
    setSelectedRevision(null);
    setLoadError(null);
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

  const start = (command: LibraryProcessingCommand) => void run(() => startLibraryProcessing(materialId, command));

  const control = (action: "pause" | "resume" | "retry" | "cancel") =>
    void run(() => controlLibraryProcessing(materialId, action));

  // Сборка Typst не зависит от проекта: тот же материал Библиотеки, те же
  // маршруты. Раньше здесь стояла заглушка, и внутри проекта кнопки молчали.
  const buildTypst = (downloadPackages: boolean, entrypoint?: string) =>
    void run(() => buildTypstMaterial(materialId, {
      download_packages: downloadPackages,
      entrypoint,
    }));

  const addTypstFile = (file: File, targetPath: string) =>
    void run(() => addTypstFiles(materialId, [file], [targetPath]));

  const restore = (revision: number) => {
    setSelectedRevision(null);
    void run(() => restoreMaterialRevision(materialId, revision));
  };

  const confirmReview = () => {
    if (!page) return;
    void run(() => confirmLibraryPageReview(materialId, page.page_number));
  };

  if (!detail && loadError) {
    return (
      <ErrorState title="Не удалось загрузить обработку" message={loadError}>
        <Button variant="secondary" onClick={() => void refresh()}>Загрузить ещё раз</Button>
      </ErrorState>
    );
  }

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
        onTypstBuild={buildTypst}
        onTypstAddFile={addTypstFile}
        onEditPage={onEditPage}
      onCleanupPage={onCleanupPage}
      onRemoveTimestamps={() => undefined}
        onFindHeaderFooter={() => setHeaderFooterOpen(true)}
        onConfirmPageReview={confirmReview}
        onIndexMaterial={() => void run(() => indexLibraryMaterial(materialId))}
        onImagesQueued={() => void refresh()}
      />
      <MaterialRevisionPanel
        material={detail}
        revisions={revisions}
        selected={selectedRevision}
        busy={busy}
        onSelect={setSelectedRevision}
        onRestore={restore}
      />
      <HeaderFooterDialog
        open={headerFooterOpen}
        projectId={projectId}
        material={{ id: detail.id, display_name: detail.display_name }}
        onOpenChange={setHeaderFooterOpen}
        onReload={async () => {
          await refresh();
        }}
        onApplied={() => onChanged()}
      />
    </>
  );
}
