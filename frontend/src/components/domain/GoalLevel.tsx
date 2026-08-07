import { RadioCards } from "../ui";

/** Четыре уровня цели из FR-G24. Порядок — порядок возрастания требований. */
export type GoalLevelValue = "awareness" | "understanding" | "application" | "mastery";

export const GOAL_LEVELS: Array<{ value: GoalLevelValue; label: string; effect: string }> = [
  {
    value: "awareness",
    label: "знать о существовании",
    effect: "одна карточка, в плане почти не занимает места",
  },
  { value: "understanding", label: "понимать", effect: "две успешные попытки до «отработан»" },
  {
    value: "application",
    label: "уметь применять",
    effect: "темы войдут в повторения и потребуют эталонного ответа",
  },
  {
    value: "mastery",
    label: "владеть свободно",
    effect: "четыре попытки, из них минимум одна — свободный ответ",
  },
];

interface GoalLevelPickerProps {
  value: GoalLevelValue;
  onChange: (value: GoalLevelValue) => void;
  /** Название раздела: уровень ставится пачкой по разделу, а не по одной теме. */
  label: string;
}

/**
 * Выбор уровня цели. Уровень определяет три вещи разом: какие активности
 * предлагаются, сколько нужно до статуса «отработан» и сколько времени тема
 * получит в плане. Поэтому рядом с выбором всегда написано, что он меняет —
 * иначе четыре слова выглядят одинаково важными.
 */
export function GoalLevelPicker({ value, onChange, label }: GoalLevelPickerProps) {
  return (
    <RadioCards
      label={`Уровень цели: ${label}`}
      value={value}
      onChange={onChange}
      className="goal-level"
      layout="rows"
      options={GOAL_LEVELS.map((level) => ({
        value: level.value,
        title: level.label,
        description: level.effect,
      }))}
    />
  );
}

export function goalLevelEffect(value: GoalLevelValue): string {
  return GOAL_LEVELS.find((level) => level.value === value)?.effect ?? "";
}
