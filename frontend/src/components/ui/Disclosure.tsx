import { useState } from "react";
import type { PropsWithChildren } from "react";
import { ChevronRight } from "lucide-react";
import { Collapsible } from "radix-ui";

interface DisclosureProps {
  /** Заголовок с числом: «Архив и завершённые (2)». */
  summary: string;
  defaultOpen?: boolean;
  /** Управляемое состояние — когда раскрыть блок решает экран, а не пользователь. */
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
  className?: string;
}

/**
 * Раскрывающийся блок: архив проектов, «Модули — изменить», подробности файла.
 * Высота содержимого анимируется через --radix-collapsible-content-height.
 */
export function Disclosure({
  summary,
  defaultOpen = false,
  open: controlledOpen,
  onOpenChange,
  className = "",
  children,
}: PropsWithChildren<DisclosureProps>) {
  const [uncontrolledOpen, setUncontrolledOpen] = useState(defaultOpen);
  const open = controlledOpen ?? uncontrolledOpen;

  return (
    <Collapsible.Root
      open={open}
      onOpenChange={(next) => {
        setUncontrolledOpen(next);
        onOpenChange?.(next);
      }}
      className={`disclosure ${className}`.trim()}
    >
      <Collapsible.Trigger className="disclosure-trigger">
        <ChevronRight size={15} aria-hidden="true" />
        {summary}
      </Collapsible.Trigger>
      <Collapsible.Content className="disclosure-content">
        <div className="disclosure-inner">{children}</div>
      </Collapsible.Content>
    </Collapsible.Root>
  );
}
