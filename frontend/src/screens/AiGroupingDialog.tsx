import { AlertTriangle, ArrowDown, ArrowUp, GripVertical, RotateCcw, Square, WandSparkles } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import type { DragEvent } from "react";
import { Link } from "react-router";
import { describeAiFailure, listAiRuns, type AiPreflight, type AiRunRead, type DecimalValue } from "../api/ai";
import {
  applyProgramGrouping,
  preflightProgramGrouping,
  ProjectApiError,
  runProgramGrouping,
  type ProgramChangeResult,
  type ProgramGroupingItem,
  type ProgramGroupingPreflightRead,
  type ProgramGroupingRunRead,
  type ProgramNodeRead,
} from "../api/projects";
import { cancelBackgroundJob, findActiveBackgroundJob, ACTIVE_JOB_STATES } from "../api/backgroundJobs";
import { useBackgroundJob } from "../hooks/useBackgroundJob";
import { AiFailureNotice } from "../components/domain";
import {
  Button,
  Checkbox,
  ConfirmDialog,
  Dialog,
  Disclosure,
  LoadingState,
  StatusBadge,
} from "../components/ui";

interface AiGroupingDialogProps {
  open: boolean;
  projectId: string;
  projectName: string;
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
    <section className="ai-preflight-summary" aria-label="Оценка группировки">
      <div><span>Модель</span><strong>{value.model_id}</strong></div>
      <div><span>Токены</span><strong>≈ {value.estimated_input_tokens.toLocaleString("ru-RU")} + {value.estimated_output_tokens.toLocaleString("ru-RU")}</strong></div>
      <div><span>Оценка</span><strong>{price(value.estimated_cost_usd, value.estimated_cost_rub)}</strong></div>
      <div><span>Курс</span><strong>{dateLabel(value.usd_rub_rate_date)}</strong></div>
      {value.cached && <StatusBadge tone="info">есть в кэше</StatusBadge>}
    </section>
  );
}

function cloneGroups(groups: ProgramGroupingItem[]): ProgramGroupingItem[] {
  return groups.map((group) => ({ ...group, node_ids: [...group.node_ids] }));
}

function validation(groups: ProgramGroupingItem[], expectedIds: string[]): string {
  if (groups.length < 2 || groups.length > 8) return "Нужно от 2 до 8 разделов.";
  const titles = new Set<string>();
  const assigned: string[] = [];
  for (const group of groups) {
    const words = group.title.trim().split(/\s+/).filter(Boolean);
    if (words.length < 2 || words.length > 8) return "Название каждого раздела должно содержать от 2 до 8 слов.";
    const folded = group.title.trim().toLocaleLowerCase("ru");
    if (titles.has(folded)) return "Названия разделов должны различаться.";
    titles.add(folded);
    if (!group.node_ids.length) return "Пустой раздел нельзя применить.";
    if (group.node_ids.length === 1 && !group.rationale.trim()) return "Для раздела из одного вопроса нужно объяснение.";
    assigned.push(...group.node_ids);
  }
  if (assigned.length !== new Set(assigned).size) return "Один вопрос оказался в нескольких разделах.";
  if (assigned.length !== expectedIds.length || expectedIds.some((id) => !assigned.includes(id))) return "Распределите каждый исходный вопрос ровно один раз.";
  return "";
}

