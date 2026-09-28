import { useState } from "react";
import { CheckCircle2, CircleDashed, Clock3, Eye, EyeOff, Lightbulb, RotateCcw, XCircle } from "lucide-react";
import {
  STUDY_TASK_FORM_LABELS,
  type StudyTaskAttemptRead,
  type StudyTaskDifficulty,
  type StudyTaskForm,
  type StudyTaskKey,
  type StudyTaskPayload,
} from "../../../../api/lessons";
import { Button } from "../../../ui";
import { MachineMark } from "../../MachineMark";
import { LessonMarkdown } from "../LessonMarkdown";
import { answerReady, initialAnswer, TaskInputs, type TaskDraftAnswer } from "./TaskInputs";

/** Общее у задания урока и задания в предложении модели. */
export interface StudyTaskView {
  form: StudyTaskForm;
  prompt_md: string;
  payload: StudyTaskPayload;
  answer_key: StudyTaskKey;
  reference_md: string | null;
  explanation_md: string | null;
  hint_md: string | null;
  difficulty: StudyTaskDifficulty;
  basis: string | null;
  sources?: Array<{ source_name: string; page_from: number; page_to: number }>;
  attempts?: number;
  last_attempt?: StudyTaskAttemptRead | null;
}

interface TaskCardProps {
  task: StudyTaskView;
  /** Подпись над заданием: «Задание», «Задание 2 из 5». */
  label?: string;
  /** Отправить ответ; без неё карточка — предпросмотр с открытым ключом. */
  onSubmit?(answer: TaskDraftAnswer): Promise<StudyTaskAttemptRead>;
  /** Проверить открытый ответ, сохранённый без моделей. */
  onCheckPending?(attemptId: string): Promise<StudyTaskAttemptRead>;
  /** Итог попытки — для сводки прохода по заданиям. */
  onResult?(attempt: StudyTaskAttemptRead): void;
}

const DIFFICULTY: Record<StudyTaskDifficulty, string> = {
  remember: "вспомнить",
  understand: "понять",
  apply: "применить",
};

function pages(from: number, to: number): string {
  return from === to ? `с. ${from}` : `с. ${from}–${to}`;
}

function Outcome({ attempt }: { attempt: StudyTaskAttemptRead }) {
  if (attempt.outcome === null) {
    return <p className="lesson-task-outcome is-pending"><Clock3 size={15} aria-hidden="true" />{attempt.pending_reason}</p>;
  }
  const passed = attempt.outcome === "passed";
  const partial = attempt.outcome === "partial";
  const Icon = passed ? CheckCircle2 : partial ? CircleDashed : XCircle;
  const title = passed ? "Верно" : partial ? "Частично" : "Неверно";
  const summary = attempt.summary && !["Верно.", "Неверно."].includes(attempt.summary) ? attempt.summary : "";
  return (
    <p className={`lesson-task-outcome is-${attempt.outcome}`}>
      <Icon size={15} aria-hidden="true" /><strong>{title}.</strong>{summary && <span>{summary}</span>}
    </p>
  );
}

function JudgePoints({ attempt }: { attempt: StudyTaskAttemptRead }) {
  const groups: Array<[string, string[], string]> = [
    ["Засчитано", attempt.credited, "is-right"],
    ["Не хватает", attempt.missed, "is-missed"],
    ["Неверно", attempt.wrong, "is-wrong"],
  ];
  const shown = groups.filter(([, items]) => items.length > 0);
  if (!shown.length) return null;
  return (
    <div className="lesson-task-points">
      {shown.map(([title, items, tone]) => (
        <div key={title} className={tone}>
          <strong>{title}</strong>
          <ul>{items.map((item) => <li key={item}>{item}</li>)}</ul>
        </div>
      ))}
    </div>
  );
}

/**
 * Задание урока: условие, ввод по форме, «Проверить», подсказка и разбор.
 * Шесть форм проверяет ключ сразу; открытый ответ — модель, без неё ответ
 * сохраняется и проверяется позже. После проверки видно, что верно по пунктам,
 * почему ответ такой и на какую страницу учебника он опирается.
 */
