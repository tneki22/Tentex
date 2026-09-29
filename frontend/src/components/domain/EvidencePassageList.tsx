import type { ReactNode } from "react";
import type { EvidenceSummary, TopicEvidence } from "../../api/coverage";
import { Disclosure } from "../ui";
import { EvidenceCard } from "./EvidenceCard";

type GroupKey = keyof Pick<TopicEvidence, "starter" | "explanations" | "practice" | "depth" | "mentions" | "legacy" | "hidden">;

const PRIMARY: Array<[GroupKey, string]> = [
  ["starter", "С чего начать"],
  ["explanations", "Объяснения"],
  ["practice", "Примеры и практика"],
  ["depth", "Углубление и связи"],
];

const SECONDARY: Array<[GroupKey, string]> = [
  ["mentions", "Упоминания"],
  ["legacy", "Из уроков и оглавления"],
  ["hidden", "Скрытые"],
];

export const PRIMARY_GROUPS = PRIMARY.map(([key]) => key);

/** Основные куски темы в порядке чтения списка: с них собирается урок. */
export function primaryPassages(groups: TopicEvidence | null): EvidenceSummary[] {
  return groups ? PRIMARY_GROUPS.flatMap((key) => groups[key]) : [];
}

/**
 * Порядок книги для вставки в урок: материалы — как в списке, внутри — по страницам.
 * Группы списка идут по назначению (определение, примеры), а урок читается подряд.
 */
export function inReadingOrder(items: EvidenceSummary[], list: EvidenceSummary[]): EvidenceSummary[] {
  const materials = new Map<string, number>();
  for (const item of list) if (!materials.has(item.material_id)) materials.set(item.material_id, materials.size);
  const index = new Map(list.map((item, position) => [item.id, position]));
  return [...items].sort((a, b) => (materials.get(a.material_id) ?? 0) - (materials.get(b.material_id) ?? 0)
    || a.page_from - b.page_from
    || (index.get(a.id) ?? 0) - (index.get(b.id) ?? 0));
}

interface EvidencePassageListProps {
  groups: TopicEvidence;
  selectedId: string | null;
  onSelect(item: EvidenceSummary): void;
  /** Упоминания, куски из уроков и скрытые — свёрнутыми разделами под основными. */
  secondary?: boolean;
  checkedIds?: ReadonlySet<string>;
  onCheckedChange?(item: EvidenceSummary, checked: boolean): void;
  badge?(item: EvidenceSummary): ReactNode;
}

/**
 * Куски темы по назначению: с чего начать, объяснения, примеры. Упоминания и то,
 * что пришло из уроков и оглавления, не смешиваются с опорами — раньше заголовки,
 * строки оглавления и номера страниц стояли в одном списке с определениями.
 */
export function EvidencePassageList({
  groups,
  selectedId,
  onSelect,
  secondary = false,
  checkedIds,
  onCheckedChange,
  badge,
}: EvidencePassageListProps) {
  const card = (item: EvidenceSummary) => (
    <EvidenceCard
      key={item.id}
      evidence={item}
      selected={item.id === selectedId}
      onSelect={() => onSelect(item)}
      checked={checkedIds?.has(item.id)}
      onCheckedChange={onCheckedChange && ((checked) => onCheckedChange(item, checked))}
      badge={badge?.(item)}
    />
  );
  return (
    <div className="evidence-passage-list">
      {PRIMARY.map(([key, label]) => groups[key].length > 0 && (
        <section key={key} aria-label={label}>
          <h3>{label}</h3>
          {groups[key].map(card)}
        </section>
      ))}
      {secondary && SECONDARY.map(([key, label]) => groups[key].length > 0 && (
        <Disclosure
          key={key}
          className="evidence-passage-more"
          summary={`${label} (${groups[key].length})`}
          defaultOpen={groups[key].some((item) => item.id === selectedId)}
        >
          {groups[key].map(card)}
        </Disclosure>
      ))}
    </div>
  );
}
