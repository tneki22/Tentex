import { ArrowDown, ArrowUp, Check } from "lucide-react";
import { RadioGroup } from "radix-ui";
import type { StudyTaskAnswer, StudyTaskAttemptRead, StudyTaskForm, StudyTaskKey, StudyTaskPayload } from "../../../../api/lessons";
import { Checkbox, Select } from "../../../ui";
import { LessonMarkdown } from "../LessonMarkdown";

/** Ответ в работе: поля формы и текст открытого ответа. */
export type TaskDraftAnswer = StudyTaskAnswer & { text?: string };

export interface TaskInputProps {
  form: StudyTaskForm;
  prompt: string;
  payload: StudyTaskPayload;
  answerKey: StudyTaskKey;
  answer: TaskDraftAnswer;
  onChange(next: TaskDraftAnswer): void;
  /** Итог проверки: пункты подсвечиваются верно / неверно, ввод закрыт. */
  result: StudyTaskAttemptRead | null;
  /** Показать ключ: верные варианты, допустимые ответы, верный порядок. */
  showKey: boolean;
  disabled?: boolean;
}

export function initialAnswer(form: StudyTaskForm, payload: StudyTaskPayload): TaskDraftAnswer {
  switch (form) {
    case "multiple_choice": return { choices: [] };
    case "fill_blanks": return { blanks: Array.from({ length: payload.blanks ?? 0 }, () => "") };
    case "numeric": return { value: "" };
    case "ordering": return { order: (payload.items ?? []).map((_, index) => index) };
    case "matching": return { pairs: (payload.left ?? []).map(() => null) };
    case "open_answer": return { text: "" };
    default: return {};
  }
}

/** Можно проверять: есть хоть какой-то ответ по форме. */
export function answerReady(form: StudyTaskForm, answer: TaskDraftAnswer): boolean {
  switch (form) {
    case "single_choice": return answer.choice !== undefined;
    case "multiple_choice": return (answer.choices ?? []).length > 0;
    case "fill_blanks": return (answer.blanks ?? []).some((item) => item.trim() !== "");
    case "numeric": return (answer.value ?? "").trim() !== "";
    case "ordering": return true;
    case "matching": return (answer.pairs ?? []).some((item) => item !== null);
    case "open_answer": return (answer.text ?? "").trim() !== "";
  }
}

function mark(right: boolean | undefined): string {
  if (right === undefined) return "";
  return right ? " is-right" : " is-wrong";
}

function formatNumber(value: number): string {
  return String(value).replace(".", ",");
}

/** Условие и ввод ответа по форме задания; после проверки — разбор по пунктам. */
export function TaskInputs(props: TaskInputProps) {
  const { form, prompt } = props;
  if (form === "fill_blanks") return <BlanksInput {...props} />;
  return (
    <>
      <LessonMarkdown className="lesson-task-prompt" text={prompt} />
      {form === "single_choice" && <SingleChoice {...props} />}
      {form === "multiple_choice" && <MultipleChoice {...props} />}
      {form === "numeric" && <NumericInput {...props} />}
      {form === "ordering" && <OrderingInput {...props} />}
      {form === "matching" && <MatchingInput {...props} />}
      {form === "open_answer" && <OpenAnswer {...props} />}
    </>
  );
}

function SingleChoice({ payload, answerKey, answer, onChange, result, showKey, disabled }: TaskInputProps) {
  const correct = new Set(answerKey.correct ?? []);
  const locked = Boolean(result) || disabled;
  return (
    <RadioGroup.Root
      className="lesson-task-options"
      value={answer.choice === undefined ? "" : String(answer.choice)}
      onValueChange={(value) => onChange({ choice: Number(value) })}
      disabled={locked}
      aria-label="Варианты ответа"
    >
      {(payload.options ?? []).map((option, index) => {
        const chosen = answer.choice === index;
        const state = result && chosen ? mark(correct.has(index)) : "";
        const key = showKey && correct.has(index) ? " is-key" : "";
        return (
          <label key={index} className={`lesson-task-option${chosen ? " is-chosen" : ""}${state}${key}`}>
            <RadioGroup.Item className="lesson-task-radio" value={String(index)}>
              <RadioGroup.Indicator className="lesson-task-radio-dot" />
            </RadioGroup.Item>
            <span>{option}</span>
          </label>
        );
      })}
    </RadioGroup.Root>
  );
}

function MultipleChoice({ payload, answerKey, answer, onChange, result, showKey, disabled }: TaskInputProps) {
  const correct = new Set(answerKey.correct ?? []);
  const chosen = new Set(answer.choices ?? []);
  return (
    <div className="lesson-task-options" role="group" aria-label="Варианты ответа — отметьте все верные">
      {(payload.options ?? []).map((option, index) => {
        const isChosen = chosen.has(index);
        const state = result && isChosen ? mark(correct.has(index)) : "";
        const missed = showKey && !isChosen && correct.has(index) ? " is-key" : "";
        return (
          <div key={index} className={`lesson-task-option${isChosen ? " is-chosen" : ""}${state}${missed}`}>
            <Checkbox
              checked={isChosen}
              disabled={Boolean(result) || disabled}
              label={option}
              onCheckedChange={(checked) => {
                const next = new Set(chosen);
                if (checked) next.add(index);
                else next.delete(index);
                onChange({ choices: [...next].sort((left, right) => left - right) });
              }}
            />
          </div>
        );
      })}
    </div>
  );
}

