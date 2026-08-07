import { Coins } from "lucide-react";

interface CostEstimateProps {
  /** Число вызовов модели. Точное, а не диапазон: цикл фиксированный (§25.2). */
  calls: number;
  /** Стоимость в долларах. */
  cost: number;
  minutes: number;
  /** Дата актуальности цен — без неё сумма не значит ничего (FR-I10). */
  pricesFrom: string;
  /** Единица обхода: «блоков», «глав». Показывается, если известна. */
  units?: string;
}

/**
 * Оценка до запуска платной операции: сколько вызовов, сколько денег, сколько
 * ждать. Показывается ПЕРЕД подтверждением — проход 1, проход 2, генерация
 * активностей, свободный вопрос агентом.
 *
 * Существует потому, что стоимость у нас предсказуема по построению: число
 * единиц ÷ размер батча × цена вызова. Это аргумент в пользу фиксированного
 * прохода против агента, и на экране он должен быть виден числом.
 */
export function CostEstimate({ calls, cost, minutes, pricesFrom, units }: CostEstimateProps) {
  return (
    <p className="cost-estimate">
      <Coins size={14} aria-hidden="true" />
      <span>
        {units ? `${units} · ` : ""}
        {calls} {plural(calls, "вызов", "вызова", "вызовов")} · ≈${cost.toFixed(2)} · ~{minutes} мин
      </span>
      <small>цены от {pricesFrom}</small>
    </p>
  );
}

function plural(n: number, one: string, few: string, many: string): string {
  const mod100 = n % 100;
  const mod10 = n % 10;
  if (mod100 >= 11 && mod100 <= 14) return many;
  if (mod10 === 1) return one;
  if (mod10 >= 2 && mod10 <= 4) return few;
  return many;
}
