import type { OutlineItem, OutlineSource } from "../../../api/materials";

export interface OutlineDraftItem extends OutlineItem {
  outline_item_key: string;
}

export interface OutlineDraftState {
  material_id: string;
  source: OutlineSource;
  items: OutlineDraftItem[];
  source_pages: number[];
  review_pages: number[];
  review_needs_check: boolean;
  edited: boolean;
  checked_at: string | null;
}

export type OutlinesByMaterialId = Record<string, OutlineDraftState>;

/** Добавляет стабильные ключи один раз; дальнейшие ручные правки их сохраняют. */
export function outlineItemsWithKeys(
  materialId: string,
  source: OutlineSource,
  items: OutlineItem[],
): OutlineDraftItem[] {
  return items.map((item, index) => ({
    ...item,
    outline_item_key: "outline_item_key" in item && typeof item.outline_item_key === "string"
      ? item.outline_item_key
      : `${materialId}:${source}:${index}:${item.page}:${item.level}`,
  }));
}
