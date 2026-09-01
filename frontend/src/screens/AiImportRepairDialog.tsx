import { AlertTriangle, Square, WandSparkles } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router";
import { describeAiFailure, listAiRuns, type AiPreflight, type AiRunRead, type DecimalValue } from "../api/ai";
import {
  preflightProgramImportRepair,
  runProgramImportRepair,
  type ProgramChangeResult,
  type ProgramImportRepairPreflightRead,
  type ProgramNodeRead,
} from "../api/projects";
import { ACTIVE_JOB_STATES, cancelBackgroundJob, findActiveBackgroundJob } from "../api/backgroundJobs";
import { useBackgroundJob } from "../hooks/useBackgroundJob";
import { AiFailureNotice } from "../components/domain";
import { Button, Checkbox, Dialog, Disclosure, LoadingState, StatusBadge } from "../components/ui";

interface AiImportRepairDialogProps {
  open: boolean;
  projectId: string;
  /** Порядок и состав должны совпадать с тем, что покажет предпросмотр
      сервера — используйте тот же список узлов, что и для группировки. */
  nodes: ProgramNodeRead[];
  onOpenChange: (open: boolean) => void;
  /** Сегодня не вызывается: применить исправление из интерфейса нельзя, пока
   *  бэкенд не отдаёт содержимое фоновой задачи через API — см. AiRunRead в
   *  api/ai.ts. Прототип сохранён ради совместимости с вызывающим экраном. */
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

export function AiImportRepairDialog({ open, projectId, nodes, onOpenChange, onApplied }: AiImportRepairDialogProps) {
  void onApplied;
  const [instruction, setInstruction] = useState("");
  const [preflight, setPreflight] = useState<ProgramImportRepairPreflightRead | null>(null);
  const [busy, setBusy] = useState<"preflight" | "starting" | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [confirmed, setConfirmed] = useState(false);
  const [jobId, setJobId] = useState<string | null>(null);
  // Задача завершилась, но бэкенд не отдаёт содержимое вызова через API (см.
  // комментарий у AiRunRead.response_payload в api/ai.ts) — исправленный
  // список посмотреть и применить из интерфейса нельзя.
  const [completedRun, setCompletedRun] = useState<AiRunRead | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const { job, error: jobError } = useBackgroundJob(jobId);
  const jobActive = Boolean(job && ACTIVE_JOB_STATES.has(job.state));

  useEffect(() => {
    if (!open) return;
    const controller = new AbortController();
    abortRef.current?.abort();
    abortRef.current = controller;
    setBusy("preflight");
    setInstruction("");
    setPreflight(null);
    setError(null);
    setConfirmed(false);
    setJobId(null);
    setCompletedRun(null);
    // При открытии сверяемся с реестром: исправление списка могло остаться
    // идти в фоне с прошлого раза, если диалог был закрыт до его завершения.
    Promise.all([
      preflightProgramImportRepair(projectId, controller.signal),
      findActiveBackgroundJob("ai_import_repair", { projectId }, controller.signal),
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
        setCompletedRun(runs.find((run) => run.job_id === job.id) ?? runs[0] ?? null);
      })
      .catch((caught) => {
        if (!controller.signal.aborted) setError(caught);
      });
    return () => controller.abort();
  }, [job?.id, job?.state]);

  function requestClose() {
    abortRef.current?.abort();
    onOpenChange(false);
  }

  async function runRepair() {
    if (!preflight || (preflight.preflight.confirmation_required && !confirmed)) return;
    const controller = new AbortController();
    abortRef.current?.abort();
    abortRef.current = controller;
    setBusy("starting");
    setError(null);
    setCompletedRun(null);
    try {
      const { job_id } = await runProgramImportRepair(projectId, {
        instruction,
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

  /** Остановить значит отменить саму фоновую задачу (реестр), а не локальное
   *  ожидание: диалог больше ничего не ждёт синхронно. */
  function stop() {
    if (!job) return;
    void cancelBackgroundJob(job.id).catch((caught) => setError(caught));
  }

  const failure = describeAiFailure(error);

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => next ? onOpenChange(true) : requestClose()}
      className="ai-consumer-dialog ai-import-repair-dialog"
      title="Исправить список вопросов"
      description="Правит формулировки, расставляет подпункты и убирает лишние заголовки; число пунктов может измениться. Дерево изменится после применения."
      footer={<>
        <Button variant="ghost" onClick={requestClose}>Закрыть</Button>
        {jobActive ? <Button variant="secondary" onClick={stop}><Square size={13} />Остановить</Button>
          : !jobId ? <Button disabled={busy !== null || !preflight || (preflight.preflight.confirmation_required && !confirmed)} onClick={() => void runRepair()}><WandSparkles size={14} />Исправить</Button>
            : null}
      </>}
    >
      <div className="ai-grouping-flow">
        <section className="ai-grouping-intro">
          <strong>{nodes.length} пунктов программы</strong>
        </section>

        <label className="ai-instruction-field">
          <span>Что не так</span>
          <textarea value={instruction} onChange={(event) => setInstruction(event.target.value)} disabled={jobId !== null} placeholder="Например: некоторые заголовки распознались как вопросы, а подпункты нужно расставить" />
          <small>Пустая инструкция исправляет только очевидные технические дефекты текста, не трогая формулировки по смыслу.</small>
        </label>

        <Disclosure summary="Что отправим">
          <div className="ai-manifest">
            <p>Текущие формулировки {nodes.length} пунктов программы, без id.</p>
            <p><strong>Не отправляются:</strong> эталоны, ответы пользователя, материалы, привязки, конспекты и попытки.</p>
            <ol className="ai-question-manifest">
              {nodes.map((node, index) => (
                <li key={node.id}>
                  <code>#{index + 1}</code>
                  <span>{node.exam_kind === "ticket" ? "Билет" : node.exam_kind === "task" ? "Задача" : node.exam_kind === "question" ? "Вопрос" : "Тема"}</span>
                  <strong>{node.title}</strong>
                </li>
              ))}
            </ol>
          </div>
        </Disclosure>

        {busy === "preflight" && !jobId && <LoadingState label="Оцениваем состав и стоимость" />}
        {preflight && !jobId && (
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
        {Boolean(error) && !failure && <p className="inline-error" role="alert">{error instanceof Error ? error.message : "Исправление не выполнено"}</p>}
        {jobError && <p className="inline-error" role="alert">{jobError}</p>}
        {jobActive && <LoadingState label="Модель готовит исправление; программа пока не меняется" />}
        {job?.state === "failed" && <p className="inline-error" role="alert">{job.error ?? "Исправление не выполнено"}</p>}
        {job?.state === "cancelled" && <p className="ai-muted" role="status">Остановлено. Программа не изменена.</p>}

        {job?.state === "completed" && (
          <section className="ai-conflict" role="status">
            <AlertTriangle size={16} />
            <div>
              <strong>Список исправлен, но не показывается</strong>
              <p>Модель отработала успешно, но бэкенд пока не отдаёт содержимое фоновой задачи через API — открыть и применить исправленный список из интерфейса нельзя. Формулировки можно исправить вручную.</p>
              {completedRun && (
                <p>
                  {(completedRun.input_tokens ?? 0).toLocaleString("ru-RU")} входных, {(completedRun.output_tokens ?? 0).toLocaleString("ru-RU")} выходных токенов
                  · {price(completedRun.actual_cost_usd, completedRun.actual_cost_rub)}
                  {completedRun.status === "cached" && " · из кэша"}
                </p>
              )}
            </div>
          </section>
        )}
      </div>
    </Dialog>
  );
}
