import type { ReactNode } from "react";
import { RadioGroup } from "radix-ui";

export interface RadioCardOption<T extends string> {
  value: T;
  title: string;
  /** Что этот вариант делает. Одна строка, конкретно. */
  description: string;
  icon?: ReactNode;
  /** Причина недоступности. Задана — карточка выключена и объясняет, почему. */
  unavailableReason?: string;
  /** Дополнение под описанием: оценка стоимости, поле ввода выбранного варианта. */
  extra?: ReactNode;
}

interface RadioCardsProps<T extends string> {
  label: string;
  value: T | null;
  options: Array<RadioCardOption<T>>;
  onChange: (value: T) => void;
  /** Одна колонка нужна там, где у вариантов есть дополнения (способы программы). */
  layout?: "grid" | "rows";
  className?: string;
}

/**
 * Выбор одного из вариантов карточками: шаблон проекта, способ получения
 * программы, режим повторения. Стрелки переключают — это roving tabindex от Radix.
 *
 * Недоступный вариант не прячется, а показывает причину: «нет материалов — шаг 2»,
 * «требует внешней модели». Скрытый вариант выглядит как отсутствие функции.
 */
export function RadioCards<T extends string>({
  label,
  value,
  options,
  onChange,
  layout = "grid",
  className = "",
}: RadioCardsProps<T>) {
  return (
    <RadioGroup.Root
      className={`radio-cards is-${layout} ${className}`.trim()}
      aria-label={label}
      value={value ?? ""}
      onValueChange={(next) => onChange(next as T)}
    >
      {options.map((option) => (
        <div className="radio-card-slot" key={option.value}>
          <RadioGroup.Item
            className="radio-card"
            value={option.value}
            disabled={Boolean(option.unavailableReason)}
          >
            <span className="radio-card-mark" aria-hidden="true">
              <RadioGroup.Indicator className="radio-card-dot" />
            </span>
            <span className="radio-card-text">
              <b>
                {option.icon}
                {option.title}
              </b>
              <small>{option.unavailableReason ?? option.description}</small>
            </span>
          </RadioGroup.Item>
          {/* Дополнение вне Item: внутри радиокнопки поля ввода недоступны с клавиатуры */}
          {option.value === value && option.extra && (
            <div className="radio-card-extra">{option.extra}</div>
          )}
        </div>
      ))}
    </RadioGroup.Root>
  );
}
