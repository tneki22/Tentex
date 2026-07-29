import type { PropsWithChildren, ReactNode } from "react";

interface EmptyStateProps {
  title: string;
  icon?: ReactNode;
  className?: string;
}

export function EmptyState({
  title,
  icon,
  className = "",
  children,
}: PropsWithChildren<EmptyStateProps>) {
  return (
    <div className={`empty-state ${className}`.trim()}>
      {icon}
      <h3>{title}</h3>
      {children}
    </div>
  );
}
