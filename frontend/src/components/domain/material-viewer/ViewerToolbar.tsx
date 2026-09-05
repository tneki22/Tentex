import {
  ChevronLeft,
  ChevronRight,
  Maximize2,
  Minimize2,
  Pencil,
  ScanLine,
  ZoomIn,
  ZoomOut,
} from "lucide-react";
import { type ReactNode, useEffect, useState } from "react";
import { IconButton, SegmentedTabs, Tooltip } from "../../ui";
import { DocumentSearchField } from "./DocumentSearchField";
import type { MaterialPresentation, MaterialViewMode, ViewerZoom } from "./types";

export interface ViewerToolbarProps {
  presentation: MaterialPresentation;
  mode: MaterialViewMode;
  /** Обе половины показывать нечем — сегмент «Сравнение» тогда не рисуется. */
  canCompare: boolean;
  page: number;
  pageCount: number;
  query: string;
  zoom: ViewerZoom;
  zoomPercent: number;
  showRegions: boolean;
  fullscreen: boolean;
  searching?: boolean;
  matchLabel?: string | null;
  versionComparison?: { left: string; right: string } | null;
  editDisabled?: boolean;
  editing?: boolean;
  panelTools?: ReactNode;
  onEditText?(): void;
  onModeChange(mode: MaterialViewMode): void;
  onPageChange(page: number): void;
  onQueryChange(query: string): void;
  onQuerySubmit?(direction: 1 | -1): void;
  onZoomChange(zoom: ViewerZoom): void;
  onToggleRegions(): void;
  onToggleFullscreen(): void;
}

/**
 * Верхняя строка просмотра: режим, страницы, поиск, масштаб, рамки, полный экран.
 * Компонент ничего не знает про проект, привязки, OCR и API — только про то,
 * что показано на сцене прямо сейчас.
 */
export function ViewerToolbar({
  presentation,
  mode,
  canCompare,
  page,
  pageCount,
  query,
  zoom,
  zoomPercent,
  showRegions,
  fullscreen,
  searching = false,
  matchLabel = null,
  versionComparison = null,
  editDisabled = false,
  editing = false,
  panelTools,
  onEditText,
  onModeChange,
  onPageChange,
  onQueryChange,
  onQuerySubmit,
  onZoomChange,
  onToggleRegions,
  onToggleFullscreen,
}: ViewerToolbarProps) {
  const tabs = versionComparison
    ? [{ value: "compare" as const, label: `${versionComparison.left} ↔ ${versionComparison.right}` }]
    : [
        ...(canCompare ? [{ value: "compare" as const, label: "Сравнение" }] : []),
        { value: "source" as const, label: presentation.sourceLabel },
        { value: "text" as const, label: presentation.textLabel === "Подготовленный текст" ? "Текст" : presentation.textLabel },
      ];

  return (
    <div className="viewer-toolbar-tools">
      <div className="viewer-toolbar-navigation">
        {editing ? <strong className="viewer-editing-label">Исправление текста</strong> : <>
        <SegmentedTabs
          className="viewer-mode-tabs"
          label="Что показать"
          value={mode}
          tabs={tabs}
          onChange={onModeChange}
        />

        {pageCount > 1 && (
          <div className="viewer-page-tools">
            <IconButton
              label="Предыдущая страница"
              disabled={page <= 1}
              onClick={() => onPageChange(page - 1)}
            >
              <ChevronLeft size={15} />
            </IconButton>
            <PageNumberInput page={page} pageCount={pageCount} onPageChange={onPageChange} />
            <IconButton
              label="Следующая страница"
              disabled={page >= pageCount}
              onClick={() => onPageChange(page + 1)}
            >
              <ChevronRight size={15} />
            </IconButton>
          </div>
        )}

        <DocumentSearchField
          query={query}
          matchLabel={matchLabel}
          searching={searching}
          onQueryChange={onQueryChange}
          onQuerySubmit={onQuerySubmit}
        />
        </>}

        {presentation.supportsZoom && (
          <div className="viewer-zoom-tools">
            <IconButton
              label="Уменьшить"
              disabled={zoomPercent <= 50}
              onClick={() => onZoomChange(Math.max(0.5, Number((zoomPercent / 100 - 0.25).toFixed(2))))}
            >
              <ZoomOut size={15} />
            </IconButton>
            <Tooltip label="Вписать страницу целиком">
              <button
                type="button"
                className={`viewer-zoom-readout ${zoom === "fit-page" ? "is-active" : ""}`.trim()}
                onClick={() => onZoomChange("fit-page")}
              >
                {zoomPercent}%
              </button>
            </Tooltip>
            <IconButton
              label="Увеличить"
              disabled={zoomPercent >= 200}
              onClick={() => onZoomChange(Math.min(2, Number((zoomPercent / 100 + 0.25).toFixed(2))))}
            >
              <ZoomIn size={15} />
            </IconButton>
            <Tooltip label="По ширине">
              <button
                type="button"
                className={`viewer-zoom-fit ${zoom === "fit-width" ? "is-active" : ""}`.trim()}
                onClick={() => onZoomChange("fit-width")}
              >
                По ширине
              </button>
            </Tooltip>
          </div>
        )}

      </div>
      <div className="viewer-toolbar-end">
        {onEditText && (
          <Tooltip label={editing ? "Выйти из исправления текста" : "Исправить текст текущей страницы"}>
            <IconButton
              label={editing ? "Выйти из исправления текста" : "Исправить текст"}
              aria-pressed={editing}
              disabled={editDisabled}
              onClick={onEditText}
            >
              <Pencil size={15} />
            </IconButton>
          </Tooltip>
        )}
        {presentation.supportsZoom && !versionComparison && (
          <Tooltip label={showRegions ? "Скрыть рамки распознанных областей" : "Показать рамки распознанных областей"}>
            <IconButton
              label="Рамки распознанных областей"
              aria-pressed={showRegions}
              onClick={onToggleRegions}
            >
              <ScanLine size={15} />
            </IconButton>
          </Tooltip>
        )}
        <Tooltip label={fullscreen ? "Выйти из полного экрана · Esc" : "Полный экран · F"}>
          <IconButton
            label={fullscreen ? "Выйти из полного экрана" : "Открыть на весь экран"}
            aria-pressed={fullscreen}
            onClick={onToggleFullscreen}
          >
            {fullscreen ? <Minimize2 size={15} /> : <Maximize2 size={15} />}
          </IconButton>
        </Tooltip>
        {panelTools}
      </div>
    </div>
  );
}

export function PageNumberInput({
  page,
  pageCount,
  onPageChange,
}: {
  page: number;
  pageCount: number;
  onPageChange(page: number): void;
}) {
  const [draft, setDraft] = useState(String(page));

  useEffect(() => {
    setDraft(String(page));
  }, [page]);

  const commit = () => {
    const parsed = Number.parseInt(draft, 10);
    const clamped = Number.isFinite(parsed) ? Math.min(Math.max(parsed, 1), pageCount) : page;
    if (clamped !== page) onPageChange(clamped);
    setDraft(String(clamped));
  };

  return (
    <span className="viewer-page-input">
      <input
        type="text"
        inputMode="numeric"
        aria-label="Номер страницы"
        value={draft}
        onChange={(event) => setDraft(event.target.value.replace(/[^0-9]/g, ""))}
        onFocus={(event) => event.target.select()}
        onBlur={commit}
        onKeyDown={(event) => {
          if (event.key === "Enter") {
            event.preventDefault();
            commit();
            event.currentTarget.blur();
          }
        }}
      />
      <span>/ {pageCount}</span>
    </span>
  );
}
