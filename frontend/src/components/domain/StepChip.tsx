import { AlertTriangle, ArrowRight } from "lucide-react";
import { Link } from "react-router";

/** Тон приходит с сервера вместе с текстом: интерфейс каскад не пересчитывает. */
export type StepTone = "accent" | "danger" | "quiet";

export interface NextStep {
  text: string;
  /** Путь целевого экрана. Пусто — шага нет, показывать нечего. */
  to?: string;
  tone: StepTone;
}

interface StepChipProps {
  step: NextStep;
  /** Крупный вид для карточки-героя единственного проекта. */
  size?: "base" | "large";
}

/**
 * Следующий шаг проекта. Одна формулировка на все поверхности: полоса действий,
 * карточка проекта, пустое состояние экрана, кнопка в боте.
 *
 * Тон «quiet» — это «на сегодня всё»: не кнопка и не ссылка. Система не
 * выдумывает занятие, которого нет, и не упрекает за сделанную работу.
 */
export function StepChip({ step, size = "base" }: StepChipProps) {
  const className = `step-chip is-${step.tone} is-${size}`;

  if (step.tone === "quiet" || !step.to) {
    return <span className={className}>{step.text}</span>;
  }

  return (
    <Link className={className} to={step.to}>
      {step.tone === "danger" ? (
        <AlertTriangle size={15} aria-hidden="true" />
      ) : (
        <ArrowRight size={15} aria-hidden="true" />
      )}
      {step.text}
    </Link>
  );
}
