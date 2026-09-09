import type { MaterialPresentationKind, PageQuality } from "../../api/materials";
import type { SearchHighlightRead, SearchResultRead } from "../../api/search";

/**
 * Найденное место — одна страница одного файла.
 *
 * Сервер ранжирует и группирует попадания по блоку, поэтому в выдаче стоит
 * «стр. 71–75»: где именно совпало, из такой строки не понять. Здесь та же
 * выдача пересобирается по страницам — единице, которую пользователь листает и
 * привязывает.
 */
export interface SourcePlace {
  /** `${materialId}:${pageNumber}` — устойчивый ключ строки и скрытых мест. */
  key: string;
  materialId: string;
  materialName: string;
  presentationKind: MaterialPresentationKind;
  pageNumber: number;
  /** Найденные фрагменты этой страницы, без повторов, в порядке ранга. */
  fragmentIds: string[];
  text: string;
  highlights: SearchHighlightRead[];
  quality: PageQuality;
  alreadyBound: boolean;
}

export const placeKey = (materialId: string, pageNumber: number): string =>
  `${materialId}:${pageNumber}`;

/**
 * Собрать выдачу поиска в список страниц.
 *
 * Порядок — по первому появлению страницы в ранжированной выдаче: лучший ранг
 * остаётся первым, и своя сортировка поверх BM25 не изобретается. Одну и ту же
 * страницу, попавшую в выдачу из разных блоков, места сливают в одну строку.
 */
export function toSourcePlaces(results: SearchResultRead[]): SourcePlace[] {
  const places = new Map<string, SourcePlace>();
  for (const result of results) {
    for (const page of result.pages) {
      const key = placeKey(result.material_id, page.page_number);
      const existing = places.get(key);
      if (!existing) {
        places.set(key, {
          key,
          materialId: result.material_id,
          materialName: result.material_name,
          presentationKind: result.presentation_kind,
          pageNumber: page.page_number,
          fragmentIds: [...page.fragment_ids],
          text: page.text,
          highlights: page.highlights,
          quality: page.quality,
          alreadyBound: page.already_bound,
        });
        continue;
      }
      for (const fragmentId of page.fragment_ids) {
        if (!existing.fragmentIds.includes(fragmentId)) existing.fragmentIds.push(fragmentId);
      }
      existing.alreadyBound = existing.alreadyBound || page.already_bound;
    }
  }
  return [...places.values()];
}

/** Места одного файла подряд, страницы по возрастанию — так их листает читатель. */
export interface SourcePlaceGroup {
  materialId: string;
  materialName: string;
  places: SourcePlace[];
}

export function groupPlacesByMaterial(places: SourcePlace[]): SourcePlaceGroup[] {
  const groups = new Map<string, SourcePlaceGroup>();
  for (const place of places) {
    const group = groups.get(place.materialId);
    if (group) group.places.push(place);
    else {
      groups.set(place.materialId, {
        materialId: place.materialId,
        materialName: place.materialName,
        places: [place],
      });
    }
  }
  for (const group of groups.values()) {
    group.places.sort((left, right) => left.pageNumber - right.pageNumber);
  }
  return [...groups.values()];
}
