import { useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router";
import { BookPlus, RotateCcw, Search } from "lucide-react";
import { createBindings } from "../../api/bindings";
import { decideCoverage, type CoverageDecisionAction } from "../../api/coverage";
import { undoProjectAction } from "../../api/projects";
import { searchProjectMaterials } from "../../api/search";
import {
  EvidenceCard,
  EvidenceDecisionMenu,
  EvidenceStructuredReader,
  LessonEvidenceDialog,
} from "../../components/domain";
import {
  Button,
  EmptyState,
  ErrorState,
  LoadingState,
  SegmentedTabs,
  StatusBadge,
} from "../../components/ui";
import { useTopicEvidence } from "../../hooks/useTopicEvidence";
import { toSourcePlaces, type SourcePlace } from "./sourcePlaces";

type SourceMode = "together" | "research" | "search";
const MODES: Array<{ value: SourceMode; label: string }> = [
  { value: "together", label: "Вместе" },
  { value: "research", label: "Исследование" },
  { value: "search", label: "Поиск" },
];

interface TextbookSourcePanelProps {
  projectId: string;
  topicId: string;
  topicTitle: string;
  initialEvidenceId?: string | null;
  returnTo?: string | null;
  onBindingsChanged(): void;
}

/** Учебниковый Источник: исследованные опоры сначала, BM25 только по явной кнопке. */
export function TextbookSourcePanel({
  projectId,
  topicId,
  topicTitle,
  initialEvidenceId,
  returnTo,
  onBindingsChanged,
}: TextbookSourcePanelProps) {
  const [params, setParams] = useSearchParams();
  const [mode, setMode] = useState<SourceMode>("together");
  const [query, setQuery] = useState(topicTitle);
  const [places, setPlaces] = useState<SourcePlace[]>([]);
  const [searched, setSearched] = useState(false);
  const [searching, setSearching] = useState(false);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [undoSequence, setUndoSequence] = useState<number | null>(null);
  const [lessonOpen, setLessonOpen] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const evidence = useTopicEvidence(projectId, topicId, initialEvidenceId);

  useEffect(() => {
    setQuery(topicTitle);
    setPlaces([]);
    setSearched(false);
    setNotice("");
  }, [topicId, topicTitle]);

  useEffect(() => {
    if (!evidence.selectedId || evidence.selectedId === params.get("evidence")) return;
    const next = new URLSearchParams(params);
    next.set("evidence", evidence.selectedId);
    if (evidence.evidence) next.set("source", evidence.evidence.material_id);
    setParams(next, { replace: true });
  }, [evidence.selectedId, evidence.evidence?.material_id]);

  async function search() {
    if (!query.trim()) return;
    setSearching(true);
    setNotice("");
    try {
      const result = await searchProjectMaterials(projectId, query, { nodeId: topicId });
      setPlaces(toSourcePlaces(result.results));
      setSearched(true);
    } catch (caught) {
      setNotice(caught instanceof Error ? caught.message : "Поиск не выполнен");
    } finally {
      setSearching(false);
    }
  }

  async function bind(place: SourcePlace) {
    setBusy(true);
    try {
      const result = await createBindings(projectId, {
        program_node_id: topicId,
        fragment_ids: place.fragmentIds,
        mechanism: "search",
      });
      setUndoSequence(result.latest_undoable_action?.sequence ?? null);
      setNotice(`Привязано фрагментов: ${result.bindings.length}.`);
      onBindingsChanged();
      await evidence.refresh();
    } catch (caught) {
      setNotice(caught instanceof Error ? caught.message : "Фрагменты не привязаны");
    } finally {
      setBusy(false);
    }
  }

  async function decide(action: CoverageDecisionAction, role?: "definition" | "explanation" | "example") {
    if (!evidence.evidence || !evidence.groups) return;
    setBusy(true);
    try {
      const result = await decideCoverage(projectId, {
        request_key: crypto.randomUUID(),
        expected_coverage_revision: evidence.groups.coverage_revision,
        action,
        binding_id: evidence.evidence.binding_id,
        role,
      });
      setNotice(result.message);
      setUndoSequence(result.action_sequence);
      onBindingsChanged();
      await evidence.refresh();
    } catch (caught) {
      setNotice(caught instanceof Error ? caught.message : "Решение не сохранено");
    } finally {
      setBusy(false);
    }
  }

  async function undo() {
    if (undoSequence === null) return;
    setBusy(true);
    try {
      await undoProjectAction(projectId, undoSequence);
      setUndoSequence(null);
      setNotice("Последнее действие отменено.");
      onBindingsChanged();
      await evidence.refresh();
    } catch (caught) {
      setNotice(caught instanceof Error ? caught.message : "Действие уже нельзя отменить");
    } finally {
      setBusy(false);
    }
  }

  const researched = evidence.groups ? [
    ...evidence.groups.starter,
    ...evidence.groups.explanations,
    ...evidence.groups.practice,
    ...evidence.groups.depth,
  ] : [];
  const displayed = mode === "research" || !evidence.groups
    ? researched
    : [...researched, ...evidence.groups.mentions, ...evidence.groups.legacy];

  return <div className="textbook-source-panel">
    <header className="textbook-source-head">
      <SegmentedTabs label="Режим источника" value={mode} tabs={MODES} onChange={setMode} />
      <div>
        {returnTo && <Link to={returnTo}>Вернуться в Покрытие</Link>}
        {mode !== "search" && <Button variant="secondary" onClick={() => { setMode("search"); requestAnimationFrame(() => inputRef.current?.focus()); }}><Search size={14} />Найти ещё</Button>}
      </div>
    </header>
    {notice && <div className="workspace-source-tab-notice" role="status"><span>{notice}</span>{undoSequence !== null && <Button variant="ghost" disabled={busy} onClick={() => void undo()}><RotateCcw size={14} />Отменить</Button>}</div>}
    {evidence.updateAvailable && <div className="coverage-refresh-offer"><span>Исследование обновилось; открытая опора оставлена на месте.</span><Button variant="secondary" onClick={() => void evidence.refresh()}>Обновить список</Button></div>}

    {mode !== "search" && <div className="textbook-source-reading">
      <aside className="textbook-source-evidence-list">
        {evidence.loading && !evidence.groups && <LoadingState label="Загружаем исследованные опоры" />}
        {evidence.error && <ErrorState message={evidence.error} />}
        {displayed.map((item) => <EvidenceCard key={item.id} evidence={item} selected={item.id === evidence.selectedId} onSelect={() => evidence.select(item.id)} />)}
        {displayed.length === 0 && !evidence.loading && <EmptyState title="Исследованных объяснений пока нет"><p>Поиск остаётся доступен вручную; он не запускается при открытии темы.</p></EmptyState>}
      </aside>
      <section className="textbook-source-reader">
        {evidence.evidence ? <>
          <header><div><small>{evidence.evidence.material_name} · стр. {evidence.evidence.page_from}{evidence.evidence.page_to !== evidence.evidence.page_from ? `–${evidence.evidence.page_to}` : ""}</small><h2>{evidence.evidence.topic_title}</h2></div><div>{evidence.evidence.preferred && <StatusBadge tone="info">читать первой</StatusBadge>}<EvidenceDecisionMenu evidence={evidence.evidence} busy={busy} onAction={(action, role) => void decide(action, role)} /></div></header>
          <EvidenceStructuredReader projectId={projectId} evidence={evidence.evidence} />
          <footer><Button onClick={() => setLessonOpen(true)} disabled={busy || evidence.evidence.stale}><BookPlus size={14} />Добавить в урок</Button></footer>
        </> : !evidence.loading && <EmptyState title="Выберите опору" />}
      </section>
    </div>}

    {mode === "search" && <section className="textbook-source-search">
      <form onSubmit={(event) => { event.preventDefault(); void search(); }}>
        <label><Search size={14} /><input ref={inputRef} type="search" value={query} onChange={(event) => setQuery(event.target.value)} aria-label="Найти ещё в материалах проекта" /></label>
        <Button type="submit" disabled={searching || !query.trim()}>Найти</Button>
      </form>
      {searching && <LoadingState label="Ищем в материалах" />}
      {searched && !searching && places.length === 0 && <EmptyState title="Совпадений нет" />}
      {places.length > 0 && <ul>{places.map((place) => <li key={place.key}><span><strong>{place.materialName} · стр. {place.pageNumber}</strong><p>{place.text}</p></span><Button variant="secondary" disabled={busy} onClick={() => void bind(place)}>Привязать</Button></li>)}</ul>}
    </section>}

    <LessonEvidenceDialog
      open={lessonOpen}
      projectId={projectId}
      evidence={evidence.evidence}
      onOpenChange={setLessonOpen}
      onAdded={(lesson) => {
        setUndoSequence(null);
        setNotice(`Материал добавлен в урок «${lesson.title}».`);
      }}
    />
  </div>;
}
