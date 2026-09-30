import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router";
import { BookPlus, RotateCcw, Search, Sparkles } from "lucide-react";
import { createBindings } from "../../api/bindings";
import { decideCoverage, type CoverageDecisionAction, type EvidenceSummary } from "../../api/coverage";
import { undoProjectAction } from "../../api/projects";
import { searchProjectMaterials } from "../../api/search";
import { EvidenceDecisionMenu } from "../../components/domain/EvidenceDecisionMenu";
import { EvidencePassageList, inReadingOrder, primaryPassages } from "../../components/domain/EvidencePassageList";
import { EvidenceStructuredReader } from "../../components/domain/EvidenceStructuredReader";
import { pagesLabel } from "../../components/domain/EvidenceCard";
import { LessonEvidenceDialog } from "../../components/domain/LessonEvidenceDialog";
import {
  Button,
  EmptyState,
  ErrorState,
  LoadingState,
  SegmentedTabs,
  StatusBadge,
} from "../../components/ui";
import { unavailableReason, useAiRoleAvailability } from "../../hooks/useAiRoleAvailability";
import { evidenceItems, useTopicEvidence } from "../../hooks/useTopicEvidence";
import { LessonBuildDialog } from "../lessons/LessonBuildDialog";
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

/**
 * Учебниковый Источник: куски исследованного текста темы, а не отдельные строки.
 * Кусок читается целиком справа и вставляется в урок одним блоком; несколько
 * отмеченных кусков встают подряд в порядке чтения. BM25 — только по «Найти ещё».
 */
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
  const [lessonItems, setLessonItems] = useState<EvidenceSummary[] | null>(null);
  /** Куски, из которых «Собрать с ИИ» строит урок; `null` — диалог закрыт. */
  const [buildItems, setBuildItems] = useState<EvidenceSummary[] | null>(null);
  const availability = useAiRoleAvailability("lesson_builder");
  const navigate = useNavigate();
  const [checked, setChecked] = useState<Set<string>>(new Set());
  const inputRef = useRef<HTMLInputElement>(null);
  const evidence = useTopicEvidence(projectId, topicId, initialEvidenceId);

  useEffect(() => {
    setQuery(topicTitle);
    setPlaces([]);
    setSearched(false);
    setNotice("");
    setChecked(new Set());
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
        binding_ids: evidence.evidence.binding_ids,
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

  function toggle(item: EvidenceSummary, value: boolean) {
    setChecked((current) => {
      const next = new Set(current);
      if (value) next.add(item.id);
      else next.delete(item.id);
      return next;
    });
  }

  const primary = primaryPassages(evidence.groups);
  const all = evidenceItems(evidence.groups);
  // Отмеченное встаёт в урок в порядке книги, а не в порядке кликов.
  const chosen = inReadingOrder(all.filter((item) => checked.has(item.id)), all);
  const selected = evidence.evidence;
  const hasAny = mode === "research" ? primary.length > 0 : all.length > 0;

  return <div className="textbook-source-panel">
    <header className="textbook-source-head">
      <SegmentedTabs label="Режим источника" value={mode} tabs={MODES} onChange={setMode} />
      <div>
        {returnTo && <Link to={returnTo}>Вернуться в Покрытие</Link>}
        {mode !== "search" && <Button variant="secondary" onClick={() => { setMode("search"); requestAnimationFrame(() => inputRef.current?.focus()); }}><Search size={14} />Найти ещё</Button>}
      </div>
    </header>
    {notice && <div className="workspace-source-tab-notice" role="status"><span>{notice}</span>{undoSequence !== null && <Button variant="ghost" disabled={busy} onClick={() => void undo()}><RotateCcw size={14} />Отменить</Button>}</div>}
    {evidence.updateAvailable && <div className="coverage-refresh-offer"><span>Исследование обновилось; открытый кусок оставлен на месте.</span><Button variant="secondary" onClick={() => void evidence.refresh()}>Обновить список</Button></div>}

    {mode !== "search" && <div className="textbook-source-reading">
      <aside className="textbook-source-evidence-list">
        {evidence.loading && !evidence.groups && <LoadingState label="Загружаем исследованный текст" />}
        {evidence.error && <ErrorState message={evidence.error} />}
        {primary.length > 0 && <div className="evidence-selection-bar">
          {checked.size > 0
            ? <>
              <span>Выбрано: {checked.size}</span>
              <Button variant="ghost" onClick={() => setChecked(new Set())}>Снять</Button>
              <Button onClick={() => setLessonItems(chosen)}><BookPlus size={14} />В урок</Button>
              <Button variant="secondary" disabled={availability.state !== "ready"} title={unavailableReason(availability)} onClick={() => setBuildItems(chosen)}><Sparkles size={14} />Собрать с ИИ</Button>
            </>
            : <>
              <span>Кусков: {primary.length}</span>
              <Button variant="ghost" onClick={() => setChecked(new Set(primary.map((item) => item.id)))}>Выбрать все</Button>
            </>}
        </div>}
        {evidence.groups && <EvidencePassageList
          groups={evidence.groups}
          selectedId={evidence.selectedId}
          onSelect={(item) => evidence.select(item.id)}
          secondary={mode === "together"}
          checkedIds={checked}
          onCheckedChange={toggle}
        />}
        {!hasAny && !evidence.loading && <EmptyState title="Исследованного текста пока нет"><p>Поиск остаётся доступен вручную; он не запускается при открытии темы.</p></EmptyState>}
      </aside>
      <section className="textbook-source-reader">
        {selected ? <>
          <header><div><small>{selected.material_name} · {pagesLabel(selected.page_from, selected.page_to)}</small><h2>{selected.title || selected.topic_title}</h2></div><div>{selected.preferred && <StatusBadge tone="info">открывается первым</StatusBadge>}{selected.legacy && <StatusBadge tone="neutral">из урока или оглавления</StatusBadge>}<EvidenceDecisionMenu evidence={selected} busy={busy} onAction={(action, role) => void decide(action, role)} /></div></header>
          <EvidenceStructuredReader projectId={projectId} evidence={selected} />
          <footer><Button onClick={() => setLessonItems([selected])} disabled={busy || selected.stale}><BookPlus size={14} />Добавить в урок</Button></footer>
        </> : !evidence.loading && <EmptyState title="Выберите кусок" />}
      </section>
    </div>}

    {mode === "search" && <section className="textbook-source-search">
      <form onSubmit={(event) => { event.preventDefault(); void search(); }}>
        <label><Search size={14} /><input ref={inputRef} type="search" value={query} onChange={(event) => setQuery(event.target.value)} aria-label="Найти ещё в материалах проекта" /></label>
        <Button type="submit" disabled={searching || !query.trim()}>Найти</Button>
      </form>
      {searching && <LoadingState label="Ищем в материалах" />}
      {searched && !searching && places.length === 0 && <EmptyState title="Совпадений нет" />}
      {places.length > 0 && <ul>{places.map((place) => <li key={place.key}><span><strong>{place.materialName} · стр. {place.pageNumber}</strong><small>{place.signals.length > 1 ? "по словам и смыслу" : place.signals[0] === "semantic" ? "по смыслу" : "по словам"}</small><p>{place.text}</p>{place.warning && <em>{place.warning}</em>}</span><Button variant="secondary" disabled={busy} onClick={() => void bind(place)}>Привязать</Button></li>)}</ul>}
    </section>}

    {/* Сборка идёт фоном, а её ход и итог показывает раздел «Уроки»: onStarted открывает ту же задачу. */}
    <LessonBuildDialog
      open={buildItems !== null}
      onOpenChange={(open) => { if (!open) setBuildItems(null); }}
      projectId={projectId}
      topic={{ id: topicId, title: topicTitle }}
      pinned={buildItems ?? []}
      onStarted={(jobId) => { setBuildItems(null); navigate(`/projects/${projectId}/lessons?topic=${topicId}&job=${jobId}`); }}
      onBuilt={(lessonId) => navigate(`/projects/${projectId}/lessons?topic=${topicId}&lesson=${lessonId}`)}
    />

    <LessonEvidenceDialog
      open={lessonItems !== null}
      projectId={projectId}
      items={lessonItems ?? []}
      topicTitle={topicTitle}
      onOpenChange={(open) => { if (!open) setLessonItems(null); }}
      onAdded={(lesson, added) => {
        setUndoSequence(null);
        setChecked(new Set());
        setNotice(added > 1 ? `Кусков добавлено в урок «${lesson.title}»: ${added}.` : `Кусок добавлен в урок «${lesson.title}».`);
      }}
    />
  </div>;
}
