import type { ReactNode } from "react";
import { Pin } from "lucide-react";
import type { EvidenceSummary } from "../../api/coverage";
import { QualityBadge } from "./QualityBadge";

export const ROLE_LABELS: Record<string, string> = {
  definition: "определение",
  explanation: "объяснение",
  example: "пример",
  exercise: "практика",
  reference: "справка",
};

interface EvidenceCardProps {
  evidence: EvidenceSummary;
  selected?: boolean;
  onSelect(): void;
  /** Флажок множественного выбора; без обработчика карточка его не рисует. */
  checked?: boolean;
  onCheckedChange?(checked: boolean): void;
  /** Метка поверх подписи: «уже в уроке», «пересекается». */
  badge?: ReactNode;
}

export function pagesLabel(from: number, to: number): string {
  return from === to ? `стр. ${from}` : `стр. ${from}–${to}`;
}

function fragmentsLabel(count: number): string {
  const tail = count % 100;
  const last = count % 10;
  const word = tail >= 11 && tail <= 14 ? "фрагментов"
    : last === 1 ? "фрагмент"
      : last >= 2 && last <= 4 ? "фрагмента"
        : "фрагментов";
  return `${count} ${word}`;
}

/**
 * Кусок чтения: название раздела, начало текста, место и роль. Выбор флажком не
 * открывает кусок, клик по карточке не меняет выбор — это два разных действия.
 */
export function EvidenceCard({ evidence, selected = false, onSelect, checked, onCheckedChange, badge }: EvidenceCardProps) {
  const roles = evidence.roles.map((role) => ROLE_LABELS[role] ?? role).join(", ");
  return (
    <div className={`evidence-card ${selected ? "is-selected" : ""} ${checked ? "is-checked" : ""}`.trim()}>
      {onCheckedChange && (
        <input
          type="checkbox"
          className="evidence-card-check"
          checked={Boolean(checked)}
          aria-label={`Выбрать «${evidence.title || evidence.quote.slice(0, 40)}»`}
          onChange={(event) => onCheckedChange(event.target.checked)}
        />
      )}
      <button type="button" className="evidence-card-body" onClick={onSelect} aria-pressed={selected}>
        <span className="evidence-card-head">
          <strong>{evidence.title || evidence.material_name}</strong>
          {evidence.preferred && <Pin size={13} aria-label="Открывается первым" />}
        </span>
        <span className="evidence-card-quote">{evidence.quote}</span>
        <span className="evidence-card-meta">
          {evidence.title && <span className="evidence-card-source">{evidence.material_name}</span>}
          <span>{pagesLabel(evidence.page_from, evidence.page_to)} · {fragmentsLabel(evidence.fragment_count)}{roles && ` · ${roles}`}</span>
        </span>
      </button>
      {(badge || evidence.quality !== "native") && (
        <span className="evidence-card-foot">
          {badge}
          <QualityBadge quality={evidence.quality} />
        </span>
      )}
    </div>
  );
}
