import { StatusBadge } from "../ui";
import type { StatusTone } from "../ui";

/** Пять статусов темы из §11.4 требований. Порядок — порядок продвижения. */
export type TopicStatus = "no-material" | "has-material" | "studied" | "drilled" | "mastered";

/**
 * Статус темы одним видом на всех экранах: карта покрытия, среда темы, покрытие,
 * план. Тон закреплён за статусом здесь и больше нигде не выбирается — иначе
 * «освоен» окажется зелёным на одном экране и синим на другом.
 *
 * «Нет материала» — нейтральный, а не danger: у проекта из входа C так выглядят
 * все темы на старте, и это нормальное состояние, а не ошибка.
 */
const STATUS: Record<TopicStatus, { label: string; tone: StatusTone }> = {
  "no-material": { label: "нет материала", tone: "neutral" },
  "has-material": { label: "есть материал", tone: "info" },
  studied: { label: "разобран", tone: "info" },
  drilled: { label: "отработан", tone: "success" },
  mastered: { label: "освоен", tone: "success" },
};

export const TOPIC_STATUSES = Object.keys(STATUS) as TopicStatus[];

export function TopicStatusBadge({ status }: { status: TopicStatus }) {
  const { label, tone } = STATUS[status];
  return <StatusBadge tone={tone}>{label}</StatusBadge>;
}

export function topicStatusLabel(status: TopicStatus): string {
  return STATUS[status].label;
}
