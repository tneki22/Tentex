import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { CSSProperties } from "react";
import { Link } from "react-router";
import { ChevronLeft, ChevronRight, EyeOff, Link2, SquareArrowOutUpRight, Unlink } from "lucide-react";
import type { BindingChangeResult, BindingFragmentRead } from "../../api/bindings";
import { createBindings, removeBinding, removeBindingsBulk } from "../../api/bindings";
import type { MaterialPageRead, MaterialRead } from "../../api/materials";
import {
  getMaterialPage,
  listMaterials,
  materialFragmentAssetUrl,
  materialPageImageUrl,
} from "../../api/materials";
import { undoProjectAction } from "../../api/projects";
import type { LatestUndoableAction } from "../../api/projects";
import { Button, Dialog, IconButton, LoadingState } from "../../components/ui";
import { QualityBadge } from "../../components/domain";
import { StructuredPage } from "../../components/domain/material-viewer";
import type { SourcePlace } from "./sourcePlaces";
import { groupPlacesByMaterial } from "./sourcePlaces";

/** Виды, у которых бэкенд отдаёт растр страницы. Остальным `/pages/{n}/image`
 *  отвечает 422 `page_image_unavailable`, и спрашивать его незачем. */
const RASTER_KINDS = new Set(["pdf", "image"]);

interface NoticeState {
  text: string;
  tone: "info" | "danger";
  undo?: LatestUndoableAction | null;
}

interface SourcePreviewDialogProps {
  projectId: string;
  node: { id: string; number: string; title: string };
  /** Видимые места выдачи в порядке ранга — по ним листает рельс слева. */
  places: SourcePlace[];
  activeKey: string;
  /** Слова запроса: подсветка подготовленного текста там, где растра нет. */
  terms: string[];
  /** Учебные привязки этого вопроса — из них видно, что уже взято. */
  bindings: BindingFragmentRead[];
  onActiveKeyChange: (key: string) => void;
  onBound: (bindings: BindingFragmentRead[]) => void;
  onUnbound: (bindingIds: string[]) => void;
  onHidePlace: (key: string) => void;
  onClose: () => void;
}

/**
 * Предпросмотр найденного места: страница документа с выделенными областями и
 * действия к ней.
 *
 * Быстрая альтернатива полной привязке в Материалах, а не её замена: строка
 * выдачи показывает один абзац, и по нему нельзя решить, тот ли это кусок.
 * Здесь тот же абзац виден на своей странице, вместе с соседями.
 */
