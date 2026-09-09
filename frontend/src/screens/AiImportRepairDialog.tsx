import { AlertTriangle, Plus, RotateCcw, Square, Trash2, WandSparkles, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router";
import { describeAiFailure, type AiPreflight, type DecimalValue } from "../api/ai";
import {
  applyProgramImportRepair,
  preflightProgramImportRepair,
  ProjectApiError,
  runProgramImportRepair,
  type DroppedItem,
  type ProgramChangeResult,
  type ProgramImportRepairPreflightRead,
  type ProgramImportRepairRunRead,
  type ProgramNodeRead,
  type RepairedItem,
  type RepairedQuestion,
} from "../api/projects";
import {
  ACTIVE_JOB_STATES,
  cancelBackgroundJob,
  findResumableBackgroundJob,
  getBackgroundJobResult,
  resolveBackgroundJob,
} from "../api/backgroundJobs";
import { AiFailureNotice } from "../components/domain";
import { useBackgroundJob } from "../hooks/useBackgroundJob";
import { Button, Checkbox, ConfirmDialog, Dialog, Disclosure, IconButton, LoadingState, SegmentedTabs, StatusBadge } from "../components/ui";

interface AiImportRepairDialogProps {
  open: boolean;
  projectId: string;
  /** Порядок и состав должны совпадать с тем, что покажет предпросмотр
      сервера — используйте тот же список узлов, что и для группировки. */
  nodes: ProgramNodeRead[];
  onOpenChange: (open: boolean) => void;
  onApplied: (result: ProgramChangeResult) => void;
}

function number(value: DecimalValue | null): number | null {
  const parsed = value === null ? NaN : Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function price(usd: DecimalValue | null, rub: DecimalValue | null): string {
  const usdValue = number(usd);
  const rubValue = number(rub);
  const dollars = usdValue === null ? "цена неизвестна" : `$${usdValue.toFixed(6).replace(/0+$/, "").replace(/\.$/, ".00")}`;
  return rubValue === null ? dollars : `${dollars}, ≈ ${rubValue.toLocaleString("ru-RU", { maximumFractionDigits: 2 })} ₽`;
}

function dateLabel(value: string | null): string {
  return value ? new Intl.DateTimeFormat("ru-RU", { dateStyle: "medium" }).format(new Date(value)) : "дата курса не задана";
}

function PreflightLine({ value }: { value: AiPreflight }) {
  return (
    <section className="ai-preflight-summary" aria-label="Оценка исправления">
      <div><span>Модель</span><strong>{value.model_id}</strong></div>
      <div><span>Токены</span><strong>≈ {value.estimated_input_tokens.toLocaleString("ru-RU")} + {value.estimated_output_tokens.toLocaleString("ru-RU")}</strong></div>
      <div><span>Оценка</span><strong>{price(value.estimated_cost_usd, value.estimated_cost_rub)}</strong></div>
      <div><span>Курс</span><strong>{dateLabel(value.usd_rub_rate_date)}</strong></div>
      {value.cached && <StatusBadge tone="info">есть в кэше</StatusBadge>}
    </section>
  );
}

function validateItems(items: RepairedItem[], hasTickets: boolean): string {
  if (items.length === 0) return "Список не может быть пустым — верните хотя бы один пункт.";
  for (const item of items) {
    if (item.kind === "ticket") {
      if (!hasTickets) return "В этом формате не может быть билетов.";
      if (!item.title.trim()) return "У билета должно быть название.";
      if (item.items.length === 0) return "В билете должен остаться хотя бы один пункт.";
      if (item.items.some((child) => !child.title.trim())) return "Формулировка вопроса или задачи не может быть пустой.";
    } else {
      if (!item.title.trim()) return "Формулировка вопроса или задачи не может быть пустой.";
    }
  }
  return "";
}

function sanitizeQuestion(item: RepairedQuestion): RepairedQuestion {
  return {
    ...item,
    title: item.title.trim(),
    subpoints: item.subpoints.map((subpoint) => subpoint.trim()).filter(Boolean),
  };
}

function sanitizeItems(items: RepairedItem[]): RepairedItem[] {
  return items.map((item) => item.kind === "ticket"
    ? { ...item, title: item.title.trim(), items: item.items.map(sanitizeQuestion) }
    : sanitizeQuestion(item));
}

interface QuestionEditorProps {
  item: RepairedQuestion;
  label: string;
  onTitleChange: (value: string) => void;
  onKindChange: (value: "question" | "task") => void;
  onSubpointChange: (index: number, value: string) => void;
  onSubpointAdd: () => void;
  onSubpointRemove: (index: number) => void;
  onRemove: () => void;
}

function QuestionEditor({ item, label, onTitleChange, onKindChange, onSubpointChange, onSubpointAdd, onSubpointRemove, onRemove }: QuestionEditorProps) {
  return (
    <li className="ai-repair-question">
      <header>
        <span className="ai-repair-item-number">{label}</span>
        <SegmentedTabs
          label="Тип пункта"
          value={item.kind}
          onChange={onKindChange}
          tabs={[{ value: "question", label: "Вопрос" }, { value: "task", label: "Задача" }]}
        />
        <IconButton label="Убрать пункт" onClick={onRemove}><Trash2 size={14} /></IconButton>
      </header>
      <textarea value={item.title} onChange={(event) => onTitleChange(event.target.value)} />
      {item.subpoints.length > 0 && (
        <ol className="ai-repair-subpoint-list">
          {item.subpoints.map((subpoint, subIndex) => (
            <li key={subIndex}>
              <input value={subpoint} onChange={(event) => onSubpointChange(subIndex, event.target.value)} />
              <IconButton label="Убрать подпункт" onClick={() => onSubpointRemove(subIndex)}><X size={13} /></IconButton>
            </li>
          ))}
        </ol>
      )}
      <Button variant="ghost" onClick={onSubpointAdd}><Plus size={13} />Добавить подпункт</Button>
    </li>
  );
}

export function AiImportRepairDialog({ open, projectId, nodes, onOpenChange, onApplied }: AiImportRepairDialogProps) {
  const [instruction, setInstruction] = useState("");
  const [preflight, setPreflight] = useState<ProgramImportRepairPreflightRead | null>(null);
  const [runResult, setRunResult] = useState<ProgramImportRepairRunRead | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [items, setItems] = useState<RepairedItem[]>([]);
  const [dropped, setDropped] = useState<DroppedItem[]>([]);
  const [originalItems, setOriginalItems] = useState<RepairedItem[]>([]);
  const [originalDropped, setOriginalDropped] = useState<DroppedItem[]>([]);
  const [busy, setBusy] = useState<"preflight" | "run" | "apply" | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [confirmed, setConfirmed] = useState(false);
  const [conflict, setConflict] = useState(false);
  const { job, error: jobError } = useBackgroundJob(jobId);
  const jobActive = Boolean(job && ACTIVE_JOB_STATES.has(job.state));
  const [discardOpen, setDiscardOpen] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const hasTickets = runResult?.has_tickets ?? preflight?.has_tickets ?? false;
  const dirty = Boolean(runResult && (
    JSON.stringify(items) !== JSON.stringify(originalItems)
    || JSON.stringify(dropped) !== JSON.stringify(originalDropped)
  ));
  const validationMessage = runResult ? validateItems(items, hasTickets) : "";

  useEffect(() => {
    if (!open) return;
    const controller = new AbortController();
    abortRef.current?.abort();
    abortRef.current = controller;
    setBusy("preflight");
    setInstruction("");
    setPreflight(null);
    setRunResult(null);
    setItems([]);
    setDropped([]);
    setOriginalItems([]);
    setOriginalDropped([]);
    setError(null);
    setConfirmed(false);
    setConflict(false);
    void preflightProgramImportRepair(projectId, controller.signal)
      .then((value) => {
        if (controller.signal.aborted) return;
        setPreflight(value);
        setConfirmed(!value.preflight.confirmation_required);
      })
      .catch((caught) => {
        if (!controller.signal.aborted) setError(caught);
      })
      .finally(() => {
        if (!controller.signal.aborted) setBusy(null);
      });
    return () => controller.abort();
  }, [open, projectId]);

  // Пользователь мог запустить исправление и уйти с экрана: при открытии
  // спрашиваем реестр, не идёт ли задача до сих пор, и подписываемся на неё
  // вместо пустого старта.
  useEffect(() => {
    if (!open) {
      setJobId(null);
      return;
    }
    const controller = new AbortController();
    void findResumableBackgroundJob("ai_import_repair", { projectId }, controller.signal)
      .then((active) => {
        if (!controller.signal.aborted && active) setJobId(active.id);
      })
      .catch(() => undefined);
    return () => controller.abort();
  }, [open, projectId]);

  // Задача досчиталась — забрать готовое предложение из реестра, а не звать
  // модель заново: повторный вызов стоил бы денег за уже сделанную работу.
  useEffect(() => {
    if (!job || job.state !== "completed" || runResult) return;
    const controller = new AbortController();
    void getBackgroundJobResult<ProgramImportRepairRunRead>(job.id, controller.signal)
      .then((result) => {
        if (!controller.signal.aborted) adoptResult(result);
      })
      .catch((caught) => {
        if (!controller.signal.aborted) setError(caught);
      });
    return () => controller.abort();
  }, [job?.id, job?.state, runResult]);

  // Закрытие диалога задачу НЕ отменяет: она живёт в очереди, и вернувшийся
  // экран подхватит её результат. Обрывается только короткий запрос preflight.
  function requestClose() {
    if (dirty) {
      setDiscardOpen(true);
      return;
    }
    abortRef.current?.abort();
    onOpenChange(false);
  }

  async function runRepair() {
    if (!preflight || (preflight.preflight.confirmation_required && !confirmed)) return;
    const controller = new AbortController();
    abortRef.current?.abort();
    abortRef.current = controller;
    setBusy("run");
    setError(null);
    setConflict(false);
    try {
      const started = await runProgramImportRepair(projectId, {
        instruction,
        expected_program_revision: preflight.program_revision,
        expected_source_hash: preflight.source_hash,
        confirmed,
      }, controller.signal);
      setJobId(started.job_id);
    } catch (caught) {
      if (!controller.signal.aborted) setError(caught);
    } finally {
      if (!controller.signal.aborted) setBusy(null);
    }
  }

  /** Разложить пришедший результат в редактируемое предложение. */
  function adoptResult(result: ProgramImportRepairRunRead) {
    setRunResult(result);
    setItems(result.items);
    setDropped(result.dropped);
    setOriginalItems(result.items);
    setOriginalDropped(result.dropped);
  }

  async function applyRepair() {
    if (!runResult || validationMessage) return;
    const controller = new AbortController();
    abortRef.current = controller;
    setBusy("apply");
    setError(null);
    setConflict(false);
    try {
      const result = await applyProgramImportRepair(projectId, {
        run_id: runResult.run_id,
        expected_program_revision: runResult.program_revision,
        expected_source_hash: runResult.source_hash,
        items: sanitizeItems(items),
      }, controller.signal);
      // Задача доведена до конца: список принят, из «ждут проверки» уходит.
      if (jobId) void resolveBackgroundJob(jobId).catch(() => undefined);
      onApplied(result);
      onOpenChange(false);
    } catch (caught) {
      if (caught instanceof ProjectApiError && caught.code === "stale_program_revision") setConflict(true);
      else if (!controller.signal.aborted) setError(caught);
    } finally {
      if (!controller.signal.aborted) setBusy(null);
    }
  }

  function stop() {
    if (!jobId) return;
    void cancelBackgroundJob(jobId).catch((caught) => setError(caught));
  }

  function updateQuestion(ticketIndex: number | null, itemIndex: number, updater: (item: RepairedQuestion) => RepairedQuestion) {
    setItems((current) => current.map((item, index) => {
      if (ticketIndex === null) {
        return index === itemIndex && item.kind !== "ticket" ? updater(item) : item;
      }
      if (index !== ticketIndex || item.kind !== "ticket") return item;
      return { ...item, items: item.items.map((child, childIndex) => childIndex === itemIndex ? updater(child) : child) };
    }));
  }

  function updateTicketTitle(ticketIndex: number, title: string) {
    setItems((current) => current.map((item, index) => index === ticketIndex && item.kind === "ticket" ? { ...item, title } : item));
  }

  function removeQuestion(ticketIndex: number | null, itemIndex: number) {
    if (ticketIndex === null) {
      const item = items[itemIndex];
      if (!item || item.kind === "ticket") return;
      setItems(items.filter((_, index) => index !== itemIndex));
      setDropped([...dropped, { source_indices: item.source_indices, reason: "Убрано вручную" }]);
      return;
    }
    const ticket = items[ticketIndex];
    if (!ticket || ticket.kind !== "ticket") return;
    const item = ticket.items[itemIndex];
    if (!item) return;
    setItems(items.map((current, index) => index === ticketIndex
      ? { ...ticket, items: ticket.items.filter((_, childIndex) => childIndex !== itemIndex) }
      : current));
    setDropped([...dropped, { source_indices: item.source_indices, reason: "Убрано вручную" }]);
  }

  function removeTicket(ticketIndex: number) {
    const ticket = items[ticketIndex];
    if (!ticket || ticket.kind !== "ticket") return;
    setItems(items.filter((_, index) => index !== ticketIndex));
    setDropped([
      ...dropped,
      { source_indices: ticket.source_indices, reason: "Убран билет целиком" },
      ...ticket.items.map((child): DroppedItem => ({ source_indices: child.source_indices, reason: "Убран вместе с билетом" })),
    ]);
  }

  function restoreDropped(dropIndex: number) {
    const entry = dropped[dropIndex];
    if (!entry) return;
    const context = preflight?.source_context ?? [];
    const positions = context.filter((node) => node.node_type === "topic" || node.exam_kind === "ticket");
    const sourceIndex = entry.source_indices[0];
    const source = positions[sourceIndex - 1];
    if (!source) return;
    const question = (index: number): RepairedQuestion => {
      const node = positions[index - 1];
      return { kind: node.exam_kind === "task" ? "task" : "question", title: node.title,
        subpoints: node.subpoints, source_indices: [index] };
    };
    if (source.exam_kind === "ticket") {
      const childIndices = positions.flatMap((node, index) => node.parent_id === source.id ? [index + 1] : []);
      const restoredIndices = new Set([sourceIndex, ...childIndices]);
      setItems([...items, { kind: "ticket", title: source.title, source_indices: [sourceIndex], items: childIndices.map(question) }]);
      setDropped(dropped.filter((item) => !item.source_indices.some((index) => restoredIndices.has(index))));
      return;
    }
    const parent = context.find((node) => node.id === source.parent_id);
    const ticketIndex = items.findIndex((item) => item.kind === "ticket" && item.source_indices.some((index) => positions[index - 1]?.id === source.parent_id));
    if (parent?.exam_kind === "ticket" && ticketIndex === -1) {
      setError(new Error("Сначала верните билет целиком — вопрос принадлежит ему."));
      return;
    }
    const restored = question(sourceIndex);
    setDropped(dropped.filter((_, index) => index !== dropIndex));
    setItems(ticketIndex === -1 ? [...items, restored] : items.map((item, index) =>
      index === ticketIndex && item.kind === "ticket" ? { ...item, items: [...item.items, restored] } : item));
  }

  function questionEditorProps(ticketIndex: number | null, itemIndex: number, item: RepairedQuestion, label: string): QuestionEditorProps {
    return {
      item,
      label,
      onTitleChange: (value) => updateQuestion(ticketIndex, itemIndex, (question) => ({ ...question, title: value })),
      onKindChange: (value) => updateQuestion(ticketIndex, itemIndex, (question) => ({ ...question, kind: value })),
      onSubpointChange: (subIndex, value) => updateQuestion(ticketIndex, itemIndex, (question) => ({
        ...question,
        subpoints: question.subpoints.map((subpoint, index) => index === subIndex ? value : subpoint),
      })),
      onSubpointAdd: () => updateQuestion(ticketIndex, itemIndex, (question) => ({ ...question, subpoints: [...question.subpoints, ""] })),
      onSubpointRemove: (subIndex) => updateQuestion(ticketIndex, itemIndex, (question) => ({
        ...question,
        subpoints: question.subpoints.filter((_, index) => index !== subIndex),
      })),
      onRemove: () => removeQuestion(ticketIndex, itemIndex),
    };
  }

  const failure = describeAiFailure(error);

  return (
    <>
      <Dialog
        open={open}
        onOpenChange={(next) => next ? onOpenChange(true) : requestClose()}
        className="ai-consumer-dialog ai-import-repair-dialog"
        title="Исправить список вопросов"
        description="Правит формулировки, расставляет подпункты и убирает лишние заголовки; число пунктов может измениться. Разделы и состав билетов сохраняются. Изменения применяются после проверки и доступны для отмены."
        footer={<>
          <Button variant="ghost" onClick={requestClose}>Закрыть</Button>
          {busy === "run" || jobActive ? <Button variant="secondary" onClick={stop}><Square size={13} />Остановить</Button>
            : runResult ? <Button disabled={busy !== null || Boolean(validationMessage) || conflict} onClick={() => void applyRepair()}>{busy === "apply" ? "Применяем…" : "Применить"}</Button>
              : <Button disabled={busy !== null || !preflight || (preflight.preflight.confirmation_required && !confirmed)} onClick={() => void runRepair()}><WandSparkles size={14} />Исправить</Button>}
        </>}
      >
        <div className="ai-grouping-flow">
          <section className="ai-grouping-intro">
            <strong>{nodes.length} пунктов программы</strong>
          </section>

          <label className="ai-instruction-field">
            <span>Что не так</span>
            <textarea value={instruction} onChange={(event) => setInstruction(event.target.value)} placeholder="Например: некоторые заголовки распознались как вопросы, а подпункты нужно расставить" />
            <small>Пустая инструкция исправляет только очевидные технические дефекты текста, не трогая формулировки по смыслу.</small>
          </label>

          <Disclosure summary="Что отправим">
            <div className="ai-manifest">
              <p>Полное дерево программы: разделы, вопросы, задачи, билеты и подпункты, их id и пути. Для ответов — только наличие и число символов.</p>
              <p><strong>Не отправляются:</strong> ответы, ответы пользователя, материалы, привязки, конспекты и попытки.</p>
              {!preflight && <p>Полный состав появится после оценки запроса.</p>}
              <ol className="ai-question-manifest">
                {(preflight?.source_context ?? []).map((node, index) => (
                  <li key={node.id}>
                    <code>#{index + 1}</code>
                    <span>{node.exam_kind === "ticket" ? "Билет" : node.exam_kind === "task" ? "Задача" : node.exam_kind === "question" ? "Вопрос" : node.node_type === "section" ? "Раздел" : node.node_type === "subpoint" ? "Подпункт" : "Тема"}</span>
                    <strong>{[...node.path, node.title].join(" → ")}</strong>
                    <small>{node.id}</small>
                  </li>
                ))}
              </ol>
            </div>
          </Disclosure>

          {busy === "preflight" && <LoadingState label="Оцениваем состав и стоимость" />}
          {preflight && (
            <>
              <PreflightLine value={preflight.preflight} />
              <Link className="ai-settings-link" to="/setup?section=ai#role-exam-import-repair">Изменить модель в Параметрах</Link>
              {preflight.preflight.confirmation_required && (
                <div className="ai-confirmation">
                  <Checkbox checked={confirmed} onCheckedChange={setConfirmed} label="Я проверил состав и подтверждаю большой или неоценённый вызов" />
                  {preflight.preflight.confirmation_reasons.map((reason) => <small key={reason}>{reason}</small>)}
                </div>
              )}
            </>
          )}

          {failure && (
            <AiFailureNotice
              error={error}
              manualAlternative="Формулировки можно исправить вручную."
            />
          )}
          {Boolean(error) && !failure && !(error instanceof DOMException && error.name === "AbortError") && <p className="inline-error" role="alert">{error instanceof Error ? error.message : "Исправление не выполнено"}</p>}
          {error instanceof DOMException && error.name === "AbortError" && <p className="ai-muted" role="status">Ожидание остановлено. Программа не изменена.</p>}
          {(busy === "run" || jobActive) && <LoadingState label="Модель готовит исправление; программа пока не меняется. Диалог можно закрыть — задача продолжится в фоне" />}
          {jobError && <p className="inline-error" role="alert">{jobError}</p>}
          {job?.state === "failed" && <p className="inline-error" role="alert">{job.error ?? "Исправление не выполнено"}</p>}
          {job?.state === "cancelled" && <p className="ai-muted" role="status">Остановлено. Программа не изменена.</p>}

          {runResult && (
            <section className="ai-cleanup-result">
              <header>
                <div><strong>Предложение готово</strong>{runResult.cached && <StatusBadge tone="info">из кэша · новая стоимость 0</StatusBadge>}</div>
                <p>{runResult.usage.input_tokens.toLocaleString("ru-RU")} входных, {runResult.usage.output_tokens.toLocaleString("ru-RU")} выходных токенов · {price(runResult.usage.actual_cost_usd, runResult.usage.actual_cost_rub)}</p>
              </header>
              <div className="ai-cleanup-preview-actions">
                <Button variant="secondary" onClick={() => { setItems(originalItems); setDropped(originalDropped); }}><RotateCcw size={14} />Вернуть предложение модели</Button>
                {dirty && <small>Список изменён вручную.</small>}
              </div>

              {hasTickets ? (
                <ol className="ai-repair-ticket-list">
                  {items.map((ticket, ticketIndex) => {
                    if (ticket.kind !== "ticket") return <QuestionEditor key={ticketIndex} {...questionEditorProps(null, ticketIndex, ticket, `${ticketIndex + 1}`)} />;
                    return (
                      <li key={ticketIndex} className="ai-repair-ticket">
                        <header>
                          <span className="ai-repair-item-number">Билет {ticketIndex + 1}</span>
                          <input value={ticket.title} onChange={(event) => updateTicketTitle(ticketIndex, event.target.value)} />
                          <IconButton label="Убрать билет" onClick={() => removeTicket(ticketIndex)}><Trash2 size={14} /></IconButton>
                        </header>
                        <ol className="ai-repair-item-list">
                          {ticket.items.map((child, childIndex) => (
                            <QuestionEditor key={childIndex} {...questionEditorProps(ticketIndex, childIndex, child, `${childIndex + 1}`)} />
                          ))}
                        </ol>
                      </li>
                    );
                  })}
                </ol>
              ) : (
                <ol className="ai-repair-item-list">
                  {items.map((item, itemIndex) => {
                    if (item.kind === "ticket") return null;
                    return <QuestionEditor key={itemIndex} {...questionEditorProps(null, itemIndex, item, `${itemIndex + 1}`)} />;
                  })}
                </ol>
              )}

              {dropped.length > 0 && (
                <div className="ai-repair-dropped-list">
                  <strong>Убрано из списка ({dropped.length})</strong>
                  <ul>
                    {dropped.map((entry, index) => (
                      <li key={index}>
                        <span>Позиция {entry.source_indices.join(", ")}: {entry.reason}</span>
                        <Button variant="ghost" onClick={() => restoreDropped(index)}><RotateCcw size={13} />Вернуть пункт</Button>
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {validationMessage && <p className="inline-error" role="alert">{validationMessage}</p>}
              {runResult.changes.length > 0 && <div className="ai-change-list"><strong>Что изменено</strong><ul>{runResult.changes.map((change) => <li key={change}>{change}</li>)}</ul></div>}
              {runResult.warnings.length > 0 && <div className="ai-warning-list"><AlertTriangle size={15} /><div><strong>Предупреждения</strong><ul>{runResult.warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul></div></div>}
            </section>
          )}

          {conflict && <section className="ai-conflict" role="alert"><AlertTriangle size={16} /><div><strong>Программа уже изменилась</strong><p>Предложение относится к старой ревизии. Закройте диалог, перечитайте дерево и запустите исправление снова.</p></div></section>}
        </div>
      </Dialog>

      <ConfirmDialog
        open={discardOpen}
        onOpenChange={setDiscardOpen}
        title="Закрыть отредактированный список?"
        confirmLabel="Закрыть без применения"
        onConfirm={() => { abortRef.current?.abort(); setDiscardOpen(false); onOpenChange(false); }}
      >
        <p>Ручные правки не сохранятся. Текущая программа не менялась.</p>
      </ConfirmDialog>
    </>
  );
}
