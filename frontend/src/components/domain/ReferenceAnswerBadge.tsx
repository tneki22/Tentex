import type { ReferenceAnswerStatus } from "../../api/projects";
import { StatusBadge } from "../ui";
import type { StatusTone } from "../ui";

const ANSWER_STATUS: Record<ReferenceAnswerStatus, { label: string; tone: StatusTone }> = {
  missing: { label: "нет ответа", tone: "neutral" },
  auto_matched: { label: "найден автоматически", tone: "info" },
  confirmed: { label: "подтверждён", tone: "success" },
  needs_review: { label: "нужно проверить", tone: "warning" },
  manual: { label: "добавлен вручную", tone: "success" },
};

export const REFERENCE_ANSWER_STATUSES = Object.keys(ANSWER_STATUS) as ReferenceAnswerStatus[];

export function ReferenceAnswerBadge({ status }: { status: ReferenceAnswerStatus }) {
  const value = ANSWER_STATUS[status];
  return <StatusBadge tone={value.tone}>{value.label}</StatusBadge>;
}

export function referenceAnswerStatusLabel(status: ReferenceAnswerStatus): string {
  return ANSWER_STATUS[status].label;
}
