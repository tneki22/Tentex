/** Горизонтальная составная полоса: доли сравниваются от общей левой границы. */

export interface BarSegment {
  value: number;
  /** CSS-переменная тона, например `--chart-fact`. */
  token: string;
  label: string;
  /** Полупрозрачная заливка вместо сплошной — для «назначено, но не открыто». */
  soft?: boolean;
}

interface StackedBarProps {
  segments: BarSegment[];
  /** Знаменатель. По умолчанию — сумма сегментов. */
  total?: number;
  size?: "base" | "large";
  ariaLabel: string;
}

/**
 * Составная полоса на всю ширину строки.
 *
 * Кольцевая диаграмма для тех же данных читалась бы хуже: длины от общей
 * левой границы сравниваются точнее углов (Cleveland & McGill, 1984).
 */
export function StackedBar({ segments, total, size = "base", ariaLabel }: StackedBarProps) {
  const sum = total ?? segments.reduce((value, segment) => value + segment.value, 0);
  const safe = Math.max(sum, 1);
  return (
    <span
      className={`stacked-bar is-${size}`}
      role="img"
      aria-label={ariaLabel}
      title={segments
        .filter((segment) => segment.value > 0)
        .map((segment) => `${segment.label}: ${segment.value}`)
        .join(", ")}
    >
      {segments.map((segment, index) =>
        segment.value > 0 ? (
          <i
            key={index}
            className={segment.soft ? "is-soft" : undefined}
            style={{
              width: `${(segment.value / safe) * 100}%`,
              background: segment.soft
                ? `color-mix(in srgb, var(${segment.token}) 26%, transparent)`
                : `var(${segment.token})`,
            }}
          />
        ) : null,
      )}
    </span>
  );
}
