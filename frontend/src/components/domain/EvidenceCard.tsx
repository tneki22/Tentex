import { BookOpenText, Pin } from "lucide-react";
import type { EvidenceSummary } from "../../api/coverage";
import { QualityBadge } from "./QualityBadge";

const ROLE_LABELS: Record<string, string> = {
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
}

/** Компактная опора: источник и роль видны до открытия полного текста. */
export function EvidenceCard({ evidence, selected = false, onSelect }: EvidenceCardProps) {
  return (
    <button
      type="button"
      className={`evidence-card ${selected ? "is-selected" : ""}`.trim()}
      onClick={onSelect}
      aria-pressed={selected}
    >
      <span className="evidence-card-head">
        <BookOpenText size={15} />
        <strong>{evidence.material_name}</strong>
        {evidence.preferred && <Pin size={13} aria-label="Открывается первой" />}
      </span>
      <span className="evidence-card-quote">{evidence.quote}</span>
      <span className="evidence-card-meta">
        стр. {evidence.page_from}{evidence.page_to !== evidence.page_from ? `–${evidence.page_to}` : ""}
        {evidence.roles.length > 0 && ` · ${evidence.roles.map((role) => ROLE_LABELS[role] ?? role).join(", ")}`}
      </span>
      <QualityBadge quality={evidence.quality} />
    </button>
  );
}
