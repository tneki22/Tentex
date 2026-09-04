/** Календарь выбора даты управляет только представлением, не данными плана. */
import { useState } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { Button } from "../../components/ui";
import { addDays } from "./dates";
export function MiniCalendar({
  value,
  today,
  onChange,
}: {
  value: string;
  today: string;
  onChange: (date: string) => void;
}) {
  const [month, setMonth] = useState(value.slice(0, 7));
  const first = `${month}-01`;
  const offset = (new Date(`${first}T12:00:00Z`).getUTCDay() + 6) % 7;
  function move(by: number) {
    const date = new Date(`${first}T12:00:00Z`);
    date.setUTCMonth(date.getUTCMonth() + by);
    setMonth(date.toISOString().slice(0, 7));
  }
  return (
    <section className="prep-mini" aria-label="Выбрать дату">
      <header>
        <Button
          variant="ghost"
          aria-label="Предыдущий месяц"
          onClick={() => move(-1)}
        >
          <ChevronLeft size={15} />
        </Button>
        <strong>
          {new Date(`${first}T12:00:00Z`).toLocaleDateString("ru-RU", {
            month: "long",
            year: "numeric",
          })}
        </strong>
        <Button
          variant="ghost"
          aria-label="Следующий месяц"
          onClick={() => move(1)}
        >
          <ChevronRight size={15} />
        </Button>
      </header>
      <div className="prep-month-grid">
        {["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"].map((day) => (
          <small key={day}>{day}</small>
        ))}
        {Array.from({ length: 42 }, (_, i) => addDays(first, i - offset)).map(
          (day) => (
            <button
              key={day}
              className={`${day === value ? "is-selected" : ""} ${day.slice(0, 7) !== month ? "is-outside" : ""}`}
              aria-current={day === today ? "date" : undefined}
              aria-label={day}
              onClick={() => onChange(day)}
            >
              {Number(day.slice(-2))}
            </button>
          ),
        )}
      </div>
      <Button
        variant="ghost"
        onClick={() => {
          setMonth(today.slice(0, 7));
          onChange(today);
        }}
      >
        Сегодня
      </Button>
    </section>
  );
}
