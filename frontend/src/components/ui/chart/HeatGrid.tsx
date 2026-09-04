/** Тепловая карта регулярности: столбец — неделя, строка — день недели. */

export interface HeatCell {
  date: string;
  /** Ступень заливки от 0 до 4. */
  level: 0 | 1 | 2 | 3 | 4;
  /** Явный пропуск и будущие дни рисуются контуром, а не заливкой. */
  state?: "rest" | "future" | "exam";
  title: string;
}

interface HeatGridProps {
  /** Недели слева направо, внутри недели — понедельник … воскресенье. */
  weeks: (HeatCell | null)[][];
  ariaLabel: string;
}

const WEEKDAYS = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"];

/**
 * Сетка занятий по неделям.
 *
 * Одноцветная шкала в пять ступеней: сравнивается интенсивность, а не
 * категория, поэтому разные оттенки здесь были бы ложной подсказкой.
 */
export function HeatGrid({ weeks, ariaLabel }: HeatGridProps) {
  return (
    <div className="heat-grid" role="img" aria-label={ariaLabel}>
      <div className="heat-grid-days" aria-hidden="true">
        {WEEKDAYS.map((day) => (
          <span key={day}>{day}</span>
        ))}
      </div>
      <div className="heat-grid-weeks">
        {weeks.map((week, index) => (
          <div className="heat-grid-week" key={index}>
            {week.map((cell, dayIndex) =>
              cell ? (
                <span
                  key={cell.date}
                  className={`heat-cell${cell.state ? ` is-${cell.state}` : ""}`}
                  style={{ background: `var(--heat-${cell.level})` }}
                  title={cell.title}
                />
              ) : (
                <span key={dayIndex} className="heat-cell is-blank" />
              ),
            )}
          </div>
        ))}
      </div>
      <p className="heat-grid-legend" aria-hidden="true">
        меньше
        {[0, 1, 2, 3, 4].map((level) => (
          <i key={level} style={{ background: `var(--heat-${level})` }} />
        ))}
        больше
      </p>
    </div>
  );
}
