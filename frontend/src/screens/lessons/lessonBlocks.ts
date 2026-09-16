import type { LessonBlockCommand, LessonBlockRead, LessonNoteVariant } from "../../api/lessons";
import type { SelectOption } from "../../components/ui";

export const NOTE_VARIANTS: Array<{ value: LessonNoteVariant; label: string }> = [
  { value: "text", label: "Текст" },
  { value: "heading", label: "Заголовок" },
  { value: "explanation", label: "Пояснение" },
  { value: "important", label: "Важно" },
  { value: "example", label: "Пример" },
  { value: "definition", label: "Определение" },
  { value: "warning", label: "Предупреждение" },
];

const VARIANT_LABELS = new Map(NOTE_VARIANTS.map((item) => [item.value, item.label]));

/**
 * Куда встанет добавленный кусок материала.
 *
 * Раньше место вставки было неявным: всё уходило после выбранного блока, а без
 * выбора — в конец урока. Собирая урок из поиска, туда попадает не то, что
 * ожидаешь, поэтому место стало отдельным видимым выбором.
 */
export type LessonInsertPoint =
  | { kind: "end" }
  | { kind: "start" }
  | { kind: "after"; blockId: string };

export const INSERT_AT_END: LessonInsertPoint = { kind: "end" };

/** Строка блока в списке «Куда вставить» — по ней блок узнаётся без прокрутки урока. */
export function blockLabel(block: LessonBlockRead): string {
  if (block.kind === "source") {
    const ref = block.refs.find((item) => item.role === "content") ?? block.refs[0];
    if (!ref) return "Кусок материала";
    const pages = ref.page_from === ref.page_to
      ? `стр. ${ref.page_from}`
      : `стр. ${ref.page_from}–${ref.page_to}`;
    return `${ref.source_name}, ${pages}`;
  }
  if (block.kind === "media") {
    const caption = plainText(block.body_md);
    const kind = block.media_kind === "link" ? "Ссылка" : "Изображение";
    return caption ? `${kind}: ${caption}` : kind;
  }
  if (block.kind === "activity") return "Задание";
  const variant = VARIANT_LABELS.get(block.variant ?? "text") ?? "Текст";
  const text = plainText(block.body_md);
  return text ? `${variant}: ${text}` : `${variant} (пусто)`;
}

/** Разметка и служебные переносы Crepe в подписи не нужны — нужен узнаваемый кусок текста. */
function plainText(body: string | null): string {
  const compact = (body ?? "")
    .replace(/<br\s*\/?>/gi, " ")
    .replace(/[#>*_`~[\]()!]/g, "")
    .replace(/\s+/g, " ")
    .trim();
  return compact.length > 42 ? `${compact.slice(0, 42)}…` : compact;
}

export function insertOptions(blocks: LessonBlockRead[]): SelectOption[] {
  return [
    { value: "end", label: "В конец урока" },
    ...(blocks.length > 0 ? [{ value: "start", label: "В начало урока" }] : []),
    ...blocks.map((block, index) => ({
      value: `after:${block.id}`,
      label: `После ${index + 1}. ${blockLabel(block)}`,
    })),
  ];
}

export function insertValue(point: LessonInsertPoint): string {
  return point.kind === "after" ? `after:${point.blockId}` : point.kind;
}

export function parseInsertValue(value: string): LessonInsertPoint {
  if (value.startsWith("after:")) return { kind: "after", blockId: value.slice("after:".length) };
  return value === "start" ? { kind: "start" } : INSERT_AT_END;
}

/** Короткое «куда» для подписи кнопки: место видно прямо у действия. */
export function insertSummary(point: LessonInsertPoint, blocks: LessonBlockRead[]): string {
  if (point.kind === "start") return "в начало урока";
  if (point.kind === "end") return "в конец урока";
  const index = blocks.findIndex((block) => block.id === point.blockId);
  return index < 0 ? "в конец урока" : `после блока ${index + 1}`;
}

/**
 * Место вставки в полях команды блока.
 *
 * Выбранный блок мог исчезнуть (его удалили или открыли другой урок) — тогда
 * место молча становится концом урока: это единственное место, которое всегда
 * существует.
 */
export function insertPlacement(
  point: LessonInsertPoint,
  blocks: LessonBlockRead[],
): Pick<LessonBlockCommand, "after_block_id" | "before_block_id"> {
  if (point.kind === "start") {
    return blocks.length > 0 ? { before_block_id: blocks[0].id } : {};
  }
  if (point.kind === "after" && blocks.some((block) => block.id === point.blockId)) {
    return { after_block_id: point.blockId };
  }
  return {};
}
