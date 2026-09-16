import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent, type PointerEvent as ReactPointerEvent } from "react";
import { ChevronLeft, ChevronRight, Crop, Plus, Search, Sparkles } from "lucide-react";
import { getTopicSources, SOURCE_ROLE_LABELS, type LessonBlockCommand, type LessonSourceRangeRead } from "../../api/lessons";
import { getMaterialPage, listMaterials, materialPageImageUrl, type MaterialPageRead, type MaterialRead } from "../../api/materials";
import { searchProjectMaterials, type SearchResultRead } from "../../api/search";
import { QualityBadge } from "../../components/domain";
import { Button, EmptyState, ErrorState, IconButton, LoadingState, SegmentedTabs, Select, StatusBadge } from "../../components/ui";
import type { ProgramTreeNode } from "../programTree";
import { toSourcePlaces } from "../workspace/sourcePlaces";
import { renderSearchHighlights } from "../workspace/searchHighlights";
import { errorText } from "./lessonTree";
import { pagesLabel } from "./LessonSourcesDialog";

type PanelTab = "outline" | "pages" | "search" | "suggested";

const PANEL_TABS: Array<{ value: PanelTab; label: string }> = [
  { value: "search", label: "Поиск" },
  { value: "suggested", label: "Предложено" },
  { value: "pages", label: "Страницы" },
  { value: "outline", label: "Оглавление" },
];

interface LessonMaterialPanelProps {
  projectId: string;
  topic: ProgramTreeNode | null;
  busy: boolean;
  /** Урок уже создан в этой сессии — перечитать диапазоны после изменений. */
  refreshKey: number;
  onCreateFromRange(materialId: string): void;
  lessonId: string | null;
  /** `${materialId}#${page}` страниц открытого урока: уже добавленное помечается «в уроке». */
  lessonPages: Set<string>;
  onAdd(command: Omit<LessonBlockCommand, "expected_revision">): void;
}

/** Правая панель «Материал для урока»: четыре вкладки (записка §2). */
export function LessonMaterialPanel({ projectId, topic, busy, refreshKey, onCreateFromRange, lessonId, lessonPages, onAdd }: LessonMaterialPanelProps) {
  const [tab, setTab] = useState<PanelTab>("search");
  return (
    <div className="lessons-material-panel">
      <header className="lessons-panel-head">
        <h2>Материал для урока</h2>
        <SegmentedTabs label="Материал для урока" value={tab} tabs={PANEL_TABS} onChange={setTab} className="lessons-panel-tabs" />
      </header>
      <div className="lessons-panel-body">
        {tab === "outline" && <OutlineTab projectId={projectId} topic={topic} busy={busy} refreshKey={refreshKey} onCreate={onCreateFromRange} lessonId={lessonId} onAdd={onAdd} />}
        {tab === "pages" && <PagesTab projectId={projectId} busy={busy} lessonId={lessonId} lessonPages={lessonPages} onAdd={onAdd} />}
        {tab === "search" && <SearchTab projectId={projectId} topic={topic} busy={busy} lessonId={lessonId} lessonPages={lessonPages} onAdd={onAdd} />}
        {tab === "suggested" && (
          <EmptyState title="Предложений пока нет" icon={<Sparkles size={24} />}>
            <p>Предложения появятся после автоматического разбора материала (проход 2).</p>
          </EmptyState>
        )}
      </div>
    </div>
  );
}

