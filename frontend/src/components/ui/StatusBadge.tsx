import type { PropsWithChildren } from "react";

export type StatusTone = "neutral" | "success" | "warning" | "danger" | "info";

interface StatusBadgeProps {
  tone?: StatusTone;
  className?: string;
}

export function StatusBadge({
  tone = "neutral",
  className = "",
  children,
}: PropsWithChildren<StatusBadgeProps>) {
  return <span className={`status-badge tone-${tone} ${className}`.trim()}>{children}</span>;
}
