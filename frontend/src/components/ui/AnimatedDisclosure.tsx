import { ChevronDown } from "lucide-react";
import type { PropsWithChildren, ReactNode } from "react";
import { useId, useState } from "react";

interface AnimatedDisclosureProps {
  title: ReactNode;
  open?: boolean;
  defaultOpen?: boolean;
  onOpenChange?: (open: boolean) => void;
  className?: string;
}

export function AnimatedDisclosure({
  title,
  open,
  defaultOpen = false,
  onOpenChange,
  className = "",
  children,
}: PropsWithChildren<AnimatedDisclosureProps>) {
  const [internalOpen, setInternalOpen] = useState(defaultOpen);
  const contentId = useId();
  const expanded = open ?? internalOpen;

  function toggle() {
    const next = !expanded;
    if (open === undefined) setInternalOpen(next);
    onOpenChange?.(next);
  }

  return (
    <section className={`animated-disclosure ${expanded ? "is-open" : ""} ${className}`.trim()}>
      <button
        type="button"
        className="animated-disclosure-trigger"
        aria-expanded={expanded}
        aria-controls={contentId}
        onClick={toggle}
      >
        <span className="animated-disclosure-title">{title}</span>
        <ChevronDown className="animated-disclosure-icon" size={16} aria-hidden="true" />
      </button>
      {expanded && (
        <div id={contentId} className="animated-disclosure-content">
          {children}
        </div>
      )}
    </section>
  );
}
