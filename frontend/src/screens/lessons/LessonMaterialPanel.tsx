import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";
import { ChevronLeft, ChevronRight, Plus, Search, Sparkles } from "lucide-react";
import { getTopicSources, SOURCE_ROLE_LABELS, type LessonSourceRangeRead } from "../../api/lessons";
import { listMaterials, materialPageImageUrl, type MaterialRead } from "../../api/materials";
import { searchProjectMaterials, type SearchResultRead } from "../../api/search";
import { QualityBadge } from "../../components/domain";
import { Button, EmptyState, ErrorState, IconButton, LoadingState, SegmentedTabs, Select, Tooltip } from "../../components/ui";
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
}

function Stage({ label, stage }: { label: string; stage: string }) {
  return (
    <Tooltip label={`Появится на этапе ${stage}`} side="left">
      <span><Button variant="ghost" disabled><Plus size={14} />{label}</Button></span>
    </Tooltip>
  );
}

/** Правая панель «Материал для урока»: четыре вкладки (записка §2). */
export function LessonMaterialPanel({ projectId, topic, busy, refreshKey, onCreateFromRange }: LessonMaterialPanelProps) {
  const [tab, setTab] = useState<PanelTab>("search");
  return (
    <div className="lessons-material-panel">
      <header className="lessons-panel-head">
        <h2>Материал для урока</h2>
        <SegmentedTabs label="Материал для урока" value={tab} tabs={PANEL_TABS} onChange={setTab} className="lessons-panel-tabs" />
      </header>
      <div className="lessons-panel-body">
        {tab === "outline" && <OutlineTab projectId={projectId} topic={topic} busy={busy} refreshKey={refreshKey} onCreate={onCreateFromRange} />}
        {tab === "pages" && <PagesTab projectId={projectId} />}
        {tab === "search" && <SearchTab projectId={projectId} topic={topic} />}
        {tab === "suggested" && (
          <EmptyState title="Предложений пока нет" icon={<Sparkles size={24} />}>
            <p>Предложения появятся после автоматического разбора материала (проход 2).</p>
          </EmptyState>
        )}
      </div>
    </div>
  );
}

function OutlineTab({ projectId, topic, busy, refreshKey, onCreate }: { projectId: string; topic: ProgramTreeNode | null; busy: boolean; refreshKey: number; onCreate(materialId: string): void }) {
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
            <Stage label="Добавить всё в открытый урок" stage="2 — ручной редактор" />
          </div>
        </li>
      ))}
    </ul>
  );
}

function PagesTab({ projectId }: { projectId: string }) {
  const [materials, setMaterials] = useState<MaterialRead[] | null>(null);
  const [materialId, setMaterialId] = useState<string | null>(null);
  const [page, setPage] = useState(1);
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
        <IconButton label="Следующая страница" disabled={page >= pageCount} onClick={() => setPage(page + 1)}><ChevronRight size={15} /></IconButton>
      </div>
      <img className="lessons-pages-image" src={materialPageImageUrl(projectId, material.id, page)} alt={`${material.original_name}, страница ${page}`} />
      <div className="lessons-outline-actions">
        <Stage label="Добавить страницу" stage="2 — ручной редактор" />
        <Stage label="Добавить блок" stage="2 — ручной редактор" />
        <Stage label="Добавить фрагменты" stage="2 — ручной редактор" />
        <Stage label="Добавить область" stage="3 — массовая подготовка" />
      </div>
    </div>
  );
}

function SearchTab({ projectId, topic }: { projectId: string; topic: ProgramTreeNode | null }) {
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
              <QualityBadge quality={place.quality} />
              <Stage label="Добавить в урок" stage="2 — ручной редактор" />
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
