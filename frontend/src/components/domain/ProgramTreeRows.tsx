import type { ButtonHTMLAttributes, ReactNode } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";

interface ProgramSectionRowProps {
  number: string;
  title: string;
  open: boolean;
  active: boolean;
  /** Справа: число тем в Рабочей области, сумма по урокам в разделе «Уроки». */
  aside: ReactNode;
  /** Слева от переключателя — чекбокс массового выбора. */
  leading?: ReactNode;
  onToggle(): void;
  onSelect(): void;
}

/** Строка раздела программы: одна на Рабочую область и раздел «Уроки». */
export function ProgramSectionRow({ number, title, open, active, aside, leading, onToggle, onSelect }: ProgramSectionRowProps) {
  return (
    <div className={`workspace-section-row ${leading ? "has-leading" : ""} ${active ? "is-active" : ""}`.trim()}>
      {leading}
      <button type="button" className="workspace-section-toggle" aria-expanded={open} aria-label={open ? `Свернуть раздел «${title}»` : `Раскрыть раздел «${title}»`} onClick={onToggle}>{open ? <ChevronDown size={15} /> : <ChevronRight size={15} />}</button>
      <button type="button" className="workspace-section-select" onClick={onSelect}><span>{number}. {title}</span></button>
      <small>{aside}</small>
    </div>
  );
}

interface ProgramTopicRowProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  depth: number;
  active: boolean;
  status: ReactNode;
  eyebrow: string;
  title: string;
  signals?: ReactNode;
}

/**
 * Строка изучаемого узла. Лишние props уходят на кнопку: так её можно отдать
 * триггером `ContextMenu` (Radix навешивает обработчики через `asChild`).
 */
export function ProgramTopicRow({ depth, active, status, eyebrow, title, signals, className = "", ...button }: ProgramTopicRowProps) {
  return (
    <button
      type="button"
      {...button}
      className={`workspace-question-row depth-${Math.min(Math.max(depth - 2, 0), 3)} ${active ? "is-active" : ""} ${className}`.trim()}
    >
      {status}
      <span className="workspace-question-copy">
        <small>{eyebrow}</small>
        <span>{title}</span>
      </span>
      <span className="workspace-question-signals">{signals}</span>
    </button>
  );
}
