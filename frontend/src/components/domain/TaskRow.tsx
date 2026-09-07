import { Check, Pause, Play, RotateCcw, X } from "lucide-react";
import { IconButton, Progress } from "../ui";

/** Что именно считается. Названия — из словаря проекта, без синонимов.
 *  Виды ИИ (ai_*, link_answers) — из `BackgroundJobKind` бэкенда (Ш1 плана). */
export type TaskKind =
  | "parse"
  | "ocr"
  | "pass1"
  | "pass2"
  | "ai_grouping"
  | "ai_import_repair"
  | "ai_preparation"
  | "ai_cleanup"
  | "link_answers"
  | "ai_answer_sections";

export interface BackgroundTask {
  id: string;
  kind: TaskKind;
  /** Файл или проект, к которому относится работа. */
  subject: string;
  /** Чем считается: движок распознавания или внешняя модель. Пусто — не показываем. */
  detail?: string;
  /** Единица обхода: у разбора — страницы, у прохода 1 — главы. Пусто у ролей
   *  ИИ: у них нет счётчика вовсе, и «0 из 0» там означало бы ложный ноль. */
  unit: string;
  done: number;
  total: number;
  /** Оценка остатка. null — пока не считается. */
  etaMinutes: number | null;
  /** `review` — работа досчитана, но предложение ещё ждёт человека. */
  state: "queued" | "running" | "paused" | "failed" | "review";
  /** Причина падения. Показывается как есть: обтекаемое «что-то пошло не так» бесполезно. */
  error?: string;
}

const KIND_LABEL: Record<TaskKind, string> = {
  parse: "Разбор",
  ocr: "Распознавание",
  pass1: "Проход 1",
  pass2: "Проход 2",
  ai_grouping: "Разложить по разделам",
  ai_import_repair: "Исправить список вопросов",
  ai_preparation: "Прогноз подготовки",
  ai_cleanup: "Очистка текста",
  link_answers: "Автопривязка ответов",
  ai_answer_sections: "Разметка ответов моделью",
};

interface TaskRowProps {
  task: BackgroundTask;
  onPause?: (id: string) => void;
  onResume?: (id: string) => void;
  onRetry?: (id: string) => void;
  /** Отменить незавершённый разбор: строящаяся версия выбрасывается, активная цела. */
  onCancel?: (id: string) => void;
  /** Убрать готовое предложение, не открывая его. Результат остаётся на сервере,
   *  из списка ожидающих задача уходит. */
  onDismiss?: (id: string) => void;
}

/** Что написать под названием задачи.
 *
 *  Счётчик показывается только там, где он есть: постранично считает разбор, а
 *  у ролей ИИ единиц обхода нет — «0 из 0» читалось как «ничего не сделано»,
 *  хотя работа шла. Вместо выдуманного нуля — состояние словами.
 */
function metaText(task: BackgroundTask): string {
  if (task.state === "review") return "результат готов — откройте и проверьте";
  if (task.state === "queued") return "в очереди";
  const parts: string[] = [];
  if (task.detail) parts.push(task.detail);
  if (task.total > 0) parts.push(`${task.unit ? `${task.unit} ` : ""}${task.done} из ${task.total}`);
  else if (task.state === "running") parts.push("идёт");
  if (task.state === "paused") parts.push("на паузе");
  if (task.etaMinutes !== null && task.state === "running") parts.push(`≈${task.etaMinutes} мин`);
  return parts.join(" · ");
}

/**
 * Строка фоновой задачи: что считается, сколько сделано, сколько ждать, пауза.
 * Одна и та же в поповере панели, в мастере, в материалах и в библиотеке.
 *
 * Счётчик «сделано из всего» — это и есть чекпоинт: он показывает ровно то, с
 * чего работа продолжится после падения, а не абстрактный процент.
 */
export function TaskRow({ task, onPause, onResume, onRetry, onCancel, onDismiss }: TaskRowProps) {
  const failed = task.state === "failed";
  const waiting = task.state === "review";
  const label = `${KIND_LABEL[task.kind]} · ${task.subject}`;
  // Отменить можно то, что ещё не завершилось: очередь, ход и паузу.
  const cancellable = task.state === "queued" || task.state === "running" || task.state === "paused";

  return (
    <div className={`task-row ${failed ? "is-failed" : ""} ${waiting ? "is-review" : ""}`.trim()}>
      <div className="task-row-head">
        <span className="task-row-label">{label}</span>
        <span className="task-row-actions">
          {task.state === "running" && onPause && (
            <IconButton label="Приостановить" onClick={() => onPause(task.id)}>
              <Pause size={14} />
            </IconButton>
          )}
          {task.state === "paused" && onResume && (
            <IconButton label="Возобновить" onClick={() => onResume(task.id)}>
              <Play size={14} />
            </IconButton>
          )}
          {failed && onRetry && (
            <IconButton label="Повторить" onClick={() => onRetry(task.id)}>
              <RotateCcw size={14} />
            </IconButton>
          )}
          {waiting && onDismiss && (
            <IconButton label="Убрать из ожидающих" onClick={() => onDismiss(task.id)}>
              <Check size={14} />
            </IconButton>
          )}
          {cancellable && onCancel && (
            <IconButton label="Отменить разбор" onClick={() => onCancel(task.id)}>
              <X size={14} />
            </IconButton>
          )}
        </span>
      </div>

      <p className="task-row-meta">
        {failed
          ? <span className="task-row-error">{task.error ?? "задача остановилась"}</span>
          : metaText(task)}
      </p>

      {/* Полоса рисуется там, где у работы есть измеримый конец. У ролей ИИ его
          нет: одна неделимая операция вместо обхода страниц — там полоса либо
          врала бы нулём, либо всегда стояла бы полной. */}
      {(task.total > 0 || waiting) && (
        <Progress
          value={waiting ? 1 : task.done}
          max={waiting ? 1 : task.total}
          label={label}
          size="thin"
        />
      )}
    </div>
  );
}