export function AiGroupingDialog({ open, projectId, projectName, nodes, onOpenChange, onApplied }: AiGroupingDialogProps) {
  const [preflight, setPreflight] = useState<ProgramGroupingPreflightRead | null>(null);
  const [runResult, setRunResult] = useState<ProgramGroupingRunRead | null>(null);
  const [groups, setGroups] = useState<ProgramGroupingItem[]>([]);
  const [originalGroups, setOriginalGroups] = useState<ProgramGroupingItem[]>([]);
  const [busy, setBusy] = useState<"preflight" | "starting" | "apply" | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [confirmed, setConfirmed] = useState(false);
  const [conflict, setConflict] = useState(false);
  const [discardOpen, setDiscardOpen] = useState(false);
  const [draggedNodeId, setDraggedNodeId] = useState<string | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  // true — задача завершилась, но бэкенд не отдаёт содержимое вызова через API
  // (см. комментарий у AiRunRead.response_payload в api/ai.ts): показать
  // предложение и применить его из интерфейса нельзя.
  const [contentUnavailable, setContentUnavailable] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const nodeById = useMemo(() => new Map(nodes.map((node) => [node.id, node])), [nodes]);
  const expectedIds = useMemo(() => nodes.map((node) => node.id), [nodes]);
  const validationMessage = validation(groups, expectedIds);
  const dirty = Boolean(runResult && JSON.stringify(groups) !== JSON.stringify(originalGroups));
  const { job, error: jobError } = useBackgroundJob(jobId);
  const jobActive = Boolean(job && ACTIVE_JOB_STATES.has(job.state));

  useEffect(() => {
    if (!open) return;
    const controller = new AbortController();
    abortRef.current?.abort();
    abortRef.current = controller;
    setBusy("preflight");
    setPreflight(null);
    setRunResult(null);
    setGroups([]);
    setOriginalGroups([]);
    setError(null);
    setConfirmed(false);
    setConflict(false);
    setJobId(null);
    setContentUnavailable(false);
    // Диалог сперва спрашивает реестр, нет ли уже активной задачи этого вида
    // для проекта — ушли и вернулись, задача всё это время шла в фоне.
    Promise.all([
      preflightProgramGrouping(projectId, controller.signal),
      findActiveBackgroundJob("ai_grouping", { projectId }, controller.signal),
    ])
      .then(([value, active]) => {
        if (controller.signal.aborted) return;
        setPreflight(value);
        setConfirmed(!value.preflight.confirmation_required);
        if (active) setJobId(active.id);
      })
      .catch((caught) => {
        if (!controller.signal.aborted) setError(caught);
      })
      .finally(() => {
        if (!controller.signal.aborted) setBusy(null);
      });
    return () => controller.abort();
  }, [open, projectId]);

  useEffect(() => {
    // Закрытие диалога задачу не отменяет — она продолжает жить в очереди.
    if (!job || job.state !== "completed") return;
    const controller = new AbortController();
    void listAiRuns({ jobId: job.id }, controller.signal)
      .then((runs) => {
        if (controller.signal.aborted) return;
        applyCompletedRun(runs.find((run) => run.job_id === job.id) ?? runs[0] ?? null);
      })
      .catch((caught) => {
        if (!controller.signal.aborted) setError(caught);
      });
    return () => controller.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [job?.id, job?.state]);

  function applyCompletedRun(run: AiRunRead | null) {
    const payload = run?.response_payload;
    const groupsPayload = payload && Array.isArray(payload.groups)
      ? payload.groups as ProgramGroupingItem[]
      : null;
    if (!run || !preflight || !groupsPayload) {
      setContentUnavailable(true);
      return;
    }
    const result: ProgramGroupingRunRead = {
      run_id: run.id,
      program_revision: preflight.program_revision,
      source_hash: preflight.source_hash,
      suggestion: { groups: groupsPayload },
      usage: {
        input_tokens: run.input_tokens ?? 0,
        output_tokens: run.output_tokens ?? 0,
        reasoning_tokens: run.reasoning_tokens ?? 0,
        provider_cached_tokens: run.provider_cached_tokens ?? 0,
        actual_cost_usd: run.actual_cost_usd,
        actual_cost_rub: run.actual_cost_rub,
      },
      requested_model_id: run.requested_model_id,
      actual_model_id: run.actual_model_id ?? run.requested_model_id,
      cached: run.status === "cached",
    };
    const suggestion = cloneGroups(result.suggestion.groups);
    setRunResult(result);
    setGroups(suggestion);
    setOriginalGroups(cloneGroups(suggestion));
  }

  function requestClose() {
    if (dirty) {
      setDiscardOpen(true);
      return;
    }
    abortRef.current?.abort();
    onOpenChange(false);
  }

  async function runGrouping() {
    if (!preflight || (preflight.preflight.confirmation_required && !confirmed)) return;
    const controller = new AbortController();
    abortRef.current?.abort();
    abortRef.current = controller;
    setBusy("starting");
    setError(null);
    setConflict(false);
    try {
      const { job_id } = await runProgramGrouping(projectId, {
        expected_program_revision: preflight.program_revision,
        expected_source_hash: preflight.source_hash,
        confirmed,
      }, controller.signal);
      setJobId(job_id);
    } catch (caught) {
      if (!controller.signal.aborted) setError(caught);
    } finally {
      if (!controller.signal.aborted) setBusy(null);
    }
  }

  async function applyGrouping() {
    if (!runResult || validationMessage) return;
    const controller = new AbortController();
    abortRef.current = controller;
    setBusy("apply");
    setError(null);
    setConflict(false);
    try {
      const result = await applyProgramGrouping(projectId, {
        run_id: runResult.run_id,
        expected_program_revision: runResult.program_revision,
        expected_source_hash: runResult.source_hash,
        groups,
      }, controller.signal);
      onApplied(result);
      onOpenChange(false);
    } catch (caught) {
      if (caught instanceof ProjectApiError && caught.code === "stale_program_revision") setConflict(true);
      else if (!controller.signal.aborted) setError(caught);
    } finally {
      if (!controller.signal.aborted) setBusy(null);
    }
  }

  /** Остановить значит отменить саму фоновую задачу (реестр), а не локальное
   *  ожидание: диалог больше ничего не ждёт синхронно. */
  function stop() {
    if (!job) return;
    void cancelBackgroundJob(job.id).catch((caught) => setError(caught));
  }

  function updateGroup(index: number, patch: Partial<ProgramGroupingItem>) {
    setGroups((current) => current.map((group, groupIndex) => groupIndex === index ? { ...group, ...patch } : group));
  }

  function moveGroup(index: number, offset: number) {
    const target = index + offset;
    if (target < 0 || target >= groups.length) return;
    setGroups((current) => {
      const next = [...current];
      [next[index], next[target]] = [next[target], next[index]];
      return next;
    });
  }

  function moveNode(nodeId: string, targetIndex: number) {
    setGroups((current) => current.map((group, index) => ({
      ...group,
      node_ids: index === targetIndex
        ? group.node_ids.includes(nodeId) ? group.node_ids : [...group.node_ids, nodeId]
        : group.node_ids.filter((id) => id !== nodeId),
    })));
  }

  function drop(event: DragEvent<HTMLElement>, groupIndex: number) {
    event.preventDefault();
    const nodeId = draggedNodeId || event.dataTransfer.getData("text/plain");
    if (nodeId) moveNode(nodeId, groupIndex);
    setDraggedNodeId(null);
  }

  const failure = describeAiFailure(error);
  const distributed = new Set(groups.flatMap((group) => group.node_ids)).size;

  return (
    <>
      <Dialog
        open={open}
        onOpenChange={(next) => next ? onOpenChange(true) : requestClose()}
        className="ai-consumer-dialog ai-grouping-dialog"
        title="Разложить вопросы по разделам"
        description="Модель предложит наименьшее полезное число связных разделов — от 2 до 8. Дерево изменится только после применения."
        footer={<>
          <Button variant="ghost" onClick={requestClose}>Закрыть</Button>
          {jobActive ? <Button variant="secondary" onClick={stop}><Square size={13} />Остановить</Button>
            : runResult ? <Button disabled={busy !== null || Boolean(validationMessage) || conflict} onClick={() => void applyGrouping()}>{busy === "apply" ? "Применяем…" : "Применить структуру"}</Button>
              : !jobId ? <Button disabled={busy !== null || !preflight || (preflight.preflight.confirmation_required && !confirmed)} onClick={() => void runGrouping()}><WandSparkles size={14} />Предложить разделы</Button>
                : null}
        </>}
      >
        <div className="ai-grouping-flow">
          <section className="ai-grouping-intro">
            <strong>{projectName}</strong>
            <span>{nodes.length} вопросов и задач</span>
          </section>
          <Disclosure summary="Что отправим">
            <div className="ai-manifest">
              <p>Название экзамена и активные узлы: id, тип и формулировка.</p>
              <p><strong>Не отправляются:</strong> эталоны, ответы пользователя, материалы, привязки, конспекты и попытки.</p>
              <ol className="ai-question-manifest">
                {nodes.map((node) => <li key={node.id}><code>{node.id}</code><span>{node.exam_kind === "task" ? "Задача" : "Вопрос"}</span><strong>{node.title}</strong></li>)}
              </ol>
            </div>
          </Disclosure>

          {busy === "preflight" && !jobId && <LoadingState label="Проверяем список и оцениваем вызов" />}
          {preflight && !jobId && (
            <>
              <PreflightLine value={preflight.preflight} />
              <Link className="ai-settings-link" to="/setup?section=ai#role-exam-program-grouping">Изменить модель в Параметрах</Link>
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
              manualAlternative="Ручное редактирование вопросов остаётся доступным."
            />
          )}
          {Boolean(error) && !failure && <p className="inline-error" role="alert">{error instanceof Error ? error.message : "Группировка не выполнена"}</p>}
          {jobError && <p className="inline-error" role="alert">{jobError}</p>}
          {jobActive && <LoadingState label="Модель собирает предложение; текущее дерево не меняется" />}
          {job?.state === "failed" && <p className="inline-error" role="alert">{job.error ?? "Группировка не выполнена"}</p>}
          {job?.state === "cancelled" && <p className="ai-muted" role="status">Остановлено. Программа не изменена.</p>}
          {job?.state === "completed" && contentUnavailable && (
            <section className="ai-conflict" role="status">
              <AlertTriangle size={16} />
              <div>
                <strong>Предложение готово, но не показывается</strong>
                <p>Модель отработала успешно, но бэкенд пока не отдаёт содержимое фоновой задачи через API — открыть и применить разделы из интерфейса нельзя. Ручное редактирование вопросов остаётся доступным.</p>
              </div>
            </section>
          )}

          {runResult && (
            <section className="ai-grouping-result">
              <header>
                <div><strong>Распределено {distributed} из {nodes.length}</strong>{runResult.cached && <StatusBadge tone="info">из кэша · новая стоимость 0</StatusBadge>}</div>
                <p>{runResult.usage.input_tokens.toLocaleString("ru-RU")} входных, {runResult.usage.output_tokens.toLocaleString("ru-RU")} выходных токенов · {price(runResult.usage.actual_cost_usd, runResult.usage.actual_cost_rub)}</p>
              </header>
              <div className="ai-grouping-toolbar">
                <Button variant="secondary" onClick={() => setGroups(cloneGroups(originalGroups))}><RotateCcw size={14} />Вернуть предложение модели</Button>
                <span>Будет создано {groups.length} разделов и перемещено {nodes.length} вопросов</span>
              </div>
              <div className="ai-group-list">
                {groups.map((group, groupIndex) => (
                  <article
                    className="ai-group-card"
                    key={`${groupIndex}-${originalGroups[groupIndex]?.title ?? group.title}`}
                    onDragOver={(event) => event.preventDefault()}
                    onDrop={(event) => drop(event, groupIndex)}
                  >
                    <header>
                      <span className="ai-group-number">{groupIndex + 1}</span>
                      <label>Название раздела<input value={group.title} onChange={(event) => updateGroup(groupIndex, { title: event.target.value })} /></label>
                      <Button variant="ghost" aria-label="Поднять раздел" disabled={groupIndex === 0} onClick={() => moveGroup(groupIndex, -1)}><ArrowUp size={14} /></Button>
                      <Button variant="ghost" aria-label="Опустить раздел" disabled={groupIndex === groups.length - 1} onClick={() => moveGroup(groupIndex, 1)}><ArrowDown size={14} /></Button>
                    </header>
                    <label className="ai-group-rationale">Объяснение<textarea value={group.rationale} onChange={(event) => updateGroup(groupIndex, { rationale: event.target.value })} placeholder="Почему эти вопросы относятся к одному разделу" /></label>
                    <ol>
                      {group.node_ids.map((nodeId) => {
                        const node = nodeById.get(nodeId);
                        if (!node) return null;
                        return (
                          <li key={nodeId} draggable onDragStart={(event) => { setDraggedNodeId(nodeId); event.dataTransfer.setData("text/plain", nodeId); }} onDragEnd={() => setDraggedNodeId(null)}>
                            <GripVertical size={14} aria-hidden="true" />
                            <span><strong>{node.title}</strong><small>{node.exam_kind === "task" ? "Задача" : "Вопрос"}</small></span>
                            <label>Переместить в<select value={groupIndex} onChange={(event) => moveNode(nodeId, Number(event.target.value))}>{groups.map((target, targetIndex) => <option key={`${targetIndex}-${target.title}`} value={targetIndex}>{target.title || `Раздел ${targetIndex + 1}`}</option>)}</select></label>
                          </li>
                        );
                      })}
                    </ol>
                  </article>
                ))}
              </div>
              {validationMessage && <p className="inline-error" role="alert">{validationMessage}</p>}
            </section>
          )}

          {conflict && <section className="ai-conflict" role="alert"><AlertTriangle size={16} /><div><strong>Программа уже изменилась</strong><p>Предложение относится к старой ревизии. Закройте диалог, перечитайте дерево и запустите группировку снова.</p></div></section>}
        </div>
      </Dialog>

      <ConfirmDialog
        open={discardOpen}
        onOpenChange={setDiscardOpen}
        title="Закрыть отредактированное предложение?"
        confirmLabel="Закрыть без применения"
        onConfirm={() => { abortRef.current?.abort(); setDiscardOpen(false); onOpenChange(false); }}
      >
        <p>Названия и распределение не сохранятся. Текущая Программа не изменялась.</p>
      </ConfirmDialog>
    </>
  );
}
