import { AlertTriangle, RotateCcw, Sparkles, Square, WandSparkles } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router";
import { describeAiFailure, type AiPreflight, type DecimalValue } from "../api/ai";
import {
  applyLibraryPageCleanup,
  applyMaterialPageCleanup,
  preflightLibraryPageCleanup,
  preflightMaterialPageCleanup,
  runLibraryPageCleanup,
  runMaterialPageCleanup,
  type CleanupPreflightRead,
  type CleanupRunRead,
  type MaterialPageRead,
  type PageCorrectionRead,
} from "../api/materials";
import { ProjectApiError } from "../api/projects";
import { ACTIVE_JOB_STATES, cancelBackgroundJob, findActiveBackgroundJob, getBackgroundJobResult } from "../api/backgroundJobs";
import { useBackgroundJob } from "../hooks/useBackgroundJob";
import { AiFailureNotice } from "../components/domain";
import {
  Button,
  Checkbox,
  ConfirmDialog,
  Dialog,
  Disclosure,
  LoadingState,
  SegmentedTabs,
  StatusBadge,
} from "../components/ui";

interface CleanupUndoSnapshot {
  originalText: string;
  appliedRevision: number;
  appliedSourceHash: string;
}

/** Уборка одинаково работает из проекта и из Библиотеки: ей нужны только
    материал и страница, а роль шлюза, кэш и учёт расхода общие. */
export interface CleanupMaterial {
  id: string;
  display_name: string;
  active_parse_revision: number;
}

interface AiCleanupPanelProps {
  open: boolean;
  /** null — уборка запущена из Библиотеки: проекта у общего материала нет. */
  projectId: string | null;
  material: CleanupMaterial;
  page: MaterialPageRead;
  onOpenChange: (open: boolean) => void;
  onManualEdit: () => void;
  onReload: () => Promise<void>;
  onApplied: (result: PageCorrectionRead, undo: CleanupUndoSnapshot) => void;
}

function decimal(value: DecimalValue | null): number | null {
  if (value === null) return null;
  const result = Number(value);
  return Number.isFinite(result) ? result : null;
}

function cost(value: DecimalValue | null, currency: "$" | "₽"): string {
  const result = decimal(value);
  if (result === null) return currency === "$" ? "цена неизвестна" : "курс не задан";
  const digits = currency === "$" ? 6 : 2;
  return currency === "$"
    ? `$${result.toFixed(digits).replace(/0+$/, "").replace(/\.$/, ".00")}`
    : `≈ ${result.toLocaleString("ru-RU", { maximumFractionDigits: digits })} ₽`;
}

function dateLabel(value: string | null): string {
  return value ? new Intl.DateTimeFormat("ru-RU", { dateStyle: "medium" }).format(new Date(value)) : "дата курса не задана";
}

async function sha256(value: string): Promise<string> {
  const bytes = new TextEncoder().encode(value);
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
}

function PreflightSummary({ value }: { value: AiPreflight }) {
  return (
    <section className="ai-preflight-summary" aria-label="Оценка вызова">
      <div><span>Модель</span><strong>{value.model_id}</strong></div>
      <div><span>Токены</span><strong>≈ {value.estimated_input_tokens.toLocaleString("ru-RU")} + {value.estimated_output_tokens.toLocaleString("ru-RU")}</strong></div>
      <div><span>Оценка</span><strong>{cost(value.estimated_cost_usd, "$")}{value.estimated_cost_rub !== null ? `, ${cost(value.estimated_cost_rub, "₽")}` : ""}</strong></div>
      <div><span>Курс</span><strong>{dateLabel(value.usd_rub_rate_date)}</strong></div>
      {value.cached && <StatusBadge tone="info">результат есть в кэше</StatusBadge>}
    </section>
  );
}

