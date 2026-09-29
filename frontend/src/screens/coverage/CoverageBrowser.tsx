import { useEffect, useState } from "react";
import { Link, useLocation, useNavigate, useSearchParams } from "react-router";
import { AlertTriangle, BookOpen, Link2, RotateCcw } from "lucide-react";
import {
  decideCoverage,
  getCoverageBlocks,
  getCoverageTopics,
  type CoverageBlock,
  type CoverageBlockPage,
  type CoverageDecisionAction,
  type CoverageTopicPage,
} from "../../api/coverage";
import { undoProjectAction, type ProgramNodeRead } from "../../api/projects";
import {
  EvidenceInspector,
  EvidencePassageList,
  LessonEvidenceDialog,
} from "../../components/domain";
import {
  Button,
  Checkbox,
  EmptyState,
  ErrorState,
  LoadingState,
  SegmentedTabs,
  StatusBadge,
  Tooltip,
} from "../../components/ui";
import { useTopicEvidence } from "../../hooks/useTopicEvidence";

type BrowserView = "reading" | "gaps" | "outside" | "action";
const PAGE_SIZE = 24;
const TABS: Array<{ value: BrowserView; label: string }> = [
  { value: "reading", label: "К чтению" },
  { value: "gaps", label: "Пробелы" },
  { value: "outside", label: "Неразобранное" },
  { value: "action", label: "Требует решения" },
];

interface CoverageBrowserProps {
  projectId: string;
  nodes: ProgramNodeRead[];
  onChanged(): void | Promise<void>;
}

function isView(value: string | null): value is BrowserView {
  return TABS.some((tab) => tab.value === value);
}

