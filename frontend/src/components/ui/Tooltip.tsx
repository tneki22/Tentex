import type { PropsWithChildren, ReactNode } from "react";
import { Tooltip as RadixTooltip } from "radix-ui";

interface TooltipProps {
  /** Короткая подпись. Длинному тексту место в тексте экрана, а не в подсказке. */
  label: ReactNode;
  side?: "top" | "right" | "bottom" | "left";
}

/**
 * Подсказка для того, что подписать негде: иконка в свёрнутой панели,
 * сокращённая метрика. Не носитель смысла — дублирует уже понятное.
 */
export function Tooltip({ label, side = "right", children }: PropsWithChildren<TooltipProps>) {
  return (
    <RadixTooltip.Root>
      <RadixTooltip.Trigger asChild>{children}</RadixTooltip.Trigger>
      <RadixTooltip.Portal>
        <RadixTooltip.Content className="tooltip" side={side} sideOffset={8}>
          {label}
          <RadixTooltip.Arrow className="tooltip-arrow" width={10} height={5} />
        </RadixTooltip.Content>
      </RadixTooltip.Portal>
    </RadixTooltip.Root>
  );
}

/** Один провайдер на приложение: задержка появления общая для всех подсказок. */
export function TooltipProvider({ children }: PropsWithChildren) {
  return <RadixTooltip.Provider delayDuration={400}>{children}</RadixTooltip.Provider>;
}
