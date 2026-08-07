import { StatusBadge } from "../ui";
import type { StatusTone } from "../ui";

/** Флаг качества страницы: родной текст · распознано · распознано плохо. */
export type PageQuality = "native" | "ocr" | "ocr_low";

/**
 * Качество распознавания страницы. Показывается везде, где показан фрагмент:
 * материалы, библиотека, просмотрщик, среда темы, разбор ответа.
 *
 * Смысл виджета — требование «текст с плохой страницы никогда не выдаётся за
 * достоверный». Поэтому у ocr_low тон warning: это не ошибка системы, а
 * предупреждение читателю о том, чему он собирается верить.
 */
const QUALITY: Record<PageQuality, { label: string; tone: StatusTone; title: string }> = {
  native: { label: "native", tone: "neutral", title: "Родной текстовый слой файла" },
  ocr: { label: "ocr", tone: "info", title: "Распознано с картинки, качество приемлемое" },
  ocr_low: { label: "ocr_low", tone: "warning", title: "Распознано плохо — сверяйте со страницей" },
};

export const PAGE_QUALITIES = Object.keys(QUALITY) as PageQuality[];

interface QualityBadgeProps {
  quality: PageQuality;
  /** Число страниц с этим флагом. Без него — просто метка качества. */
  count?: number;
}

export function QualityBadge({ quality, count }: QualityBadgeProps) {
  const { label, tone, title } = QUALITY[quality];
  return (
    <span title={title}>
      <StatusBadge tone={tone}>{count === undefined ? label : `${label} ${count}`}</StatusBadge>
    </span>
  );
}
