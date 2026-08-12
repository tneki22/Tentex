import { useId, useMemo, useState } from "react";
import { Check, CircleMinus, X } from "lucide-react";
import type {
  AttemptOutcome,
  GradeRead,
  RubricPointRead,
  VerdictPayload,
} from "../../../api/chat";
import { CostEstimate } from "../../../components/domain";
import { Button } from "../../../components/ui";

type SelfAssessment = Exclude<AttemptOutcome, "unscored">;
type BandTone = "credited" | "missed" | "wrong";

const OUTCOME_LABELS: Record<AttemptOutcome, string> = {
  passed: "Засчитано",
  partial: "Частично",
  failed: "Не засчитано",
  unscored: "Система не проверила",
};

const METHOD_LABELS: Record<NonNullable<VerdictPayload["method"]>, string> = {
  exact_match: "точное совпадение",
  key_terms: "по ключевым терминам",
  sql: "SQL-проверка",
  semantic: "семантическая проверка",
  ai_judge: "ИИ-судья",
  self_assessment: "самооценка",
};

const SELF_LABELS: Record<SelfAssessment, string> = {
  passed: "знал",
  partial: "частично",
  failed: "не знал",
};

const BAND_META: Record<BandTone, { title: string; empty: string; citation: string }> = {
  credited: { title: "Засчитано", empty: "Нет пунктов", citation: "засчитано" },
  missed: { title: "Упущено", empty: "Нет пунктов", citation: "упущено" },
  wrong: { title: "Неверно", empty: "Нет пунктов", citation: "неверно" },
};

interface VerdictCardProps {
  verdict: VerdictPayload;
  answer: string;
  attemptId: string;
  onSelfAssessment?: (attemptId: string, outcome: SelfAssessment) => Promise<void>;
  headingRef?: (node: HTMLHeadingElement | null) => void;
  compact?: boolean;
}

interface Citation {
  key: string;
  pointId: string;
  citationId: string;
  start: number;
  end: number;
  tone: Exclude<BandTone, "missed">;
  label: string;
}

