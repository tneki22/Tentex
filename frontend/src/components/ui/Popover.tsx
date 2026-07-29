import type { PropsWithChildren } from "react";

interface PopoverProps {
  id?: string;
  label: string;
  className?: string;
}

export function Popover({ id, label, className = "", children }: PropsWithChildren<PopoverProps>) {
  return (
    <div id={id} className={`popover-surface ${className}`.trim()} role="region" aria-label={label}>
      {children}
    </div>
  );
}
