/** Полоса блоков подготовки: одна дорожка, пересечения запрещены (§3.2). */
import { Flag, Plus, Wand2 } from "lucide-react";
import { ContextMenu, IconButton, Tooltip } from "../../components/ui";
import type { Overview, Phase } from "../../api/preparation";
import { addDays, dateLabel, dayNumber } from "./dates";
import { phaseKind } from "./model";

interface BlocksStripProps {
  overview: Overview;
  start: string;
  end: string;
  onEdit: (phase: Phase) => void;
  onAdd: (range: { start: string; end: string }) => void;
  onAuto: () => void;
  disabled?: boolean;
}

interface Gap {
  start: string;
  end: string;
}

/** Пустые промежутки между блоками — места, куда можно добавить новый. */
function gapsBetween(phases: Phase[], start: string, end: string): Gap[] {
  const sorted = [...phases].sort((left, right) => left.start.localeCompare(right.start));
  const gaps: Gap[] = [];
  let cursor = start;
  for (const phase of sorted) {
    if (phase.start > cursor) gaps.push({ start: cursor, end: addDays(phase.start, -1) });
    if (phase.end >= cursor) cursor = addDays(phase.end, 1);
  }
  if (cursor <= end) gaps.push({ start: cursor, end });
  return gaps.filter((gap) => gap.start <= gap.end);
}

/**
 * Отрезок от сегодня до экзамена с блоками подготовки.
 *
 * Раскладки по нескольким дорожкам больше нет: блоки не пересекаются,
 * поэтому одной дорожки достаточно и полоса читается сразу.
 */
export function BlocksStrip({
  overview,
  start,
  end,
  onEdit,
  onAdd,
  onAuto,
  disabled = false,
}: BlocksStripProps) {
  const span = Math.max(1, dayNumber(end) - dayNumber(start) + 1);
  const percent = (date: string) => ((dayNumber(date) - dayNumber(start)) / span) * 100;
  const width = (from: string, to: string) => ((dayNumber(to) - dayNumber(from) + 1) / span) * 100;
  const phases = overview.plan.phases.filter((phase) => phase.end >= start && phase.start <= end);
  const gaps = gapsBetween(phases, start, end);
  const short = span <= 21;

  return (
    <section className="prep-blocks" aria-label="Периоды подготовки">
      <header className="prep-area-head">
        <h2 className="prep-area-title">Периоды подготовки</h2>
        <Tooltip label="Разметить периоды автоматически" side="left">
          <span>
            <IconButton label="Разметить периоды автоматически" onClick={onAuto} disabled={disabled}>
              <Wand2 size={15} />
            </IconButton>
          </span>
        </Tooltip>
      </header>
      <ContextMenu
        label="Периоды подготовки"
        items={[
          {
            label: "Добавить блок",
            icon: <Plus size={13} />,
            disabled,
            onSelect: () => onAdd({ start, end: addDays(start, Math.min(6, span - 1)) }),
          },
        ]}
        trigger={
          <div className="prep-strip">
            {gaps.map((gap) => (
              <button
                type="button"
                key={gap.start}
                className="prep-strip-gap"
                style={{ left: `${percent(gap.start)}%`, width: `${width(gap.start, gap.end)}%` }}
                onClick={() => onAdd(gap)}
                disabled={disabled}
                aria-label={`Добавить блок с ${dateLabel(gap.start)} по ${dateLabel(gap.end)}`}
              >
                <Plus size={13} />
              </button>
            ))}
            {phases.map((phase) => {
              const kind = phaseKind(phase.kind);
              const from = phase.start < start ? start : phase.start;
              const to = phase.end > end ? end : phase.end;
              return (
                <button
                  type="button"
                  key={phase.id}
                  className="prep-block"
                  style={{
                    left: `${percent(from)}%`,
                    width: `${width(from, to)}%`,
                    ["--purpose" as string]: `var(${kind.token})`,
                  }}
                  onClick={() => onEdit(phase)}
                  disabled={disabled}
                >
                  <strong>{phase.title}</strong>
                  <small>
                    {dateLabel(phase.start)} — {dateLabel(phase.end)} · {kind.label}
                  </small>
                </button>
              );
            })}
            {overview.today >= start && overview.today <= end && (
              <span className="prep-strip-now" style={{ left: `${percent(overview.today)}%` }}>
                <i />
                <em>сегодня</em>
              </span>
            )}
          </div>
        }
      />
      <div className="prep-strip-axis" aria-hidden="true">
        <span>{short ? dateLabel(start) : monthOf(start)}</span>
        {overview.deadline && (
          <span className="prep-strip-exam">
            <Flag size={12} /> {dateLabel(overview.deadline)}
            {overview.exam_time ? `, ${overview.exam_time.slice(0, 5)}` : ""}
          </span>
        )}
      </div>
    </section>
  );
}

const monthOf = (date: string) =>
  new Date(`${date}T12:00:00Z`).toLocaleDateString("ru-RU", { month: "long", timeZone: "UTC" });
