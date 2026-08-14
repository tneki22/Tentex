import { StatusBadge } from "../ui";
import type { StatusTone } from "../ui";

/** Флаг качества страницы. Значения — внутренние, из хранилища. */
export type PageQuality = "native" | "ocr" | "ocr_low";

/**
 * Качество распознавания страницы. Показывается везде, где показан фрагмент:
 * материалы, Библиотека, просмотрщик, среда темы, разбор ответа.
 *
 * Смысл виджета — требование «текст с плохой страницы никогда не выдаётся за
 * достоверный». Поэтому у «Нужно проверить» тон warning: это не ошибка системы,
 * а предупреждение читателю о том, чему он собирается верить.
 *
 * Это единственная точка перевода внутренних значений в человеческие: строк
 * `native`, `ocr` и `ocr_low` в пользовательском тексте быть не должно.
 */
const QUALITY: Record<PageQuality, { label: string; tone: StatusTone; title: string }> = {
  native: {
    label: "Текст из файла",
    tone: "neutral",
    title: "Текст взят из текстового слоя документа.",
  },
  ocr: {
    label: "Распознано",
    tone: "info",
    title: "Текст распознан по изображению.",
  },
  ocr_low: {
    label: "Нужно проверить",
    tone: "warning",
    title: "Распознавание могло ошибиться — сравните текст с оригиналом.",
  },
};

export const PAGE_QUALITIES = Object.keys(QUALITY) as PageQuality[];

/** Подпись качества отдельной строкой: сводки, подсказки, aria-label. */
export function qualityLabel(quality: PageQuality): string {
  return QUALITY[quality].label;
}

/** Пояснение: почему этому тексту можно или нельзя верить. */
export function qualityHint(quality: PageQuality): string {
  return QUALITY[quality].title;
}

interface QualityBadgeProps {
  quality: PageQuality;
  /** Число страниц с этим флагом. Без него — просто метка качества. */
  count?: number;
}

export function QualityBadge({ quality, count }: QualityBadgeProps) {
  const { label, tone, title } = QUALITY[quality];
  return (
    <span title={title}>
      <StatusBadge tone={tone}>{count === undefined ? label : `${label}: ${count}`}</StatusBadge>
    </span>
  );
}
