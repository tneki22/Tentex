import { useId, useLayoutEffect, useRef, useState } from "react";
import type { CSSProperties } from "react";
import { Tooltip } from "./Tooltip";

interface SegmentedTab<T extends string> {
  value: T;
  label: string;
  disabled?: boolean;
  tooltip?: string;
}

interface SegmentedTabsProps<T extends string> {
  label: string;
  value: T;
  tabs: Array<SegmentedTab<T>>;
  onChange: (value: T) => void;
  className?: string;
}

export function SegmentedTabs<T extends string>({
  label,
  value,
  tabs,
  onChange,
  className = "",
}: SegmentedTabsProps<T>) {
  const tabId = useId();
  const currentIndex = Math.max(0, tabs.findIndex((tab) => tab.value === value));
  const trackRef = useRef<HTMLDivElement>(null);
  const buttonRefs = useRef(new Map<string, HTMLButtonElement>());
  // Трек — grid-auto-columns: 1fr, то есть minmax(auto, 1fr): длинная вкладка
  // забирает больше своей доли, а бегунок по формуле равных долей уезжает
  // мимо её подписи. Меряем фактический прямоугольник выбранной кнопки и
  // подставляем его в CSS пикселями; пока измерения нет (первый кадр, трек
  // скрыт — нулевая ширина), CSS сам считает по равным долям как запасной путь.
  const [metrics, setMetrics] = useState<{ left: number; width: number } | null>(null);

  useLayoutEffect(() => {
    const track = trackRef.current;
    const button = buttonRefs.current.get(value);
    if (!track || !button) {
      setMetrics(null);
      return;
    }
    const trackRect = track.getBoundingClientRect();
    if (trackRect.width === 0) {
      setMetrics(null);
      return;
    }
    const buttonRect = button.getBoundingClientRect();
    setMetrics({ left: buttonRect.left - trackRect.left, width: buttonRect.width });
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(() => {
      const nextButton = buttonRefs.current.get(value);
      if (!track || !nextButton) return;
      const nextTrackRect = track.getBoundingClientRect();
      const nextButtonRect = nextButton.getBoundingClientRect();
      setMetrics({ left: nextButtonRect.left - nextTrackRect.left, width: nextButtonRect.width });
    });
    observer.observe(track);
    return () => observer.disconnect();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value, tabs.length]);

  function move(from: number, direction: -1 | 1) {
    for (let offset = 1; offset <= tabs.length; offset += 1) {
      const next = tabs[(from + direction * offset + tabs.length) % tabs.length];
      if (!next.disabled) {
        onChange(next.value);
        return;
      }
    }
  }

  return (
    <div
      ref={trackRef}
      className={`segmented-tabs ${className}`.trim()}
      role="tablist"
      aria-label={label}
      /* Запасной путь по равным долям, пока нет измерения (см. --tab-left/--tab-width ниже). */
      style={{ "--tab-count": tabs.length, "--tab-index": currentIndex } as CSSProperties}
    >
      {tabs.map((tab, index) => {
        const button = (
          <button
            id={`${tabId}-${tab.value}-tab`}
            key={tab.value}
            ref={(node) => {
              if (node) buttonRefs.current.set(tab.value, node);
              else buttonRefs.current.delete(tab.value);
            }}
            role="tab"
            type="button"
            aria-selected={tab.value === value}
            aria-controls={`${tabId}-tabpanel`}
            disabled={tab.disabled}
            tabIndex={tab.value === value ? 0 : -1}
            onClick={() => onChange(tab.value)}
            onKeyDown={(event) => {
              if (event.key === "ArrowRight") {
                event.preventDefault();
                move(index, 1);
              } else if (event.key === "ArrowLeft") {
                event.preventDefault();
                move(index, -1);
              } else if (event.key === "Home") {
                event.preventDefault();
                const first = tabs.find((candidate) => !candidate.disabled);
                if (first) onChange(first.value);
              } else if (event.key === "End") {
                event.preventDefault();
                const last = [...tabs].reverse().find((candidate) => !candidate.disabled);
                if (last) onChange(last.value);
              }
            }}
          >
            {tab.label}
          </button>
        );
        return tab.tooltip ? (
          <Tooltip key={tab.value} label={tab.tooltip} side="bottom">
            {button}
          </Tooltip>
        ) : button;
      })}
      <span
        className="segmented-tabs-indicator"
        aria-hidden="true"
        style={metrics ? ({ "--tab-left": `${metrics.left}px`, "--tab-width": `${metrics.width}px` } as CSSProperties) : undefined}
      />
    </div>
  );
}
