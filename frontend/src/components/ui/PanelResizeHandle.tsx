import { useRef } from "react";
import type { PointerEvent as ReactPointerEvent } from "react";

interface PanelResizeHandleProps {
  label: string;
  value: number;
  min: number;
  max: number;
  className?: string;
  onDelta: (delta: number) => void;
  onReset: () => void;
}

/** Изменяемый мышью и клавиатурой вертикальный разделитель двух панелей. */
export function PanelResizeHandle({
  label,
  value,
  min,
  max,
  className = "",
  onDelta,
  onReset,
}: PanelResizeHandleProps) {
  const lastX = useRef<number | null>(null);

  function stopResize(event: ReactPointerEvent<HTMLDivElement>) {
    lastX.current = null;
    document.body.classList.remove("is-resizing-workspace");
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
  }

  return (
    <div
      className={`workspace-resize-handle ${className}`.trim()}
      role="separator"
      tabIndex={0}
      aria-label={label}
      aria-orientation="vertical"
      aria-valuemin={min}
      aria-valuemax={max}
      aria-valuenow={Math.round(value)}
      onDoubleClick={onReset}
      onKeyDown={(event) => {
        if (event.key === "ArrowLeft") onDelta(-24);
        else if (event.key === "ArrowRight") onDelta(24);
        else if (event.key === "Home") onDelta(-10_000);
        else if (event.key === "End") onDelta(10_000);
        else return;
        event.preventDefault();
      }}
      onPointerDown={(event) => {
        lastX.current = event.clientX;
        event.currentTarget.setPointerCapture(event.pointerId);
        document.body.classList.add("is-resizing-workspace");
      }}
      onPointerMove={(event) => {
        if (lastX.current === null) return;
        const delta = event.clientX - lastX.current;
        lastX.current = event.clientX;
        onDelta(delta);
      }}
      onPointerUp={stopResize}
      onPointerCancel={stopResize}
    >
      <span />
    </div>
  );
}
