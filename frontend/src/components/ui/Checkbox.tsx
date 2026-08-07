import { useId } from "react";
import { Check } from "lucide-react";
import { Checkbox as RadixCheckbox } from "radix-ui";

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
 */
export function Checkbox({ checked, onCheckedChange, label, disabled }: CheckboxProps) {
  const id = useId();

  return (
    <div className="checkbox-row">
      <RadixCheckbox.Root
        id={id}
        className="checkbox"
        checked={checked}
        onCheckedChange={(value) => onCheckedChange(value === true)}
        disabled={disabled}
      >
        <RadixCheckbox.Indicator className="checkbox-indicator">
          <Check size={12} strokeWidth={3} aria-hidden="true" />
        </RadixCheckbox.Indicator>
      </RadixCheckbox.Root>
      <label htmlFor={id}>{label}</label>
    </div>
  );
}
