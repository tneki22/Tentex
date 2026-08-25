import { ArrowLeft, Eye, ListTree, PanelRight, X } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import type { CSSProperties } from "react";
import { useLocation, useNavigate, useParams, useSearchParams } from "react-router";
import {
  confirmLibraryPageReview,
  deleteLibraryMaterial,
  getLibraryPage,
  getMaterialDeletePreview,
  refreshLibrarySource,
  restoreMaterialRevision,
  searchLibraryMaterial,
  updateLibraryPageText,
  type MaterialDeletePreview,
  type MaterialPageRead,
  type MaterialPurpose,
} from "../../api/materials";
import {
  DocumentStage,
  getMaterialPresentation,
  PdfOutline,
  ViewerToolbar,
  type MaterialViewMode,
} from "../../components/domain/material-viewer";
import {
  Button,
  ConfirmDialog,
  Dialog,
  ErrorState,
  IconButton,
  LoadingState,
  StatusBadge,
  Tooltip,
} from "../../components/ui";
import { useDocumentSearch } from "../../hooks/useDocumentSearch";
import { useLibraryMaterial } from "../../hooks/useLibraryMaterial";
import { useMaterialViewport } from "../../hooks/useMaterialViewport";
import { AiCleanupPanel } from "../AiCleanupPanel";
import { AddToProjectDialog } from "./AddToProjectDialog";
import { LibraryMaterialInspector, type InspectorTab } from "./LibraryMaterialInspector";
import { MaterialSourceView, MaterialTextView } from "./MaterialSourceView";

const PURPOSE: Record<MaterialPurpose, string> = {
  exam_structure: "список вопросов",
  reference_answers: "эталонные ответы",
  study_source: "учебный источник",
};

const STATUS_LABEL: Record<string, { label: string; tone: "neutral" | "info" | "warning" | "danger" | "success" }> = {
  ready_to_process: { label: "Не подготовлен", tone: "neutral" },
  queued: { label: "В очереди", tone: "info" },
  processing: { label: "Обрабатывается", tone: "info" },
  paused: { label: "На паузе", tone: "warning" },
  ready: { label: "Готов", tone: "success" },
  failed: { label: "Ошибка", tone: "danger" },
};

