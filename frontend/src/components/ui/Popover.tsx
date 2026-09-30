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
  /** Закрытие возвращает фокус кнопке-триггеру; `preventDefault()` отменяет
   *  это, когда следом открывается другая всплывашка: возвращённый фокус
   *  оказался бы «снаружи» неё и тут же её закрыл. */
  onCloseAutoFocus?: (event: Event) => void;
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
  onCloseAutoFocus,
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
          onCloseAutoFocus={onCloseAutoFocus}
        >
          {title && <p className="popover-title">{title}</p>}
          {children}
          <RadixPopover.Arrow className="popover-arrow" width={12} height={6} />
        </RadixPopover.Content>
      </RadixPopover.Portal>
    </RadixPopover.Root>
  );
}
