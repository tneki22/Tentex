import type { ReactNode } from "react";
import { ContextMenu as RadixContextMenu } from "radix-ui";
import { ChevronRight } from "lucide-react";

export interface ContextMenuItem {
  label: string;
  icon?: ReactNode;
  onSelect?: () => void;
  disabled?: boolean;
  destructive?: boolean;
  /** Один уровень вложенности — для «Пометить» и подобных групп выбора. */
  items?: ContextMenuItem[];
}

interface ContextMenuProps {
  trigger: ReactNode;
  label: string;
  items: ContextMenuItem[];
  onCloseAutoFocus?: (event: Event) => void;
}

/**
 * Своё меню по правой кнопке мыши вместо системного. Поведение и позиционирование
 * взяты у Radix (пакет `radix-ui`), внешний вид переиспользует .menu/.menu-item
 * из выпадающего Menu — это одно и то же визуально, только другой триггер.
 */
export function ContextMenu({ trigger, label, items, onCloseAutoFocus }: ContextMenuProps) {
  return (
    <RadixContextMenu.Root>
      <RadixContextMenu.Trigger asChild>{trigger}</RadixContextMenu.Trigger>
      <RadixContextMenu.Portal>
        <RadixContextMenu.Content className="menu" aria-label={label} onCloseAutoFocus={onCloseAutoFocus}>
          {items.map((item) => item.items ? (
            <RadixContextMenu.Sub key={item.label}>
              <RadixContextMenu.SubTrigger className="menu-item">
                {item.icon}{item.label}
                <ChevronRight size={13} className="menu-item-chevron" />
              </RadixContextMenu.SubTrigger>
              <RadixContextMenu.Portal>
                <RadixContextMenu.SubContent className="menu" sideOffset={2} alignOffset={-4}>
                  {item.items.map((sub) => (
                    <RadixContextMenu.Item
                      key={sub.label}
                      className={`menu-item ${sub.destructive ? "is-destructive" : ""}`.trim()}
                      disabled={sub.disabled}
                      onSelect={sub.onSelect}
                    >
                      {sub.icon}{sub.label}
                    </RadixContextMenu.Item>
                  ))}
                </RadixContextMenu.SubContent>
              </RadixContextMenu.Portal>
            </RadixContextMenu.Sub>
          ) : (
            <RadixContextMenu.Item
              key={item.label}
              className={`menu-item ${item.destructive ? "is-destructive" : ""}`.trim()}
              disabled={item.disabled}
              onSelect={item.onSelect}
            >
              {item.icon}{item.label}
            </RadixContextMenu.Item>
          ))}
        </RadixContextMenu.Content>
      </RadixContextMenu.Portal>
    </RadixContextMenu.Root>
  );
}