/** Рабочая часть Обзора: один список и постоянный инспектор для четырёх честных видов. */
export function CoverageBrowser({ projectId, nodes, onChanged }: CoverageBrowserProps) {
  const [params, setParams] = useSearchParams();
  const location = useLocation();
  const navigate = useNavigate();
  const rawView = params.get("view");
  const view: BrowserView = isView(rawView) ? rawView : "reading";
  const selectedTopic = params.get("topic");
  const selectedEvidence = params.get("evidence");
  const selectedBlock = params.get("block");
  const offset = Number(params.get("offset") ?? 0) || 0;
  const [topics, setTopics] = useState<CoverageTopicPage | null>(null);
  const [blocks, setBlocks] = useState<CoverageBlockPage | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [feedback, setFeedback] = useState<{ notice: string; undoSequence: number | null }>({
    notice: "",
    undoSequence: null,
  });
  const [lessonOpen, setLessonOpen] = useState(false);
  const [targetTopics, setTargetTopics] = useState<string[]>([]);
  const evidence = useTopicEvidence(projectId, selectedTopic, selectedEvidence);

  const setQuery = (values: Record<string, string | null>) => {
    const next = new URLSearchParams(params);
    for (const [key, value] of Object.entries(values)) {
      if (value === null) next.delete(key); else next.set(key, value);
    }
    setParams(next, { replace: true });
  };

  const load = async (signal?: AbortSignal, resetSelection = false) => {
    setLoading(true);
    setError("");
    try {
      if (view === "reading" || view === "gaps") {
        const page = await getCoverageTopics(
          projectId,
          view === "reading" ? "readable" : "gaps",
          offset,
          PAGE_SIZE,
          signal,
        );
        if (signal?.aborted) return;
        setTopics(page);
        setBlocks(null);
        if (page.items[0] && (resetSelection || !selectedTopic)) {
          setQuery({ topic: page.items[0].node_id, evidence: null, source: null });
        } else if (resetSelection) {
          setQuery({ topic: null, evidence: null, source: null });
        }
      } else {
        const page = await getCoverageBlocks(
          projectId,
          view === "outside" ? "outside_program" : "needs_action",
          offset,
          PAGE_SIZE,
          signal,
        );
        if (signal?.aborted) return;
        setBlocks(page);
        setTopics(null);
        if (page.items[0] && (resetSelection || !selectedBlock)) {
          setQuery({ block: page.items[0].block_id });
        } else if (resetSelection) {
          setQuery({ block: null });
        }
      }
    } catch (caught) {
      if (!signal?.aborted) setError(caught instanceof Error ? caught.message : "Список покрытия не загрузился");
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  };

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [projectId, view, offset]);

  useEffect(() => {
    if (evidence.selectedId && evidence.selectedId !== selectedEvidence) {
      setQuery({ evidence: evidence.selectedId, source: evidence.evidence?.material_id ?? null });
    }
  }, [evidence.selectedId, evidence.evidence?.material_id]);

  const activeBlock = blocks?.items.find((item) => item.block_id === selectedBlock) ?? null;
  const revision = topics?.coverage_revision ?? blocks?.coverage_revision ?? evidence.groups?.coverage_revision;
  const studyNodes = nodes.filter((node) => node.node_type !== "section"
    && node.is_in_current_program && !node.is_archived);
  const returnTo = `${location.pathname}${location.search}`;

  async function decide(
    action: CoverageDecisionAction,
    values: { bindingIds?: string[]; blockId?: string; topicIds?: string[]; role?: "definition" | "explanation" | "example" } = {},
  ) {
    if (revision === undefined) return;
    setBusy(true);
    setFeedback({ notice: "", undoSequence: null });
    try {
      const result = await decideCoverage(projectId, {
        request_key: crypto.randomUUID(),
        expected_coverage_revision: revision,
        action,
        binding_ids: values.bindingIds,
        block_id: values.blockId,
        topic_ids: values.topicIds,
        role: values.role,
      });
      setFeedback({ notice: result.message, undoSequence: result.action_sequence });
      const resolvesBlock = action === "reassign" || action === "service" || action === "outside_goal";
      await Promise.all([load(undefined, resolvesBlock), evidence.refresh(), onChanged()]);
    } catch (caught) {
      setFeedback({
        notice: caught instanceof Error ? caught.message : "Решение не сохранено",
        undoSequence: null,
      });
    } finally {
      setBusy(false);
    }
  }

  async function undo() {
    if (feedback.undoSequence === null) return;
    setBusy(true);
    try {
      await undoProjectAction(projectId, feedback.undoSequence);
      setFeedback({ notice: "Последнее решение отменено.", undoSequence: null });
      await Promise.all([
        load(undefined, view === "outside" || view === "action"),
        evidence.refresh(),
        onChanged(),
      ]);
    } catch (caught) {
      setFeedback({
        notice: caught instanceof Error ? caught.message : "Решение уже нельзя отменить",
        undoSequence: null,
      });
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="coverage-browser" aria-labelledby="coverage-browser-title">
      <header className="coverage-browser-head">
        <div><h2 id="coverage-browser-title">Работа с результатом</h2><p>Читайте точный текст, используйте его в Уроках и исправляйте только выбранную связь.</p></div>
        <SegmentedTabs label="Вид покрытия" value={view} tabs={TABS} onChange={(next) => setQuery({ view: next, topic: null, evidence: null, source: null, block: null, offset: null })} />
      </header>
      {feedback.notice && <div className="coverage-browser-notice" role="status"><span>{feedback.notice}</span>{feedback.undoSequence !== null && <Button variant="ghost" disabled={busy} onClick={() => void undo()}><RotateCcw size={14} />Отменить</Button>}</div>}
      {error && <ErrorState message={error}><Button onClick={() => void load()}>Повторить</Button></ErrorState>}
      {loading && !topics && !blocks && <LoadingState label="Загружаем результат" />}
      {!error && <div className="coverage-browser-grid">
        <div className="coverage-browser-list">
          {topics?.items.map((topic) => (
            <button
              type="button"
              key={topic.node_id}
              className={selectedTopic === topic.node_id ? "is-selected" : ""}
              onClick={() => setQuery({ topic: topic.node_id, evidence: null, source: null })}
            >
              <span><strong>{topic.title}</strong>{topic.parent_title && <small>{topic.parent_title}</small>}</span>
              <StatusBadge tone={view === "gaps" ? "warning" : "info"}>
                {view === "gaps" ? "нет содержания" : `Фрагментов: ${topic.evidence_count}`}
              </StatusBadge>
            </button>
          ))}
          {blocks?.items.map((block) => (
            <button
              type="button"
              key={block.block_id}
              className={selectedBlock === block.block_id ? "is-selected" : ""}
              onClick={() => { setTargetTopics([]); setQuery({ block: block.block_id }); }}
            >
              <span><strong>{block.title || `Блок на стр. ${block.page_from}`}</strong><small>{block.material_name} · стр. {block.page_from}{block.page_to !== block.page_from ? `–${block.page_to}` : ""}</small></span>
              {view === "action" && <AlertTriangle size={15} />}
            </button>
          ))}
          {((topics && topics.total === 0) || (blocks && blocks.total === 0)) && <EmptyState title={view === "gaps" ? "Пробелов нет" : view === "outside" ? "Неразобранного нет" : view === "action" ? "Решений не требуется" : "Опор для чтения пока нет"} />}
          {((topics?.total ?? blocks?.total ?? 0) > PAGE_SIZE) && <div className="coverage-browser-pagination">
            <Button variant="ghost" disabled={offset === 0} onClick={() => setQuery({ offset: String(Math.max(0, offset - PAGE_SIZE)), topic: null, evidence: null, source: null, block: null })}>Назад</Button>
            <span>{offset + 1}–{Math.min(offset + PAGE_SIZE, topics?.total ?? blocks?.total ?? 0)} из {topics?.total ?? blocks?.total}</span>
            <Button variant="ghost" disabled={offset + PAGE_SIZE >= (topics?.total ?? blocks?.total ?? 0)} onClick={() => setQuery({ offset: String(offset + PAGE_SIZE), topic: null, evidence: null, source: null, block: null })}>Дальше</Button>
          </div>}
        </div>

        <div className="coverage-browser-detail">
          {view === "reading" && selectedTopic && <>
            {evidence.updateAvailable && <div className="coverage-refresh-offer"><span>Покрытие обновилось. Открытый текст оставлен на месте.</span><Button variant="secondary" onClick={() => void evidence.refresh()}>Показать обновление</Button></div>}
            <div className="coverage-evidence-layout">
              <div className="coverage-evidence-groups">
                {evidence.groups && <EvidencePassageList
                  groups={evidence.groups}
                  selectedId={evidence.selectedId}
                  secondary
                  onSelect={(item) => { evidence.select(item.id); setQuery({ evidence: item.id, source: item.material_id }); }}
                />}
              </div>
              <EvidenceInspector
                evidence={evidence.evidence}
                projectId={projectId}
                loading={evidence.loading}
                error={evidence.error}
                busy={busy}
                onDecision={(action, role) => evidence.evidence && void decide(action, { bindingIds: evidence.evidence.binding_ids, role })}
                onAddToLesson={() => setLessonOpen(true)}
                onOpenSource={() => evidence.evidence && navigate(`/projects/${projectId}/materials/${evidence.evidence.material_id}?page=${evidence.evidence.page_from}`)}
              />
            </div>
            <Link className="coverage-read-in-workspace" to={`/projects/${projectId}?topic=${selectedTopic}&tab=source&evidence=${encodeURIComponent(evidence.selectedId ?? "")}&returnTo=${encodeURIComponent(returnTo)}`}><BookOpen size={14} />Читать в Рабочей области</Link>
          </>}
          {view === "gaps" && selectedTopic && <EmptyState title="Для темы нет актуального содержания" icon={<BookOpen size={23} />}><p>Упоминания и прежние связи не считаются материалом для чтения. Подключите источник или дождитесь следующего исследования.</p></EmptyState>}
          {view === "outside" && activeBlock && <BlockDecision
            block={activeBlock}
            topics={studyNodes}
            selected={targetTopics}
            busy={busy}
            onToggle={(topicId) => setTargetTopics((current) => current.includes(topicId) ? current.filter((id) => id !== topicId) : [...current, topicId])}
            onReassign={() => void decide("reassign", { blockId: activeBlock.block_id, topicIds: targetTopics })}
            onService={() => void decide("service", { blockId: activeBlock.block_id })}
            onOutside={() => void decide("outside_goal", { blockId: activeBlock.block_id })}
            projectId={projectId}
          />}
          {view === "action" && activeBlock && <ActionBlock block={activeBlock} projectId={projectId} />}
        </div>
      </div>}
      <LessonEvidenceDialog
        open={lessonOpen}
        projectId={projectId}
        items={evidence.evidence ? [evidence.evidence] : []}
        topicTitle={evidence.evidence?.topic_title ?? ""}
        onOpenChange={setLessonOpen}
        onAdded={(lesson) => setFeedback({ notice: `Кусок добавлен в урок «${lesson.title}».`, undoSequence: null })}
      />
    </section>
  );
}

interface BlockDecisionProps {
  block: CoverageBlock;
  topics: ProgramNodeRead[];
  selected: string[];
  busy: boolean;
  projectId: string;
  onToggle(topicId: string): void;
  onReassign(): void;
  onService(): void;
  onOutside(): void;
}

function BlockDecision({ block, topics, selected, busy, projectId, onToggle, onReassign, onService, onOutside }: BlockDecisionProps) {
  return <article className="coverage-block-decision">
    <header><small>{block.material_name} · стр. {block.page_from}{block.page_to !== block.page_from ? `–${block.page_to}` : ""}</small><h3>{block.title || "Блок вне программы"}</h3></header>
    <p>Это результат разбора, а не ошибка. Выберите существующие темы либо явно оставьте блок вне учебной цели.</p>
    <fieldset><legend>Привязать к темам</legend>{topics.map((topic) => <Checkbox key={topic.id} checked={selected.includes(topic.id)} onCheckedChange={() => onToggle(topic.id)} label={topic.title} />)}</fieldset>
    <div className="coverage-block-actions"><Button disabled={busy || selected.length === 0} onClick={onReassign}><Link2 size={14} />Привязать выбранное</Button><Button variant="secondary" disabled={busy} onClick={onService}>Служебный блок</Button><Button variant="secondary" disabled={busy} onClick={onOutside}>Вне моей цели</Button><Tooltip label="Создание тем появится в И7"><span><Button variant="ghost" disabled>Создать новую тему</Button></span></Tooltip></div>
    <Link to={`/projects/${projectId}/materials/${block.material_id}?page=${block.page_from}`}>Открыть первичный текст</Link>
  </article>;
}

function ActionBlock({ block, projectId }: { block: CoverageBlock; projectId: string }) {
  const rawReason = block.reason?.replace(/^invalid_decision:/, "") ?? block.bucket;
  const reason = ({
    evidence_not_found: "не найден подтверждающий фрагмент",
    invalid_target: "не найдена подходящая тема",
    unresolved: "результат не удалось уверенно отнести к теме",
    error: "разбор блока завершился ошибкой",
    stale: "источник изменился после разбора",
  } as Record<string, string>)[rawReason] ?? "результат требует ручной проверки";
  return <article className="coverage-block-decision is-action"><header><StatusBadge tone={block.bucket === "error" ? "danger" : "warning"}>{block.bucket === "stale" ? "устарело" : block.bucket === "error" ? "ошибка" : "не решено"}</StatusBadge><h3>{block.title || `Блок на стр. ${block.page_from}`}</h3></header><p>Причина: {reason}. Откройте исходный текст; повторный анализ и визуальный разбор относятся к следующему слою исследования.</p><Link to={`/projects/${projectId}/materials/${block.material_id}?page=${block.page_from}`}>К первичному тексту</Link></article>;
}
