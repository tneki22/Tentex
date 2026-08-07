import { useId } from "react";
import { Switch as RadixSwitch } from "radix-ui";

interface SwitchProps {
  checked: boolean;
  onCheckedChange: (checked: boolean) => void;
  label: string;
  /** Строка под подписью: что изменится. Особенно нужна выключателям моделей. */
  hint?: string;
  disabled?: boolean;
}

/**
 * Тумблер: модули проекта, внешние модели, роли моделей, напоминания.
 * Переключает сразу, без «Сохранить» — отсюда требование к подписи: она должна
 * называть состояние, а не действие («Внешние модели», не «Включить модели»).
 */
export function Switch({ checked, onCheckedChange, label, hint, disabled }: SwitchProps) {
  const id = useId();

  return (
    <div className={`switch-row ${disabled ? "is-disabled" : ""}`.trim()}>
      <span className="switch-text">
        <label htmlFor={id}>{label}</label>
        {hint && <small>{hint}</small>}
      </span>
      <RadixSwitch.Root
        id={id}
        className="switch"
        checked={checked}
        onCheckedChange={onCheckedChange}
        disabled={disabled}
      >
        <RadixSwitch.Thumb className="switch-thumb" />
      </RadixSwitch.Root>
    </div>
  );
}