export function SourcePreviewDialog({
  projectId,
  node,
  places,
  activeKey,
  terms,
  bindings,
  onActiveKeyChange,
  onBound,
  onUnbound,
  onHidePlace,
  onClose,
}: SourcePreviewDialogProps) {
  const groups = useMemo(() => groupPlacesByMaterial(places), [places]);
  const place = places.find((item) => item.key === activeKey) ?? places[0] ?? null;
  const placeKey = place?.key;
  const [materials, setMaterials] = useState<MaterialRead[]>([]);
  const [page, setPage] = useState<MaterialPageRead | null>(null);
  const [pageNumber, setPageNumber] = useState(place?.pageNumber ?? 1);
  const [pageLoading, setPageLoading] = useState(false);
  const [pageError, setPageError] = useState("");
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<NoticeState | null>(null);
  const railRef = useRef<HTMLDivElement>(null);

  const material = materials.find((item) => item.id === place?.materialId) ?? null;
  const pageCount = material?.page_count ?? null;
  const onFoundPage = place ? pageNumber === place.pageNumber : false;

  useEffect(() => {
    const controller = new AbortController();
    listMaterials(projectId, controller.signal).then(setMaterials).catch(() => undefined);
    return () => controller.abort();
  }, [projectId]);

  // Смена места возвращает на найденную страницу: соседняя страница относится к
  // прошлому месту и на новом означала бы совсем другой кусок документа.
  useEffect(() => {
    if (place) setPageNumber(place.pageNumber);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [placeKey]);

  useEffect(() => {
    if (!place) return;
    const controller = new AbortController();
    setPageLoading(true);
    setPageError("");
    getMaterialPage(projectId, place.materialId, pageNumber, controller.signal)
      .then((loaded) => {
        setPage(loaded);
        setPageError("");
      })
      .catch((caught: unknown) => {
        if (controller.signal.aborted) return;
        setPage(null);
        setPageError(caught instanceof Error ? caught.message : "Страница не загрузилась");
      })
      .finally(() => {
        if (!controller.signal.aborted) setPageLoading(false);
      });
    return () => controller.abort();
  }, [projectId, place?.materialId, pageNumber]);

  // По умолчанию отмечено ровно то, что нашёл поиск: это и есть предложение
  // системы, а снять лишнее дешевле, чем собирать выбор с нуля.
  useEffect(() => {
    setSelectedIds(onFoundPage && place ? [...place.fragmentIds] : []);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [placeKey, onFoundPage]);

  const pageBindings = useMemo(
    () => bindings.filter(
      (binding) => binding.material_id === place?.materialId && binding.page_number === pageNumber,
    ),
    [bindings, place?.materialId, pageNumber],
  );
  const boundFragmentIds = useMemo(
    () => new Set(pageBindings.map((binding) => binding.fragment_id)),
    [pageBindings],
  );

  /** Содержательные фрагменты страницы: колонтитул и номер страницы вопросу
   *  ничего не свидетельствуют, и в режиме привязки документа их тоже нет. */
  const contentFragmentIds = useMemo(() => {
    if (!page) return [];
    const serviceBlocks = new Set(
      page.blocks.filter((block) => block.block_class === "service").map((block) => block.id),
    );
    return page.fragments
      .filter((fragment) => !serviceBlocks.has(fragment.block_id))
      .map((fragment) => fragment.id);
  }, [page]);

  const foundOnPage = useMemo(
    () => new Set(onFoundPage && place ? place.fragmentIds : []),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [placeKey, onFoundPage],
  );

  const index = places.findIndex((item) => item.key === placeKey);

  /**
   * Перейти на соседнюю страницу документа.
   *
   * Если соседняя страница сама есть в выдаче, она становится активным местом:
   * иначе её совпадения остались бы неотмеченными, а рельс продолжал бы
   * показывать активной предыдущую страницу — два разных ответа на вопрос
   * «где я сейчас».
   */
  function goToPage(next: number) {
    const known = places.find(
      (item) => item.materialId === place?.materialId && item.pageNumber === next,
    );
    if (known) onActiveKeyChange(known.key);
    else setPageNumber(next);
  }

  const goToPlace = useCallback((offset: number) => {
    if (index < 0) return;
    const next = places[index + offset];
    if (next) onActiveKeyChange(next.key);
  }, [index, places, onActiveKeyChange]);

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      const target = event.target;
      if (target instanceof HTMLElement
        && (target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.isContentEditable)) {
        return;
      }
      if (event.key === "ArrowLeft") {
        event.preventDefault();
        goToPlace(-1);
      }
      if (event.key === "ArrowRight") {
        event.preventDefault();
        goToPlace(1);
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [goToPlace]);

  /** Показать активную страницу в рельсе, где бы она ни лежала в списке. */
  const revealActivePlace = useCallback(() => {
    const active = railRef.current?.querySelector<HTMLElement>("button.is-active");
    active?.focus({ preventScroll: true });
    active?.scrollIntoView({ block: "nearest" });
  }, []);

  useEffect(() => {
    const frame = requestAnimationFrame(revealActivePlace);
    return () => cancelAnimationFrame(frame);
  }, [placeKey, revealActivePlace]);

  async function run(
    action: () => Promise<BindingChangeResult>,
    done: (result: BindingChangeResult) => NoticeState,
  ) {
    setBusy(true);
    try {
      const result = await action();
      setNotice(done(result));
    } catch (caught) {
      setNotice({
        text: caught instanceof Error ? caught.message : "Действие не выполнено",
        tone: "danger",
      });
    } finally {
      setBusy(false);
    }
  }

  function bind(fragmentIds: string[], label: string) {
    if (!place || fragmentIds.length === 0) return;
    void run(
      () => createBindings(projectId, {
        program_node_id: node.id,
        fragment_ids: fragmentIds,
        mechanism: "search",
      }),
      (result) => {
        onBound(result.bindings);
        return { text: label, tone: "info", undo: result.latest_undoable_action };
      },
    );
  }

  function unbindOne(bindingId: string) {
    void run(
      () => removeBinding(projectId, bindingId),
      (result) => {
        onUnbound([bindingId]);
        return { text: "Привязка снята.", tone: "info", undo: result.latest_undoable_action };
      },
    );
  }

  function unbindPage() {
    if (!place) return;
    void run(
      () => removeBindingsBulk(projectId, {
        materialId: place.materialId,
        pageNumber,
        nodeId: node.id,
      }),
      (result) => {
        onUnbound(result.bindings.map((binding) => binding.id));
        return {
          text: "Страница отвязана от вопроса.",
          tone: "info",
          undo: result.latest_undoable_action,
        };
      },
    );
  }

  function undo(action: LatestUndoableAction) {
    setBusy(true);
    undoProjectAction(projectId, action.sequence)
      .then(() => {
        setNotice({ text: "Действие отменено.", tone: "info" });
        onUnbound(pageBindings.map((binding) => binding.id));
      })
      .catch((caught: unknown) => setNotice({
        text: caught instanceof Error ? caught.message : "Отменить не удалось",
        tone: "danger",
      }))
      .finally(() => setBusy(false));
  }

  function hide() {
    if (!place) return;
    const next = places[index + 1] ?? places[index - 1] ?? null;
    onHidePlace(place.key);
    if (next) onActiveKeyChange(next.key);
    else onClose();
  }

  function toggleFragment(fragmentId: string) {
    setSelectedIds((current) => (current.includes(fragmentId)
      ? current.filter((id) => id !== fragmentId)
      : [...current, fragmentId]));
  }

  if (!place) return null;

  const raster = RASTER_KINDS.has(place.presentationKind);
  const materialsLink = `/projects/${projectId}/materials/${place.materialId}`
    + `?page=${pageNumber}&focus=${place.fragmentIds[0] ?? ""}&node=${node.id}`;

  return (
    <Dialog
      open
      onOpenChange={(next) => { if (!next) onClose(); }}
      title={place.materialName}
      description={`Страница ${pageNumber}${pageCount ? ` из ${pageCount}` : ""}`}
      className="source-preview-dialog"
      onOpenAutoFocus={(event) => {
        // Иначе Radix ставит фокус на первую страницу рельса, а браузер
        // прокручивает список наверх — мимо места, которое открывали.
        event.preventDefault();
        revealActivePlace();
      }}
      footer={(
        <div className="source-preview-footer">
          <span>Место {index + 1} из {places.length}</span>
          <div className="source-preview-footer-steps">
            <IconButton label="Предыдущее место" disabled={index <= 0} onClick={() => goToPlace(-1)}>
              <ChevronLeft size={15} />
            </IconButton>
            <IconButton
              label="Следующее место"
              disabled={index < 0 || index >= places.length - 1}
              onClick={() => goToPlace(1)}
            >
              <ChevronRight size={15} />
            </IconButton>
            <Button variant="secondary" onClick={onClose}>Закрыть</Button>
          </div>
        </div>
      )}
    >
      <div className="source-preview">
        <nav className="source-preview-rail" ref={railRef} aria-label="Найденные места">
          {groups.map((group) => (
            <section key={group.materialId}>
              <h3>{group.materialName}</h3>
              <ul>
                {group.places.map((item) => (
                  <li key={item.key}>
                    <button
                      type="button"
                      className={item.key === placeKey ? "is-active" : ""}
                      onClick={() => onActiveKeyChange(item.key)}
                    >
                      <span>стр. {item.pageNumber}</span>
                      <small>
                        {item.fragmentIds.length} совпад.
                        {item.alreadyBound ? " · привязано" : ""}
                      </small>
                    </button>
                  </li>
                ))}
              </ul>
            </section>
          ))}
        </nav>

        <div className="source-preview-page">
          {pageLoading && <LoadingState label="Загружаем страницу" />}
          {!pageLoading && pageError && <p className="source-preview-page-error">{pageError}</p>}
          {!pageLoading && !pageError && page && (raster ? (
            <div className="source-preview-sheet">
              <img
                src={materialPageImageUrl(projectId, place.materialId, pageNumber)}
                alt={`Страница ${pageNumber} — ${place.materialName}`}
              />
              <div className="source-preview-regions">
                {page.fragments.map((fragment) => (
                  <button
                    type="button"
                    key={fragment.id}
                    className={regionClass(
                      foundOnPage.has(fragment.id),
                      boundFragmentIds.has(fragment.id),
                      selectedIds.includes(fragment.id),
                    )}
                    aria-pressed={selectedIds.includes(fragment.id)}
                    aria-label={`Фрагмент: ${preview(fragment.text)}`}
                    onClick={() => toggleFragment(fragment.id)}
                    style={{
                      left: `${fragment.bbox[0] * 100}%`,
                      top: `${fragment.bbox[1] * 100}%`,
                      width: `${(fragment.bbox[2] - fragment.bbox[0]) * 100}%`,
                      height: `${(fragment.bbox[3] - fragment.bbox[1]) * 100}%`,
                    } as CSSProperties}
                  />
                ))}
              </div>
            </div>
          ) : (
            <div className="source-preview-text">
              <p className="source-preview-text-note">
                У этого формата нет исходной страницы — показан подготовленный текст.
              </p>
              <StructuredPage
                page={page}
                terms={terms}
                assetUrl={(fragmentId) => materialFragmentAssetUrl(projectId, place.materialId, fragmentId)}
                showOcrReview={false}
                fragmentProps={(fragment) => ({
                  className: regionClass(
                    foundOnPage.has(fragment.id),
                    boundFragmentIds.has(fragment.id),
                    selectedIds.includes(fragment.id),
                  ),
                  onClick: () => toggleFragment(fragment.id),
                })}
              />
            </div>
          ))}
          <div className="source-preview-page-steps">
            <Button
              variant="ghost"
              disabled={pageNumber <= 1}
              onClick={() => goToPage(pageNumber - 1)}
            >
              <ChevronLeft size={14} /> стр. {pageNumber - 1}
            </Button>
            {!onFoundPage && (
              <Button variant="ghost" onClick={() => setPageNumber(place.pageNumber)}>
                Вернуться к найденному
              </Button>
            )}
            <Button
              variant="ghost"
              disabled={pageCount !== null && pageNumber >= pageCount}
              onClick={() => goToPage(pageNumber + 1)}
            >
              стр. {pageNumber + 1} <ChevronRight size={14} />
            </Button>
          </div>
        </div>

        <aside className="source-preview-actions">
          <p className="source-preview-target">
            Привязываем к: <strong>{node.number}. {node.title}</strong>
          </p>

          {notice && (
            <p className={`source-preview-notice is-${notice.tone}`} role="status">
              {notice.text}
              {notice.undo && (
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => undo(notice.undo as LatestUndoableAction)}
                >
                  Отменить
                </button>
              )}
            </p>
          )}

          <Button
            disabled={busy || contentFragmentIds.length === 0}
            onClick={() => bind(contentFragmentIds, `Привязана вся страница ${pageNumber}.`)}
          >
            <Link2 size={15} /> Привязать всю страницу
          </Button>
          <p className="source-preview-hint">
            Немного лишнего не мешает — это самый быстрый путь. Ниже можно оставить
            только нужные куски.
          </p>

          {page && (
            <section className="source-preview-picks">
              <h3>Фрагменты страницы</h3>
              <ul>
                {page.fragments.map((fragment) => (
                  <li key={fragment.id} className={foundOnPage.has(fragment.id) ? "is-found" : ""}>
                    <label>
                      <input
                        type="checkbox"
                        checked={selectedIds.includes(fragment.id)}
                        onChange={() => toggleFragment(fragment.id)}
                      />
                      <span>{preview(fragment.text)}</span>
                    </label>
                    {boundFragmentIds.has(fragment.id) && <em>привязан</em>}
                  </li>
                ))}
              </ul>
              <Button
                variant="secondary"
                disabled={busy || selectedIds.length === 0}
                onClick={() => bind(selectedIds, `Привязано фрагментов: ${selectedIds.length}.`)}
              >
                Привязать выбранные · {selectedIds.length}
              </Button>
            </section>
          )}

          {pageBindings.length > 0 && (
            <section className="source-preview-bound">
              <h3>Уже привязано с этой страницы</h3>
              <ul>
                {pageBindings.map((binding) => (
                  <li key={binding.id}>
                    <span>{preview(binding.text)}</span>
                    <IconButton
                      label="Снять привязку"
                      disabled={busy}
                      onClick={() => unbindOne(binding.id)}
                    >
                      <Unlink size={14} />
                    </IconButton>
                  </li>
                ))}
              </ul>
              <Button variant="ghost" disabled={busy} onClick={unbindPage}>
                Снять всё со страницы · {pageBindings.length}
              </Button>
            </section>
          )}

          <div className="source-preview-links">
            <QualityBadge quality={place.quality} />
            <Link className="secondary-button" to={materialsLink} onClick={onClose}>
              <SquareArrowOutUpRight size={14} /> Открыть в материалах
            </Link>
            <Button variant="ghost" onClick={hide}>
              <EyeOff size={14} /> Скрыть это место
            </Button>
          </div>
        </aside>
      </div>
    </Dialog>
  );
}

/** Четыре состояния области: найдено поиском, выбрано, уже привязано, обычное. */
function regionClass(found: boolean, bound: boolean, picked: boolean): string {
  return [found ? "is-found" : "", bound ? "is-bound" : "", picked ? "is-picked" : ""]
    .filter(Boolean)
    .join(" ");
}

/** Строка списка должна отличать фрагменты на взгляд, а не по номеру страницы. */
function preview(text: string): string {
  const compact = text.replace(/\s+/g, " ").trim();
  if (!compact) return "Без текста";
  return compact.length > 90 ? `${compact.slice(0, 90)}…` : compact;
}