export function LibraryMaterialWorkspace() {
  const { materialId = "" } = useParams();
  const navigate = useNavigate();
  const location = useLocation();
  const [searchParams, setSearchParams] = useSearchParams();

  const revisionParam = Number(searchParams.get("revision"));
  const selectedRevision = Number.isFinite(revisionParam) && revisionParam > 0 ? revisionParam : null;
  const compareParam = Number(searchParams.get("compareRevision"));
  const compareRevision = Number.isFinite(compareParam) && compareParam > 0 ? compareParam : null;
  const inspectorTab = (searchParams.get("panel") as InspectorTab | null) ?? "processing";

  const [mode, setMode] = useState<MaterialViewMode | null>(null);
  const wideEnough = () => window.innerWidth >= 900;
  const [outlineOpen, setOutlineOpen] = useState(wideEnough);
  /* На узком окне панели открываются слоем поверх сцены, поэтому по умолчанию
     они закрыты: иначе документ прячется ровно в тот момент, когда его открыли. */
  const [inspectorOpen, setInspectorOpen] = useState(wideEnough);
  const [narrow, setNarrow] = useState(() => !wideEnough());
  const [focusedFragmentId, setFocusedFragmentId] = useState<string | null>(null);
  const [currentTime, setCurrentTime] = useState(0);
  const [editOpen, setEditOpen] = useState(false);
  const [editText, setEditText] = useState("");
  const [editBusy, setEditBusy] = useState(false);
  const [cleanupOpen, setCleanupOpen] = useState(false);
  const [attachOpen, setAttachOpen] = useState(false);
  const [deletePreview, setDeletePreview] = useState<MaterialDeletePreview | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [comparisonPage, setComparisonPage] = useState<MaterialPageRead | null>(null);
  const [comparisonLoading, setComparisonLoading] = useState(false);
  const [comparisonError, setComparisonError] = useState<string | null>(null);

  useEffect(() => {
    const onResize = () => setNarrow((current) => {
      const next = !wideEnough();
      if (next !== current) {
        setOutlineOpen(!next);
        setInspectorOpen(!next);
      }
      return next;
    });
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  /* Геометрия просмотра нужна раньше карточки: страница — это то, что мы
     запрашиваем. Поэтому число страниц и масштабируемость приезжают в неё
     отдельным состоянием, как только карточка загрузилась. */
  const [geometry, setGeometry] = useState({ pageCount: 1, zoomable: false });
  const view = useMaterialViewport(geometry);
  const store = useLibraryMaterial(materialId, {
    page: view.page,
    revision: selectedRevision,
  });
  const { detail, page } = store;
  const primaryRevision = selectedRevision ?? detail?.active_parse_revision ?? 0;
  const isVersionComparison = compareRevision !== null && compareRevision !== primaryRevision;

  useEffect(() => {
    if (!isVersionComparison || compareRevision === null) {
      setComparisonPage(null);
      setComparisonError(null);
      setComparisonLoading(false);
      return;
    }
    const controller = new AbortController();
    setComparisonLoading(true);
    setComparisonError(null);
    void getLibraryPage(materialId, view.page, {
      revision: compareRevision,
      signal: controller.signal,
    })
      .then((next) => {
        if (!controller.signal.aborted) setComparisonPage(next);
      })
      .catch((caught: unknown) => {
        if (controller.signal.aborted) return;
        setComparisonPage(null);
        setComparisonError(caught instanceof Error ? caught.message : "Не удалось открыть версию для сравнения");
      })
      .finally(() => {
        if (!controller.signal.aborted) setComparisonLoading(false);
      });
    return () => controller.abort();
  }, [materialId, view.page, compareRevision, isVersionComparison]);

  const presentation = useMemo(
    () => (detail ? getMaterialPresentation(detail.presentation_kind) : null),
    [detail?.presentation_kind],
  );
  const pageCount = detail?.page_count ?? 1;
  const activePage = view.page;

  useEffect(() => {
    if (!detail || !presentation) return;
    setGeometry((current) => {
      const next = { pageCount: detail.page_count ?? 1, zoomable: presentation.supportsZoom };
      return current.pageCount === next.pageCount && current.zoomable === next.zoomable
        ? current
        : next;
    });
  }, [detail?.page_count, presentation]);

  const searchProvider = useCallback(
    async (query: string, signal: AbortSignal) => {
      const result = await searchLibraryMaterial(materialId, query, {
        revision: selectedRevision ?? undefined,
        signal,
      });
      return result.hits.map((hit) => ({
        fragmentId: hit.fragment_id,
        pageNumber: hit.page_number,
        text: hit.text,
        blockTitle: hit.block_title,
      }));
    },
    [materialId, selectedRevision],
  );
  const search = useDocumentSearch(searchProvider);

  useEffect(() => {
    if (!search.current) return;
    setFocusedFragmentId(search.current.fragmentId);
    if (search.current.pageNumber !== activePage) view.goToPage(search.current.pageNumber);
    // Прокрутка к найденному фрагменту происходит после отрисовки страницы.
    const timer = window.setTimeout(() => {
      document.getElementById(`fragment-${search.current?.fragmentId}`)
        ?.scrollIntoView({ block: "center", behavior: "smooth" });
    }, 120);
    return () => window.clearTimeout(timer);
  }, [search.current?.fragmentId, search.current?.pageNumber]);

  useEffect(() => {
    if (!presentation || mode !== null) return;
    setMode(detail?.capabilities.can_compare ? presentation.defaultMode : "text");
  }, [presentation, detail?.capabilities.can_compare, mode]);

  /* На узком окне половины не помещаются рядом, поэтому «Сравнение» там не
     предлагается: сегмент, который показывает не то, что обещает, хуже его
     отсутствия. */
  const canCompare = Boolean(detail?.capabilities.can_compare) && !narrow;
  const stageMode: MaterialViewMode = !canCompare && (mode ?? "text") === "compare"
    ? "text"
    : (mode ?? presentation?.defaultMode ?? "text");

  const readOnly = selectedRevision !== null && selectedRevision !== detail?.active_parse_revision;
  const hasOutline = Boolean(detail && detail.outline_source !== "none" && detail.outline.length > 0);
  const showOutline = hasOutline && outlineOpen && !narrow;
  const showInspector = inspectorOpen && !narrow;
  const inspectorVisible = showInspector || (narrow && inspectorOpen);

  function setParam(key: string, value: string | null) {
    const next = new URLSearchParams(searchParams);
    if (value === null) next.delete(key);
    else next.set(key, value);
    setSearchParams(next, { replace: true });
  }

  function selectRevision(revision: number | null) {
    const next = new URLSearchParams(searchParams);
    if (revision === null) next.delete("revision");
    else next.set("revision", String(revision));
    const opened = revision ?? detail?.active_parse_revision ?? 0;
    if (Number(next.get("compareRevision")) === opened) next.delete("compareRevision");
    setSearchParams(next, { replace: true });
  }

  function compareWithRevision(revision: number | null) {
    const next = new URLSearchParams(searchParams);
    if (revision === null || revision === primaryRevision) next.delete("compareRevision");
    else next.set("compareRevision", String(revision));
    setSearchParams(next, { replace: true });
  }

  /* Возврат ведёт туда, откуда пришли: в сохранённый список Библиотеки или на
     ту же страницу проектного просмотрщика. По прямой ссылке — просто в список. */
  function goBack() {
    const state = location.state as { libraryReturnTo?: string } | null;
    navigate(returnTo ?? state?.libraryReturnTo ?? "/library");
  }

  const returnTo = searchParams.get("returnTo");
  const backLabel = returnTo?.startsWith("/projects/")
    ? "Вернуться в проект"
    : "Вернуться в Библиотеку";

  async function savePageText() {
    if (!detail || !page || !editText.trim()) return;
    setEditBusy(true);
    try {
      const result = await updateLibraryPageText(detail.id, page.page_number, editText);
      setEditOpen(false);
      setNotice(
        result.orphaned_binding_ids.length > 0
          ? `Текст сохранён новой версией. Привязок перенесено: ${result.transferred_bindings}, осиротело: ${result.orphaned_binding_ids.length}.`
          : "Текст сохранён новой версией; исходный файл не изменился.",
      );
      await store.refreshDetail();
    } catch (caught) {
      store.setError(caught instanceof Error ? caught.message : "Не удалось сохранить исправление");
    } finally {
      setEditBusy(false);
    }
  }

  if (store.loading) {
    return (
      <div className="library-workspace is-skeleton">
        <div className="library-skeleton-outline" />
        <div className="library-skeleton-stage"><LoadingState label="Открываем материал" /></div>
        <div className="library-skeleton-inspector" />
      </div>
    );
  }

  if (store.notFound || !detail || !presentation) {
    return (
      <div className="library-workspace is-empty">
        <ErrorState
          title="Материал не найден"
          message={store.error ?? "Возможно, его удалили из Библиотеки."}
        >
          <Button onClick={goBack}>{backLabel}</Button>
        </ErrorState>
      </div>
    );
  }

  const status = STATUS_LABEL[detail.status] ?? STATUS_LABEL.ready_to_process;
  const prepared = detail.active_parse_revision > 0;
  const building = detail.task
    && (detail.task.state === "running" || detail.task.state === "queued")
    ? true
    : false;
  const revisionLabel = (revision: number) => {
    const row = store.revisions.find((item) => item.revision === revision);
    const modeLabel = row?.parser_mode === "textbook"
      ? "Учебник"
      : row?.parser_mode === "fast"
        ? "Быстро"
        : "правка";
    return `Версия ${revision} · ${modeLabel}`;
  };
  const comparisonLabels = isVersionComparison && compareRevision !== null
    ? { left: revisionLabel(primaryRevision), right: revisionLabel(compareRevision) }
    : null;

  const stage = (
    <DocumentStage
      mode={isVersionComparison ? "compare" : stageMode}
      storageKey={detail.id}
      sourceLabel={comparisonLabels?.left ?? presentation.sourceLabel}
      textLabel={comparisonLabels?.right ?? presentation.textLabel}
      canPrevPage={activePage > 1}
      canNextPage={activePage < pageCount}
      onPrevPage={pageCount > 1 ? () => view.goToPage(activePage - 1) : undefined}
      onNextPage={pageCount > 1 ? () => view.goToPage(activePage + 1) : undefined}
      source={
        isVersionComparison ? (
          <MaterialTextView
            material={detail}
            page={page}
            query={search.query}
            focusedFragmentId={focusedFragmentId}
            currentTime={currentTime}
            onSeek={setCurrentTime}
          />
        ) : (
          <MaterialSourceView
            material={detail}
            page={page}
            pageNumber={activePage}
            revision={selectedRevision}
            query={search.query}
            zoom={view.effectiveZoom}
            showRegions={view.showRegions}
            focusedFragmentId={focusedFragmentId}
            currentTime={currentTime}
            onTimeUpdate={setCurrentTime}
            scrollRef={view.attachScroll}
          />
        )
      }
      text={
        isVersionComparison ? (
          comparisonError ? (
            <ErrorState message={comparisonError} />
          ) : comparisonLoading || !comparisonPage ? (
            <LoadingState label="Открываем версию для сравнения" />
          ) : (
            <MaterialTextView
              material={detail}
              page={comparisonPage}
              query={search.query}
              focusedFragmentId={null}
              currentTime={currentTime}
              onSeek={setCurrentTime}
            />
          )
        ) : (
          <MaterialTextView
            material={detail}
            page={page}
            query={search.query}
            focusedFragmentId={focusedFragmentId}
            currentTime={currentTime}
            onSeek={setCurrentTime}
            processing={building}
          />
        )
      }
    />
  );

  return (
    <div
      className={[
        "library-workspace",
        showOutline ? "has-outline" : "",
        showInspector ? "has-inspector" : "",
        view.fullscreen ? "is-fullscreen" : "",
        narrow ? "is-narrow" : "",
      ].filter(Boolean).join(" ")}
      style={{ "--viewer-zoom": view.effectiveZoom } as CSSProperties}
    >
      <header className="library-workspace-head">
        <div className="library-head-lead">
          <Tooltip label={backLabel}>
            <button type="button" className="workspace-back-button" onClick={goBack} aria-label={backLabel}>
              <ArrowLeft size={15} />
            </button>
          </Tooltip>
          <div className="library-head-title">
            <h1 title={detail.original_name}>{detail.original_name}</h1>
            <div className="library-head-meta">
              <StatusBadge tone={status.tone}>{status.label}</StatusBadge>
              {detail.usage.length > 0 && (
                <span
                  className="library-head-usage"
                  title={detail.usage.map((usage) => `${usage.project_name}: ${usage.purposes.map((item) => PURPOSE[item]).join(", ")}`).join("\n")}
                >
                  {detail.usage.length === 1
                    ? detail.usage[0].project_name
                    : `в ${detail.usage.length} проектах`}
                </span>
              )}
            </div>
          </div>
        </div>

        {prepared && (
          <ViewerToolbar
            presentation={presentation}
            mode={isVersionComparison ? "compare" : stageMode}
            canCompare={!isVersionComparison && canCompare}
            page={activePage}
            pageCount={pageCount}
            query={search.query}
            zoom={view.zoom}
            zoomPercent={view.zoomPercent}
            showRegions={view.showRegions}
            fullscreen={view.fullscreen}
            searching={search.loading}
            matchLabel={search.label}
            versionComparison={comparisonLabels}
            onModeChange={isVersionComparison ? () => undefined : setMode}
            onPageChange={view.goToPage}
            onQueryChange={search.setQuery}
            onQuerySubmit={search.step}
            onZoomChange={view.setZoom}
            onToggleRegions={view.toggleRegions}
            onToggleFullscreen={() => view.setFullscreen(!view.fullscreen)}
          />
        )}

        <div className="library-head-panels">
          <Tooltip label={hasOutline ? "Оглавление" : "В документе нет оглавления."}>
            <IconButton
              label="Оглавление"
              aria-pressed={showOutline}
              disabled={!hasOutline}
              onClick={() => setOutlineOpen((value) => !value)}
            >
              <ListTree size={15} />
            </IconButton>
          </Tooltip>
          <Tooltip label={inspectorOpen ? "Скрыть панель обработки" : "Показать панель обработки"}>
            <IconButton
              label="Панель обработки"
              aria-pressed={inspectorOpen}
              onClick={() => setInspectorOpen((value) => !value)}
            >
              <PanelRight size={15} />
            </IconButton>
          </Tooltip>
        </div>
      </header>

      {comparisonLabels && (
        <div className="library-readonly-bar is-comparison" role="status">
          <Eye size={15} aria-hidden="true" />
          <p>Сравниваются {comparisonLabels.left} и {comparisonLabels.right}.</p>
          <Button variant="ghost" onClick={() => compareWithRevision(null)}>Закрыть сравнение</Button>
        </div>
      )}

      {readOnly && (
        <div className="library-readonly-bar" role="status">
          <Eye size={15} aria-hidden="true" />
          <p>
            Вы смотрите версию {selectedRevision}
            {store.revisions.find((item) => item.revision === selectedRevision)
              ? ` от ${new Date(store.revisions.find((item) => item.revision === selectedRevision)!.created_at).toLocaleDateString("ru-RU")}`
              : ""}. Изменения недоступны.
          </p>
          <Button variant="ghost" onClick={() => selectRevision(null)}>Вернуться к текущей</Button>
        </div>
      )}

      {notice && (
        <div className="library-notice" role="status">
          <p>{notice}</p>
          <IconButton label="Скрыть сообщение" onClick={() => setNotice(null)}><X size={13} /></IconButton>
        </div>
      )}

      {store.error && !store.notFound && <ErrorState message={store.error} />}

      <div className="library-workspace-body">
        {showOutline && (
          <PdfOutline
            outline={detail.outline}
            outlineSource={detail.outline_source}
            page={activePage}
            pageCount={pageCount}
            pageStates={readOnly ? [] : detail.page_states}
            storageKey={detail.id}
            onPageChange={view.goToPage}
          />
        )}

        <main className="library-workspace-main">
          {!prepared && !building ? (
            <div className="library-stage-empty">
              <h2>Материал загружен</h2>
              <p>Подготовьте текст, чтобы сравнивать его с исходником.</p>
              {inspectorVisible ? (
                <p className="library-stage-hint">Запустите обработку в панели справа.</p>
              ) : (
                <Button
                  onClick={() => {
                    setInspectorOpen(true);
                    setParam("panel", "processing");
                  }}
                >
                  Открыть панель обработки
                </Button>
              )}
            </div>
          ) : store.pageError && !store.pageLoading ? (
            <div className="library-stage-empty">
              <ErrorState message={store.pageError}>
                <p>
                  {building
                    ? "Эта страница ещё не готова — она появится по мере обработки."
                    : "Текущая версия не изменилась."}
                </p>
              </ErrorState>
            </div>
          ) : stage}
        </main>

        {showInspector && (
          <LibraryMaterialInspector
            material={detail}
            page={page}
            revisions={store.revisions}
            selectedRevision={selectedRevision}
            compareRevision={compareRevision}
            tab={inspectorTab}
            busy={store.busy}
            readOnly={readOnly}
            onTabChange={(tab) => setParam("panel", tab === "processing" ? null : tab)}
            onSelectRevision={selectRevision}
            onCompareRevision={compareWithRevision}
            onStart={(command) => void store.startProcessing({
              parser_mode: command.parser_mode,
              scope: command.scope,
              page_from: command.page_from ?? null,
              page_to: command.page_to ?? null,
            })}
            onControl={(action) => void store.controlProcessing(action)}
            onEditPage={() => {
              if (!page) return;
              setEditText(page.markdown || page.text);
              setEditOpen(true);
            }}
            onCleanupPage={() => setCleanupOpen(true)}
            onConfirmPageReview={() => {
              if (!page) return;
              void store.run(() => confirmLibraryPageReview(detail.id, page.page_number));
            }}
            onRestore={(revision) => void store.run(async () => {
              const restored = await restoreMaterialRevision(detail.id, revision);
              setParam("revision", null);
              setNotice(`Версия ${revision} восстановлена как версия ${restored.active_parse_revision}.`);
              return restored;
            })}
            onAddToProject={() => setAttachOpen(true)}
            onRefreshSource={() => void store.run(async () => {
              const result = await refreshLibrarySource(detail.id);
              setNotice(result.changed
                ? `Источник обновлён: создана версия ${result.revision}.`
                : "Источник не изменился с прошлого снимка.");
              return result;
            })}
            onDelete={() => void getMaterialDeletePreview(detail.id).then(setDeletePreview)}
          />
        )}
      </div>

      {narrow && (
        <nav className="library-narrow-bar" aria-label="Панели рабочей области">
          {hasOutline && (
            <Button variant="ghost" onClick={() => setOutlineOpen((value) => !value)}>
              <ListTree size={14} /> Оглавление
            </Button>
          )}
          <Button variant="ghost" onClick={() => setInspectorOpen((value) => !value)}>
            <PanelRight size={14} /> Обработка
          </Button>
        </nav>
      )}

      {narrow && outlineOpen && hasOutline && (
        <div className="library-layer" role="dialog" aria-label="Оглавление">
          <div className="library-layer-head">
            <strong>Оглавление</strong>
            <IconButton label="Закрыть оглавление" onClick={() => setOutlineOpen(false)}><X size={15} /></IconButton>
          </div>
          <PdfOutline
            outline={detail.outline}
            outlineSource={detail.outline_source}
            page={activePage}
            pageCount={pageCount}
            pageStates={readOnly ? [] : detail.page_states}
            storageKey={detail.id}
            onPageChange={(next) => {
              view.goToPage(next);
              setOutlineOpen(false);
            }}
          />
        </div>
      )}

      {narrow && inspectorOpen && (
        <div className="library-layer is-inspector" role="dialog" aria-label="Обработка материала">
          <div className="library-layer-head">
            <strong>Материал</strong>
            <IconButton label="Закрыть панель" onClick={() => setInspectorOpen(false)}><X size={15} /></IconButton>
          </div>
          <LibraryMaterialInspector
            material={detail}
            page={page}
            revisions={store.revisions}
            selectedRevision={selectedRevision}
            compareRevision={compareRevision}
            tab={inspectorTab}
            busy={store.busy}
            readOnly={readOnly}
            onTabChange={(tab) => setParam("panel", tab === "processing" ? null : tab)}
            onSelectRevision={selectRevision}
            onCompareRevision={compareWithRevision}
            onStart={(command) => void store.startProcessing({
              parser_mode: command.parser_mode,
              scope: command.scope,
              page_from: command.page_from ?? null,
              page_to: command.page_to ?? null,
            })}
            onControl={(action) => void store.controlProcessing(action)}
            onEditPage={() => {
              if (!page) return;
              setEditText(page.markdown || page.text);
              setEditOpen(true);
            }}
            onCleanupPage={() => setCleanupOpen(true)}
            onConfirmPageReview={() => {
              if (!page) return;
              void store.run(() => confirmLibraryPageReview(detail.id, page.page_number));
            }}
            onRestore={(revision) => void store.run(() => restoreMaterialRevision(detail.id, revision))}
            onAddToProject={() => setAttachOpen(true)}
            onRefreshSource={() => void store.run(() => refreshLibrarySource(detail.id))}
            onDelete={() => void getMaterialDeletePreview(detail.id).then(setDeletePreview)}
          />
        </div>
      )}

      <Dialog
        open={editOpen}
        onOpenChange={setEditOpen}
        title={`Исправить текст страницы ${page?.page_number ?? ""}`}
        description="Исправление сохранится новой версией. Исходный файл не меняется, и оно будет видно во всех проектах с этим материалом."
        footer={
          <>
            <Button variant="ghost" onClick={() => setEditOpen(false)}>Отменить</Button>
            <Button disabled={editBusy || !editText.trim()} onClick={() => void savePageText()}>
              Сохранить исправление
            </Button>
          </>
        }
      >
        <label className="materials-page-editor">
          Текст страницы
          <textarea autoFocus value={editText} onChange={(event) => setEditText(event.target.value)} />
        </label>
      </Dialog>

      {page && (
        <AiCleanupPanel
          open={cleanupOpen}
          projectId={null}
          material={{
            id: detail.id,
            display_name: detail.original_name,
            active_parse_revision: detail.active_parse_revision,
          }}
          page={page}
          onOpenChange={setCleanupOpen}
          onManualEdit={() => {
            setEditText(page.markdown || page.text);
            setEditOpen(true);
          }}
          onReload={async () => {
            await store.refreshDetail();
          }}
          onApplied={() => {
            setNotice("Текст страницы обновлён новой версией.");
            void store.refreshDetail();
          }}
        />
      )}

      <AddToProjectDialog
        open={attachOpen}
        materialId={detail.id}
        materialName={detail.original_name}
        attachedProjectIds={detail.usage.map((usage) => usage.project_id)}
        onOpenChange={setAttachOpen}
        onAttached={() => {
          setNotice("Материал подключён к проекту. Обработка не запускалась заново.");
          void store.refreshDetail();
        }}
      />

      <ConfirmDialog
        open={deletePreview !== null}
        onOpenChange={(open) => !open && setDeletePreview(null)}
        title={`Удалить ${detail.original_name}?`}
        confirmLabel="Удалить файл везде"
        destructive
        onConfirm={() => void deleteLibraryMaterial(detail.id).then(goBack)}
      >
        <p className="dialog-lead">
          Файл, все его версии, страницы и фрагменты удалятся из установки.
        </p>
        <ul className="consequences">
          {deletePreview?.material.usage.map((usage) => (
            <li key={usage.project_id}>
              {usage.project_name}: {usage.purposes.map((item) => PURPOSE[item]).join(", ")}
            </li>
          ))}
          {deletePreview?.reference_answer_count ? (
            <li>Эталонов из файла: {deletePreview.reference_answer_count}. Текст сохранится, источник станет недоступен.</li>
          ) : null}
          {deletePreview?.binding_count ? (
            <li>Привязок к фрагментам: {deletePreview.binding_count}. Они уйдут вместе с файлом.</li>
          ) : null}
          {deletePreview?.active_task && <li>Текущая обработка будет остановлена.</li>}
          {deletePreview && deletePreview.material.usage.length === 0
            && !deletePreview.reference_answer_count
            && !deletePreview.binding_count
            && <li>Материал не используется ни одним проектом.</li>}
        </ul>
      </ConfirmDialog>
    </div>
  );
}