function OutlineTab({ projectId, topic, busy, refreshKey, onCreate, lessonId, onAdd }: { projectId: string; topic: ProgramTreeNode | null; busy: boolean; refreshKey: number; onCreate(materialId: string): void; lessonId: string | null; onAdd: LessonMaterialPanelProps["onAdd"] }) {
  const [ranges, setRanges] = useState<LessonSourceRangeRead[] | null>(null);
  const [error, setError] = useState("");
  const studyTopic = topic && topic.node_type !== "section" ? topic : null;

  useEffect(() => {
    if (!studyTopic) return;
    const controller = new AbortController();
    setRanges(null);
    setError("");
    getTopicSources(projectId, studyTopic.id, controller.signal)
      .then((result) => { if (!controller.signal.aborted) setRanges(result.ranges); })
      .catch((caught: unknown) => { if (!controller.signal.aborted) setError(errorText(caught, "Диапазоны не загрузились")); });
    return () => controller.abort();
  }, [projectId, studyTopic?.id, refreshKey]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!studyTopic) return <p className="lessons-panel-hint">Выберите тему — здесь появятся её страницы из оглавления.</p>;
  if (error) return <ErrorState message={error} />;
  if (!ranges) return <LoadingState label="Загружаем диапазоны темы" />;
  if (ranges.length === 0) return <p className="lessons-panel-hint">У темы нет страниц из оглавления — соберите урок вручную (этап 2).</p>;

  return (
    <ul className="lessons-outline-list">
      {ranges.map((item) => (
        <li key={item.material_id}>
          <div className="lessons-outline-title">
            <strong>{item.source_name}</strong>
            <span>{SOURCE_ROLE_LABELS[item.source_role]}</span>
          </div>
          <p>
            Оглавление: {pagesLabel(item.outline_page_from, item.outline_page_to)}
            {(item.page_from !== item.outline_page_from || item.page_to !== item.outline_page_to || item.starts_at_heading || item.ends_mid_page) && (
              <> · уточнено: {pagesLabel(item.page_from, item.page_to)}{item.starts_at_heading ? ", с заголовка" : ""}{item.ends_mid_page ? ", до следующего пункта" : ""}</>
            )}
          </p>
          {!item.is_parsed && <p className="lessons-panel-hint">Материал не разобран: урок пойдёт по страницам, без привязок.</p>}
          <div className="lessons-outline-actions">
            <Button variant="secondary" disabled={busy} onClick={() => onCreate(item.material_id)}>Создать урок из этого диапазона</Button>
            <Button variant="ghost" disabled={!lessonId || busy} onClick={() => onAdd({ operation: "add_outline", material_id: item.material_id, page_from: item.page_from, page_to: item.page_to })}><Plus size={14} />Добавить всё в открытый урок</Button>
          </div>
        </li>
      ))}
    </ul>
  );
}

function PagesTab({ projectId, busy, lessonId, lessonPages, onAdd }: { projectId: string; busy: boolean; lessonId: string | null; lessonPages: Set<string>; onAdd: LessonMaterialPanelProps["onAdd"] }) {
  const [materials, setMaterials] = useState<MaterialRead[] | null>(null);
  const [materialId, setMaterialId] = useState<string | null>(null);
  const [page, setPage] = useState(1);
  const [view, setView] = useState<PageView>("original");
  const [error, setError] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    listMaterials(projectId, controller.signal)
      .then((items) => {
        if (controller.signal.aborted) return;
        const paged = items.filter((item) => (item.page_count ?? 0) > 0);
        setMaterials(paged);
        setMaterialId((current) => current ?? paged[0]?.id ?? null);
      })
      .catch((caught: unknown) => { if (!controller.signal.aborted) setError(errorText(caught, "Материалы не загрузились")); });
    return () => controller.abort();
  }, [projectId]);

  if (error) return <ErrorState message={error} />;
  if (!materials) return <LoadingState label="Загружаем материалы проекта" />;
  if (materials.length === 0 || !materialId) return <p className="lessons-panel-hint">В проекте нет материалов со страницами.</p>;
  const material = materials.find((item) => item.id === materialId) ?? materials[0];
  const pageCount = material.page_count ?? 1;

  return (
    <div className="lessons-pages-tab">
      <Select
        ariaLabel="Источник"
        value={material.id}
        options={materials.map((item) => ({ value: item.id, label: item.display_name || item.original_name }))}
        onValueChange={(value) => { if (value) { setMaterialId(value); setPage(1); } }}
      />
      <div className="lessons-pages-nav">
        <IconButton label="Предыдущая страница" disabled={page <= 1} onClick={() => setPage(page - 1)}><ChevronLeft size={15} /></IconButton>
        <span>Страница {page} из {pageCount}</span>
        {lessonPages.has(`${material.id}#${page}`) && <StatusBadge tone="info">в уроке</StatusBadge>}
        <IconButton label="Следующая страница" disabled={page >= pageCount} onClick={() => setPage(page + 1)}><ChevronRight size={15} /></IconButton>
      </div>
      <SegmentedTabs label="Как показать страницу" value={view} tabs={PAGE_VIEW_TABS} onChange={setView} />
      {view === "original" && <img className="lessons-pages-image" src={materialPageImageUrl(projectId, material.id, page)} alt={`${material.original_name}, страница ${page}`} />}
      <div className="lessons-outline-actions">
        <Button variant="ghost" disabled={!lessonId || busy} onClick={() => onAdd({ operation: "add_page", material_id: material.id, page_from: page })}><Plus size={14} />Добавить страницу</Button>
        {view === "original" && <Button variant="ghost" onClick={() => setView("fragments")}>Выбрать абзацы или блок…</Button>}
      </div>
      {view === "fragments" && (
        <FragmentPicker key={`${material.id}#${page}`} projectId={projectId} materialId={material.id} page={page} busy={busy} lessonId={lessonId} onAdd={onAdd} />
      )}
      {view === "region" && (
        <RegionPicker key={`${material.id}#${page}`} projectId={projectId} material={material} page={page} busy={busy} lessonId={lessonId} onAdd={onAdd} />
      )}
    </div>
  );
}

