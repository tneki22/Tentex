import { useCallback, useEffect, useRef, useState } from "react";
import type { CSSProperties, ReactNode } from "react";
import type { MaterialViewMode } from "./types";

const MIN_RATIO = 0.25;
const MAX_RATIO = 0.75;
const STORAGE_PREFIX = "tentex-viewer-split";

interface DocumentStageProps {
  mode: MaterialViewMode;
  /** Ключ раскладки: ширина разделителя запоминается для каждого материала. */
  storageKey: string;
  sourceLabel: string;
  textLabel: string;
  source: ReactNode;
  text: ReactNode;
  /** Края сцены листают страницы. Не рисуются, когда страница одна. */
  onPrevPage?: () => void;
  onNextPage?: () => void;
  canPrevPage?: boolean;
  canNextPage?: boolean;
}

/**
 * Две половины сцены с перетаскиваемым разделителем.
 *
 * Разделитель — `separator` с `aria-valuenow`: стрелками он двигается так же,
 * как мышью, иначе раскладка была бы доступна только указателю.
 */
export function DocumentStage({
  mode,
  storageKey,
  sourceLabel,
  textLabel,
  source,
  text,
  onPrevPage,
  onNextPage,
  canPrevPage = false,
  canNextPage = false,
}: DocumentStageProps) {
  const frame = useRef<HTMLDivElement>(null);
  const [ratio, setRatio] = useState(() => {
    const stored = Number(localStorage.getItem(`${STORAGE_PREFIX}:${storageKey}`));
    return Number.isFinite(stored) && stored >= MIN_RATIO && stored <= MAX_RATIO ? stored : 0.5;
  });
  const [dragging, setDragging] = useState(false);

  useEffect(() => {
    const stored = Number(localStorage.getItem(`${STORAGE_PREFIX}:${storageKey}`));
    setRatio(Number.isFinite(stored) && stored >= MIN_RATIO && stored <= MAX_RATIO ? stored : 0.5);
  }, [storageKey]);

  const apply = useCallback((next: number) => {
    const clamped = Math.min(MAX_RATIO, Math.max(MIN_RATIO, next));
    setRatio(clamped);
    localStorage.setItem(`${STORAGE_PREFIX}:${storageKey}`, clamped.toFixed(3));
  }, [storageKey]);

  useEffect(() => {
    if (!dragging) return;
    function onMove(event: PointerEvent) {
      const box = frame.current?.getBoundingClientRect();
      if (!box || box.width === 0) return;
      apply((event.clientX - box.left) / box.width);
    }
    function onUp() {
      setDragging(false);
    }
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
    return () => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
    };
  }, [dragging, apply]);

  const edges = (onPrevPage || onNextPage) && (
    <>
      <button
        type="button"
        className="viewer-page-edge is-prev"
        aria-label="Предыдущая страница"
        disabled={!canPrevPage}
        onClick={onPrevPage}
      />
      <button
        type="button"
        className="viewer-page-edge is-next"
        aria-label="Следующая страница"
        disabled={!canNextPage}
        onClick={onNextPage}
      />
    </>
  );

  if (mode !== "compare") {
    return (
      <div className="viewer-stage is-single" ref={frame}>
        {edges}
        <section
          className="viewer-pane"
          aria-label={mode === "source" ? sourceLabel : textLabel}
        >
          {mode === "source" ? source : text}
        </section>
      </div>
    );
  }

  return (
    <div
      className={`viewer-stage is-compare ${dragging ? "is-dragging" : ""}`.trim()}
      ref={frame}
      style={{ "--viewer-split": ratio } as CSSProperties}
    >
      {edges}
      <section className="viewer-pane is-source" aria-label={sourceLabel}>{source}</section>
      <div
        className="viewer-split-handle"
        role="separator"
        aria-orientation="vertical"
        aria-label="Ширина исходника"
        aria-valuemin={Math.round(MIN_RATIO * 100)}
        aria-valuemax={Math.round(MAX_RATIO * 100)}
        aria-valuenow={Math.round(ratio * 100)}
        tabIndex={0}
        onPointerDown={(event) => {
          event.preventDefault();
          setDragging(true);
        }}
        onKeyDown={(event) => {
          if (event.key === "ArrowLeft") {
            event.preventDefault();
            apply(ratio - 0.02);
          } else if (event.key === "ArrowRight") {
            event.preventDefault();
            apply(ratio + 0.02);
          } else if (event.key === "Home") {
            event.preventDefault();
            apply(0.5);
          }
        }}
      >
        <span aria-hidden="true" />
      </div>
      <section className="viewer-pane is-text" aria-label={textLabel}>{text}</section>
    </div>
  );
}
