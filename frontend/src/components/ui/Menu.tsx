import type { ReactNode } from "react";
import { DropdownMenu } from "radix-ui";

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
}

/**
 * Меню редких действий над объектом: архивировать проект, завершить, экспорт.
 * Частому действию в меню не место — оно живёт кнопкой на виду.
 */
export function Menu({ trigger, label, items }: MenuProps) {
  return (
    <DropdownMenu.Root>
      <DropdownMenu.Trigger asChild>{trigger}</DropdownMenu.Trigger>
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
