import { useEffect, useMemo, useState } from "react";
import { ListOrdered, Sparkles, Undo2 } from "lucide-react";
import type { AiModelSelection } from "../../api/ai";
import { getBackgroundJobResult } from "../../api/backgroundJobs";
import {
  createBulkLessons,
  LESSON_BASIS_LABELS,
  LESSON_TEMPLATE_LABELS,
  previewLessonAiBulk,
  startLessonAiBulk,
  type LessonAiBulkPreflightRead,
  type LessonAiBulkResult,
  type LessonBasis,
  type LessonBulkAction,
  type LessonSummaryRead,
  type LessonTemplate,
} from "../../api/lessons";
import { undoProjectAction } from "../../api/projects";
import { Button, Checkbox, Progress, SegmentedTabs, Select, Tooltip } from "../../components/ui";
import { useBackgroundJob } from "../../hooks/useBackgroundJob";
import type { ProgramTreeNode } from "../programTree";
import { ChatModelControl } from "../workspace/chat/ChatModelControl";
import { countsByNode, errorText } from "./lessonTree";

type BulkAction = LessonBulkAction | "skip" | "ai";

const ACTION_OPTIONS = [
  { value: "quick", label: "быстрый урок" },
  { value: "manual", label: "вручную" },
  { value: "ai", label: "с ИИ" },
  { value: "skip", label: "пропустить" },
];
const TEMPLATES: LessonTemplate[] = ["explain", "guide", "practice", "cheatsheet"];
const BASIS_ORDER: LessonBasis[] = ["sources_and_model", "sources", "model_only"];
const MODEL_KEY = (projectId: string) => `tentex:lesson-ai-model:${projectId}`;

function readModel(projectId: string): AiModelSelection | null {
  try {
    const raw = window.localStorage.getItem(MODEL_KEY(projectId));
    return raw ? (JSON.parse(raw) as AiModelSelection) : null;
  } catch {
    return null;
  }
}

interface LessonBulkTableProps {
  projectId: string;
  topics: ProgramTreeNode[];
  lessons: LessonSummaryRead[];
  onClear(): void;
  /** Состав уроков изменился: перечитать обзор. */
  onChanged(): void;
  onOpenLesson(nodeId: string, lessonId: string): void;
}

function rangeLabel(topic: ProgramTreeNode): string {
  const range = topic.source_page_ranges[0];
  if (!range) return "—";
  const extra = topic.source_page_ranges.length > 1 ? ` +${topic.source_page_ranges.length - 1}` : "";
  return `${range.source_name_snapshot} ${range.page_from}–${range.page_to}${extra}`;
}

function plural(count: number): string {
  const tail = count % 100 > 10 && count % 100 < 20 ? 0 : count % 10;
  if (tail === 1) return "черновик";
  return tail >= 2 && tail <= 4 ? "черновика" : "черновиков";
}

function usd(value: string | null): string {
  if (value === null) return "цена неизвестна";
  const number = Number(value);
  return number < 0.01 ? `≈$${number.toFixed(4)}` : `≈$${number.toFixed(2)}`;
}

/**
 * Массовая подготовка: умолчания и одна отмена на всё — записка «Уроки» §4.5.
 * «с ИИ» собирает черновики одной фоновой задачей в порядке программы: шаблон,
 * основа и модель общие, понятия уже собранных тем идут в «уже известно» следующих.
 */
