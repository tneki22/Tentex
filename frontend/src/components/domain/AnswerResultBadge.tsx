/** Результат сдачи ответа: четыре значения, а не деление «хороший — плохой». */

export type AnswerResult = "good" | "partial" | "weak" | "unchecked";

export const answerResultLabel: Record<AnswerResult, string> = {
  good: "Хороший",
  partial: "Частично",
  weak: "Слабый",
  unchecked: "Без проверки",
};

/** Токен тона результата — он же используется сегментами диаграмм. */
export const answerResultToken: Record<AnswerResult, string> = {
  good: "--result-good",
  partial: "--result-partial",
  weak: "--result-weak",
  unchecked: "--result-unchecked",
};

/**
 * Приводит серверный исход проверки к одному из четырёх результатов.
 *
 * Частичный результат и ответ без проверки не сливаются с неуспешным:
 * иначе половина истории превратилась бы в «плохо».
 */
export function answerResultOf(outcome: string | null | undefined): AnswerResult {
  if (outcome === "passed") return "good";
  if (outcome === "partial") return "partial";
  if (outcome === "failed") return "weak";
  return "unchecked";
}

export function AnswerResultBadge({ result }: { result: AnswerResult }) {
  return (
    <span className={`answer-result is-${result}`}>
      <i aria-hidden="true" />
      {answerResultLabel[result]}
    </span>
  );
}
