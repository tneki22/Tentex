/** Составные столбцы по дням: результаты сдач и деление работы на изучение и повторение. */
import { useState } from "react";
import { useChartWidth } from "./useChartWidth";

export interface ColumnSegment {
  value: number;
  /** CSS-переменная тона сегмента, например `--result-good`. */
  token: string;
}

export interface ColumnDatum {
  key: string;
  label: string;
  segments: ColumnSegment[];
  tooltip?: string;
}

interface StackedColumnsProps {
  data: ColumnDatum[];
  height?: number;
  ariaLabel: string;
  emptyLabel?: string;
  onSelect?: (key: string) => void;
}

const AXIS = 18;

/**
 * Составная столбчатая диаграмма.
 *
 * Сегменты укладываются снизу вверх в порядке массива, поэтому самый важный
 * тон ставится первым и всегда лежит на базовой линии.
 */
export function StackedColumns({
  data,
  height = 96,
  ariaLabel,
  emptyLabel = "Нет данных за период",
  onSelect,
}: StackedColumnsProps) {
  const { ref, width } = useChartWidth();
  const [hover, setHover] = useState<number | null>(null);
  const totals = data.map((d) => d.segments.reduce((sum, s) => sum + s.value, 0));
  const peak = Math.max(...totals, 1);
  const empty = totals.every((value) => value === 0);
  const step = width && data.length ? width / data.length : 0;
  const barWidth = Math.max(3, Math.min(18, step * 0.56));
  const labelEvery = Math.max(1, Math.ceil(data.length / 12));

  return (
    <div className="chart" ref={ref}>
      {width > 0 && (
        <svg
          width={width}
          height={height + AXIS}
          role="img"
          aria-label={ariaLabel}
          onMouseLeave={() => setHover(null)}
        >
          <line x1={0} x2={width} y1={height} y2={height} className="chart-baseline" />
          {data.map((datum, index) => {
            const x = index * step + (step - barWidth) / 2;
            let offset = 0;
            return (
              <g
                key={datum.key}
                onMouseEnter={() => setHover(index)}
                onClick={onSelect ? () => onSelect(datum.key) : undefined}
                className={onSelect ? "chart-bar-group is-clickable" : "chart-bar-group"}
              >
                <rect x={index * step} y={0} width={step} height={height} fill="transparent" />
                {datum.segments.map((segment, segmentIndex) => {
                  if (segment.value <= 0) return null;
                  const size = (segment.value / peak) * height;
                  offset += size;
                  return (
                    <rect
                      key={segmentIndex}
                      x={x}
                      y={height - offset}
                      width={barWidth}
                      height={size}
                      rx={segmentIndex === datum.segments.length - 1 ? 2 : 0}
                      fill={`var(${segment.token})`}
                    />
                  );
                })}
                {index % labelEvery === 0 && (
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