export function LessonBulkTable({ projectId, topics, lessons, onClear, onChanged, onOpenLesson }: LessonBulkTableProps) {
  const counts = useMemo(() => countsByNode(lessons), [lessons]);
  const [overrides, setOverrides] = useState<Record<string, BulkAction>>({});
  const [allAction, setAllAction] = useState<BulkAction | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  // Одна транзакция — одна отмена, и она остаётся рядом с действием (записка §4.5).
  const [created, setCreated] = useState<{ lessons: LessonSummaryRead[]; sequence: number } | null>(null);
  const [template, setTemplate] = useState<LessonTemplate>("explain");
  const [basis, setBasis] = useState<LessonBasis>("sources_and_model");
  const [model, setModel] = useState<AiModelSelection | null>(() => readModel(projectId));
  const [confirmUnknown, setConfirmUnknown] = useState(false);
  const [preview, setPreview] = useState<LessonAiBulkPreflightRead | null>(null);
  const [aiJobId, setAiJobId] = useState<string | null>(null);
  const [aiResult, setAiResult] = useState<LessonAiBulkResult | null>(null);
  const { job } = useBackgroundJob(aiJobId);

  // «Тема с диапазоном и без урока — быстрый урок»: черновик тоже урок, второй молча не нужен.
  const defaultAction = (topic: ProgramTreeNode): BulkAction => {
    const item = counts.get(topic.id);
    if (item && item.ready + item.drafts > 0) return "skip";
    return topic.source_page_ranges.length > 0 ? "quick" : "manual";
  };
  const actionOf = (topic: ProgramTreeNode) => overrides[topic.id] ?? defaultAction(topic);
  function chooseAll(action: BulkAction) {
    setCreated(null);
    setAllAction(action);
    setOverrides(Object.fromEntries(topics.map((topic) => [
      topic.id,
      defaultAction(topic) === "skip" ? "skip"
        : action === "quick" && topic.source_page_ranges.length === 0 ? "manual" : action,
    ])));
  }
  const planned = topics
    .map((topic) => ({ topic, action: actionOf(topic) }))
    .filter((row): row is { topic: ProgramTreeNode; action: LessonBulkAction } =>
      row.action === "quick" || row.action === "manual");
  const aiTopics = topics.filter((topic) => actionOf(topic) === "ai");
  const aiKey = aiTopics.map((topic) => topic.id).join(",");
  const order = useMemo(() => ({ program_node_ids: aiKey ? aiKey.split(",") : [], template, basis, model }),
    [aiKey, template, basis, model]);

  useEffect(() => {
    if (!order.program_node_ids.length || aiJobId) {
      setPreview(null);
      return;
    }
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      previewLessonAiBulk(projectId, order, controller.signal)
        .then((value) => { if (!controller.signal.aborted) setPreview(value); })
        .catch((caught) => { if (!controller.signal.aborted) setError(errorText(caught, "Оценка не посчиталась")); });
    }, 400);
    return () => { window.clearTimeout(timer); controller.abort(); };
  }, [projectId, order, aiJobId]);

  useEffect(() => {
    if (!aiJobId || job?.state !== "completed") return;
    const controller = new AbortController();
    getBackgroundJobResult<LessonAiBulkResult>(aiJobId, controller.signal)
      .then((result) => { if (!controller.signal.aborted) { setAiResult(result); onChanged(); } })
      .catch(() => undefined);
    return () => controller.abort();
  }, [aiJobId, job?.state]); // eslint-disable-line react-hooks/exhaustive-deps

  function chooseModel(value: AiModelSelection | null) {
    setModel(value);
    try {
      if (value) window.localStorage.setItem(MODEL_KEY(projectId), JSON.stringify(value));
      else window.localStorage.removeItem(MODEL_KEY(projectId));
    } catch { /* выбор живёт до закрытия вкладки */ }
  }

  async function create() {
    setBusy(true);
    setError("");
    try {
      if (planned.length) {
        const result = await createBulkLessons(
          projectId,
          planned.map(({ topic, action }) => ({ program_node_id: topic.id, action })),
        );
        const sequence = result.latest_undoable_action?.sequence;
        setCreated(sequence ? { lessons: result.lessons, sequence } : null);
      }
      if (aiTopics.length) {
        const upper = preview?.cost_usd ? (Math.ceil(Number(preview.cost_usd) * 1000) / 1000).toFixed(3) : null;
        const started = await startLessonAiBulk(projectId, { ...order, max_cost_usd: upper, confirm_unknown_price: confirmUnknown });
        setAiResult(null);
        setAiJobId(started.job_id);
      }
      onChanged();
    } catch (caught) {
      setError(errorText(caught, "Не удалось создать черновики"));
    } finally {
      setBusy(false);
    }
  }

  async function undo() {
    if (!created) return;
    setBusy(true);
    setError("");
    try {
      await undoProjectAction(projectId, created.sequence);
      setCreated(null);
      onChanged();
    } catch (caught) {
      setError(errorText(caught, "Не удалось отменить создание"));
    } finally {
      setBusy(false);
    }
  }

  const aiRunning = Boolean(aiJobId && job && ["queued", "running", "paused"].includes(job.state));
  const aiFailed = Boolean(aiJobId && job && (job.state === "failed" || job.state === "cancelled"));
  const offline = preview !== null && !preview.models_available;
  const priceBlocked = Boolean(preview && preview.models_available && !preview.price_known && !confirmUnknown);
  const total = planned.length + aiTopics.length;
  const blocked = aiTopics.length > 0 && (!preview || offline || priceBlocked || aiRunning);
  const built = aiResult?.lessons.filter((item) => item.lesson_id) ?? [];
  const skipped = aiResult?.lessons.filter((item) => !item.lesson_id) ?? [];

  return (
    <div className="lessons-center-scroll">
      <header className="lessons-center-head">
        <span className="lessons-eyebrow">Массовая подготовка</span>
        <h1>Подготовка уроков · {topics.length} тем</h1>
        <p>Готовый урок молча не перезаписывается; тема без диапазона оглавления собирается вручную или с ИИ.</p>
      </header>
      <div className="lessons-bulk-scroll">
        <table className="lessons-bulk-table">
          <thead><tr><th>#</th><th>Тема</th><th>Материал</th><th>Уроки</th><th><span className="lessons-bulk-action-head">Действие<Select ariaLabel="Действие для всех тем" value={allAction} emptyOption="Для всех…" options={ACTION_OPTIONS} onValueChange={(value) => { if (value) chooseAll(value as BulkAction); }} /></span></th></tr></thead>
          <tbody>
            {topics.map((topic, index) => {
              const item = counts.get(topic.id);
              const found = preview?.topics.find((row) => row.program_node_id === topic.id);
              return (
                <tr key={topic.id}>
                  <td>{index + 1}</td>
                  <td>{topic.title}</td>
                  <td>
                    {rangeLabel(topic)}
                    {actionOf(topic) === "ai" && found && (
                      <small className={`lessons-bulk-found${found.sources_available ? "" : " is-empty"}`}>
                        {found.sources_available ? `кусков: ${found.candidates}` : "материала не нашлось"}
                      </small>
                    )}
                  </td>
                  <td>{item && item.ready + item.drafts > 0 ? `${item.ready > 0 ? `✓ ${item.ready}` : ""}${item.drafts > 0 ? ` ● ${item.drafts}` : ""}` : "—"}</td>
                  <td>
                    <Select
                      ariaLabel={`Действие для «${topic.title}»`}
                      value={actionOf(topic)}
                      options={ACTION_OPTIONS.map((option) => option.value === "quick" && topic.source_page_ranges.length === 0 ? { ...option, disabled: true } : option)}
                      onValueChange={(value) => {
                        if (!value) return;
                        setCreated(null);
                        setAllAction(null);
                        setOverrides((current) => ({ ...current, [topic.id]: value as BulkAction }));
                      }}
                    />
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {aiTopics.length > 0 && !aiJobId && (
        <section className="lessons-bulk-ai" aria-label="Сборка с ИИ">
          <div className="lessons-bulk-ai-head">
            <Sparkles size={15} aria-hidden="true" />
            <strong>С ИИ · {aiTopics.length} тем</strong>
            <span>Уровень «Черновик», по порядку программы: понятия собранных тем станут «уже известным» для следующих.</span>
          </div>
          <div className="lessons-bulk-ai-row">
            <Select
              ariaLabel="Шаблон урока"
              value={template}
              options={TEMPLATES.map((value) => ({ value, label: LESSON_TEMPLATE_LABELS[value] }))}
              onValueChange={(value) => { if (value) setTemplate(value as LessonTemplate); }}
            />
            <SegmentedTabs label="Основа уроков" value={basis} onChange={setBasis}
              tabs={BASIS_ORDER.map((value) => ({ value, label: LESSON_BASIS_LABELS[value] }))} />
            <ChatModelControl role="lesson_builder" capabilities={["structured_output"]} value={model} parameters={{}} messageCount={0} onChange={(value) => chooseModel(value)} />
            <span className="lessons-bulk-ai-cost">
              {offline ? preview?.models_unavailable_reason ?? "Внешние модели недоступны"
                : preview ? `${preview.calls} вызовов · ${usd(preview.cost_usd)} · верх оценки станет пределом` : "Считаем…"}
            </span>
          </div>
          {preview && preview.models_available && !preview.price_known && (
            <Checkbox checked={confirmUnknown} onCheckedChange={setConfirmUnknown} label="Цена модели неизвестна — запустить без оценки" />
          )}
        </section>
      )}

      {aiJobId && (
        <section className="lessons-bulk-ai" role="status" aria-label="Сборка с ИИ">
          {aiRunning && job && (
            <>
              <div className="lessons-bulk-ai-head">
                <Sparkles size={15} aria-hidden="true" />
                <strong>Собираем с ИИ · {job.done} из {job.total}</strong>
                <span>Идёт в «Фоне» — экран можно закрыть.</span>
              </div>
              <Progress value={job.done} max={Math.max(job.total, 1)} label="Черновики с ИИ" />
            </>
          )}
          {aiFailed && job && (
            <p className="inline-error" role="alert">
              {job.state === "cancelled" ? "Сборка отменена" : `Сборка остановилась: ${job.error ?? "ошибка"}`}. Готовые темы сохранены; продолжить можно в «Фоне».
            </p>
          )}
          {aiResult && (
            <div className="lessons-bulk-result">
              <span>Собрано с ИИ: {built.length}{skipped.length ? ` · пропущено ${skipped.length}` : ""}{aiResult.cost_usd ? ` · $${Number(aiResult.cost_usd).toFixed(4)}` : ""}</span>
              {built[0]?.lesson_id && (
                <Button variant="ghost" onClick={() => onOpenLesson(built[0].program_node_id, built[0].lesson_id!)}>Открыть первый</Button>
              )}
              <Button variant="ghost" onClick={() => { setAiJobId(null); setAiResult(null); setOverrides({}); setAllAction(null); }}>Готово</Button>
            </div>
          )}
          {skipped.length > 0 && (
            <ul className="lessons-bulk-skipped">
              {skipped.map((item) => <li key={item.program_node_id}>{item.topic_title}: {item.skipped}</li>)}
            </ul>
          )}
        </section>
      )}

      {created && (
        <div className="lessons-bulk-result" role="status">
          <span>Создано черновиков: {created.lessons.length}</span>
          <Button variant="ghost" disabled={busy} onClick={() => {
            const first = created.lessons[0];
            if (first) onOpenLesson(first.program_node_ids[0], first.id);
          }}>Открыть первый</Button>
          <Button variant="ghost" disabled={busy} onClick={() => void undo()}><Undo2 size={14} />Отменить</Button>
        </div>
      )}
      <footer className="lessons-bulk-footer">
        {error && <p className="inline-error" role="alert">{error}</p>}
        <Button variant="ghost" onClick={onClear} disabled={busy}>Очистить выбор</Button>
        <Tooltip label="Вернуть каждой теме действие по умолчанию: готовый урок — пропустить, диапазон есть — быстрый урок" side="top">
          <Button variant="secondary" onClick={() => { setCreated(null); setOverrides({}); setAllAction(null); }} disabled={busy}>
            <ListOrdered size={15} />Создать по порядку
          </Button>
        </Tooltip>
        <Button onClick={() => void create()} disabled={busy || total === 0 || created !== null || blocked}>
          {busy ? "Создаём…" : aiTopics.length
            ? `Создать ${total} ${plural(total)} · с ИИ: ${aiTopics.length}`
            : `Создать ${total} ${plural(total)}`}
        </Button>
      </footer>
    </div>
  );
}