export function TaskCard({ task, label = "Задание", onSubmit, onCheckPending, onResult }: TaskCardProps) {
  const preview = !onSubmit;
  const [answer, setAnswer] = useState<TaskDraftAnswer>(() => initialAnswer(task.form, task.payload));
  const [result, setResult] = useState<StudyTaskAttemptRead | null>(null);
  const [showKey, setShowKey] = useState(preview);
  const [showHint, setShowHint] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const attempts = (task.attempts ?? 0) + (result ? 1 : 0);
  const graded = Boolean(result && result.outcome !== null);
  const last = result ?? task.last_attempt ?? null;

  async function run(action: () => Promise<StudyTaskAttemptRead>) {
    setBusy(true);
    setError("");
    try {
      const attempt = await action();
      setResult(attempt);
      if (attempt.outcome !== null) onResult?.(attempt);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Ответ не проверился");
    } finally {
      setBusy(false);
    }
  }

  function retry() {
    setResult(null);
    setShowKey(false);
    setAnswer(initialAnswer(task.form, task.payload));
  }

  const sources = task.sources ?? [];
  const modelOnly = task.basis === "model_only";
  return (
    <section className={`lesson-task${result ? ` is-checked is-${result.outcome ?? "pending"}` : ""}`} aria-label={label}>
      <header className="lesson-task-head">
        <span className="lesson-task-label">{label}</span>
        <span className="lesson-task-meta">{STUDY_TASK_FORM_LABELS[task.form]} · {DIFFICULTY[task.difficulty]}</span>
        {!preview && !result && last?.outcome && (
          <span className={`lesson-task-last is-${last.outcome}`}>
            {last.outcome === "passed" ? "решено" : "была ошибка"} · попыток {attempts}
          </span>
        )}
        {modelOnly && <MachineMark origin="ИИ · знания модели — не подтверждено материалами" />}
      </header>

      <TaskInputs
        form={task.form}
        prompt={task.prompt_md}
        payload={task.payload}
        answerKey={task.answer_key}
        answer={answer}
        onChange={setAnswer}
        result={result}
        showKey={showKey}
        disabled={preview || busy}
      />

      {showHint && task.hint_md && !result && (
        <p className="lesson-task-hint"><Lightbulb size={14} aria-hidden="true" />{task.hint_md}</p>
      )}

      {result && <Outcome attempt={result} />}
      {result && task.form === "open_answer" && <JudgePoints attempt={result} />}
      {error && <p className="inline-error" role="alert">{error}</p>}

      {(graded || showKey) && (
        <div className="lesson-task-explain">
          {showKey && task.form === "open_answer" && task.reference_md && (
            <>
              <strong>Образец ответа</strong>
              <LessonMarkdown className="lesson-task-reference" text={task.reference_md} />
              {(task.answer_key.points ?? []).length > 0 && (
                <ul className="lesson-task-key-points">{task.answer_key.points?.map((item) => <li key={item}>{item}</li>)}</ul>
              )}
            </>
          )}
          {task.explanation_md && <LessonMarkdown className="lesson-task-explanation" text={task.explanation_md} />}
          {sources.length > 0 && (
            <p className="lesson-task-source">Опора: {sources.map((item) => `${item.source_name}, ${pages(item.page_from, item.page_to)}`).join("; ")}</p>
          )}
        </div>
      )}

      {!preview && (
        <div className="lesson-task-actions">
          {!result && (
            <Button disabled={busy || !answerReady(task.form, answer)} onClick={() => void run(() => onSubmit!(answer))}>
              {busy ? "Проверяем…" : "Проверить"}
            </Button>
          )}
          {!result && task.hint_md && (
            <Button variant="ghost" onClick={() => setShowHint((value) => !value)}><Lightbulb size={14} />{showHint ? "Скрыть подсказку" : "Подсказка"}</Button>
          )}
          {result?.outcome === null && onCheckPending && (
            <Button disabled={busy} onClick={() => void run(() => onCheckPending(result.id))}>{busy ? "Проверяем…" : "Проверить сейчас"}</Button>
          )}
          {result && graded && (
            <>
              {result.outcome !== "passed" && <Button variant="secondary" onClick={retry}><RotateCcw size={14} />Ещё раз</Button>}
              <Button variant="ghost" onClick={() => setShowKey((value) => !value)}>
                {showKey ? <><EyeOff size={14} />Скрыть ответ</> : <><Eye size={14} />Показать ответ</>}
              </Button>
            </>
          )}
        </div>
      )}
    </section>
  );
}
