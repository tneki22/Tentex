import type { ReactNode } from "react";

/**
 * Схемы руководства — встроенный SVG, а не картинки: они перекрашиваются вместе
 * с темой и не теряют резкость. В странице подключаются строкой
 * `:::diagram имя`. Цвета — классы `.gd-*` в guide.css, значения из токенов.
 */

function Overview() {
  return (
    <svg viewBox="0 0 720 250" role="img" aria-label="Материалы дают Программу, Программа ведёт к занятиям, Покрытие измеряет связь в обе стороны">
      <defs>
        <marker id="gd-arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
          <path d="M1 1 L9 5 L1 9" className="gd-arrow-head" />
        </marker>
      </defs>

      <g className="gd-node gd-info">
        <rect x="16" y="24" width="184" height="88" rx="16" />
        <text x="108" y="62" className="gd-title">Материалы</text>
        <text x="108" y="84" className="gd-sub">книги, конспекты, ссылки</text>
      </g>
      <g className="gd-node gd-accent">
        <rect x="268" y="24" width="184" height="88" rx="16" />
        <text x="360" y="62" className="gd-title">Программа</text>
        <text x="360" y="84" className="gd-sub">вопросы или темы</text>
      </g>
      <g className="gd-node gd-success">
        <rect x="520" y="24" width="184" height="88" rx="16" />
        <text x="612" y="62" className="gd-title">Занятия</text>
        <text x="612" y="84" className="gd-sub">уроки, карточки, план</text>
      </g>

      <path d="M204 68 H262" className="gd-arrow" markerEnd="url(#gd-arrow)" />
      <path d="M456 68 H514" className="gd-arrow" markerEnd="url(#gd-arrow)" />

      <path d="M108 116 V168 M612 116 V168" className="gd-arrow gd-dashed" />
      <path d="M360 116 V168" className="gd-arrow gd-dashed" />

      <g className="gd-node gd-warning">
        <rect x="16" y="168" width="688" height="60" rx="16" />
        <text x="360" y="194" className="gd-title">Покрытие</text>
        <text x="360" y="214" className="gd-sub">чем подтверждён каждый вопрос — и что в материалах осталось без темы</text>
      </g>
    </svg>
  );
}

const DIAGRAMS: Record<string, () => ReactNode> = {
  overview: Overview,
};

export function GuideDiagram({ name }: { name: string }) {
  const Diagram = DIAGRAMS[name];
  if (!Diagram) return <p className="guide-missing">Схема «{name}» ещё не нарисована.</p>;
  return <Diagram />;
}
