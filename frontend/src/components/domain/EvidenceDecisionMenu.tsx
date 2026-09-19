import { Check, Eye, EyeOff, MoreHorizontal, Pin, RotateCcw, Unlink } from "lucide-react";
import type { CoverageDecisionAction, EvidenceDetail } from "../../api/coverage";
import { IconButton, Menu } from "../ui";

interface EvidenceDecisionMenuProps {
  evidence: EvidenceDetail;
  busy?: boolean;
  onAction(action: CoverageDecisionAction, role?: "definition" | "explanation" | "example"): void;
}

/** Редкие решения связи; чтение и вставка в урок остаются видимыми кнопками. */
export function EvidenceDecisionMenu({ evidence, busy = false, onAction }: EvidenceDecisionMenuProps) {
  const removed = evidence.status === "removed";
  return (
    <Menu
      label="Решения по связи"
      tooltip="Решения по связи"
      trigger={<IconButton label="Решения по связи" disabled={busy}><MoreHorizontal size={15} /></IconButton>}
      items={[
        { label: "Подтвердить связь", icon: <Check size={14} />, disabled: removed, onSelect: () => onAction("confirm") },
        { label: evidence.preferred ? "Не открывать первой" : "Читать первой", icon: <Pin size={14} />, disabled: removed, onSelect: () => onAction(evidence.preferred ? "clear_prefer" : "prefer") },
        { label: "Считать определением", disabled: removed, onSelect: () => onAction("change_role", "definition") },
        { label: "Считать объяснением", disabled: removed, onSelect: () => onAction("change_role", "explanation") },
        { label: "Считать примером", disabled: removed, onSelect: () => onAction("change_role", "example") },
        { label: evidence.hidden ? "Вернуть в рекомендации" : "Скрыть из рекомендаций", icon: evidence.hidden ? <Eye size={14} /> : <EyeOff size={14} />, onSelect: () => onAction(evidence.hidden ? "show" : "hide") },
        removed
          ? { label: "Восстановить связь", icon: <RotateCcw size={14} />, onSelect: () => onAction("restore") }
          : { label: "Снять связь", icon: <Unlink size={14} />, destructive: true, onSelect: () => onAction("remove") },
      ]}
    />
  );
}
