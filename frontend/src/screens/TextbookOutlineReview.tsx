import {
  ArrowDown,
  ArrowLeft,
  ArrowRight,
  ArrowUp,
  ChevronLeft,
  ChevronRight,
  Plus,
  Trash2,
  Undo2,
  WandSparkles,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import { getAiSettings, type AiSettingsRead } from "../api/ai";
import {
  getMaterialOutline,
  materialPageImageUrl,
  runMaterialOutlineModel,
  type MaterialRead,
  type OutlineItem,
  type OutlineSource,
} from "../api/materials";
import { Button, ConfirmDialog, Field, IconButton, LoadingState, Select } from "../components/ui";
import { DocumentStage } from "../components/domain/material-viewer/DocumentStage";
import { PageNumberInput } from "../components/domain/material-viewer/ViewerToolbar";
import { buildTree } from "../components/domain/material-viewer/PdfOutline";

export interface OutlineDraftState {
  material_id: string;
  source: OutlineSource;
  items: OutlineItem[];
  source_pages: number[];
  /** Страница для просмотрщика по умолчанию — см. `OutlineDetailRead.review_pages`. */
  review_pages: number[];
  review_needs_check: boolean;
  edited: boolean;
  checked_at: string | null;
}

const SOURCE_LABEL: Record<OutlineSource, string> = {
  embedded: "закладки PDF",
  printed: "печатная страница",
  recognized: "заголовки текста",
  model: "с ИИ",
  none: "не найдено",
};

function modelUnavailableReason(settings: AiSettingsRead | null, loaded: boolean): string | null {
  if (!loaded) return "Проверяем настройки внешних моделей";
  if (!settings?.external_models_enabled) return "Внешние модели выключены в Параметрах";
  const role = settings.roles.find((candidate) => candidate.role === "study_outline_extract");
  if (!role?.enabled || !role.resolved_provider_id || !role.resolved_model) {
    return "Для этой функции не настроена текстовая модель";
  }
  const provider = settings.providers.find((candidate) => candidate.id === role.resolved_provider_id);
  if (!provider?.has_api_key) return "Для выбранного провайдера не сохранён API-ключ";
  return null;
}

interface TextbookOutlineReviewProps {
  projectId: string;
  materials: MaterialRead[];
  value: OutlineDraftState | null;
  onChange: (next: OutlineDraftState | null) => void;
}

/**
 * Блок «Проверка оглавления» шага 3: слева страница документа, справа дерево
 * найденного оглавления с правкой. Импорт в настоящую программу здесь не
 * происходит — это только визуальная проверка перед шагом 4 (Работа 5 плана
 * правок мастера учебника).
 */
export function TextbookOutlineReview({ projectId, materials, value, onChange }: TextbookOutlineReviewProps) {
  const candidates = materials.filter((material) => (material.page_count ?? 0) > 0);
  const [materialId, setMaterialId] = useState(
    () => value?.material_id
      ?? candidates.find((item) => item.source_role === "main")?.id
      ?? candidates[0]?.id
      ?? "",
  );
  const material = candidates.find((item) => item.id === materialId) ?? null;

  useEffect(() => {
    // Материалы проекта грузятся асинхронно и на первом кадре ещё пусты:
    // как только список пришёл, а выбор всё ещё не указывает ни на один
    // реальный материал, подставляем основной (или первый попавшийся).
    if (materialId && candidates.some((item) => item.id === materialId)) return;
    const next = candidates.find((item) => item.source_role === "main")?.id ?? candidates[0]?.id;
    if (next) setMaterialId(next);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [candidates.map((item) => item.id).join(",")]);

  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState("");
  const [page, setPage] = useState(() => value?.review_pages?.[0] ?? value?.source_pages[0] ?? 1);
  const [aiSettings, setAiSettings] = useState<AiSettingsRead | null>(null);
  const [aiSettingsLoaded, setAiSettingsLoaded] = useState(false);
  const [aiRunning, setAiRunning] = useState(false);
  const [aiError, setAiError] = useState("");
  const [history, setHistory] = useState<OutlineItem[][]>([]);
  const [clearConfirmOpen, setClearConfirmOpen] = useState(false);
  const fetchedFor = useRef<string | null>(null);

  useEffect(() => {
    const abort = new AbortController();
    void getAiSettings(abort.signal)
      .then(setAiSettings)
      .catch(() => undefined)
      .finally(() => setAiSettingsLoaded(true));
    return () => abort.abort();
  }, []);

  useEffect(() => {
    if (!materialId) return;
    if ((value && value.material_id === materialId) || fetchedFor.current === materialId) return;
    fetchedFor.current = materialId;
    setLoading(true);
    setLoadError("");
    getMaterialOutline(projectId, materialId, "auto")
      .then((detail) => {
        if (detail.source === "none") {
          onChange(null);
          return;
        }
        onChange({
          material_id: materialId,
          source: detail.source,
          items: detail.items,
          source_pages: detail.source_pages,
          review_pages: detail.review_pages,
          review_needs_check: detail.review_needs_check,
          edited: false,
          checked_at: new Date().toISOString(),
        });
        setPage(detail.review_pages[0] ?? detail.source_pages[0] ?? 1);
      })
      .catch((caught) => setLoadError(caught instanceof Error ? caught.message : "Не удалось получить оглавление"))
      .finally(() => setLoading(false));
  }, [projectId, materialId, value, onChange]);

  function commit(items: OutlineItem[]) {
    if (!value) return;
    setHistory((current) => [...current, value.items]);
    onChange({ ...value, items, edited: true });
  }

  function undo() {
    if (!value || history.length === 0) return;
    const previous = history[history.length - 1];
    setHistory((current) => current.slice(0, -1));
    onChange({ ...value, items: previous, edited: true });
  }

  function renameItem(index: number, title: string) {
    if (!value) return;
    commit(value.items.map((item, itemIndex) => (itemIndex === index ? { ...item, title } : item)));
  }

  function deleteItem(index: number) {
    if (!value) return;
    commit(value.items.filter((_, itemIndex) => itemIndex !== index));
  }

  function moveItem(index: number, direction: -1 | 1) {
    if (!value) return;
    const target = index + direction;
    if (target < 0 || target >= value.items.length) return;
    const next = [...value.items];
    [next[index], next[target]] = [next[target], next[index]];
    commit(next);
  }

  function changeLevel(index: number, delta: 1 | -1) {
    if (!value) return;
    const item = value.items[index];
    const nextLevel = Math.max(1, Math.min(4, item.level + delta));
    if (nextLevel === item.level) return;
    commit(value.items.map((current, itemIndex) => (itemIndex === index ? { ...current, level: nextLevel } : current)));
  }

  function addItem(afterIndex: number) {
    if (!value) return;
    const anchor = value.items[afterIndex];
    const draft: OutlineItem = { level: anchor?.level ?? 1, title: "Новый пункт", page: anchor?.page ?? page };
    const next = [...value.items];
    next.splice(afterIndex + 1, 0, draft);
    commit(next);
  }

  function skipOutline() {
    onChange({
      material_id: materialId,
      source: "none",
      items: [],
      source_pages: [],
      review_pages: [],
      review_needs_check: false,
      edited: true,
      checked_at: new Date().toISOString(),
    });
    setHistory([]);
  }

  function retrySearch() {
    fetchedFor.current = null;
    setHistory([]);
    onChange(null);
  }

  async function runModel() {
    if (!materialId) return;
    setAiRunning(true);
    setAiError("");
    try {
      const result = await runMaterialOutlineModel(projectId, materialId);
      const firstItemPage = result.items[0]?.page;
      onChange({
        material_id: materialId,
        source: "model",
        items: result.items,
        source_pages: [],
        review_pages: firstItemPage ? [firstItemPage] : [],
        review_needs_check: !firstItemPage,
        edited: false,
        checked_at: new Date().toISOString(),
      });
      setPage(firstItemPage ?? page);
      setHistory([]);
    } catch (caught) {
      setAiError(caught instanceof Error ? caught.message : "Не удалось получить оглавление от модели");
    } finally {
      setAiRunning(false);
    }
  }

  if (candidates.length === 0) return null;

  const pageCount = material?.page_count ?? 1;
  const isReady = material?.status === "ready";
  const isFailed = material?.status === "failed";
  const modelReason = modelUnavailableReason(aiSettings, aiSettingsLoaded);

  return (
    <section className="textbook-outline-review" aria-label="Проверка оглавления">
      <header className="textbook-outline-review-head">
        <h2>Проверка оглавления</h2>
        {candidates.length > 1 && (
          <Field label="Источник">
            <Select
              value={materialId}
              ariaLabel="Материал для проверки оглавления"
              options={candidates.map((item) => ({ value: item.id, label: item.display_name }))}
              onValueChange={(next) => next && setMaterialId(next)}
            />
          </Field>
        )}
      </header>

      {loading && <LoadingState label="Ищем оглавление" />}
      {loadError && <p className="inline-error" role="alert">{loadError}</p>}

      {!loading && value && value.items.length > 0 && (
        <>
          <p className="textbook-outline-source-note">
            Источник: {SOURCE_LABEL[value.source]}.
            {!isReady && " Текст ещё готовится, на оглавление это не влияет."}
          </p>
          {value.review_needs_check && (
            <p className="textbook-outline-source-note is-warning">
              Печатная страница с оглавлением не нашлась — проверьте вручную, с какой страницы начинается книга.
            </p>
          )}
          <DocumentStage
            mode="compare"
            storageKey={`textbook-outline:${materialId}`}
            sourceLabel="Страница документа"
            textLabel="Оглавление"
            source={
              <>
                <div className="textbook-outline-page-toolbar">
                  <IconButton
                    label="Предыдущая страница"
                    disabled={page <= 1}
                    onClick={() => setPage((current) => Math.max(1, current - 1))}
                  >
                    <ChevronLeft size={15} />
                  </IconButton>
                  <PageNumberInput page={page} pageCount={pageCount} onPageChange={setPage} />
                  <IconButton
                    label="Следующая страница"
                    disabled={page >= pageCount}
                    onClick={() => setPage((current) => Math.min(pageCount, current + 1))}
                  >
                    <ChevronRight size={15} />
                  </IconButton>
                </div>
                <div className="viewer-pane-scroll textbook-outline-page-scroll">
                  <img
                    className="textbook-outline-page-image"
                    src={materialPageImageUrl(projectId, materialId, page)}
                    alt={`Страница ${page}`}
                  />
                </div>
              </>
            }
            text={
              <div className="viewer-pane-scroll textbook-outline-tree">
                <div className="textbook-outline-tree-actions">
                  <Button variant="ghost" onClick={() => setClearConfirmOpen(true)}>
                    <Trash2 size={14} aria-hidden="true" />Удалить дерево
                  </Button>
                  <Button variant="ghost" disabled={history.length === 0} onClick={undo}>
                    <Undo2 size={14} aria-hidden="true" />Отменить
                  </Button>
                </div>
                {renderOutlineRows(value.items, {
                  onRename: renameItem,
                  onDelete: deleteItem,
                  onMove: moveItem,
                  onLevel: changeLevel,
                  onAdd: addItem,
                  onPage: setPage,
                })}
              </div>
            }
          />
          <ConfirmDialog
            open={clearConfirmOpen}
            onOpenChange={setClearConfirmOpen}
            title="Удалить дерево оглавления?"
            confirmLabel="Удалить дерево"
            destructive
            onConfirm={skipOutline}
          >
            <p>Распознанное и отредактированное оглавление этого материала уберётся из черновика. Его можно будет поискать заново.</p>
          </ConfirmDialog>
        </>
      )}

      {!loading && value && value.items.length === 0 && (
        <div className="textbook-outline-empty">
          <p>Оглавление не используется и не попадёт в программу.</p>
          <Button variant="secondary" onClick={retrySearch}>Поискать оглавление ещё раз</Button>
        </div>
      )}

      {!loading && !value && !isReady && !isFailed && (
        <div className="textbook-outline-empty">
          <p>Подождите разбора или продолжайте без распознанного оглавления.</p>
          <Button variant="secondary" onClick={skipOutline}>Продолжить без оглавления</Button>
        </div>
      )}

      {!loading && !value && (isReady || isFailed) && (
        <div className="textbook-outline-empty">
          <p>Оглавление не найдено ни закладками PDF, ни печатной страницей, ни заголовками текста.</p>
          {aiError && <p className="inline-error" role="alert">{aiError}</p>}
          <div className="material-entry-actions">
            <Button variant="secondary" disabled={aiRunning || Boolean(modelReason)} onClick={() => void runModel()}>
              <WandSparkles size={15} aria-hidden="true" />
              {aiRunning ? "Ищем с ИИ…" : "Попробовать с ИИ"}
            </Button>
            <Button variant="ghost" onClick={skipOutline}>Продолжить без оглавления</Button>
          </div>
          {modelReason && <p className="textbook-outline-source-note">{modelReason}</p>}
        </div>
      )}
    </section>
  );
}

interface RowActions {
  onRename: (index: number, title: string) => void;
  onDelete: (index: number) => void;
  onMove: (index: number, direction: -1 | 1) => void;
  onLevel: (index: number, delta: 1 | -1) => void;
  onAdd: (afterIndex: number) => void;
  onPage: (page: number) => void;
}

function renderOutlineRows(items: OutlineItem[], actions: RowActions) {
  const tree = buildTree(items);
  const indexByNode = new Map(items.map((item, index) => [item, index]));

  function renderNode(node: ReturnType<typeof buildTree>[number], depth: number): ReactNode {
    const index = indexByNode.get(node.item) ?? -1;
    return (
      <div className="textbook-outline-row" key={node.key} style={{ paddingInlineStart: `${depth * 16}px` }}>
        <button type="button" className="textbook-outline-row-page" onClick={() => actions.onPage(node.item.page)}>
          {node.item.page}
        </button>
        <input
          className="textbook-outline-row-title"
          value={node.item.title}
          title={node.item.title}
          onChange={(event) => actions.onRename(index, event.target.value)}
          aria-label={`Формулировка пункта «${node.item.title}»`}
        />
        <div className="textbook-outline-row-actions">
          <IconButton label="Поднять" disabled={index <= 0} onClick={() => actions.onMove(index, -1)}><ArrowUp size={14} /></IconButton>
          <IconButton label="Опустить" disabled={index >= items.length - 1} onClick={() => actions.onMove(index, 1)}><ArrowDown size={14} /></IconButton>
          <IconButton label="Уменьшить вложенность" disabled={node.item.level <= 1} onClick={() => actions.onLevel(index, -1)}><ArrowLeft size={14} /></IconButton>
          <IconButton label="Увеличить вложенность" disabled={node.item.level >= 4} onClick={() => actions.onLevel(index, 1)}><ArrowRight size={14} /></IconButton>
          <IconButton label="Добавить пункт после" onClick={() => actions.onAdd(index)}><Plus size={14} /></IconButton>
          <IconButton label="Удалить пункт" onClick={() => actions.onDelete(index)}><Trash2 size={14} /></IconButton>
        </div>
      </div>
    );
  }

  function walk(nodes: ReturnType<typeof buildTree>, depth: number): ReactNode[] {
    return nodes.flatMap((node) => [renderNode(node, depth), ...walk(node.children, depth + 1)]);
  }

  return <div role="tree" aria-label="Дерево оглавления">{walk(tree, 0)}</div>;
}