export function AiCleanupPanel({
  open,
  projectId,
  material,
  page,
  onOpenChange,
  onManualEdit,
  onReload,
  onApplied,
}: AiCleanupPanelProps) {
  const originalText = page.markdown || page.text;
  const [instruction, setInstruction] = useState("");
  const [preflight, setPreflight] = useState<CleanupPreflightRead | null>(null);
  const [runResult, setRunResult] = useState<CleanupRunRead | null>(null);
  const [preview, setPreview] = useState("");
  const [originalSuggestion, setOriginalSuggestion] = useState("");
  const [busy, setBusy] = useState<"preflight" | "starting" | "apply" | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [confirmed, setConfirmed] = useState(false);
  const [conflict, setConflict] = useState(false);
  const [compareTab, setCompareTab] = useState<"result" | "source">("result");
  const [discardOpen, setDiscardOpen] = useState(false);
  const [jobId, setJobId] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const dirty = Boolean(runResult && preview !== originalSuggestion);
  const { job, error: jobError } = useBackgroundJob(jobId);
  const jobActive = Boolean(job && ACTIVE_JOB_STATES.has(job.state));

  const wasOpen = useRef(false);

  useEffect(() => {
    if (!open || wasOpen.current) {
      wasOpen.current = open;
      return;
    }
    wasOpen.current = true;
    setInstruction("");
    setPreflight(null);
    setRunResult(null);
    setPreview("");
    setOriginalSuggestion("");
    setError(null);
    setConfirmed(false);
    setConflict(false);
    setCompareTab("result");
    setJobId(null);
    // При открытии сверяемся с реестром: уборка этой страницы могла остаться
    // идти в фоне с прошлого раза, когда диалог был закрыт.
    const controller = new AbortController();
    void findActiveBackgroundJob(
      "ai_cleanup",
      { materialId: material.id, projectId: projectId ?? undefined },
      controller.signal,
    )
      .then((active) => { if (!controller.signal.aborted && active) setJobId(active.id); })
      .catch(() => undefined);
    return () => controller.abort();
  }, [open, material.id, projectId]);

  useEffect(() => {
    if (!open || busy === "starting" || busy === "apply" || jobActive) return;
    const controller = new AbortController();
    abortRef.current?.abort();
    abortRef.current = controller;
    setBusy("preflight");
    setError(null);
    const timer = window.setTimeout(() => {
      void (projectId === null
        ? preflightLibraryPageCleanup(material.id, page.page_number, instruction, controller.signal)
        : preflightMaterialPageCleanup(projectId, material.id, page.page_number, instruction, controller.signal))
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
    }, 350);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [open, projectId, material.id, page.id, page.page_number, instruction, jobActive]);

  // Закрытие панели задачу не отменяет — она живёт в очереди, и вернувшийся
  // экран забирает её готовую уборку из реестра, а не зовёт модель заново.
  useEffect(() => {
    if (!job || job.state !== "completed" || runResult) return;
    const controller = new AbortController();
    void getBackgroundJobResult<CleanupRunRead>(job.id, controller.signal)
      .then((result) => {
        if (controller.signal.aborted) return;
        setRunResult(result);
        setPreview(result.suggestion.markdown);
        setOriginalSuggestion(result.suggestion.markdown);
      })
      .catch((caught) => {
        if (!controller.signal.aborted) setError(caught);
      });
    return () => controller.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [job?.id, job?.state, runResult]);

  function requestClose() {
    if (dirty) {
      setDiscardOpen(true);
      return;
    }
    abortRef.current?.abort();
    onOpenChange(false);
  }

  async function runCleanup() {
    if (!preflight || (preflight.preflight.confirmation_required && !confirmed)) return;
    const controller = new AbortController();
    abortRef.current?.abort();
    abortRef.current = controller;
    setBusy("starting");
    setError(null);
    setConflict(false);
    setRunResult(null);
    try {
      const send = projectId === null
        ? (command: Parameters<typeof runLibraryPageCleanup>[2], signal: AbortSignal) =>
          runLibraryPageCleanup(material.id, page.page_number, command, signal)
        : (command: Parameters<typeof runLibraryPageCleanup>[2], signal: AbortSignal) =>
          runMaterialPageCleanup(projectId, material.id, page.page_number, command, signal);
      const { job_id } = await send({
        instruction,
        expected_revision: preflight.revision,
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

  async function applyCleanup() {
    if (!runResult || !preview.trim()) return;
    const controller = new AbortController();
    abortRef.current = controller;
    setBusy("apply");
    setError(null);
    setConflict(false);
    try {
      const send = projectId === null
        ? (command: Parameters<typeof applyLibraryPageCleanup>[2], signal: AbortSignal) =>
          applyLibraryPageCleanup(material.id, page.page_number, command, signal)
        : (command: Parameters<typeof applyLibraryPageCleanup>[2], signal: AbortSignal) =>
          applyMaterialPageCleanup(projectId, material.id, page.page_number, command, signal);
      const result = await send({
        run_id: runResult.run_id,
        expected_revision: runResult.revision,
        expected_source_hash: runResult.source_hash,
        markdown: preview,
      }, controller.signal);
      const appliedText = result.page.markdown || result.page.text;
      onApplied(result, {
        originalText,
        appliedRevision: runResult.revision + 1,
        appliedSourceHash: await sha256(appliedText),
      });
      onOpenChange(false);
    } catch (caught) {
      if (caught instanceof ProjectApiError && ["stale_material_revision", "stale_material_source"].includes(caught.code ?? "")) {
        setConflict(true);
      } else if (!controller.signal.aborted) {
        setError(caught);
      }
    } finally {
      if (!controller.signal.aborted) setBusy(null);
    }
  }

  /** Остановить значит отменить саму фоновую задачу (реестр), а не локальное
   *  ожидание: панель больше ничего не ждёт синхронно. */
  function stop() {
    if (!job) return;
    void cancelBackgroundJob(job.id).catch((caught) => setError(caught));
  }

  const aiFailure = describeAiFailure(error);
  const preflightValue = preflight?.preflight ?? null;

  return (
    <>
      <Dialog
        open={open}
        onOpenChange={(next) => next ? onOpenChange(true) : requestClose()}
        className="ai-consumer-dialog ai-cleanup-dialog"
        title={`Прибрать текст страницы ${page.page_number}`}
        description={`${material.display_name}. Результат будет сохранён как новая ревизия; исходный файл не изменится.`}
        footer={<>
          <Button variant="ghost" onClick={requestClose}>Закрыть</Button>
          {jobActive ? (
            <Button variant="secondary" onClick={stop}><Square size={13} />Остановить</Button>
          ) : runResult ? (
            <>
              <Button variant="secondary" disabled={busy !== null} onClick={() => void runCleanup()}><RotateCcw size={14} />Запустить ещё раз</Button>
              <Button disabled={busy !== null || !preview.trim() || conflict} onClick={() => void applyCleanup()}>{busy === "apply" ? "Применяем…" : "Применить"}</Button>
            </>
          ) : (
            <Button disabled={busy !== null || !preflight || (preflightValue?.confirmation_required && !confirmed)} onClick={() => void runCleanup()}><Sparkles size={14} />Прибрать текст</Button>
          )}
        </>}
      >
        <div className="ai-cleanup-flow">
          <section className="ai-cleanup-source">
            <header><strong>Исходный текст</strong><span>ревизия {preflight?.revision ?? material.active_parse_revision}</span></header>
            <pre>{originalText}</pre>
          </section>

          <label className="ai-instruction-field">
            <span>Что изменить</span>
            <textarea value={instruction} onChange={(event) => setInstruction(event.target.value)} placeholder="Например: сократи вступление, убери повторы и сохрани определения" />
            <small>Пустая инструкция исправляет разрывы строк, пунктуацию, списки, заголовки и отступы — без новых фактов, удаления смысла и сокращения текста.</small>
          </label>

          {busy === "preflight" && !preflightValue && !jobId && <LoadingState label="Оцениваем состав и стоимость" />}
          {preflightValue && !jobId && (
            <>
              <PreflightSummary value={preflightValue} />
              <Disclosure summary="Что отправим">
                <div className="ai-manifest">
                  <p>Материал «{material.display_name}», страница {page.page_number}, {originalText.length.toLocaleString("ru-RU")} символов, пользовательская инструкция{instruction.trim() ? "" : " отсутствует"}.</p>
                  <p><strong>Не отправляются:</strong> эталоны, привязки, другие страницы, материалы и история проекта.</p>
                  <pre>{JSON.stringify(preflightValue.context_manifest, null, 2)}</pre>
                </div>
              </Disclosure>
              <Link className="ai-settings-link" to="/setup?section=ai#role-material-text-cleanup">Изменить модель в Параметрах</Link>
              {preflightValue.confirmation_required && (
                <div className="ai-confirmation">
                  <Checkbox checked={confirmed} onCheckedChange={setConfirmed} label="Я проверил состав и подтверждаю большой или неоценённый вызов" />
                  {preflightValue.confirmation_reasons.map((reason) => <small key={reason}>{reason}</small>)}
                </div>
              )}
            </>
          )}

          {aiFailure && (
            <>
              <AiFailureNotice error={error} manualAlternative="Страницу можно исправить вручную." />
              <Button variant="secondary" onClick={() => { onManualEdit(); onOpenChange(false); }}>Исправить текст вручную</Button>
            </>
          )}
          {Boolean(error) && !aiFailure && <p className="inline-error" role="alert">{error instanceof Error ? error.message : "Вызов не выполнен"}</p>}
          {jobError && <p className="inline-error" role="alert">{jobError}</p>}

          {jobActive && <LoadingState label="Модель готовит предложение; страницу пока не меняем" />}
          {job?.state === "failed" && <p className="inline-error" role="alert">{job.error ?? "Вызов не выполнен"}</p>}
          {job?.state === "cancelled" && <p className="ai-muted" role="status">Остановлено. Страница не изменена.</p>}
          {runResult && (
            <section className="ai-cleanup-result">
              <header>
                <div><strong>Предложение готово</strong>{runResult.cached && <StatusBadge tone="info">из кэша · новая стоимость 0</StatusBadge>}</div>
                <p>{runResult.usage.input_tokens.toLocaleString("ru-RU")} входных, {runResult.usage.output_tokens.toLocaleString("ru-RU")} выходных токенов · {cost(runResult.usage.actual_cost_usd, "$")}{runResult.usage.actual_cost_rub !== null ? `, ${cost(runResult.usage.actual_cost_rub, "₽")}` : ""} · курс на {dateLabel(preflightValue?.usd_rub_rate_date ?? null)}</p>
              </header>
              <SegmentedTabs
                className="ai-cleanup-mobile-tabs"
                label="Сравнение текста"
                value={compareTab}
                onChange={setCompareTab}
                tabs={[{ value: "result", label: "Результат" }, { value: "source", label: "Исходный" }]}
              />
              <div className={`ai-cleanup-compare is-${compareTab}`}>
                <label className="ai-cleanup-preview"><span>Результат</span><textarea value={preview} onChange={(event) => setPreview(event.target.value)} /></label>
                <div className="ai-cleanup-original"><span>Исходный</span><pre>{originalText}</pre></div>
              </div>
              <div className="ai-cleanup-preview-actions">
                <Button variant="secondary" onClick={() => setPreview(originalText)}><RotateCcw size={14} />Вернуть к исходному виду</Button>
                {preview !== originalSuggestion && <small>Предпросмотр изменён вручную.</small>}
              </div>
              {runResult.suggestion.changes.length > 0 && <div className="ai-change-list"><strong>Что изменено</strong><ul>{runResult.suggestion.changes.map((change) => <li key={change}>{change}</li>)}</ul></div>}
              {runResult.suggestion.warnings.length > 0 && <div className="ai-warning-list"><AlertTriangle size={15} /><div><strong>Предупреждения</strong><ul>{runResult.suggestion.warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul></div></div>}
            </section>
          )}

          {conflict && (
            <section className="ai-conflict" role="alert">
              <AlertTriangle size={16} />
              <div><strong>Текст страницы уже обновлён</strong><p>Старое предложение не применяется. Перезагрузите исходный текст; введённая инструкция останется.</p></div>
              <Button variant="secondary" onClick={() => void onReload().then(() => { setRunResult(null); setPreview(""); setConflict(false); })}><WandSparkles size={14} />Обновить исходный текст</Button>
            </section>
          )}
        </div>
      </Dialog>

      <ConfirmDialog
        open={discardOpen}
        onOpenChange={setDiscardOpen}
        title="Закрыть изменённый предпросмотр?"
        confirmLabel="Закрыть без применения"
        onConfirm={() => {
          abortRef.current?.abort();
          setDiscardOpen(false);
          onOpenChange(false);
        }}
      >
        <p>Ручные изменения предложения не сохранены. Исходная страница не менялась.</p>
      </ConfirmDialog>
    </>
  );
}
