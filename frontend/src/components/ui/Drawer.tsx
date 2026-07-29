import type { PropsWithChildren } from "react";

interface DrawerProps {
  id?: string;
  label: string;
  open: boolean;
  side?: "left" | "right";
  className?: string;
}

export function Drawer({
  id,
  label,
  open,
  side = "right",
  className = "",
  children,
}: PropsWithChildren<DrawerProps>) {
  return (
    <aside
      id={id}
      className={`drawer-panel drawer-${side} ${open ? "is-open" : ""} ${className}`.trim()}
      aria-label={label}
      aria-hidden={!open}
    >
      {children}
    </aside>
  );
}
