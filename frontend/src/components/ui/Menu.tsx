import type { ReactNode } from "react";
import { DropdownMenu } from "radix-ui";
import { Tooltip } from "./Tooltip";

export interface MenuItem {
  label: string;
  icon?: ReactNode;
  onSelect: () => void;
  /** Необратимое действие: красится в danger и стоит последним. */
  destructive?: boolean;
  disabled?: boolean;
}

interface MenuProps {
  trigger: ReactNode;
  label: string;
  items: MenuItem[];
  /** Подсказка по наведению — когда у триггера видна только иконка. */
  tooltip?: string;
}

/**
 * Меню редких действий над объектом: архивировать проект, завершить, экспорт.
 * Частому действию в меню не место — оно живёт кнопкой на виду.
 */
export function Menu({ trigger, label, items, tooltip }: MenuProps) {
  // Подсказка оборачивает именно триггер меню: оба примитива отдают свои props
  // одному и тому же элементу через asChild, как в рецепте композиции Radix.
  const triggerNode = <DropdownMenu.Trigger asChild>{trigger}</DropdownMenu.Trigger>;
  return (
    <DropdownMenu.Root>
      {tooltip ? <Tooltip label={tooltip} side="bottom">{triggerNode}</Tooltip> : triggerNode}
      <DropdownMenu.Portal>
        <DropdownMenu.Content className="menu" align="end" sideOffset={6} aria-label={label}>
          {items.map((item) => (
            <DropdownMenu.Item
              key={item.label}
              className={`menu-item ${item.destructive ? "is-destructive" : ""}`.trim()}
              disabled={item.disabled}
              onSelect={item.onSelect}
            >
              {item.icon}
              {item.label}
            </DropdownMenu.Item>
          ))}
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  );
}
