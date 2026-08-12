import { useEffect, useId, useState } from "react";
import { ChevronDown, History } from "lucide-react";
import {
  checkAttempt,
  getAttempt,
  listAttempts,
  setAttemptSelfAssessment,
  type AttemptDetailRead,
  type AttemptOutcome,
  type AttemptSummaryRead,
  type GradeMethod,
} from "../../api/chat";
import { Button } from "../../components/ui";
import { VerdictCard, verdictFromGrade } from "./chat/VerdictCard";

interface AttemptHistoryProps {
  projectId: string;
  nodeId: string;
  refreshKey?: number;
}

const OUTCOME_LABELS: Record<AttemptOutcome, string> = {
  passed: "Засчитано",
  partial: "Частично",
  failed: "Не засчитано",
  unscored: "Система не проверила",
};

const METHOD_LABELS: Record<GradeMethod, string> = {
  exact_match: "точное совпадение",
  key_terms: "по ключевым терминам",
  sql: "SQL-проверка",
  semantic: "семантическая проверка",
  ai_judge: "ИИ-судья",
  self_assessment: "самооценка",
};

function attemptDate(iso: string): string {
  return new Intl.DateTimeFormat("ru-RU", { day: "numeric", month: "long" }).format(new Date(iso));
}

export function AttemptHistory({ projectId, nodeId, refreshKey = 0 }: AttemptHistoryProps) {
  const headingId = `attempt-history-${useId().replace(/:/g, "")}`;
  const [attempts, setAttempts] = useState<AttemptSummaryRead[] | null>(null);
  const [details, setDetails] = useState<Record<string, AttemptDetailRead>>({});
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [localRevision, setLocalRevision] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    setAttempts(null);
    setDetails({});
    setExpandedId(null);
    setError("");
    listAttempts(projectId, nodeId, controller.signal)
      .then(setAttempts)
      .catch((caught: unknown) => {
        if (!(caught instanceof DOMException && caught.name === "AbortError")) {
          setError(caught instanceof Error ? caught.message : "История не загрузилась");
        }
      });
    return () => controller.abort();
  }, [projectId, nodeId, refreshKey, localRevision]);

  async function toggleAttempt(attemptId: string) {
    if (expandedId === attemptId) {
      setExpandedId(null);
      return;
    }
    setExpandedId(attemptId);
    if (details[attemptId]) return;
    setBusyId(attemptId);
    setError("");
    try {
      const detail = await getAttempt(projectId, attemptId);
      setDetails((current) => ({ ...current, [attemptId]: detail }));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Попытка не загрузилась");
    } finally {
      setBusyId(null);
    }
  }

  async function retryCheck(attemptId: string) {
    setBusyId(attemptId);
    setError("");
    try {
      await checkAttempt(projectId, attemptId);
      const detail = await getAttempt(projectId, attemptId);
      setDetails((current) => ({ ...current, [attemptId]: detail }));
      setLocalRevision((value) => value + 1);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Проверка не завершена");
    } finally {
      setBusyId(null);
    }
  }

  async function assessAttempt(
    attemptId: string,
    outcome: Exclude<AttemptOutcome, "unscored">,
  ) {
    setError("");
    try {
      await setAttemptSelfAssessment(projectId, attemptId, outcome);
      const detail = await getAttempt(projectId, attemptId);
      setDetails((current) => ({ ...current, [attemptId]: detail }));
      setAttempts((current) => current?.map((item) => item.id === attemptId
        ? { ...item, self_assessment: outcome }
        : item) ?? null);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Самооценка не сохранилась");
    }
  }

  return (
    <section className="workspace-attempt-history" aria-labelledby={headingId}>
      <header>
        <div>
          <History size={17} aria-hidden="true" />
          <h2 id={headingId}>Мои попытки</h2>
        </div>
        {attempts && attempts.length > 0 && <span>{attempts.length}</span>}
      </header>

      {error && <p className="inline-error" role="alert">{error}</p>}
      {attempts === null && !error && <p className="workspace-attempt-empty">Загружаем попытки…</p>}
      {attempts?.length === 0 && (
        <p className="workspace-attempt-empty">По этому вопросу ещё не было попыток</p>
      )}

      {attempts && attempts.length > 0 && (
        <div className="workspace-attempt-list">
          {attempts.map((attempt) => {
            const expanded = expandedId === attempt.id;
            const detail = details[attempt.id];
            const outcome = attempt.outcome ? OUTCOME_LABELS[attempt.outcome] : "Проверка не завершена";
            const method = attempt.method ? METHOD_LABELS[attempt.method] : null;
            return (
              <article className="workspace-attempt-row" key={attempt.id}>
                <button
                  type="button"
                  className="workspace-attempt-trigger"
                  aria-expanded={expanded}
                  aria-controls={`attempt-${attempt.id}`}
                  onClick={() => void toggleAttempt(attempt.id)}
                >
                  <span>
                    <strong>Попытка {attempt.ordinal}</strong>
                    <small>{attemptDate(attempt.created_at)} · {outcome}{method ? ` · ${method}` : ""}</small>
                  </span>
                  <ChevronDown size={16} aria-hidden="true" />
                </button>
                {expanded && (
                  <div className="workspace-attempt-detail" id={`attempt-${attempt.id}`}>
                    {busyId === attempt.id && !detail && <p>Загружаем разбор…</p>}
                    {detail?.grade ? (
                      <VerdictCard
                        compact
                        verdict={verdictFromGrade(detail.grade)}
                        answer={detail.attempt.text}
                        attemptId={detail.attempt.id}
                        onSelfAssessment={assessAttempt}
                      />
                    ) : detail ? (
                      <div className="workspace-attempt-unchecked">
                        <p>{detail.attempt.text}</p>
                        <span>Система не завершила проверку этой попытки.</span>
                        <Button
                          onClick={() => void retryCheck(attempt.id)}
                          disabled={busyId === attempt.id}
                        >
                          {busyId === attempt.id ? "Проверяем…" : "Проверить ещё раз"}
                        </Button>
                      </div>
                    ) : null}
                  </div>
                )}
              </article>
            );
          })}
        </div>
      )}
    </section>
  );
}