type PageView = "original" | "fragments" | "region";

const PAGE_VIEW_TABS: Array<{ value: PageView; label: string }> = [
  { value: "original", label: "Оригинал" },
  { value: "fragments", label: "Абзацы" },
  { value: "region", label: "Область" },
];

/**
 * Выбор области страницы рамкой: схема или таблица, которой нет в текстовом слое.
 *
 * Координаты хранятся долями листа, как `bbox` фрагмента, поэтому рамка не зависит
 * от масштаба картинки в панели.
 */
function RegionPicker({ projectId, material, page, busy, lessonId, onAdd }: { projectId: string; material: MaterialRead; page: number; busy: boolean; lessonId: string | null; onAdd: LessonMaterialPanelProps["onAdd"] }) {
  // Якорь рамки — ref, а не состояние: первый `pointermove` приходит до перерисовки.
  const start = useRef<[number, number] | null>(null);
  const [box, setBox] = useState<number[] | null>(null);

  function pointAt(event: ReactPointerEvent<HTMLDivElement>): [number, number] {
    const bounds = event.currentTarget.getBoundingClientRect();
    return [
      Math.min(1, Math.max(0, (event.clientX - bounds.left) / bounds.width)),
      Math.min(1, Math.max(0, (event.clientY - bounds.top) / bounds.height)),
    ];
  }

  function stretchTo(event: ReactPointerEvent<HTMLDivElement>) {
    const from = start.current;
    if (!from) return;
    const [x, y] = pointAt(event);
    setBox([
      Math.min(from[0], x), Math.min(from[1], y),
      Math.max(from[0], x), Math.max(from[1], y),
    ]);
  }

  // Рамка тоньше 2 % листа — это промах мимо картинки, а не выделение.
  const usable = box !== null && box[2] - box[0] > 0.02 && box[3] - box[1] > 0.02;
  const overlay = box && {
    left: `${box[0] * 100}%`, top: `${box[1] * 100}%`,
    width: `${(box[2] - box[0]) * 100}%`, height: `${(box[3] - box[1]) * 100}%`,
  };

  return (
    <div className="lessons-region-picker">
      <p className="lessons-panel-hint">Обведите схему или таблицу. В уроке область встанет вырезом страницы; абзацы внутри рамки привяжутся к теме.</p>
      <div
        className="lessons-region-frame"
        onPointerDown={(event) => {
          event.currentTarget.setPointerCapture(event.pointerId);
          start.current = pointAt(event);
          stretchTo(event);
        }}
        onPointerMove={stretchTo}
        onPointerUp={(event) => {
          stretchTo(event);
          start.current = null;
        }}
        onPointerCancel={() => { start.current = null; }}
      >
        <img src={materialPageImageUrl(projectId, material.id, page)} alt={`${material.original_name}, страница ${page}`} draggable={false} />
        {overlay && <span className="lessons-region-box" style={overlay} />}
      </div>
      <div className="lessons-outline-actions">
        <Button variant="secondary" disabled={!lessonId || busy || !usable}
          onClick={() => { if (box) { onAdd({ operation: "add_region", material_id: material.id, page_from: page, region_bbox: box }); setBox(null); } }}>
          <Crop size={14} />Добавить область
        </Button>
        <Button variant="ghost" disabled={!box} onClick={() => setBox(null)}>Сбросить рамку</Button>
      </div>
    </div>
  );
}

