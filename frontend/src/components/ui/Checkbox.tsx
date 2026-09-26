import { useId } from "react";
import { Check } from "lucide-react";

interface CheckboxProps {
  checked: boolean;
  onCheckedChange: (checked: boolean) => void;
  label: string;
  disabled?: boolean;
}

/**
 * Флажок: исключить тему в мастере, выделить поддерево для массового действия,
 * фильтры карты покрытия. От тумблера отличается смыслом: флажок — это выбор
 * в наборе, тумблер — включение режима.
 *
 * Разметка повторяет Radix Checkbox (`button[role=checkbox]`, `data-state`,
 * индикатор только у отмеченного), но без его контекстов и Presence: флажок
 * стоит в каждой строке дерева программы, и у учебника на 669 узлов Radix-версия
 * добавляла около секунды к каждому рендеру дерева. Поля формы у флажка нет —
 * значение всегда читают из состояния экрана.
 */
export function Checkbox({ checked, onCheckedChange, label, disabled }: CheckboxProps) {
  const id = useId();
  const state = checked ? "checked" : "unchecked";

  return (
    <div className="checkbox-row">
      <button
        id={id}
        type="button"
        role="checkbox"
        aria-checked={checked}
        data-state={state}
        data-disabled={disabled ? "" : undefined}
        className="checkbox"
        disabled={disabled}
        onClick={() => onCheckedChange(!checked)}
        // По WAI-ARIA флажок переключает пробел; Enter — нет (как в Radix).
        onKeyDown={(event) => { if (event.key === "Enter") event.preventDefault(); }}
      >
        {checked && (
          <span className="checkbox-indicator" data-state={state}>
            <Check size={12} strokeWidth={3} aria-hidden="true" />
          </span>
        )}
      </button>
      <label htmlFor={id} title={label}>{label}</label>
    </div>
  );
}
