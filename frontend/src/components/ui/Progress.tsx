import type { CSSProperties } from "react";
import { Progress as RadixProgress } from "radix-ui";

interface ProgressProps {
  /** Обработано единиц. */
  value: number;
  /** Всего единиц. */
  max: number;
  label: string;
  /** Тонкая полоса в 2px — для карточки проекта, обычная 6px — для строки задачи. */
  size?: "thin" | "base";
  className?: string;
}

/**
 * Полоса прогресса РАБОТЫ: разбор файла, проход по материалу, копирование.
 *
 * Только для процессов с известным концом. Метрику покрытия полосой рисовать
 * нельзя: полоса к 100% читается как «надо дойти до конца», а покрытие материала
 * ниже 100% — результат работы, а не дефект (FR-D17).
 */
export function Progress({ value, max, label, size = "base", className = "" }: ProgressProps) {
  const percent = max > 0 ? Math.min(100, Math.round((value / max) * 100)) : 0;

  return (
    <RadixProgress.Root
      className={`progress is-${size} ${className}`.trim()}
      value={value}
      max={max}
      aria-label={label}
      style={{ "--done": `${percent}%` } as CSSProperties}
    >
      <RadixProgress.Indicator className="progress-fill" />
    </RadixProgress.Root>
  );
}
