import type {
  AnswerFormPayload,
  AttemptOutcome,
  ChatMessageRead,
  GradeMethod,
  GradeUsageRead,
  RubricPointRead,
  VerdictPayload,
} from "../../../api/chat";

export type ParsedPayload =
  | { kind: "none" }
  | { kind: "answer_form"; data: AnswerFormPayload }
  | { kind: "verdict"; data: VerdictPayload }
  | { kind: "unknown" };

const OUTCOMES = new Set<AttemptOutcome>(["passed", "partial", "failed", "unscored"]);
const METHODS = new Set<GradeMethod>([
  "exact_match", "key_terms", "sql", "semantic", "ai_judge", "self_assessment",
]);

function isAnswerFormPayload(value: unknown): value is AnswerFormPayload {
  const record = value as Record<string, unknown>;
  return (
    Boolean(record) &&
    typeof record.question === "string" &&
    typeof record.ordinal === "number" &&
    typeof record.submitted_at === "string" &&
    typeof record.text === "string"
  );
}

function rubricPoints(value: unknown): RubricPointRead[] | null {
  if (!Array.isArray(value)) return null;
  const points: RubricPointRead[] = [];
  for (const item of value) {
    const record = item as Record<string, unknown>;
    if (!record || typeof record.point !== "string") return null;
    points.push({
      point: record.point,
      quote: typeof record.quote === "string" ? record.quote : null,
      quote_start: typeof record.quote_start === "number" ? record.quote_start : null,
      quote_end: typeof record.quote_end === "number" ? record.quote_end : null,
    });
  }
  return points;
}

function usage(value: unknown): GradeUsageRead {
  const record = (value ?? {}) as Record<string, unknown>;
  return {
    input_tokens: Number(record.input_tokens ?? 0),
    output_tokens: Number(record.output_tokens ?? 0),
    reasoning_tokens: Number(record.reasoning_tokens ?? 0),
    provider_cached_tokens: Number(record.provider_cached_tokens ?? 0),
    actual_cost_usd: typeof record.actual_cost_usd === "string" || typeof record.actual_cost_usd === "number"
      ? record.actual_cost_usd
      : null,
    actual_cost_rub: typeof record.actual_cost_rub === "string" || typeof record.actual_cost_rub === "number"
      ? record.actual_cost_rub
      : null,
  };
}

function verdictPayload(value: unknown): VerdictPayload | null {
  const record = value as Record<string, unknown>;
  const credited = rubricPoints(record?.credited);
  const missed = rubricPoints(record?.missed);
  const wrong = rubricPoints(record?.wrong);
  if (
    !record ||
    !OUTCOMES.has(record.outcome as AttemptOutcome) ||
    (record.method !== null && !METHODS.has(record.method as GradeMethod)) ||
    typeof record.summary !== "string" ||
    !credited || !missed || !wrong
  ) return null;
  const selfAssessment = OUTCOMES.has(record.self_assessment as AttemptOutcome)
    ? record.self_assessment as AttemptOutcome
    : null;
  return {
    outcome: record.outcome as AttemptOutcome,
    method: record.method as GradeMethod | null,
    credited,
    missed,
    wrong,
    summary: record.summary,
    usage: usage(record.usage),
    cached: Boolean(record.cached),
    actual_model_id: typeof record.actual_model_id === "string" ? record.actual_model_id : null,
    self_assessment: selfAssessment,
  };
}

/** Разбор по дискриминанту `payload_kind`. Вердикт, задание и интерактив — итерация 1b/2. */
export function parsePayload(message: ChatMessageRead): ParsedPayload {
  if (message.payload_kind === "answer_form" && isAnswerFormPayload(message.payload)) {
    return { kind: "answer_form", data: message.payload };
  }
  if (message.payload_kind === "verdict") {
    const verdict = verdictPayload(message.payload);
    return verdict ? { kind: "verdict", data: verdict } : { kind: "unknown" };
  }
  if (message.payload_kind === "none") return { kind: "none" };
  return { kind: "unknown" };
}