/**
 * Выбор абзацев страницы: первый щелчок отмечает абзац, следующий расширяет
 * отрезок до себя. Кусок урока непрерывен, поэтому выделение всегда отрезок.
 */
function FragmentPicker({ projectId, materialId, page, busy, lessonId, onAdd }: { projectId: string; materialId: string; page: number; busy: boolean; lessonId: string | null; onAdd: LessonMaterialPanelProps["onAdd"] }) {
  const [data, setData] = useState<MaterialPageRead | null>(null);
  const [error, setError] = useState("");
  const [range, setRange] = useState<[number, number] | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    getMaterialPage(projectId, materialId, page, controller.signal)
      .then((result) => { if (!controller.signal.aborted) setData(result); })
      .catch((caught: unknown) => { if (!controller.signal.aborted) setError(errorText(caught, "Текст страницы не загрузился")); });
    return () => controller.abort();
  }, [projectId, materialId, page]);

  if (error) return <p className="lessons-panel-hint">{error} Страницу можно добавить целиком.</p>;
  if (!data) return <LoadingState label="Загружаем абзацы" />;
  if (data.fragments.length === 0) return <p className="lessons-panel-hint">Текст страницы не распознан — добавьте её целиком.</p>;
  const serviceBlocks = new Set(data.blocks.filter((block) => block.block_class === "service").map((block) => block.id));
  const fragments = data.fragments;

  function toggle(index: number) {
    setRange((current) => {
      if (!current) return [index, index];
      if (current[0] === index && current[1] === index) return null;
      return [Math.min(current[0], index), Math.max(current[1], index)];
    });
  }

  const inRange = (index: number) => range !== null && index >= range[0] && index <= range[1];
  const selectedBlock = range ? data.blocks.find((block) => block.id === fragments[range[0]].block_id) : undefined;

  return (
    <div className="lessons-fragment-picker">
      <p className="lessons-panel-hint">Щёлкните первый и последний абзац. Служебные строки видны в уроке страницами, но к теме не привязываются.</p>
      <ol className="lessons-fragment-list">
        {fragments.map((fragment, index) => (
          <li key={fragment.id}>
            <button
              type="button"
              aria-pressed={inRange(index)}
              className={[inRange(index) ? "is-selected" : "", serviceBlocks.has(fragment.block_id) ? "is-service" : "", fragment.element_kind === "heading" ? "is-heading" : ""].filter(Boolean).join(" ")}
              onClick={() => toggle(index)}
            >
              {fragment.text.length > 220 ? `${fragment.text.slice(0, 220)}…` : fragment.text || "[изображение]"}
            </button>
          </li>
        ))}
      </ol>
      <div className="lessons-outline-actions">
        <Button variant="secondary" disabled={!lessonId || busy || !range}
          onClick={() => { if (range) { onAdd({ operation: "add_fragments", material_id: materialId, from_fragment_id: fragments[range[0]].id, to_fragment_id: fragments[range[1]].id }); setRange(null); } }}>
          <Plus size={14} />Добавить выделенное{range ? ` · ${range[1] - range[0] + 1}` : ""}
        </Button>
        <Button variant="ghost" disabled={!lessonId || busy || !selectedBlock}
          onClick={() => { if (range) { onAdd({ operation: "add_block", material_id: materialId, fragment_id: fragments[range[0]].id }); setRange(null); } }}>
          <Plus size={14} />Добавить блок{selectedBlock?.title ? ` «${selectedBlock.title}»` : ""}{selectedBlock && selectedBlock.page_to > selectedBlock.page_from ? ` · стр. ${selectedBlock.page_from}–${selectedBlock.page_to}` : ""}
        </Button>
      </div>
    </div>
  );
}

