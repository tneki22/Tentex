/** ИИ использует тот же preview-контракт; job id переживает уход с экрана. */
import { useEffect, useRef, useState } from "react";
import { Button, Dialog, Field, ErrorState } from "../../components/ui";
import {
  preparation,
  revisions,
  errorText,
  type AiWrite,
  type Coach,
  type Draft,
  type Overview,
  type Schema,
} from "../../api/preparation";
import { useBackgroundJob } from "../../hooks/useBackgroundJob";
import {
  cancelBackgroundJob,
  getBackgroundJobResult,
} from "../../api/backgroundJobs";
export function AiPreparation({
  overview,
  onDraft,
  onAction,
}: {
  overview: Overview;
  onDraft: (draft: Draft) => void;
  onAction: (action: Coach["action"]) => void;
}) {
  const key = `tentex-preparation-ai:${overview.project_id}`;
  const [jobId, setJobId] = useState<string | null>(() =>
    localStorage.getItem(key),
  );
  const [action, setAction] = useState<AiWrite["action"]>("full");
  const [open, setOpen] = useState(false);
  const [instruction, setInstruction] = useState("");
  const [preflight, setPreflight] = useState<
    Schema["PreparationAiPreflightRead"] | null
  >(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [coach, setCoach] = useState<Coach | null>(overview.coach);
  const once = useRef("");
  const delivered = useRef<string | null>(null);
  useEffect(() => {
    setCoach((current) => current?.origin === "ai" ? current : overview.coach);
  }, [overview.coach]);
  const { job, error: jobError, refresh } = useBackgroundJob(jobId);
  const saveJob = (id: string | null) => {
    setJobId(id);
    if (id) localStorage.setItem(key, id);
    else localStorage.removeItem(key);
  };
  useEffect(() => {
    if (overview.readonly) return;
    const day = `${overview.project_id}:${overview.today}`;
    if (once.current === day) return;
    once.current = day;
    preparation
      .ai(overview.project_id, {
        ...revisions(overview),
        action: "coach",
        automatic: true,
        instruction: "",
        confirmed: false,
      })
      .then((result) => {
        if (result.coach) setCoach(result.coach);
        if (result.job_id && !jobId) saveJob(result.job_id);
        // Локальная рекомендация — штатный режим при выключенных внешних моделях.
      })
      .catch((caught) => setError(errorText(caught)));
  }, [overview.project_id, overview.today]);
  useEffect(() => {
    if (job?.state !== "completed" || !jobId || delivered.current === jobId)
      return;
    delivered.current = jobId;
    getBackgroundJobResult<Draft | Coach>(jobId)
      .then((result) => {
        if ("base_revision" in result) {
          onDraft(result);
          setOpen(false);
        } else setCoach(result);
        saveJob(null);
      })
      .catch((caught) => {
        delivered.current = null;
        setError(errorText(caught));
      });
  }, [job?.state, jobId]);
  async function prepare() {
    setBusy(true);
    setError(null);
    try {
      setPreflight(
        await preparation.preflight(overview.project_id, {
          ...revisions(overview),
          action,
          instruction,
          automatic: false,
          confirmed: false,
        }),
      );
    } catch (caught) {
      setError(errorText(caught));
    } finally {
      setBusy(false);
    }
  }
  async function launch() {
    setBusy(true);
    try {
      const result = await preparation.ai(overview.project_id, {
        ...revisions(overview),
        action,
        instruction,
        confirmed: true,
        automatic: false,
      });
      if (result.job_id) saveJob(result.job_id);
      if (result.coach) setCoach(result.coach);
      if (result.reason) setError(result.reason);
      setPreflight(null);
    } catch (caught) {
      setError(errorText(caught));
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <div className="prep-actions">
        {(
          [
            ["phases", "Предложить блоки"],
            ["distribute", "Распределить с ИИ"],
            ["full", "Весь план с ИИ"],
            ["coach", "Совет с ИИ"],
          ] as const
        ).map(([value, label]) => (
          <Button
            key={value}
            variant="ghost"
            disabled={Boolean(
              jobId && job?.state !== "failed" && job?.state !== "cancelled",
            )}
            onClick={() => {
              setAction(value);
              setPreflight(null);
              setError(null);
              setOpen(true);
            }}
          >
            {label}
          </Button>
        ))}
      </div>
      {coach && (
        <div className="prep-coach-ai">
          {coach.text}
          <small>
            {coach.origin === "ai"
              ? "Рекомендация ИИ"
              : "Локальная рекомендация"}
            {coach.reason ? ` · ${coach.reason}` : ""}
          </small>
          <Button variant="ghost" onClick={() => onAction(coach.action)}>
            {coach.action === "start" ? "Открыть очередь дня" : coach.action === "redistribute"
              ? "Перераспределить остаток" : "Составить план"}
          </Button>
        </div>
      )}
      {jobId && (
        <div className="prep-card" role="status">
          <p>
            {job?.state === "failed"
              ? job.error
              : job?.state === "cancelled"
                ? "Задача отменена"
                : `ИИ: ${job?.state ?? "загрузка"} · ${job?.done ?? 0}/${job?.total ?? 0}`}
          </p>
          {jobError && <p>{jobError}</p>}
          <Button variant="ghost" onClick={() => void refresh()}>
            Обновить статус
          </Button>
          {job?.state === "failed" || job?.state === "cancelled" ? (
            <Button
              onClick={() => {
                saveJob(null);
                setOpen(true);
              }}
            >
              Повторить
            </Button>
          ) : (
            <Button
              variant="ghost"
              onClick={() => {
                void cancelBackgroundJob(jobId)
                  .then(refresh)
                  .catch((caught) => setError(errorText(caught)));
              }}
            >
              Отменить задачу
            </Button>
          )}
        </div>
      )}
      {error && !open && (
        <p role="status" className="prep-muted">
          {error}
        </p>
      )}
      <Dialog
        open={open}
        onOpenChange={setOpen}
        title="Предложение ИИ"
        description="Модель предложит изменения; расписание изменится только после просмотра и принятия."
        footer={
          <>
            <Button variant="ghost" onClick={() => setOpen(false)}>
              Закрыть
            </Button>
            <Button
              disabled={
                busy ||
                Boolean(
                  jobId &&
                  job?.state !== "failed" &&
                  job?.state !== "cancelled",
                )
              }
              onClick={() => void (preflight ? launch() : prepare())}
            >
              {busy
                ? "Готовим…"
                : preflight
                  ? "Подтвердить и запустить"
                  : "Проверить контекст и стоимость"}
            </Button>
          </>
        }
      >
        {error && <ErrorState title="ИИ не запущен" message={error} />}
        <Field label="Пожелания">
          <textarea
            maxLength={8000}
            value={instruction}
            onChange={(event) => {
              setInstruction(event.target.value);
              setPreflight(null);
            }}
          />
        </Field>
        {preflight && (
          <section>
            <p>
              Обращений: {preflight.calls.length}. Общая оценка:{" "}
              {preflight.calls.some((call) => call.estimated_cost_usd === null)
                ? "неполная"
                : `$${preflight.calls.reduce((sum, call) => sum + Number(call.estimated_cost_usd ?? 0), 0).toFixed(4)}`}
            </p>
            {preflight.calls.map((call, index) => (
              <p key={index}>
                {index + 1}. {call.role}: {call.model_id} ·{" "}
                {call.provider_label} ·{" "}
                {call.estimated_cost_usd === null
                  ? "нет оценки"
                  : `$${call.estimated_cost_usd}`}
                {call.cached ? " · из кэша" : ""}
              </p>
            ))}
            {preflight.confirmation_reasons.map((reason) => (
              <p key={reason}>{reason}</p>
            ))}
            <details open>
              <summary>Передаваемый контекст</summary>
              <pre className="prep-manifest">
                {JSON.stringify(preflight.context, null, 2)}
              </pre>
            </details>
          </section>
        )}
      </Dialog>
    </>
  );
}
