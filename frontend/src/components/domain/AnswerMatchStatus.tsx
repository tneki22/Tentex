import {
  AlertTriangle,
  CheckCircle2,
  LoaderCircle,
  RotateCcw,
  X,
  XCircle,
} from "lucide-react";
import type { AnswersLinkProgress, AnswersLinkRead } from "../../api/bindings";
import type { AnswerAutoMatchState } from "../../hooks/useAnswerAutoMatch";
import { Button, IconButton, Progress } from "../ui";

interface AnswerMatchStatusProps {
  state: AnswerAutoMatchState;
  onRetry: () => void;
  onDismiss: () => void;
  compact?: boolean;
}

function plural(count: number, one: string, few: string, many: string): string {
  const mod10 = count % 10;
  const mod100 = count % 100;
  if (mod10 === 1 && mod100 !== 11) return one;
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return few;
  return many;
}

function progressText(progress: AnswersLinkProgress | null): string {
  if (!progress || progress.phase === "preparing") return "Готовим файл и вопросы программы.";
  if (progress.phase === "matching") {
    return `Нашли ${progress.phase_completed} ${plural(progress.phase_completed, "раздел", "раздела", "разделов")} для ${progress.phase_total} ${plural(progress.phase_total, "вопроса", "вопросов", "вопросов")}.`;
  }
  if (progress.phase === "binding") {
    return `Связываем страницы с вопросами: ${progress.phase_completed} из ${progress.phase_total}.`;
  }
  if (progress.phase === "importing") {
    return `Обновляем эталоны: ${progress.phase_completed} из ${progress.phase_total}.`;
  }
  return "Проверяем, что эталоны доступны во всех зонах проекта.";
}

function ResultMetrics({ result }: { result: AnswersLinkRead }) {
  const metrics = [
    ["Создано", result.created_answers],
    ["Обновлено", result.updated_answers],
    ["Восстановлено", result.restored_answers],
    ["Сохранено существующих", result.preserved_answers],
    ["Без изменений", result.unchanged_answers],
  ].filter(([, value]) => Number(value) > 0) as [string, number][];
  if (metrics.length === 0) return <p className="answer-match-unchanged">Изменений не потребовалось.</p>;
  return (
    <div className="answer-match-metrics" aria-label="Изменения эталонов">
      {metrics.map(([label, value]) => (
        <span key={label}><strong>{value}</strong><small>{label}</small></span>
      ))}
    </div>
  );
}

function attentionText(result: AnswersLinkRead): string {
  const issues: string[] = [];
  if (result.unavailable_node_ids.length) {
    const count = result.unavailable_node_ids.length;
    issues.push(`${count} ${plural(count, "эталон недоступен", "эталона недоступны", "эталонов недоступны")}`);
  }
  if (result.suggestions.length) {
    const count = result.suggestions.length;
    issues.push(`${count} ${plural(count, "заголовок нужно выбрать", "заголовка нужно выбрать", "заголовков нужно выбрать")} вручную`);
  }
  if (result.missing_node_ids.length) {
    const count = result.missing_node_ids.length;
    issues.push(`${count} ${plural(count, "вопрос не сопоставлен", "вопроса не сопоставлены", "вопросов не сопоставлены")}`);
  }
  return issues.join(" · ") || "Проверьте результат сопоставления.";
}

export function AnswerMatchStatus({
  state,
  onRetry,
  onDismiss,
  compact = false,
}: AnswerMatchStatusProps) {
  if (state.status === "idle") return null;
  const className = `answer-match-status is-${state.status} ${compact ? "is-compact" : ""}`.trim();

  if (state.status === "running") {
    const determinate = state.progress && state.progress.total > 0;
    return (
      <section className={className} role="status" aria-live="polite" aria-busy="true">
        <div className="answer-match-status-head">
          <LoaderCircle className="answer-match-spinner" size={19} />
          <div><strong>Сопоставляем ответы</strong><p>{progressText(state.progress)}</p></div>
          {determinate && <b>{Math.round((state.progress!.completed / state.progress!.total) * 100)}%</b>}
        </div>
        {determinate && (
          <Progress
            value={state.progress!.completed}
            max={state.progress!.total}
            label="Ход сопоставления ответов"
            size="thin"
          />
        )}
      </section>
    );
  }

  if (state.status === "error") {
    return (
      <section className={className} role="alert">
        <div className="answer-match-status-head">
          <XCircle size={19} />
          <div><strong>Не удалось сопоставить ответы</strong><p>{state.message}</p></div>
          <IconButton label="Скрыть сводку" onClick={onDismiss}><X size={16} /></IconButton>
        </div>
        <Button variant="secondary" onClick={onRetry}><RotateCcw size={14} />Повторить</Button>
      </section>
    );
  }

  const result = state.result;
  const complete = state.status === "complete";
  return (
    <section className={className} role="status" aria-live="polite">
      <div className="answer-match-status-head">
        {complete ? <CheckCircle2 size={19} /> : <AlertTriangle size={19} />}
        <div>
          <strong>
            {complete
              ? `Готово: эталоны доступны у ${result.available_node_ids.length} из ${result.expected_questions} вопросов`
              : `Требуется проверка: сопоставлено ${result.matched_node_ids.length}, эталоны доступны у ${result.available_node_ids.length} из ${result.expected_questions}`}
          </strong>
          {!complete && <p>{attentionText(result)}</p>}
        </div>
        <IconButton label="Скрыть сводку" onClick={onDismiss}><X size={16} /></IconButton>
      </div>
      <ResultMetrics result={result} />
      <Button variant="ghost" onClick={onRetry}><RotateCcw size={14} />Сопоставить снова</Button>
    </section>
  );
}
