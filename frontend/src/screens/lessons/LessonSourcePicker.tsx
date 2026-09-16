import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Crop, Layers, Plus, SquareDashed } from "lucide-react";
import type { LessonBlockCommand, LessonBlockRead } from "../../api/lessons";
import {
  getMaterialPage,
  materialFragmentAssetUrl,
  type MaterialPageRead,
  type MaterialRead,
} from "../../api/materials";
import { QualityBadge } from "../../components/domain";
import { PageNumberInput, PdfOutline, StructuredPage } from "../../components/domain/material-viewer";
import { Button, Dialog, LoadingState, Select, StatusBadge } from "../../components/ui";
import { groupPlacesByMaterial, type SourcePlace } from "../workspace/sourcePlaces";
import { fragmentPreview, LessonPageSheet } from "./LessonPageSheet";
import { errorText } from "./lessonTree";
import {
  insertOptions, insertSummary, insertValue, parseInsertValue, type LessonInsertPoint,
} from "./lessonBlocks";

/** Виды, у которых бэкенд отдаёт растр страницы; остальные показываются текстом. */
const RASTER_KINDS = new Set(["pdf", "image", "typst"]);

/** Где открыть просмотр: материал и его страница. Место в выдаче узнаётся по этой паре. */
export interface LessonPickerTarget {
  materialId: string;
  page: number;
}

interface LessonSourcePickerProps {
  projectId: string;
  lessonId: string | null;
  busy: boolean;
  materials: MaterialRead[];
  target: LessonPickerTarget;
  /** Найденные места поиска — рельс «Найдено»; пусто, когда открыли со «Страниц». */
  places: SourcePlace[];
  terms: string[];
  /** `${materialId}#${page}` страниц открытого урока — чтобы не добавить одно дважды. */
  lessonPages: Set<string>;
  blocks: LessonBlockRead[];
  insertPoint: LessonInsertPoint;
  onInsertPointChange(point: LessonInsertPoint): void;
  onAdd(command: Omit<LessonBlockCommand, "expected_revision">): Promise<boolean>;
  onClose(): void;
}

/**
 * Страница материала во весь диалог: что именно берём в урок и куда оно встанет.
 *
 * Тот же приём, что у «Предпросмотра найденного места» экзамена: строка выдачи
 * показывает один абзац, и по нему нельзя решить, тот ли это кусок. Здесь абзац
 * виден на своей странице вместе с соседями, а вместо привязки к вопросу —
 * вставка в урок в выбранное место.
 */
