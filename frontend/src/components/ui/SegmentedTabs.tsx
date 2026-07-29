import { useId } from "react";

interface SegmentedTab<T extends string> {
  value: T;
  label: string;
  disabled?: boolean;
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
    <div className={`segmented-tabs ${className}`.trim()} role="tablist" aria-label={label}>
      {tabs.map((tab, index) => (
        <button
          id={`${tabId}-${tab.value}-tab`}
          key={tab.value}
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
      ))}
      <span
        className="segmented-tabs-indicator"
        aria-hidden="true"
        style={{
          width: `${100 / tabs.length}%`,
          transform: `translateX(${currentIndex * 100}%)`,
        }}
      />
    </div>
  );
}
