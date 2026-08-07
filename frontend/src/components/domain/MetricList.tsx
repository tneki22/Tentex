export interface Metric {
  label: string;
  /** null означает «модуль выключен»: метрика не показывается совсем (FR-P3). */
  value: string | null;
}

interface MetricListProps {
  metrics: Metric[];
  /** «row» — строка через точку для карточки, «grid» — столбец для панели проекта. */
  layout?: "row" | "grid";
}

/**
 * Метрики проекта или темы. Единственное место, где решается, как метрика
 * выглядит, — и единственное, где соблюдается FR-P3: выключенная модулем
 * метрика не показывается и НЕ заменяется нулём.
 *
 * Числа набираются текстом, без прогресс-баров. Полоса появляется только у
 * прогресса работы (см. Progress) — метрика к 100% не стремится (FR-D17).
 */
export function MetricList({ metrics, layout = "row" }: MetricListProps) {
  const shown = metrics.filter((metric) => metric.value !== null);
  if (shown.length === 0) return null;

  if (layout === "row") {
    return (
      <p className="metric-row">
        {shown.map((metric, index) => (
          <span key={metric.label}>
            {index > 0 && <i aria-hidden="true"> · </i>}
            {metric.label} {metric.value}
          </span>
        ))}
      </p>
    );
  }

  return (
    <dl className="metric-grid">
      {shown.map((metric) => (
        <div key={metric.label}>
          <dt>{metric.label}</dt>
          <dd>{metric.value}</dd>
        </div>
      ))}
    </dl>
  );
}
