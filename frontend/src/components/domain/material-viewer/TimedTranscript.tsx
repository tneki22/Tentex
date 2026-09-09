import { useEffect, useRef } from "react";
import type { MaterialFragmentRead } from "../../../api/materials";
import { highlight } from "./StructuredPage";

/** «01:02:03» для длинного и «12:34» для короткого — часы без нужды не пишем. */
export function formatTime(seconds: number): string {
  const total = Math.max(0, Math.floor(seconds));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const rest = total % 60;
  const pad = (value: number) => String(value).padStart(2, "0");
  return hours > 0 ? `${hours}:${pad(minutes)}:${pad(rest)}` : `${pad(minutes)}:${pad(rest)}`;
}

interface TimedTranscriptProps {
  fragments: MaterialFragmentRead[];
  /** Текущее время воспроизведения: по нему подсвечивается сегмент. */
  currentTime?: number;
  terms?: string[];
  onSeek(seconds: number): void;
  emptyHint?: string;
}

/**
 * Расшифровка с временной шкалой. Сегмент — кнопка: нажатие перематывает
 * запись или открывает ролик с этого момента.
 */
export function TimedTranscript({
  fragments,
  currentTime = 0,
  terms = [],
  onSeek,
  emptyHint = "У этого источника пока нет расшифровки.",
}: TimedTranscriptProps) {
  const activeRef = useRef<HTMLButtonElement>(null);
  const timed = fragments.filter((fragment) => fragment.time_from !== null);
  const activeIndex = timed.reduce((best, fragment, index) => {
    const from = fragment.time_from ?? 0;
    return from <= currentTime ? index : best;
  }, -1);

  useEffect(() => {
    activeRef.current?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [activeIndex]);

  if (timed.length === 0) {
    return (
      <div className="timed-transcript is-plain">
        {fragments.length === 0
          ? <p className="structured-page-empty">{emptyHint}</p>
          : fragments.map((fragment) => <p key={fragment.id}>{fragment.text}</p>)}
      </div>
    );
  }

  return (
    <div className="timed-transcript" role="list" aria-label="Расшифровка по времени">
      {timed.map((fragment, index) => {
        const isActive = index === activeIndex;
        return (
          <button
            type="button"
            role="listitem"
            key={fragment.id}
            ref={isActive ? activeRef : undefined}
            className={`timed-segment ${isActive ? "is-active" : ""}`.trim()}
            aria-current={isActive ? "true" : undefined}
            onClick={() => onSeek(fragment.time_from ?? 0)}
          >
            <span className="timed-stamp">{formatTime(fragment.time_from ?? 0)}</span>
            <span className="timed-text">{highlight(fragment.text, terms)}</span>
          </button>
        );
      })}
    </div>
  );
}