export function LessonSourcePicker({
  projectId, lessonId, busy, materials, target, places, terms, lessonPages, blocks,
  insertPoint, onInsertPointChange, onAdd, onClose,
}: LessonSourcePickerProps) {
  const [materialId, setMaterialId] = useState(target.materialId);
  const [pageNumber, setPageNumber] = useState(target.page);
  const [page, setPage] = useState<MaterialPageRead | null>(null);
  const [loading, setLoading] = useState(false);
  const [pageError, setPageError] = useState("");
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [drawing, setDrawing] = useState(false);
  const [box, setBox] = useState<number[] | null>(null);
  const [notice, setNotice] = useState<{ text: string; tone: "info" | "danger" } | null>(null);
  const foundRef = useRef<HTMLElement>(null);

  const material = materials.find((item) => item.id === materialId) ?? materials[0] ?? null;
  const pageCount = material?.page_count ?? 1;
  const foundHere = useMemo(
    () => places.find((item) => item.materialId === materialId && item.pageNumber === pageNumber) ?? null,
    [places, materialId, pageNumber],
  );
  const foundIds = useMemo(() => new Set(foundHere?.fragmentIds ?? []), [foundHere]);

  useEffect(() => {
    if (!material) return;
    const controller = new AbortController();
    setLoading(true);
    setPageError("");
    getMaterialPage(projectId, material.id, pageNumber, controller.signal)
      .then((loaded) => { if (!controller.signal.aborted) setPage(loaded); })
      .catch((caught: unknown) => {
        if (controller.signal.aborted) return;
        setPage(null);
        setPageError(errorText(caught, "Страница не загрузилась"));
      })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [projectId, material?.id, pageNumber]); // eslint-disable-line react-hooks/exhaustive-deps

  // По умолчанию отмечено ровно то, что нашёл поиск: снять лишнее дешевле, чем
  // собирать выбор с нуля. На странице без совпадений выбор пуст.
  useEffect(() => {
    setSelectedIds(foundHere ? [...foundHere.fragmentIds] : []);
    setBox(null);
  }, [foundHere, materialId, pageNumber]);

  /** Служебные блоки страницы: колонтитул и номер листа уроку ничего не дают. */
  const serviceBlocks = useMemo(
    () => new Set((page?.blocks ?? []).filter((item) => item.block_class === "service").map((item) => item.id)),
    [page],
  );
  const contentIds = useMemo(
    () => (page?.fragments ?? []).filter((item) => !serviceBlocks.has(item.block_id)).map((item) => item.id),
    [page, serviceBlocks],
  );

  const structureBlock = useMemo(() => {
    const first = page?.fragments.find((item) => selectedIds.includes(item.id));
    return first ? page?.blocks.find((item) => item.id === first.block_id) ?? null : null;
  }, [page, selectedIds]);

  function goToPlace(place: SourcePlace) {
    setMaterialId(place.materialId);
    setPageNumber(place.pageNumber);
  }

  /** Показать текущее место в рельсе: открытая страница может быть где угодно в выдаче. */
  const revealActivePlace = useCallback((focus: boolean) => {
    const active = foundRef.current?.querySelector<HTMLElement>("button.is-active");
    if (!active) return;
    if (focus) active.focus({ preventScroll: true });
    active.scrollIntoView({ block: "nearest" });
  }, []);

  useEffect(() => {
    const frame = requestAnimationFrame(() => revealActivePlace(false));
    return () => cancelAnimationFrame(frame);
  }, [materialId, pageNumber, revealActivePlace]);

  async function add(command: Omit<LessonBlockCommand, "expected_revision">, done: string) {
    const ok = await onAdd(command);
    setNotice(ok
      ? { text: `${done} · ${insertSummary(insertPoint, blocks)}`, tone: "info" }
      : { text: "Не удалось добавить — подробности в панели урока.", tone: "danger" });
    if (ok) setBox(null);
  }

  const inLesson = lessonPages.has(`${materialId}#${pageNumber}`);
  const canAdd = Boolean(lessonId) && !busy;
  const raster = material ? RASTER_KINDS.has(material.presentation_kind) : false;

  return (
    <Dialog
      open
      onOpenChange={(next) => { if (!next) onClose(); }}
      title={material ? material.display_name || material.original_name : "Материал"}
      description={`Страница ${pageNumber} из ${pageCount}`}
      className="lesson-picker-dialog"
      onOpenAutoFocus={(event) => {
        // Иначе фокус уезжает на первую кнопку рельса, а браузер прокручивает
        // список к ней — мимо места, которое открывали.
        if (places.length === 0) return;
        event.preventDefault();
        revealActivePlace(true);
      }}
      footer={(
        <div className="lesson-picker-footer">
          <span>{inLesson ? "Эта страница уже есть в уроке" : "Выберите, что взять в урок"}</span>
          <Button variant="secondary" onClick={onClose}>Закрыть</Button>
        </div>
      )}
    >
      <div className="lesson-picker-head">
        <Select
          ariaLabel="Источник"
          className="lesson-picker-source"
          value={material?.id ?? null}
          options={materials.map((item) => ({ value: item.id, label: item.display_name || item.original_name }))}
          onValueChange={(value) => { if (value) { setMaterialId(value); setPageNumber(1); } }}
        />
        <PageNumberInput page={pageNumber} pageCount={pageCount} onPageChange={setPageNumber} />
        {inLesson && <StatusBadge tone="info">в уроке</StatusBadge>}
        {page && <QualityBadge quality={page.quality} showReview={false} />}
      </div>

      <div className="lesson-picker">
        <nav className="lesson-picker-rail" aria-label="Навигация по материалу">
          {places.length > 0 && (
            <section className="lesson-picker-found" ref={foundRef}>
              <h3>Найдено · {places.length}</h3>
              {groupPlacesByMaterial(places).map((group) => (
                <div key={group.materialId}>
                  <h4>{group.materialName}</h4>
                  <ul>
                    {group.places.map((item) => (
                      <li key={item.key}>
                        <button
                          type="button"
                          className={item.materialId === materialId && item.pageNumber === pageNumber ? "is-active" : ""}
                          onClick={() => goToPlace(item)}
                        >
                          <span>стр. {item.pageNumber}</span>
                          <small>{item.fragmentIds.length} совпад.</small>
                        </button>
                      </li>
                    ))}
                  </ul>
                </div>
              ))}
            </section>
          )}
          {material && (
            <PdfOutline
              outline={material.outline}
              outlineSource="embedded"
              page={pageNumber}
              pageCount={pageCount}
              pageStates={[]}
              showOcrReview={false}
              storageKey={`lesson-picker:${material.id}`}
              onPageChange={setPageNumber}
            />
          )}
        </nav>

        <div className="lesson-picker-page">
          {loading && <LoadingState label="Загружаем страницу" />}
          {!loading && pageError && <p className="lessons-panel-hint">{pageError}</p>}
          {!loading && !pageError && page && (raster ? (
            <LessonPageSheet
              projectId={projectId}
              materialId={materialId}
              page={page}
              pageNumber={pageNumber}
              foundIds={foundIds}
              selectedIds={selectedIds}
              drawing={drawing}
              box={box}
              onBoxChange={setBox}
              onToggle={(id) => toggle(setSelectedIds, id)}
            />
          ) : (
            <StructuredPage
              page={page}
              terms={terms}
              showOcrReview={false}
              assetUrl={(fragmentId) => materialFragmentAssetUrl(projectId, materialId, fragmentId)}
              fragmentProps={(fragment) => ({
                className: [foundIds.has(fragment.id) ? "is-found" : "", selectedIds.includes(fragment.id) ? "is-picked" : ""].filter(Boolean).join(" "),
                onClick: () => toggle(setSelectedIds, fragment.id),
              })}
            />
          ))}
        </div>

        <aside className="lesson-picker-actions">
          <label className="lesson-picker-where">
            <span>Куда вставить</span>
            <Select
              ariaLabel="Куда вставить в урок"
              value={insertValue(insertPoint)}
              options={insertOptions(blocks)}
              disabled={!lessonId}
              onValueChange={(value) => { if (value) onInsertPointChange(parseInsertValue(value)); }}
            />
          </label>

          {notice && <p className={`lesson-picker-notice is-${notice.tone}`} role="status">{notice.text}</p>}
          {!lessonId && <p className="lessons-panel-hint">Сначала создайте урок — добавлять пока некуда.</p>}

          <Button
            className="lesson-picker-add"
            disabled={!canAdd}
            onClick={() => void add({ operation: "add_page", material_id: materialId, page_from: pageNumber }, `Страница ${pageNumber} добавлена`)}
          >
            <Plus size={15} />Страницу целиком
          </Button>
          <Button
            className="lesson-picker-add"
            variant="secondary"
            disabled={!canAdd || selectedIds.length === 0}
            onClick={() => {
              const ordered = (page?.fragments ?? []).filter((item) => selectedIds.includes(item.id));
              if (ordered.length === 0) return;
              void add({
                operation: "add_fragments", material_id: materialId,
                from_fragment_id: ordered[0].id, to_fragment_id: ordered[ordered.length - 1].id,
              }, `Абзацев добавлено: ${ordered.length}`);
            }}
          >
            <Plus size={15} />Выбранные абзацы · {selectedIds.length}
          </Button>
          <Button
            className="lesson-picker-add"
            variant="secondary"
            disabled={!canAdd || !structureBlock}
            onClick={() => {
              const first = page?.fragments.find((item) => selectedIds.includes(item.id));
              if (first) void add({ operation: "add_block", material_id: materialId, fragment_id: first.id }, "Блок добавлен");
            }}
          >
            <Layers size={15} />
            Блок целиком{structureBlock?.title ? ` · «${structureBlock.title}»` : ""}
          </Button>

          {raster && (
            <div className="lesson-picker-region">
              <Button
                variant={drawing ? "secondary" : "ghost"}
                aria-pressed={drawing}
                onClick={() => { setDrawing((value) => !value); setBox(null); }}
              >
                <Crop size={15} />{drawing ? "Выйти из выделения области" : "Выделить область…"}
              </Button>
              {drawing && (
                <>
                  <p className="lessons-panel-hint">Обведите схему или таблицу прямо на странице. В уроке область встанет вырезом листа.</p>
                  <Button
                    disabled={!canAdd || !usableBox(box)}
                    onClick={() => { if (box) void add({ operation: "add_region", material_id: materialId, page_from: pageNumber, region_bbox: box }, "Область добавлена"); }}
                  >
                    <Crop size={15} />Добавить область
                  </Button>
                  <Button variant="ghost" disabled={!box} onClick={() => setBox(null)}>Сбросить рамку</Button>
                </>
              )}
            </div>
          )}

          <div className="lesson-picker-picks">
            <div className="lesson-picker-picks-head">
              <h3>Абзацы страницы</h3>
              <Button variant="ghost" disabled={contentIds.length === 0} onClick={() => setSelectedIds(selectedIds.length === contentIds.length ? [] : contentIds)}>
                <SquareDashed size={14} />{selectedIds.length === contentIds.length && contentIds.length > 0 ? "Снять всё" : "Выбрать всё"}
              </Button>
            </div>
            <ul>
              {(page?.fragments ?? []).map((fragment) => (
                <li
                  key={fragment.id}
                  className={[foundIds.has(fragment.id) ? "is-found" : "", serviceBlocks.has(fragment.block_id) ? "is-service" : ""].filter(Boolean).join(" ")}
                >
                  <label>
                    <input
                      type="checkbox"
                      checked={selectedIds.includes(fragment.id)}
                      onChange={() => toggle(setSelectedIds, fragment.id)}
                    />
                    <span>{fragmentPreview(fragment)}</span>
                  </label>
                </li>
              ))}
            </ul>
            {page?.fragments.length === 0 && <p className="lessons-panel-hint">Текст страницы не распознан — её можно добавить целиком.</p>}
          </div>
        </aside>
      </div>
    </Dialog>
  );
}

function toggle(set: (update: (current: string[]) => string[]) => void, id: string) {
  set((current) => (current.includes(id) ? current.filter((item) => item !== id) : [...current, id]));
}

/** Рамка тоньше 2 % листа — промах мимо картинки, а не выделение. */
function usableBox(box: number[] | null): boolean {
  return box !== null && box[2] - box[0] > 0.02 && box[3] - box[1] > 0.02;
}
