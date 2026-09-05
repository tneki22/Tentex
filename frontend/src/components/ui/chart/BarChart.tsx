/** Столбцы по дням: факт, остаток до цели контуром и превышение цели отдельным тоном. */
import { useState } from "react";
import { useChartWidth } from "./useChartWidth";

export interface BarDatum {
  /** Стабильный ключ столбца, обычно дата. */
  key: string;
  /** Подпись под столбцом. */
  label: string;
  value: number;
  /** Индивидуальный бюджет дня: контур за фактическим временем. */
  target?: number;
  /** Контурная часть сверху: сколько ещё осталось до цели сегодня. */
  ghost?: number;
  /** Явно пропущенный день: вместо столбца точка на базовой линии. */
  hollow?: boolean;
  /** Текущий день выделяется акцентной обводкой. */
  current?: boolean;
  tooltip?: string;
}

interface BarChartProps {
  data: BarDatum[];
  /** Пунктирная линия цели, например дневной бюджет. */
  target?: number | null;
  targetLabel?: string;
  height?: number;
  ariaLabel: string;
  emptyLabel?: string;
}

const AXIS = 18;

/**
 * Столбчатая диаграмма по дням с необязательной линией цели.
 *
 * Часть столбца выше цели красится отдельным тоном: превышение бюджета
 * остаётся видимым, но не выглядит ошибкой.
 */
export function BarChart({
  data,
  target = null,
  targetLabel,
  height = 96,
  ariaLabel,
  emptyLabel = "Нет данных за период",
}: BarChartProps) {
  const { ref, width } = useChartWidth();
  const [hover, setHover] = useState<number | null>(null);
  // Запас сверху: иначе линия цели встаёт вплотную к краю и её подпись обрезается.
  const maximum = Math.max(target ?? 0, ...data.map((d) => Math.max(d.target ?? 0, d.value + (d.ghost ?? 0))), 1);
  const tick = Math.max(1, Math.ceil(maximum / 3 / (maximum > 30 ? 10 : 1))) * (maximum > 30 ? 10 : 1);
  const peak = tick * 3;
  const empty = data.every((d) => d.value === 0);
  const left = 28;
  const step = width && data.length ? (width - left) / data.length : 0;
  const barWidth = Math.max(3, Math.min(18, step * 0.56));
  const scale = (value: number) => (value / peak) * height;
  const labelEvery = Math.max(1, Math.ceil(data.length / Math.max(2, Math.floor(width / 34))));

  return (
    <div className="chart" ref={ref}>
      {width > 0 && (
        <svg
          width={width}
          height={height + AXIS + 8}
          role="img"
          aria-label={ariaLabel}
          onMouseLeave={() => setHover(null)}
          style={{ paddingTop: 8 }}
        >
          {[0, tick, tick * 2, peak].map(value => <g key={value}>
            <line x1={left} x2={width} y1={height - scale(value)} y2={height - scale(value)} className="chart-grid" />
            <text x={left - 6} y={height - scale(value) + 4} textAnchor="end" className="chart-axis-label">{value}</text>
          </g>)}
          {target != null && target > 0 && (
            <g>
              <line
                x1={0}
                x2={width}
                y1={height - scale(target)}
                y2={height - scale(target)}
                className="chart-target"
              />
              {targetLabel && (
                <text
                  x={width}
                  y={height - scale(target) - 4}
                  textAnchor="end"
                  className="chart-target-label"
                >
                  {targetLabel}
                </text>
              )}
            </g>
          )}
          <line x1={left} x2={width} y1={height} y2={height} className="chart-baseline" />
          {data.map((datum, index) => {
            const x = left + index * step + (step - barWidth) / 2;
            const over = target != null && target > 0 ? Math.max(0, datum.value - target) : 0;
            const base = datum.value - over;
            const ghost = datum.ghost ?? 0;
            return (
              <g
                key={datum.key}
                onMouseEnter={() => setHover(index)}
                onFocus={() => setHover(index)}
                onBlur={() => setHover(null)}
                tabIndex={0}
                aria-label={datum.tooltip ?? `${datum.label}: ${datum.value}`}
                className={`chart-bar-group${datum.current ? " is-current" : ""}`}
              >
                <title>{datum.tooltip ?? datum.label}</title>
                <rect x={left + index * step} y={0} width={step} height={height} fill="transparent" />
                {(datum.target ?? 0) > 0 && <rect x={x - 2} y={height - scale(datum.target!)} width={barWidth + 4} height={scale(datum.target!)} rx={3} className="chart-day-budget" />}
                {datum.hollow ? (
                  <circle cx={x + barWidth / 2} cy={height - 3} r={2.5} className="chart-bar-rest" />
                ) : (
                  <>
                    {base > 0 && (
                      <rect
                        x={x}
                        y={height - scale(base)}
                        width={barWidth}
                        height={scale(base)}
                        rx={2}
                        className="chart-bar"
                      />
                    )}
                    {over > 0 && (
                      <rect
                        x={x}
                        y={height - scale(datum.value)}
                        width={barWidth}
                        height={scale(over)}
                        rx={2}
                        className="chart-bar-over"
                      />
                    )}
                    {ghost > 0 && (
                      <rect
                        x={x + 0.5}
                        y={height - scale(datum.value + ghost)}
                        width={barWidth - 1}
                        height={scale(ghost)}
                        rx={2}
                        className="chart-bar-ghost"
                      />
                    )}
                  </>
                )}
                {(index % labelEvery === 0 || index === data.length - 1) && (
                  <text x={x + barWidth / 2} y={height + 13} textAnchor="middle" className="chart-axis-label">
                    {datum.label}
                  </text>
                )}
              </g>
            );
          })}
        </svg>
      )}
      {empty && <p className="chart-empty">{emptyLabel}</p>}
      {hover != null && data[hover]?.tooltip && (
        <p className="chart-readout" role="status">
          {data[hover].tooltip}
        </p>
      )}
    </div>
  );
}
