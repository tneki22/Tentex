import { Check, ChevronDown, ChevronUp } from "lucide-react";
import { Select as RadixSelect } from "radix-ui";

const EMPTY_VALUE = "__tentex_select_empty__";

export interface SelectOption {
  value: string;
  label: string;
  description?: string;
  disabled?: boolean;
}

interface SelectProps {
  value: string | null;
  options: SelectOption[];
  onValueChange: (value: string | null) => void;
  ariaLabel: string;
  placeholder?: string;
  emptyOption?: string;
  disabled?: boolean;
  className?: string;
  id?: string;
  "aria-invalid"?: boolean;
}

/**
 * Общий выпадающий список Tentex. Клавиатура, ARIA и позиционирование — Radix;
 * подписи, состояния и движение — из нашей дизайн-системы.
 */
export function Select({
  value,
  options,
  onValueChange,
  ariaLabel,
  placeholder = "Выберите значение",
  emptyOption,
  disabled = false,
  className = "",
  id,
  "aria-invalid": ariaInvalid,
}: SelectProps) {
  const currentValue = value ?? (emptyOption ? EMPTY_VALUE : undefined);

  return (
    <RadixSelect.Root
      value={currentValue}
      disabled={disabled}
      onValueChange={(next) => onValueChange(next === EMPTY_VALUE ? null : next)}
    >
      <RadixSelect.Trigger
        id={id}
        className={`select-trigger ${className}`.trim()}
        aria-label={ariaLabel}
        aria-invalid={ariaInvalid}
      >
        <RadixSelect.Value placeholder={placeholder} />
        <RadixSelect.Icon className="select-chevron">
          <ChevronDown size={15} aria-hidden="true" />
        </RadixSelect.Icon>
      </RadixSelect.Trigger>
      <RadixSelect.Portal>
        <RadixSelect.Content
          className="select-content"
          position="popper"
          sideOffset={6}
          collisionPadding={12}
        >
          <RadixSelect.ScrollUpButton className="select-scroll-button">
            <ChevronUp size={15} aria-hidden="true" />
          </RadixSelect.ScrollUpButton>
          <RadixSelect.Viewport className="select-viewport">
            {emptyOption && (
              <RadixSelect.Item className="select-item" value={EMPTY_VALUE}>
                <RadixSelect.ItemText>{emptyOption}</RadixSelect.ItemText>
                <RadixSelect.ItemIndicator className="select-indicator">
                  <Check size={14} aria-hidden="true" />
                </RadixSelect.ItemIndicator>
              </RadixSelect.Item>
            )}
            {options.map((option) => (
              <RadixSelect.Item
                key={option.value}
                className="select-item"
                value={option.value}
                disabled={option.disabled}
              >
                <span className="select-item-copy">
                  <RadixSelect.ItemText>{option.label}</RadixSelect.ItemText>
                  {option.description && <small>{option.description}</small>}
                </span>
                <RadixSelect.ItemIndicator className="select-indicator">
                  <Check size={14} aria-hidden="true" />
                </RadixSelect.ItemIndicator>
              </RadixSelect.Item>
            ))}
          </RadixSelect.Viewport>
          <RadixSelect.ScrollDownButton className="select-scroll-button">
            <ChevronDown size={15} aria-hidden="true" />
          </RadixSelect.ScrollDownButton>
        </RadixSelect.Content>
      </RadixSelect.Portal>
    </RadixSelect.Root>
  );
}