function SearchTab({ projectId, topic, busy, lessonId, lessonPages, onAdd }: { projectId: string; topic: ProgramTreeNode | null; busy: boolean; lessonId: string | null; lessonPages: Set<string>; onAdd: LessonMaterialPanelProps["onAdd"] }) {
  const topicId = topic?.node_type === "section" ? undefined : topic?.id;
  const topicTitle = topic?.node_type === "section" ? "" : topic?.title ?? "";
  const [query, setQuery] = useState(topicTitle);
  const [results, setResults] = useState<SearchResultRead[] | null>(null);
  const [terms, setTerms] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const search = useCallback(async (value: string, signal?: AbortSignal) => {
    if (!value.trim()) return;
    setLoading(true);
    setError("");
    try {
      const response = await searchProjectMaterials(projectId, value.trim(), { nodeId: topicId, limit: 20 }, signal);
      if (signal?.aborted) return;
      setResults(response.results);
      setTerms(response.terms);
    } catch (caught) {
      if (!signal?.aborted) setError(errorText(caught, "Поиск не выполнился"));
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  }, [projectId, topicId]);

  useEffect(() => {
    setQuery(topicTitle);
    setResults(null);
    setTerms([]);
    if (!topicTitle) return;
    const controller = new AbortController();
    void search(topicTitle, controller.signal);
    return () => controller.abort();
  }, [topicTitle, search]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    await search(query);
  }

  const places = useMemo(() => results ? toSourcePlaces(results) : [], [results]);

  return (
    <div className="lessons-search-tab">
      <form className="lessons-search-form" onSubmit={(event) => void submit(event)}>
        <label className="workspace-tree-search">
          <Search size={15} />
          <span className="sr-only">Поиск по материалам</span>
          <input type="search" placeholder="Ethernet кадр FCS" value={query} onChange={(event) => setQuery(event.target.value)} />
        </label>
        <Button type="submit" variant="secondary" disabled={loading}>Найти</Button>
      </form>
      {error && <ErrorState message={error} />}
      {loading && <LoadingState label="Ищем" />}
      {terms.length > 0 && !loading && <p className="lessons-panel-hint">Искали по: {terms.join(" · ")}</p>}
      {results && places.length === 0 && <p className="lessons-panel-hint">Ничего не найдено.</p>}
      {places.length > 0 && (
        <ul className="lessons-search-results">
          {places.map((place) => (
            <li key={place.key}>
              <div className="lessons-search-result-copy">
                <p>{renderSearchHighlights(place.text, place.highlights)}</p>
                <small>{place.materialName} · стр. {place.pageNumber} · {place.fragmentIds.length} совпад.</small>
              </div>
              <div className="lessons-search-result-actions">
                <QualityBadge quality={place.quality} />
                {lessonPages.has(`${place.materialId}#${place.pageNumber}`) && <StatusBadge tone="info">в уроке</StatusBadge>}
                <Button variant="ghost" disabled={!lessonId || busy} onClick={() => onAdd({ operation: "add_page", material_id: place.materialId, page_from: place.pageNumber })}><Plus size={14} />Страницу</Button>
                <Button variant="ghost" disabled={!lessonId || busy} onClick={() => onAdd({ operation: "add_fragments", material_id: place.materialId, from_fragment_id: place.fragmentIds[0], to_fragment_id: place.fragmentIds.at(-1) })}><Plus size={14} />Найденные абзацы</Button>
                <Button variant="ghost" disabled={!lessonId || busy} onClick={() => onAdd({ operation: "add_block", material_id: place.materialId, fragment_id: place.fragmentIds[0] })}><Plus size={14} />Блок</Button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
