import type { CoverageSourceOverview } from "../../api/coverage";
import type { StatusTone } from "../ui";

/** Что сделать с материалом дальше: исследовать (впервые или заново) либо смотреть ход. */
export type ResearchAction = "research" | "continue" | "rerun" | "progress";

export interface ResearchState {
  label: string;
  detail: string;
  tone: StatusTone;
  action: ResearchAction;
  /** Источник уже участвовал в исследовании. */
  researched: boolean;
  /** Нужен запуск: не исследован, исследован частично или текст изменился. */
  needed: boolean;
}

const DAY = new Intl.DateTimeFormat("ru-RU", { day: "numeric", month: "long" });
const DAY_YEAR = new Intl.DateTimeFormat("ru-RU", { day: "numeric", month: "long", year: "numeric" });

function dateLabel(value: string | null): string {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return (date.getFullYear() === new Date().getFullYear() ? DAY : DAY_YEAR).format(date);
}

/**
 * Состояние исследования одного источника по сводке покрытия. «Файл разобран» и
 * «содержание исследовано» — разные вещи: без этой строки Игошин на «Мат логике»
 * выглядел исследованным, хотя ни один его блок модель не читала.
 */
export function researchState(source: CoverageSourceOverview | undefined): ResearchState | null {
  if (!source || source.total === 0) return null;
  const { pending, processing, stale, unresolved } = source.distribution;
  const done = source.total - pending - processing;
  const progress = `${done} из ${source.total} блоков`;
  if (source.run_state === "queued" || source.run_state === "running") {
    return { label: "Исследуется", detail: progress, tone: "info", action: "progress", researched: done > 0, needed: false };
  }
  if (source.run_state === "paused") {
    return { label: "Исследование на паузе", detail: progress, tone: "warning", action: "progress", researched: done > 0, needed: false };
  }
  if (pending === source.total) {
    return { label: "Не исследован", detail: "", tone: "neutral", action: "research", researched: false, needed: true };
  }
  if (stale > 0) {
    return {
      label: "Нужно исследовать заново",
      detail: "текст изменился после исследования",
      tone: "warning",
      action: "continue",
      researched: true,
      needed: true,
    };
  }
  if (pending > 0) {
    return { label: "Исследован частично", detail: progress, tone: "warning", action: "continue", researched: true, needed: true };
  }
  const when = dateLabel(source.researched_at);
  return {
    label: when ? `Исследован ${when}` : "Исследован",
    detail: unresolved > 0 ? `ждут уточнения: ${unresolved}` : "",
    tone: "success",
    action: "rerun",
    researched: true,
    needed: false,
  };
}

export const RESEARCH_ACTION_LABEL: Record<ResearchAction, string> = {
  research: "Исследовать",
  continue: "Доисследовать",
  rerun: "Исследовать заново",
  progress: "Ход исследования",
};
