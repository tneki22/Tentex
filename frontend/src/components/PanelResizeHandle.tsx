import type { PointerEvent as ReactPointerEvent } from "react";

interface PanelResizeHandleProps {
  label: string;
  value: number;
  min: number;
  max: number;
  onChange: (value: number) => void;
  onPointerStart: (event: ReactPointerEvent<HTMLDivElement>) => void;
  onReset: () => void;
}

export function PanelResizeHandle({
  label,
  value,
  min,
  max,
  onChange,
  onPointerStart,
  onReset,
}: PanelResizeHandleProps) {
  return (
    <div
      className="panel-resize-handle"
      role="separator"
      tabIndex={0}
      aria-label={label}
      aria-orientation="vertical"
      aria-valuenow={Math.round(value)}
      aria-valuemin={Math.round(min)}
      aria-valuemax={Math.round(max)}
      onPointerDown={onPointerStart}
      onDoubleClick={onReset}
      onKeyDown={(event) => {
        if (event.key === "ArrowLeft") onChange(value - 12);
        else if (event.key === "ArrowRight") onChange(value + 12);
        else if (event.key === "Home") onChange(min);
        else if (event.key === "End") onChange(max);
        else return;
        event.preventDefault();
      }}
    >
      <span />
    </div>
  );
}
