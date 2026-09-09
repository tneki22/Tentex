/** Короткое пожелание по центру экрана. Никакого таймера этим не запускается (§3.7). */
import { useEffect } from "react";
import type { QueueCard } from "./model";

interface StartDayGreetingProps {
  cards: QueueCard[];
  onClose: () => void;
}

const AUTO_CLOSE_MS = 4000;

function plural(count: number, one: string, few: string, many: string) {
  const mod10 = count % 10;
  const mod100 = count % 100;
  if (mod10 === 1 && mod100 !== 11) return one;
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return few;
  return many;
}

function greeting() {
  const hour = new Date().getHours();
  if (hour < 5) return "Доброй ночи!";
  if (hour < 12) return "Доброе утро!";
  if (hour < 18) return "Добрый день!";
  return "Добрый вечер!";
}

/** Числа берутся из сегодняшнего плана; вопрос с обоими действиями остаётся одним. */
function sentence(cards: QueueCard[]) {
  if (!cards.length) return "На сегодня назначений нет. Хороший день, чтобы заглянуть вперёд.";
  const done = cards.filter((card) => card.opened).length;
  if (done === cards.length)
    return `На сегодня всё пройдено. ${cards.length} ${plural(cards.length, "вопрос", "вопроса", "вопросов")} из ${cards.length} — можно отдыхать.`;
  const tickets = cards.filter((card) => card.kind === "ticket").length;
  const study = cards.filter((card) => card.purpose === "study" || card.purpose === "both").length;
  const review = cards.filter((card) => card.purpose === "review" || card.purpose === "both").length;
  const head = tickets
    ? `Сегодня ${tickets} ${plural(tickets, "билет", "билета", "билетов")}`
    : `Сегодня ${cards.length} ${plural(cards.length, "вопрос", "вопроса", "вопросов")}`;
  // Когда назначение одно, разбивка повторяет само число и ничего не добавляет.
  if (study && !review) return `${head} на изучение.`;
  if (review && !study) return `${head} на повторение.`;
  return `${head}: ${study} изучить и ${review} повторить.`;
}

export function StartDayGreeting({ cards, onClose }: StartDayGreetingProps) {
  useEffect(() => {
    const timer = window.setTimeout(onClose, AUTO_CLOSE_MS);
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => {
      window.clearTimeout(timer);
      window.removeEventListener("keydown", onKey);
    };
  }, [onClose]);

  return (
    <div className="prep-greeting-scrim" onClick={onClose} role="presentation">
      <p className="prep-greeting" role="status">
        <strong>{greeting()}</strong>
        <span>{sentence(cards)}</span>
        <em>Удачи в подготовке!</em>
      </p>
    </div>
  );
}
