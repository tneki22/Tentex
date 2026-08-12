import type { PropsWithChildren, ReactNode } from "react";
import { Popover as RadixPopover } from "radix-ui";

interface PopoverProps {
  /** Что нажимают, чтобы открыть. Оборачивается asChild: своя разметка сохраняется. */
  trigger: ReactNode;
  /** Заголовок всплывашки. Без него содержимое читается как обрывок. */
  title?: string;
  align?: "start" | "center" | "end";
  side?: "top" | "right" | "bottom" | "left";
  className?: string;
  /** Управляемое состояние — нужно, чтобы закрыть всплывашку по выбору пункта списка внутри. */
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
}

/**
 * Всплывашка: состояние фоновых задач, «чего не хватает до следующего статуса»,
 * подробности метрики. Немодальная — работать под ней можно.
 *
 * Позиционирование, фокус, Esc и клик мимо — на Radix: сами мы это писали бы
 * долго и хуже (правило «готовое вместо своего»).
 */
export function Popover({
  trigger,
  title,
  align = "start",
  side = "right",
  className = "",
  open,
  onOpenChange,
  children,
}: PropsWithChildren<PopoverProps>) {
  return (
    <RadixPopover.Root open={open} onOpenChange={onOpenChange}>
      <RadixPopover.Trigger asChild>{trigger}</RadixPopover.Trigger>
      <RadixPopover.Portal>
        <RadixPopover.Content
          className={`popover ${className}`.trim()}
          side={side}
          align={align}
          sideOffset={8}
          collisionPadding={12}
        >
          {title && <p className="popover-title">{title}</p>}
          {children}
          <RadixPopover.Arrow className="popover-arrow" width={12} height={6} />
        </RadixPopover.Content>
      </RadixPopover.Portal>
    </RadixPopover.Root>
  );
}
