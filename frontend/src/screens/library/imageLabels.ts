import type { ImageProcessing, ImageRole } from "../../api/materials";

/** Названия осей изображения — одно место для инвентаря и просмотра фрагмента. */
export const IMAGE_ROLE_LABEL: Record<ImageRole, string> = {
  content: "Содержание",
  service: "Служебное",
  decorative: "Украшение",
  unknown: "Роль не ясна",
};

export const IMAGE_PROCESSING_LABEL: Record<ImageProcessing, string> = {
  unprocessed: "Не обработано",
  text_only: "Только надписи",
  described: "Описано моделью",
  legacy: "Подпись прошлой версии",
  skipped: "Пропущено при разборе",
  error: "Описание не удалось",
};

/** Почему изображение исключено, сомнительно или требует проверки. */
const IMAGE_REASON_LABEL: Record<string, string> = {
  asset_missing: "нет выреза оригинала",
  bbox_unreliable: "рамка неточная",
  repeated_body: "повторяется на нескольких страницах",
  repeated_margin: "повтор в поле страницы — похоже на колонтитул",
  repeated_margin_large: "крупный повтор в поле страницы",
  unsupported_format: "формат выреза не читается",
  missed_by_model: "модель страницы этот участок не прочитала",
  crop_suspect: "вырез обрезан или захватил лишнее",
  crop_cut_off: "обрезан край",
  crop_extra_text: "захвачен лишний текст",
  crop_multiple_objects: "несколько объектов в одном вырезе",
  crop_empty: "вырез пустой",
  crop_unreadable: "не читается",
  tiny: "слишком мелкое",
  page_scan: "скан целой страницы — его читают страницей, а не описанием",
  model_error: "модель не ответила",
  budget_exhausted: "не хватило предела запуска",
  low_confidence: "модель не уверена",
  summary_short: "слишком короткое описание",
  unreadable_parts: "часть надписей не прочитана",
  table_invalid: "таблица без разметки",
  latex_invalid: "формула не собирается",
  empty_answer: "пустой ответ",
  model_role_decorative: "модель сочла украшением",
  model_role_service: "модель сочла служебным",
  image_mode_skip: "изображения пропущены в этом запуске",
};

// Уже сказано состоянием обработки («Подпись прошлой версии») — второй раз не пишем.
const SILENT_REASONS = new Set(["legacy_caption"]);

export function imageReasonText(reasons: readonly string[]): string {
  return reasons
    .filter((reason) => !SILENT_REASONS.has(reason))
    .map((reason) => IMAGE_REASON_LABEL[reason] ?? reason)
    .join(" · ");
}

/** Доллары для оценки: «меньше цента» честнее, чем `0.0004 $`. */
export function usdLabel(value: string | number | null): string {
  if (value === null) return "цена неизвестна";
  const usd = Number(value);
  if (usd >= 1) return `${usd.toFixed(2)} $`;
  if (usd >= 0.01) return `${usd.toFixed(3)} $`;
  return "меньше цента";
}
