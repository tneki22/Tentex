import type { PropsWithChildren, ReactNode } from "react";
import { HoverCard as RadixHoverCard } from "radix-ui";

interface HoverCardProps {
  /** Что наводят. Оборачивается asChild: своя разметка сохраняется. */
  trigger: ReactNode;
  side?: "top" | "right" | "bottom" | "left";
  align?: "start" | "center" | "end";
  className?: string;
}

/**
 * Карточка по наведению с содержимым, с которым можно работать: в отличие от
 * `Tooltip`, внутрь можно положить переключатели и поля. Открывается и по
 * фокусу триггера, поэтому строка списка остаётся доступной с клавиатуры.
 *
 * Задержка та же, что у `TooltipProvider` — иначе при проходе курсора по
 * списку карточки мигали бы вразнобой с подсказками.
 */
export function HoverCard({
  trigger,
  side = "right",
  align = "start",
  className = "",
  children,
}: PropsWithChildren<HoverCardProps>) {
  return (
    <RadixHoverCard.Root openDelay={400} closeDelay={120}>
      <RadixHoverCard.Trigger asChild>{trigger}</RadixHoverCard.Trigger>
      <RadixHoverCard.Portal>
        <RadixHoverCard.Content
          className={`hover-card ${className}`.trim()}
          side={side}
          align={align}
          sideOffset={8}
          collisionPadding={12}
        >
          {children}
          <RadixHoverCard.Arrow className="hover-card-arrow" width={12} height={6} />
        </RadixHoverCard.Content>
      </RadixHoverCard.Portal>
    </RadixHoverCard.Root>
  );
}
