/** Дерево дней: месяцы, две колонки, прошлое свёрнуто отдельной группой. */
import { CalendarOff, Flag, Undo2 } from "lucide-react";
import { ContextMenu, Disclosure } from "../../components/ui";
import { PurposeDot } from "../../components/domain";
import { monthLabel, plural, WEEKDAYS_SHORT, type DayFacts } from "./model";

interface DayTreeProps {
  days: DayFacts[];
  selected: string;
  onSelect: (date: string) => void;
  onToggleRest: (date: string) => void;
  onCatchUp: (date: string) => void;
  hasDebt: boolean;
  draftDates?: Set<string>;
  disabled?: boolean;
}

const stateLabel: Record<DayFacts["state"], string> = {
  empty: "без назначений",
  planned: "запланирован",
  partial: "частично пройден",
  done: "пройден",
  missed: "не начат",
};

/** Подпись под числом: вопросы, билеты или пропуск. */
function countLabel(day: DayFacts) {
  if (day.isRest && !day.planned) return "Пропуск";
  if (!day.planned) return "";
  const questions = `${day.planned} ${plural(day.planned, "вопрос", "вопроса", "вопросов")}`;
  return day.tickets ? `${day.tickets} ${plural(day.tickets, "билет", "билета", "билетов")} · ${questions}` : questions;
}

function DayCard({
  day,
  selected,
  onSelect,
  onToggleRest,
  onCatchUp,
  isDraft,
  disabled,
  hasDebt,
}: {
  day: DayFacts;
  selected: boolean;
  onSelect: (date: string) => void;
  onToggleRest: (date: string) => void;
  onCatchUp: (date: string) => void;
  isDraft: boolean;
  disabled: boolean;
  hasDebt: boolean;
}) {
  const label = countLabel(day);
  return (
    <ContextMenu
      label={`Действия дня ${day.day}`}
      items={[
        {
          label: day.isRest ? "Снять отметку пропуска" : "Отметить пропускаемым",
          icon: <CalendarOff size={13} />,
          disabled,
          onSelect: () => onToggleRest(day.date),
        },
        {
          label: "Наверстать сюда",
          icon: <Undo2 size={13} />,
          disabled: disabled || !hasDebt,
          onSelect: () => onCatchUp(day.date),
        },
      ]}
      trigger={
        <button
          type="button"
          className={[
            "prep-day",
            `is-${day.state}`,
            selected ? "is-selected" : "",
            day.isRest ? "is-rest" : "",
            day.isToday ? "is-today" : "",
            isDraft ? "is-draft" : "",
          ]
            .filter(Boolean)
            .join(" ")}
          aria-current={day.isToday ? "date" : undefined}
          aria-pressed={selected}
          onClick={() => onSelect(day.date)}
        >
          <span className="prep-day-head">
            <b>{day.day}</b>
            <em>{WEEKDAYS_SHORT[day.weekdayIndex]}</em>
          </span>
          {label && <span className="prep-day-count">{label}</span>}
          {day.phaseTitle && day.purpose !== "none" && (
            <span className="prep-day-purpose">
              <PurposeDot purpose={day.purpose} />
              {day.phaseTitle}
            </span>
          )}
          <span className="sr-only">{stateLabel[day.state]}</span>
        </button>
      }
    />
  );
}

/**
 * Список оставшихся дней подготовки.
 *
 * Прошлое лежит в свёрнутой группе: оно должно оставаться доступным для работы
 * с долгом, но не растягивать список на весь срок подготовки.
 */
export function DayTree({
  days,
  selected,
  onSelect,
  onToggleRest,
  onCatchUp,
  hasDebt,
  draftDates,
  disabled = false,
}: DayTreeProps) {
  const past = days.filter((day) => day.isPast);
  const upcoming = days.filter((day) => !day.isPast && !day.isExam);
  const exam = days.find((day) => day.isExam) ?? null;
  const missed = past.filter((day) => day.state === "missed" || day.state === "partial").length;

  const months = new Map<string, DayFacts[]>();
  for (const day of upcoming) {
    const bucket = months.get(day.monthKey) ?? [];
    bucket.push(day);
    months.set(day.monthKey, bucket);
  }

  const card = (day: DayFacts) => (
    <DayCard
      key={day.date}
      day={day}
      selected={day.date === selected}
      onSelect={onSelect}
      onToggleRest={onToggleRest}
      onCatchUp={onCatchUp}
      isDraft={draftDates?.has(day.date) ?? false}
      disabled={disabled}
      hasDebt={hasDebt}
    />
  );

  return (
    <div className="prep-day-tree">
      {past.length > 0 && (
        <Disclosure
          summary={missed ? `Прошедшие дни · ${missed} с долгом` : "Прошедшие дни"}
          className="prep-day-group"
        >
          <div className="prep-day-grid">{past.map(card)}</div>
        </Disclosure>
      )}
      {[...months.entries()].map(([key, list], index) => (
        <Disclosure key={key} summary={monthLabel(key)} defaultOpen={index === 0} className="prep-day-group">
          <div className="prep-day-grid">{list.map(card)}</div>
        </Disclosure>
      ))}
      {exam && (
        <button
          type="button"
          className={`prep-day is-exam${exam.date === selected ? " is-selected" : ""}`}
          onClick={() => onSelect(exam.date)}
        >
          <Flag size={14} />
          <span>
            {exam.day} {monthLabel(exam.monthKey).split(" ")[0]} · экзамен
          </span>
        </button>
      )}
    </div>
  );
}
