import { useEffect, useRef, useState } from "react";
import { AlertTriangle, Sparkles, Square } from "lucide-react";
import { Link } from "react-router";
import { describeAiFailure, type AiPreflight } from "../../api/ai";
import {
  applyLinkAnswersAi,
  preflightLinkAnswersAi,
  startLinkAnswersAi,
  type AnswersAiPlanRead,
  type AnswersAiPreflightRead,
  type AnswersLinkRead,
} from "../../api/bindings";
import {
  ACTIVE_JOB_STATES,
  cancelBackgroundJob,
  findActiveBackgroundJob,
  getBackgroundJobResult,
} from "../../api/backgroundJobs";
import { AiFailureNotice } from "../../components/domain";
import { useBackgroundJob } from "../../hooks/useBackgroundJob";
import { Button, Checkbox, Dialog, Disclosure, LoadingState, StatusBadge } from "../../components/ui";

interface AnswersAiPlanDialogProps {
  open: boolean;
  projectId: string;
  materialId: string;
  nodeNumberById: Map<string, string>;
  onOpenChange: (open: boolean) => void;
  onApplied: (result: AnswersLinkRead) => void;
}

function PreflightSummary({ calls, batchCount }: { calls: AiPreflight[]; batchCount: number }) {
  const totalIn = calls.reduce((sum, call) => sum + call.estimated_input_tokens, 0);
  const totalOut = calls.reduce((sum, call) => sum + call.estimated_output_tokens, 0);
  const cost = calls.reduce((sum, call) => sum + (Number(call.estimated_cost_usd) || 0), 0);
  const model = calls[0]?.model_id ?? "";
  const cached = calls.length > 0 && calls.every((call) => call.cached);
  return (
    <section className="ai-preflight-summary" aria-label="Оценка разметки">
      <div><span>Модель</span><strong>{model}</strong></div>
      <div><span>Пакетов</span><strong>{batchCount}</strong></div>
      <div><span>Токены</span><strong>≈ {totalIn.toLocaleString("ru-RU")} + {totalOut.toLocaleString("ru-RU")}</strong></div>
      <div><span>Оценка</span><strong>{cost > 0 ? `$${cost.toFixed(6).replace(/0+$/, "").replace(/\.$/, ".00")}` : "цена неизвестна"}</strong></div>
      {cached && <StatusBadge tone="info">есть в кэше</StatusBadge>}
    </section>
  );
}

/**
 * Разметка файла эталонных ответов моделью (срез F): когда заголовки или
 * нумерация разошлись со структурой документа настолько, что режим «На
 * основе заголовков» не справляется. Модель получает не текст ответов, а
 * только скелет документа — строки-кандидаты в границы разделов; план
 * применяется только после того, как пользователь отметил нужные строки.
 */
