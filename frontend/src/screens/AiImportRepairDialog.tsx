import { AlertTriangle, RotateCcw, Square, WandSparkles } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router";
import { isAiApiError, type AiPreflight, type DecimalValue } from "../api/ai";
import {
  applyProgramImportRepair,
  preflightProgramImportRepair,
  ProjectApiError,
  runProgramImportRepair,
  type ProgramChangeResult,
  type ProgramImportRepairPreflightRead,
  type ProgramImportRepairRunRead,
  type ProgramNodeRead,
} from "../api/projects";
import { OfflineNotice } from "../components/domain";
import { Button, Checkbox, ConfirmDialog, Dialog, Disclosure, LoadingState, StatusBadge } from "../components/ui";

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

function aiFailure(error: unknown): { unreachable: boolean; message: string } | null {
  if (!isAiApiError(error)) return null;
  return {
    unreachable: ["ai_provider_unavailable", "ai_timeout", "ai_rate_limited", "ai_invalid_credentials"].includes(error.code),
    message: error.message,
  };
}

export function AiImportRepairDialog({ open, projectId, nodes, onOpenChange, onApplied }: AiImportRepairDialogProps) {
  const [instruction, setInstruction] = useState("");
  const [preflight, setPreflight] = useState<ProgramImportRepairPreflightRead | null>(null);
  const [runResult, setRunResult] = useState<ProgramImportRepairRunRead | null>(null);
  const [items, setItems] = useState<string[]>([]);
  const [originalItems, setOriginalItems] = useState<string[]>([]);
  const [busy, setBusy] = useState<"preflight" | "run" | "apply" | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [confirmed, setConfirmed] = useState(false);
  const [conflict, setConflict] = useState(false);
  const [discardOpen, setDiscardOpen] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const dirty = Boolean(runResult && JSON.stringify(items) !== JSON.stringify(originalItems));

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
    setOriginalItems([]);
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
      const result = await runProgramImportRepair(projectId, {
        instruction,
        expected_program_revision: preflight.program_revision,
        expected_source_hash: preflight.source_hash,
        confirmed,
      }, controller.signal);
      setRunResult(result);
      setItems(result.items);
      setOriginalItems(result.items);
    } catch (caught) {
      if (!controller.signal.aborted) setError(caught);
    } finally {
      if (!controller.signal.aborted) setBusy(null);
    }
  }

  async function applyRepair() {
    if (!runResult || items.some((item) => !item.trim())) return;
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
        items,
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

  function stop() {
    abortRef.current?.abort();
    setBusy(null);
    setError(new DOMException("Ожидание остановлено пользователем", "AbortError"));
  }

  const failure = aiFailure(error);

  return (
    <>
      <Dialog
        open={open}
        onOpenChange={(next) => next ? onOpenChange(true) : requestClose()}
        className="ai-consumer-dialog ai-import-repair-dialog"
        title="Исправить список вопросов"
        description="Переписывает только формулировки: количество и порядок пунктов не меняются. Дерево изменится после применения."
        footer={<>
          <Button variant="ghost" onClick={requestClose}>Закрыть</Button>
          {busy === "run" ? <Button variant="secondary" onClick={stop}><Square size={13} />Остановить</Button>
            : runResult ? <Button disabled={busy !== null || items.some((item) => !item.trim()) || conflict} onClick={() => void applyRepair()}>{busy === "apply" ? "Применяем…" : "Применить"}</Button>
              : <Button disabled={busy !== null || !preflight || (preflight.preflight.confirmation_required && !confirmed)} onClick={() => void runRepair()}><WandSparkles size={14} />Исправить</Button>}
        </>}
      >
        <div className="ai-grouping-flow">
          <section className="ai-grouping-intro">
            <strong>{nodes.length} пунктов программы</strong>
          </section>

          <label className="ai-instruction-field">
            <span>Что не так</span>
            <textarea value={instruction} onChange={(event) => setInstruction(event.target.value)} placeholder="Например: слова слиплись без пробелов, разорванные переносы" />
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
                    <span>{node.exam_kind === "task" ? "Задача" : node.exam_kind === "question" ? "Вопрос" : "Тема"}</span>
                    <strong>{node.title}</strong>
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
            <OfflineNotice
              reason={failure.unreachable ? "unreachable" : "disabled"}
              alternative={failure.unreachable ? `${failure.message} Формулировки можно исправить вручную.` : "Формулировки можно исправить вручную."}
            />
          )}
          {Boolean(error) && !failure && !(error instanceof DOMException && error.name === "AbortError") && <p className="inline-error" role="alert">{error instanceof Error ? error.message : "Исправление не выполнено"}</p>}
          {error instanceof DOMException && error.name === "AbortError" && <p className="ai-muted" role="status">Ожидание остановлено. Программа не изменена.</p>}
          {busy === "run" && <LoadingState label="Модель готовит исправление; программа пока не меняется" />}

          {runResult && (
            <section className="ai-cleanup-result">
              <header>
                <div><strong>Предложение готово</strong>{runResult.cached && <StatusBadge tone="info">из кэша · новая стоимость 0</StatusBadge>}</div>
                <p>{runResult.usage.input_tokens.toLocaleString("ru-RU")} входных, {runResult.usage.output_tokens.toLocaleString("ru-RU")} выходных токенов · {price(runResult.usage.actual_cost_usd, runResult.usage.actual_cost_rub)}</p>
              </header>
              <div className="ai-cleanup-preview-actions">
                <Button variant="secondary" onClick={() => setItems(originalItems)}><RotateCcw size={14} />Вернуть предложение модели</Button>
                {dirty && <small>Список изменён вручную.</small>}
              </div>
              <ol className="ai-repair-item-list">
                {items.map((text, index) => (
                  <li key={index}>
                    <span className="ai-repair-item-number">{index + 1}</span>
                    <textarea
                      value={text}
                      onChange={(event) => setItems((current) => current.map((item, itemIndex) => itemIndex === index ? event.target.value : item))}
                    />
                  </li>
                ))}
              </ol>
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
        <p>Ручные правки формулировок не сохранятся. Текущая программа не менялась.</p>
      </ConfirmDialog>
    </>
  );
}