const MARKER = /\{\{(\d+)\}\}/g;
// Markdown в условии с пропусками — показать текстом и поля ниже; иначе поля встают в текст.
const RICH_MARKUP = /[*_`#$|>[\]\n]/;

function BlanksInput({ prompt, answerKey, answer, onChange, result, showKey, disabled }: TaskInputProps) {
  const blanks = answer.blanks ?? [];
  const accepted = answerKey.answers ?? [];
  const field = (index: number) => (
    <span key={`blank-${index}`} className="lesson-task-blank">
      <input
        aria-label={`Пропуск ${index + 1}`}
        className={`lesson-task-blank-input${result ? mark(result.items[index]) : ""}`}
        value={blanks[index] ?? ""}
        disabled={Boolean(result) || disabled}
        size={Math.max(8, (blanks[index] ?? "").length + 2)}
        onChange={(event) => onChange({ blanks: blanks.map((item, position) => position === index ? event.target.value : item) })}
      />
      {showKey && <small className="lesson-task-accepted">{accepted[index]?.join(" / ")}</small>}
    </span>
  );

  if (!RICH_MARKUP.test(prompt.replace(MARKER, ""))) {
    const parts = prompt.split(MARKER);
    return (
      <p className="lesson-task-prompt lesson-task-inline">
        {parts.map((part, index) => (index % 2 === 1 ? field(Number(part) - 1) : <span key={index}>{part}</span>))}
      </p>
    );
  }
  return (
    <>
      <LessonMarkdown className="lesson-task-prompt" text={prompt.replace(MARKER, (_, number: string) => `**(${number})**`)} />
      <div className="lesson-task-blank-list">
        {blanks.map((_, index) => (
          <label key={index} className="lesson-task-blank-row"><span>({index + 1})</span>{field(index)}</label>
        ))}
      </div>
    </>
  );
}

function NumericInput({ payload, answerKey, answer, onChange, result, showKey, disabled }: TaskInputProps) {
  const tolerance = answerKey.tolerance ?? 0;
  const spread = tolerance > 0 ? (answerKey.relative ? ` ± ${formatNumber(tolerance * 100)}%` : ` ± ${formatNumber(tolerance)}`) : "";
  return (
    <div className="lesson-task-numeric">
      <input
        aria-label="Числовой ответ"
        inputMode="decimal"
        className={`lesson-task-number${result ? mark(result.items[0]) : ""}`}
        value={answer.value ?? ""}
        disabled={Boolean(result) || disabled}
        onChange={(event) => onChange({ value: event.target.value })}
        placeholder="Число"
      />
      {payload.unit && <span className="lesson-task-unit">{payload.unit}</span>}
      {showKey && answerKey.value !== undefined && (
        <small className="lesson-task-accepted">Ответ: {formatNumber(answerKey.value)}{spread}{payload.unit ? ` ${payload.unit}` : ""}</small>
      )}
    </div>
  );
}

function OrderingInput({ payload, answerKey, answer, onChange, result, showKey, disabled }: TaskInputProps) {
  const items = payload.items ?? [];
  const order = answer.order ?? items.map((_, index) => index);
  const locked = Boolean(result) || disabled;
  const move = (position: number, shift: number) => {
    const next = [...order];
    const target = position + shift;
    [next[position], next[target]] = [next[target], next[position]];
    onChange({ order: next });
  };
  return (
    <>
      <ol className="lesson-task-order" aria-label="Шаги — расставьте по порядку">
        {order.map((itemIndex, position) => (
          <li key={itemIndex} className={`lesson-task-order-item${result ? mark(result.items[position]) : ""}`}>
            <span className="lesson-task-order-number">{position + 1}</span>
            <span className="lesson-task-order-text">{items[itemIndex]}</span>
            {!locked && (
              <span className="lesson-task-order-tools">
                <button type="button" aria-label={`Поднять шаг «${items[itemIndex]}»`} disabled={position === 0} onClick={() => move(position, -1)}><ArrowUp size={14} /></button>
                <button type="button" aria-label={`Опустить шаг «${items[itemIndex]}»`} disabled={position === order.length - 1} onClick={() => move(position, 1)}><ArrowDown size={14} /></button>
              </span>
            )}
          </li>
        ))}
      </ol>
      {showKey && (
        <ol className="lesson-task-key-list" aria-label="Верный порядок">
          {(answerKey.order ?? []).map((itemIndex) => <li key={itemIndex}>{items[itemIndex]}</li>)}
        </ol>
      )}
    </>
  );
}

function MatchingInput({ payload, answerKey, answer, onChange, result, showKey, disabled }: TaskInputProps) {
  const left = payload.left ?? [];
  const right = payload.right ?? [];
  const pairs = answer.pairs ?? left.map(() => null);
  const options = right.map((item, index) => ({ value: String(index), label: item }));
  return (
    <div className="lesson-task-matching">
      {left.map((item, index) => (
        <div key={index} className={`lesson-task-match${result ? mark(result.items[index]) : ""}`}>
          <span className="lesson-task-match-left">{item}</span>
          <Select
            ariaLabel={`Пара для «${item}»`}
            value={pairs[index] === null || pairs[index] === undefined ? null : String(pairs[index])}
            options={options}
            placeholder="Выберите пару"
            disabled={Boolean(result) || disabled}
            onValueChange={(value) => onChange({ pairs: pairs.map((current, position) => position === index ? (value === null ? null : Number(value)) : current) })}
          />
          {showKey && answerKey.match && (
            <small className="lesson-task-accepted"><Check size={12} aria-hidden="true" /> {right[answerKey.match[index]]}</small>
          )}
        </div>
      ))}
    </div>
  );
}

function OpenAnswer({ answer, onChange, result, disabled }: TaskInputProps) {
  return (
    <textarea
      aria-label="Ваш ответ"
      className="lesson-task-open"
      rows={4}
      value={answer.text ?? ""}
      disabled={Boolean(result && result.outcome !== null) || disabled}
      placeholder="Объясните своими словами"
      onChange={(event) => onChange({ text: event.target.value })}
    />
  );
}
