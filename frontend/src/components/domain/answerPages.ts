import type { BindingFragmentRead } from "../../api/bindings";
import type { ReferenceAnswerRead } from "../../api/projects";

export interface AnswerScanGroup {
  materialId: string;
  materialName: string;
  /** Номера страниц по возрастанию, без пропусков внутри диапазона ответа. */
  pages: number[];
}

/**
 * Страницы документа, на которых лежит ответ на вопрос.
 *
 * Два источника, потому что одного не хватает. Диапазон `source_page_from…to`
 * есть только у эталонов, приехавших из файла ответов. Привязки есть и у
 * вписанных руками: страницу с ответом можно отметить выделением в Материалах.
 * Берём объединение — иначе режим сканов молча пуст на половине вопросов.
 *
 * Страница показывается целиком, даже если ответ занимает её половину: обрезать
 * по координатам фрагментов значит рисковать потерять формулу или подпись
 * к рисунку, которые в разбор не попали.
 */
export function answerScanGroups(
  answer: ReferenceAnswerRead | null,
  bindings: BindingFragmentRead[],
  materialNameById?: Map<string, string>,
): AnswerScanGroup[] {
  const pages = new Map<string, Set<number>>();
  const names = new Map<string, string>();

  for (const binding of bindings) {
    const known = pages.get(binding.material_id) ?? new Set<number>();
    known.add(binding.page_number);
    pages.set(binding.material_id, known);
    names.set(binding.material_id, binding.material_name);
  }

  const ownMaterialId = answer?.is_active ? answer.source_material_id : null;
  if (ownMaterialId && answer?.source_page_from) {
    const from = answer.source_page_from;
    const to = answer.source_page_to ?? from;
    const known = pages.get(ownMaterialId) ?? new Set<number>();
    for (let page = from; page <= to; page += 1) known.add(page);
    pages.set(ownMaterialId, known);
  }

  const groups = [...pages.entries()].map(([materialId, known]) => ({
    materialId,
    materialName: materialNameById?.get(materialId) ?? names.get(materialId) ?? "Материал проекта",
    pages: [...known].sort((left, right) => left - right),
  }));

  // Файл, из которого собран сам эталон, идёт первым: с него читают.
  return groups.sort((left, right) => {
    if (left.materialId === ownMaterialId) return -1;
    if (right.materialId === ownMaterialId) return 1;
    return left.materialName.localeCompare(right.materialName, "ru");
  });
}

export function scanPageCount(groups: AnswerScanGroup[]): number {
  return groups.reduce((total, group) => total + group.pages.length, 0);
}
