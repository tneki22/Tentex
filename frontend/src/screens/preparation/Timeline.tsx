/** Числовая ось с отдельными дорожками для пересекающихся блоков. */
import { useEffect, useState } from "react";
import { Button, ContextMenu, SegmentedTabs } from "../../components/ui";
import type { Overview, Phase } from "../../api/preparation";
import { addDays, dateLabel, dayNumber, duration } from "./dates";
export function Timeline({
  overview,
  selected,
  onEdit,
}: {
  overview: Overview;
  selected: string;
  onEdit: (phase: Phase) => void;
}) {
  const [scale, setScale] = useState<"week" | "month" | "all">("all");
  const [now, setNow] = useState(Date.parse(overview.now));
  useEffect(() => {
    const started = Date.now();
    const tick = () => setNow(Date.parse(overview.now) + Date.now() - started);
    tick();
    const timer = window.setInterval(tick, 30_000);
    return () => clearInterval(timer);
  }, [overview.now]);
  const remaining = overview.exam_at ? Math.max(0, Date.parse(overview.exam_at) - now) : null;
  const countdown = remaining === null
    ? overview.deadline ? `${Math.max(0, dayNumber(overview.deadline) - dayNumber(overview.today))} дней · уточните время экзамена` : "Укажите дату экзамена"
    : remaining === 0 ? "Экзамен уже начался"
      : `${Math.floor(remaining / 86_400_000)} д ${Math.floor(remaining / 3_600_000) % 24} ч ${Math.floor(remaining / 60_000) % 60} мин`;
  const phases = [...overview.plan.phases].sort((a, b) =>
    a.start.localeCompare(b.start),
  );
  const beginning = [
    overview.today,
    ...phases.map((phase) => phase.start),
    ...overview.plan.items.map((item) => item.on_date),
  ].sort()[0];
  const ending = [
    overview.deadline ?? addDays(overview.today, 30),
    ...phases.map((phase) => phase.end),
  ]
    .sort()
    .at(-1)!;
  const start = scale === "all" ? beginning : selected;
  const end =
    scale === "all" ? ending : addDays(start, scale === "week" ? 6 : 29);
  const total = Math.max(1, dayNumber(end) - dayNumber(start) + 1);
  const percent = (value: string) =>
    Math.max(
      0,
      Math.min(100, ((dayNumber(value) - dayNumber(start)) / total) * 100),
    );
  const lanes: string[] = [];
  const positioned = phases
    .filter((phase) => phase.end >= start && phase.start <= end)
    .map((phase) => {
      let lane = lanes.findIndex((last) => last < phase.start);
      if (lane < 0) lane = lanes.length;
      lanes[lane] = phase.end;
      return { phase, lane };
    });
  const create = () =>
    onEdit({
      id: crypto.randomUUID(),
      title: "Новый блок",
      start: selected,
      end: selected,
      kind: "learn",
      order: phases.length,
      origin: "manual",
    });
  return (
    <section className="prep-timeline">
      <header className="prep-section-head">
        <h2>Время до экзамена</h2>
        <SegmentedTabs
          label="Масштаб"
          value={scale}
          onChange={setScale}
          tabs={[
            { value: "week", label: "Неделя" },
            { value: "month", label: "Месяц" },
            { value: "all", label: "Весь срок" },
          ]}
        />
        <Button variant="ghost" onClick={create}>
          Добавить блок
        </Button>
      </header>
      <div className="prep-section-head">
        <p>До экзамена — <strong>{countdown}</strong></p>
        <p>На занятия — <strong>{duration(overview.summary.available_minutes * 60)}</strong></p>
      </div>
      <ContextMenu
        label="Блоки подготовки"
        items={[{ label: "Добавить блок", onSelect: create }]}
        trigger={
          <div
            className="prep-axis"
            tabIndex={0}
            aria-label="Временная ось. Добавить блок можно кнопкой выше."
            style={{
              minHeight: `calc(var(--space-12) * ${Math.max(lanes.length, 1) + 1})`,
            }}
          >
            <div
              className="prep-future"
              style={{ left: `${percent(overview.today)}%` }}
            />
            <div className="prep-axis-labels">
              <span>{dateLabel(start)}</span>
              <span>{dateLabel(end)}</span>
            </div>
            {overview.today >= start && overview.today <= end && (
              <div
                className="prep-now"
                style={{ left: `${percent(overview.today)}%` }}
              >
                <small>Сейчас</small>
              </div>
            )}
            {overview.deadline && overview.deadline >= start && overview.deadline <= end && (
              <div className="prep-now prep-exam" style={{left: `${percent(overview.deadline)}%`}}>
                <small>Экзамен</small>
              </div>
            )}
            {positioned.map(({ phase, lane }) => (
              <button
                key={phase.id}
                className="prep-phase"
                onClick={() => onEdit(phase)}
                style={{
                  left: `${percent(phase.start)}%`,
                  width: `${Math.max(2, percent(addDays(phase.end, 1)) - percent(phase.start))}%`,
                  top: `calc(var(--space-12) * ${lane + 1})`,
                }}
              >
                <strong>{phase.title}</strong>
                <small>
                  {dateLabel(phase.start)} — {dateLabel(phase.end)}
                </small>
              </button>
            ))}
          </div>
        }
      />
      <p className="prep-muted">
        Начало: {dateLabel(beginning)} ·{" "}
        {overview.deadline
          ? `Экзамен: ${dateLabel(overview.deadline)}${overview.exam_time ? `, ${overview.exam_time.slice(0, 5)}` : ", время не задано"}`
          : "Дата экзамена не задана"}
      </p>
    </section>
  );
}
