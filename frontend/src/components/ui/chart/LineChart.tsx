/** Накопительный график: план, факт, потолок программы и пунктирный прогноз. */
import { useId, useState } from "react";
import { useChartWidth } from "./useChartWidth";

export interface LinePoint {
  x: number;
  y: number;
}

export interface LineSeries {
  key: string;
  points: LinePoint[];
  /** CSS-переменная цвета линии. */
  token: string;
  label: string;
  dashed?: boolean;
  filled?: boolean;
  /** План рисуется ступенями: он меняется датами, а не непрерывно. */
  stepped?: boolean;
}

export interface LineMarker {
  x: number;
  label: string;
  token?: string;
}

interface LineChartProps {
  series: LineSeries[];
  markers?: LineMarker[];
  xLabels: { x: number; label: string }[];
  maxX: number;
  maxY: number;
  ceilingLabel?: string;
  /** Штриховка между днём экзамена и прогнозируемым окончанием. */
  overrun?: { from: number; to: number } | null;
  height?: number;
  ariaLabel: string;
  readout?: (x: number) => string | null;
}

const PAD_LEFT = 38;
const PAD_TOP = 12;
const PAD_BOTTOM = 20;
const PAD_RIGHT = 10;

/** Ломаная с необязательными ступенями между точками. */
function toPath(points: LinePoint[], px: (x: number) => number, py: (y: number) => number, stepped: boolean) {
  if (!points.length) return "";
  return points
    .map((point, index) => {
      if (index === 0) return `M ${px(point.x)} ${py(point.y)}`;
      const previous = points[index - 1];
      if (stepped) return `L ${px(point.x)} ${py(previous.y)} L ${px(point.x)} ${py(point.y)}`;
      return `L ${px(point.x)} ${py(point.y)}`;
    })
    .join(" ");
}

/**
 * Линейный график с общей осью дней.
 *
 * Один график отвечает сразу на план и факт, отставание и прогноз завершения,
 * поэтому в аналитике он стоит первым и занимает всю ширину.
 */
export function LineChart({
  series,
  markers = [],
  xLabels,
  maxX,
  maxY,
  ceilingLabel,
  overrun = null,
  height = 220,
  ariaLabel,
  readout,
}: LineChartProps) {
  const { ref, width } = useChartWidth();
  const clipId = useId();
  const [hover, setHover] = useState<number | null>(null);
  const plotWidth = Math.max(1, width - PAD_LEFT - PAD_RIGHT);
  const plotHeight = height - PAD_TOP - PAD_BOTTOM;
  const px = (x: number) => PAD_LEFT + (x / Math.max(maxX, 1)) * plotWidth;
  const py = (y: number) => PAD_TOP + plotHeight - (y / Math.max(maxY, 1)) * plotHeight;
  const ticks = [...new Set([0, 0.25, 0.5, 0.75, 1].map((share) => Math.round(maxY * share)))];

  return (
    <div className="chart is-line" ref={ref}>
      {width > 0 && (
        <svg
          width={width}
          height={height}
          role="img"
          aria-label={ariaLabel}
          onMouseLeave={() => setHover(null)}
          onMouseMove={(event) => {
            const box = event.currentTarget.getBoundingClientRect();
            const local = event.clientX - box.left - PAD_LEFT;
            const value = Math.round((local / plotWidth) * maxX);
            setHover(value >= 0 && value <= maxX ? value : null);
          }}
        >
          <defs><clipPath id={clipId}><rect x={PAD_LEFT} y={PAD_TOP - 2} width={plotWidth} height={plotHeight + 4} /></clipPath></defs>
          {ticks.map((tick) => (
            <g key={tick}>
              <line x1={PAD_LEFT} x2={width - PAD_RIGHT} y1={py(tick)} y2={py(tick)} className="chart-grid" />
              <text x={PAD_LEFT - 6} y={py(tick) + 4} textAnchor="end" className="chart-axis-label">
                {tick}
              </text>
            </g>
          ))}
          <line
            x1={PAD_LEFT}
            x2={width - PAD_RIGHT}
            y1={py(maxY)}
            y2={py(maxY)}
            className="chart-ceiling"
          />
          {ceilingLabel && (
            <text x={width - PAD_RIGHT} y={py(maxY) - 4} textAnchor="end" className="chart-target-label">
              {ceilingLabel}
            </text>
          )}
          {overrun && (
            <rect
              x={px(overrun.from)}
              y={PAD_TOP}
              width={Math.max(0, px(overrun.to) - px(overrun.from))}
              height={plotHeight}
              className="chart-overrun"
            />
          )}
          {markers.map((marker) => (
            <g key={marker.label}>
              <line
                x1={px(marker.x)}
                x2={px(marker.x)}
                y1={PAD_TOP}
                y2={PAD_TOP + plotHeight}
                className="chart-marker"
                style={marker.token ? { stroke: `var(${marker.token})` } : undefined}
              />
              <text x={px(marker.x) + (marker.x > maxX * .8 ? -4 : 4)} textAnchor={marker.x > maxX * .8 ? "end" : "start"} y={PAD_TOP + 16} className="chart-marker-label">
                {marker.label}
              </text>
            </g>
          ))}
          {series.map((line) => {
            const path = toPath(line.points, px, py, line.stepped ?? false);
            if (!path) return null;
            const last = line.points[line.points.length - 1];
            const first = line.points[0];
            return (
              <g key={line.key} clipPath={`url(#${clipId})`}>
                {line.filled && (
                  <path
                    d={`${path} L ${px(last.x)} ${py(0)} L ${px(first.x)} ${py(0)} Z`}
                    className="chart-area"
                  />
                )}
                <path
                  d={path}
                  fill="none"
                  className={line.dashed ? "chart-line is-dashed" : "chart-line"}
                  style={{ stroke: `var(${line.token})` }}
                />
              </g>
            );
          })}
          {hover != null && (
            <g>
            <line
              x1={px(hover)}
              x2={px(hover)}
              y1={PAD_TOP}
              y2={PAD_TOP + plotHeight}
              className="chart-crosshair"
            />
            {series.filter(line => !line.dashed).map(line => {
              const point = line.points.find(point => point.x === hover);
              return point ? <circle key={line.key} cx={px(point.x)} cy={py(point.y)} r={4} fill={`var(${line.token})`} stroke="var(--paper)" strokeWidth={2} /> : null;
            })}
            </g>
          )}
          {xLabels.map((tick) => (
            <text key={tick.x} x={px(tick.x)} y={height - 5} textAnchor={tick.x >= maxX ? "end" : "middle"} className="chart-axis-label">
              {tick.label}
            </text>
          ))}
        </svg>
      )}
      {readout && <p className="chart-readout" role="status">{hover != null ? readout(hover) : "Наведи на график, чтобы сравнить план и факт за день"}</p>}
      <div className="chart-series-legend">{series.map(line => <span key={line.key}><i style={{ borderColor: `var(${line.token})`, borderTopStyle: line.dashed ? "dashed" : "solid" }} />{line.label}</span>)}</div>
    </div>
  );
}
