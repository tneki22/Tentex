import { useEffect, useState } from "react";
import { MarkdownMessage } from "./MarkdownMessage";

interface ProgressiveMarkdownProps {
  text: string;
  active?: boolean;
  durationMs?: number;
}

function prefersReducedMotion() {
  return typeof window.matchMedia === "function"
    && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

export function ProgressiveMarkdown({
  text,
  active = true,
  durationMs = 520,
}: ProgressiveMarkdownProps) {
  const reducedMotion = prefersReducedMotion();
  const [visibleLength, setVisibleLength] = useState(
    !active || reducedMotion ? text.length : 0,
  );

  useEffect(() => {
    if (!active || reducedMotion) {
      setVisibleLength(text.length);
      return;
    }

    setVisibleLength(0);
    const startedAt = performance.now();
    const timer = window.setInterval(() => {
      const elapsed = performance.now() - startedAt;
      const progress = Math.min(1, elapsed / Math.max(1, durationMs));
      setVisibleLength(Math.max(1, Math.ceil(text.length * progress)));
      if (progress >= 1) window.clearInterval(timer);
    }, 24);
    return () => window.clearInterval(timer);
  }, [active, durationMs, reducedMotion, text]);

  const complete = visibleLength >= text.length;
  return (
    <div className="progressive-text">
      <MarkdownMessage text={text.slice(0, visibleLength)} />
      {!complete && (
        <button type="button" onClick={() => setVisibleLength(text.length)}>
          Показать сразу
        </button>
      )}
    </div>
  );
}