function numeric(value: string | number | null): number | null {
  if (value === null) return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

export function verdictFromGrade(grade: GradeRead): VerdictPayload {
  return {
    outcome: grade.outcome,
    method: grade.method,
    credited: grade.credited_points,
    missed: grade.missed_points,
    wrong: grade.wrong_points,
    summary: grade.summary,
    usage: grade.usage,
    cached: grade.cached,
    actual_model_id: grade.actual_model_id,
    self_assessment: grade.self_assessment,
  };
}

export function VerdictCard({
  verdict,
  answer,
  attemptId,
  onSelfAssessment,
  headingRef,
  compact = false,
}: VerdictCardProps) {
  const rawId = useId().replace(/:/g, "");
  const [activePoint, setActivePoint] = useState<string | null>(null);
  const [selfBusy, setSelfBusy] = useState<SelfAssessment | null>(null);
  const bands: Array<{ tone: BandTone; points: RubricPointRead[] }> = [
    { tone: "credited", points: verdict.credited },
    { tone: "missed", points: verdict.missed },
    { tone: "wrong", points: verdict.wrong },
  ];

  const citations = useMemo(() => {
    const candidates: Citation[] = [];
    for (const { tone, points } of bands) {
      if (tone === "missed") continue;
      points.forEach((point, index) => {
        const start = point.quote_start;
        const end = point.quote_end;
        if (start === null || end === null || start < 0 || end <= start || end > answer.length) return;
        const key = `${tone}-${index}`;
        candidates.push({
          key,
          pointId: `${rawId}-point-${key}`,
          citationId: `${rawId}-quote-${key}`,
          start,
          end,
          tone,
          label: BAND_META[tone].citation,
        });
      });
    }
    candidates.sort((left, right) => left.start - right.start || left.end - right.end);
    const nonOverlapping: Citation[] = [];
    let cursor = -1;
    for (const citation of candidates) {
      if (citation.start < cursor) continue;
      nonOverlapping.push(citation);
      cursor = citation.end;
    }
    return nonOverlapping;
    // bands contain the same point arrays carried by verdict; answer/verdict changes rebuild the list.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [answer, rawId, verdict]);

  const citationByKey = new Map(citations.map((citation) => [citation.key, citation]));

  async function chooseSelfAssessment(outcome: SelfAssessment) {
    if (!onSelfAssessment || selfBusy) return;
    setSelfBusy(outcome);
    try {
      await onSelfAssessment(attemptId, outcome);
    } finally {
      setSelfBusy(null);
    }
  }

  function highlightedAnswer() {
    if (citations.length === 0) return answer;
    const chunks = [];
    let cursor = 0;
    for (const citation of citations) {
      if (citation.start > cursor) chunks.push(answer.slice(cursor, citation.start));
      chunks.push(
        <span className="chat-verdict-quote-wrap" key={citation.key}>
          <mark
            id={citation.citationId}
            className={`chat-verdict-quote is-${citation.tone} ${activePoint === citation.key ? "is-active" : ""}`}
            aria-describedby={citation.pointId}
          >
            {answer.slice(citation.start, citation.end)}
          </mark>
          <span className={`chat-verdict-quote-label is-${citation.tone}`} aria-hidden="true">
            {citation.label}
          </span>
        </span>,
      );
      cursor = citation.end;
    }
    if (cursor < answer.length) chunks.push(answer.slice(cursor));
    return chunks;
  }

  const methodLabel = verdict.method ? METHOD_LABELS[verdict.method] : "без автоматической проверки";
  const tokenCount = verdict.usage.input_tokens + verdict.usage.output_tokens;

  return (
    <article className={`chat-verdict-card is-${verdict.outcome} ${compact ? "is-compact" : ""}`}>
      <header className="chat-verdict-header">
        <div>
          <p className="chat-verdict-kicker">Разбор ответа</p>
          <h3 ref={headingRef} tabIndex={-1}>{OUTCOME_LABELS[verdict.outcome]}</h3>
        </div>
        <span className={`chat-verdict-outcome is-${verdict.outcome}`}>{OUTCOME_LABELS[verdict.outcome]}</span>
      </header>

      <p className="chat-verdict-summary">{verdict.summary}</p>
      <div className="chat-verdict-answer" aria-label="Ответ с отмеченными цитатами" aria-readonly="true">
        {highlightedAnswer()}
      </div>

      <div className="chat-verdict-bands">
        {bands.map(({ tone, points }) => (
          <section className={`chat-verdict-band is-${tone}`} key={tone} aria-labelledby={`${rawId}-${tone}`}>
            <h4 id={`${rawId}-${tone}`}>
              {tone === "credited" ? <Check size={14} /> : tone === "missed" ? <CircleMinus size={14} /> : <X size={14} />}
              {BAND_META[tone].title}
            </h4>
            {points.length === 0 ? (
              <p className="chat-verdict-empty">{BAND_META[tone].empty}</p>
            ) : (
              <ul>
                {points.map((point, index) => {
                  const key = `${tone}-${index}`;
                  const citation = citationByKey.get(key);
                  return (
                    <li key={`${point.point}-${index}`}>
                      {citation ? (
                        <button
                          type="button"
                          id={citation.pointId}
                          aria-describedby={citation.citationId}
                          onMouseEnter={() => setActivePoint(key)}
                          onMouseLeave={() => setActivePoint(null)}
                          onFocus={() => setActivePoint(key)}
                          onBlur={() => setActivePoint(null)}
                        >
                          {point.point}
                        </button>
                      ) : <span>{point.point}</span>}
                    </li>
                  );
                })}
              </ul>
            )}
          </section>
        ))}
      </div>

      {verdict.self_assessment && verdict.self_assessment !== "unscored" && (
        <p className="chat-verdict-double-result" role="status">
          Система: {methodLabel} — {OUTCOME_LABELS[verdict.outcome].toLowerCase()} · Вы: {SELF_LABELS[verdict.self_assessment]}
        </p>
      )}

      {verdict.method !== "ai_judge" && onSelfAssessment && (
        <div className="chat-verdict-self" aria-label="Самооценка ответа">
          <span>Как было на самом деле?</span>
          <div>
            {(["passed", "partial", "failed"] as const).map((outcome) => (
              <Button
                key={outcome}
                variant="secondary"
                aria-pressed={verdict.self_assessment === outcome}
                disabled={selfBusy !== null}
                onClick={() => void chooseSelfAssessment(outcome)}
              >
                {outcome === "passed" ? "Знал" : outcome === "partial" ? "Частично" : "Не знал"}
              </Button>
            ))}
          </div>
        </div>
      )}

      <p className="chat-verdict-method">Способ: {methodLabel}</p>
      <CostEstimate
        variant="actual"
        className="chat-verdict-cost"
        model={verdict.actual_model_id}
        inputTokens={verdict.usage.input_tokens}
        outputTokens={verdict.usage.output_tokens}
        costUsd={numeric(verdict.usage.actual_cost_usd)}
        costRub={numeric(verdict.usage.actual_cost_rub)}
        cached={verdict.cached}
      />
      <span className="sr-only">Всего токенов: {tokenCount}</span>
    </article>
  );
}
