import { Pause, Play, RotateCcw, X } from "lucide-react";
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
  | "link_answers";

export interface BackgroundTask {
  id: string;
  kind: TaskKind;
  /** Файл или проект, к которому относится работа. */
  subject: string;
  /** Единица обхода и счётчик: у разбора — страницы, у прохода 1 — главы. */
  unit: string;
  done: number;
  total: number;
  /** Оценка остатка. null — пока не считается. */
  etaMinutes: number | null;
  state: "queued" | "running" | "paused" | "failed";
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
};

interface TaskRowProps {
  task: BackgroundTask;
  onPause?: (id: string) => void;
  onResume?: (id: string) => void;
  onRetry?: (id: string) => void;
  /** Отменить незавершённый разбор: строящаяся версия выбрасывается, активная цела. */
  onCancel?: (id: string) => void;
}

/**
 * Строка фоновой задачи: что считается, сколько сделано, сколько ждать, пауза.
 * Одна и та же в поповере панели, в мастере, в материалах и в библиотеке.
 *
 * Счётчик «сделано из всего» — это и есть чекпоинт: он показывает ровно то, с
 * чего работа продолжится после падения, а не абстрактный процент.
 */
export function TaskRow({ task, onPause, onResume, onRetry, onCancel }: TaskRowProps) {
  const failed = task.state === "failed";
  const label = `${KIND_LABEL[task.kind]} · ${task.subject}`;
  // Отменить можно то, что ещё не завершилось: очередь, ход и паузу.
  const cancellable = task.state === "queued" || task.state === "running" || task.state === "paused";

  return (
    <div className={`task-row ${failed ? "is-failed" : ""}`.trim()}>
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
          {cancellable && onCancel && (
            <IconButton label="Отменить разбор" onClick={() => onCancel(task.id)}>
              <X size={14} />
            </IconButton>
          )}
        </span>
      </div>

      <p className="task-row-meta">
        {failed ? (
          <span className="task-row-error">{task.error ?? "задача остановилась"}</span>
        ) : (
          <>
            {task.unit} {task.done} из {task.total}
            {task.state === "paused" && " · на паузе"}
            {task.state === "queued" && " · в очереди"}
            {task.etaMinutes !== null && task.state === "running" && ` · ≈${task.etaMinutes} мин`}
          </>
        )}
      </p>

      <Progress value={task.done} max={task.total} label={label} size="thin" />
    </div>
  );
}