export function AnswersAiPlanDialog({
  open,
  projectId,
  materialId,
  nodeNumberById,
  onOpenChange,
  onApplied,
}: AnswersAiPlanDialogProps) {
  const [preflight, setPreflight] = useState<AnswersAiPreflightRead | null>(null);
  const [plan, setPlan] = useState<AnswersAiPlanRead | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [accepted, setAccepted] = useState<Set<number>>(new Set());
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState<"preflight" | "run" | "apply" | null>(null);
  const [error, setError] = useState<unknown>(null);
  const { job, error: jobError } = useBackgroundJob(jobId);
  const jobActive = Boolean(job && ACTIVE_JOB_STATES.has(job.state));
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    if (!open) return;
    const controller = new AbortController();
    abortRef.current?.abort();
    abortRef.current = controller;
    setBusy("preflight");
    setPreflight(null);
    setPlan(null);
    setAccepted(new Set());
    setError(null);
    setConfirmed(false);
    void preflightLinkAnswersAi(projectId, materialId, controller.signal)
      .then((value) => {
        if (controller.signal.aborted) return;
        setPreflight(value);
        setConfirmed(!value.confirmation_required);
      })
      .catch((caught) => { if (!controller.signal.aborted) setError(caught); })
      .finally(() => { if (!controller.signal.aborted) setBusy(null); });
    return () => controller.abort();
  }, [open, projectId, materialId]);

  useEffect(() => {
    if (!open) { setJobId(null); return; }
    const controller = new AbortController();
    void findActiveBackgroundJob("ai_answer_sections", { projectId, materialId }, controller.signal)
      .then((active) => { if (!controller.signal.aborted && active) setJobId(active.id); })
      .catch(() => undefined);
    return () => controller.abort();
  }, [open, projectId, materialId]);

  useEffect(() => {
    if (!job || job.state !== "completed" || plan) return;
    const controller = new AbortController();
    void getBackgroundJobResult<AnswersAiPlanRead>(job.id, controller.signal)
      .then((result) => {
        if (controller.signal.aborted) return;
        setPlan(result);
        setAccepted(new Set(result.rows.map((row) => row.index)));
      })
      .catch((caught) => { if (!controller.signal.aborted) setError(caught); });
    return () => controller.abort();
  }, [job?.id, job?.state, plan]);

  function requestClose() {
    abortRef.current?.abort();
    onOpenChange(false);
  }

  async function run() {
    if (!preflight || (preflight.confirmation_required && !confirmed)) return;
    const controller = new AbortController();
    abortRef.current?.abort();
    abortRef.current = controller;
    setBusy("run");
    setError(null);
    try {
      const started = await startLinkAnswersAi(
        projectId,
        materialId,
        { expectedSourceHash: preflight.source_hash, confirmed },
        controller.signal,
      );
      setJobId(started.job_id);
    } catch (caught) {
      if (!controller.signal.aborted) setError(caught);
    } finally {
      if (!controller.signal.aborted) setBusy(null);
    }
  }

  async function apply() {
    if (!plan || accepted.size === 0) return;
    const controller = new AbortController();
    abortRef.current = controller;
    setBusy("apply");
    setError(null);
    try {
      const result = await applyLinkAnswersAi(
        projectId,
        materialId,
        { runId: plan.run_id, expectedSourceHash: plan.source_hash, accepted: [...accepted] },
        controller.signal,
      );
      onApplied(result);
      onOpenChange(false);
    } catch (caught) {
      if (!controller.signal.aborted) setError(caught);
    } finally {
      if (!controller.signal.aborted) setBusy(null);
    }
  }

  function stop() {
    if (!jobId) return;
    void cancelBackgroundJob(jobId).catch((caught) => setError(caught));
  }

  function toggle(index: number) {
    setAccepted((current) => {
      const next = new Set(current);
      if (next.has(index)) next.delete(index); else next.add(index);
      return next;
    });
  }

  const failure = describeAiFailure(error);

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => (next ? onOpenChange(true) : requestClose())}
      className="ai-consumer-dialog answers-ai-plan-dialog"
      title="Разметить ответы моделью"
      description="Модель получает не текст ответов, а только заголовки-кандидаты и номера страниц — и возвращает, какой раздел к какому вопросу относится. Текст эталона собирается на сервере из уже загруженного файла."
      footer={<>
        <Button variant="ghost" onClick={requestClose}>Закрыть</Button>
        {busy === "run" || jobActive ? (
          <Button variant="secondary" onClick={stop}><Square size={13} />Остановить</Button>
        ) : plan ? (
          <Button disabled={busy !== null || accepted.size === 0} onClick={() => void apply()}>
            {busy === "apply" ? "Применяем…" : `Применить (${accepted.size})`}
          </Button>
        ) : (
          <Button
            disabled={busy !== null || !preflight || (preflight.confirmation_required && !confirmed)}
            onClick={() => void run()}
          >
            <Sparkles size={14} />Разметить
          </Button>
        )}
      </>}
    >
      <div className="ai-grouping-flow">
        <Disclosure summary="Что отправим">
          <div className="ai-manifest">
            <p>
              {preflight
                ? `${preflight.candidate_count} строк-кандидатов в границы разделов (заголовок, номер страницы, до 100 знаков текста) и формулировки ${preflight.question_count} вопросов программы.`
                : "Состав появится после оценки запроса."}
            </p>
            <p><strong>Не отправляются:</strong> текст ответов целиком, привязки, попытки, конспекты, ваши ответы.</p>
          </div>
        </Disclosure>

        {busy === "preflight" && <LoadingState label="Оцениваем состав и стоимость" />}
        {preflight && !plan && (
          <>
            <PreflightSummary calls={preflight.calls} batchCount={preflight.batch_count} />
            <Link className="ai-settings-link" to="/setup?section=ai#role-exam-answer-sections">Изменить модель в Параметрах</Link>
            {preflight.confirmation_required && (
              <div className="ai-confirmation">
                <Checkbox checked={confirmed} onCheckedChange={setConfirmed} label="Я проверил состав и подтверждаю большой или неоценённый вызов" />
                {preflight.confirmation_reasons.map((reason) => <small key={reason}>{reason}</small>)}
              </div>
            )}
          </>
        )}

        {failure && <AiFailureNotice error={error} manualAlternative="Разделы можно связать вручную." />}
        {Boolean(error) && !failure && !(error instanceof DOMException && error.name === "AbortError") && (
          <p className="inline-error" role="alert">{error instanceof Error ? error.message : "Разметка не выполнена"}</p>
        )}
        {(busy === "run" || jobActive) && (
          <LoadingState label="Модель размечает разделы; файл пока не изменён. Диалог можно закрыть — задача продолжится в фоне" />
        )}
        {jobError && <p className="inline-error" role="alert">{jobError}</p>}
        {job?.state === "failed" && <p className="inline-error" role="alert">{job.error ?? "Разметка не выполнена"}</p>}
        {job?.state === "cancelled" && <p className="ai-muted" role="status">Остановлено. Файл не изменён.</p>}

        {plan && (
          <section className="answers-ai-plan">
            <header>
              <strong>План готов · {plan.rows.length} раздел{plan.rows.length === 1 ? "" : "ов"}</strong>
              {plan.cached && <StatusBadge tone="info">из кэша · новая стоимость 0</StatusBadge>}
            </header>
            {plan.rows.length === 0 && <p className="ai-muted">Модель не нашла ни одного раздела с ответом.</p>}
            <ul className="answers-ai-plan-rows">
              {plan.rows.map((row) => (
                <li key={row.index} className="answers-ai-plan-row">
                  <Checkbox
                    checked={accepted.has(row.index)}
                    onCheckedChange={() => toggle(row.index)}
                    label="Принять"
                  />
                  <div className="answers-ai-plan-row-body">
                    <div className="answers-ai-plan-row-title">
                      <strong>{nodeNumberById.get(row.node_id) ? `${nodeNumberById.get(row.node_id)}. ` : ""}{row.node_title}</strong>
                      <StatusBadge tone={row.confidence === "high" ? "success" : "warning"}>
                        {row.confidence === "high" ? "уверенно" : "проверьте"}
                      </StatusBadge>
                    </div>
                    <small>
                      стр. {row.page_from === row.page_to ? row.page_from : `${row.page_from}–${row.page_to}`}
                      {" · "}
                      {row.char_count.toLocaleString("ru-RU")} знаков
                      {" · "}заголовок в файле: «{row.heading}»
                    </small>
                    <p>{row.preview}</p>
                    {row.note && <small className="ai-muted">{row.note}</small>}
                  </div>
                </li>
              ))}
            </ul>

            {plan.skipped_questions.length > 0 && (
              <div className="ai-warning-list">
                <AlertTriangle size={15} />
                <div>
                  <strong>Вопросы без ответа в файле ({plan.skipped_questions.length})</strong>
                  <small>Модель не нашла в файле раздел для {plan.skipped_questions.length} вопрос{plan.skipped_questions.length === 1 ? "а" : "ов"} программы.</small>
                </div>
              </div>
            )}
            {plan.structural_boundaries > 0 && (
              <p className="ai-muted">
                Границ без вопроса (оглавление, служебные заголовки): {plan.structural_boundaries}.
              </p>
            )}
            {plan.warnings.length > 0 && (
              <div className="ai-warning-list">
                <AlertTriangle size={15} />
                <div>
                  <strong>Заголовки без текста</strong>
                  <ul>{plan.warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul>
                </div>
              </div>
            )}
          </section>
        )}
      </div>
    </Dialog>
  );
}
