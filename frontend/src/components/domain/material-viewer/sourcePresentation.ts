import type { MaterialPresentationKind } from "../../../api/materials";
import type { MaterialPresentation } from "./types";

const PRESENTATIONS: Record<MaterialPresentationKind, Omit<MaterialPresentation, "kind">> = {
  pdf: {
    defaultMode: "source",
    sourceLabel: "Оригинал",
    textLabel: "Подготовленный текст",
    processingTitle: "Распознавание",
    supportsZoom: true,
    supportsOutline: true,
    supportsTimeline: false,
  },
  image: {
    defaultMode: "source",
    sourceLabel: "Изображение",
    textLabel: "Распознанный текст",
    processingTitle: "Распознавание",
    supportsZoom: true,
    supportsOutline: false,
    supportsTimeline: false,
  },
  document: {
    // Пиксельной копии Word конвейер не обещает, поэтому не «Оригинальная
    // страница», а честный «Документ».
    defaultMode: "compare",
    sourceLabel: "Документ",
    textLabel: "Подготовленный текст",
    processingTitle: "Разбор документа",
    supportsZoom: false,
    supportsOutline: true,
    supportsTimeline: false,
  },
  plain_text: {
    defaultMode: "text",
    sourceLabel: "Исходный текст",
    textLabel: "Подготовленный текст",
    processingTitle: "Подготовка текста",
    supportsZoom: false,
    supportsOutline: true,
    supportsTimeline: false,
  },
  web: {
    defaultMode: "text",
    sourceLabel: "Сохранённая страница",
    textLabel: "Подготовленный текст",
    processingTitle: "Снимок и извлечение",
    supportsZoom: false,
    supportsOutline: true,
    supportsTimeline: false,
  },
  youtube: {
    defaultMode: "text",
    sourceLabel: "Источник",
    textLabel: "Расшифровка",
    processingTitle: "Субтитры",
    supportsZoom: false,
    supportsOutline: false,
    supportsTimeline: true,
  },
  audio: {
    defaultMode: "text",
    sourceLabel: "Запись",
    textLabel: "Расшифровка",
    processingTitle: "Расшифровка",
    supportsZoom: false,
    supportsOutline: false,
    supportsTimeline: true,
  },
};

/**
 * Чистая функция: вид источника → как его называть и чем показывать.
 *
 * Полнота таблицы проверяется типом `Record<MaterialPresentationKind, …>`:
 * новый вид не даст собраться проекту, пока для него не описали подписи.
 * Молчаливый откат в PDF-умолчание врал бы пользователю.
 */
export function getMaterialPresentation(kind: MaterialPresentationKind): MaterialPresentation {
  return { kind, ...PRESENTATIONS[kind] };
}
