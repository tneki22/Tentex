import type { ButtonHTMLAttributes, PropsWithChildren } from "react";

interface IconButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  label: string;
  /** Скрыть нативный title — когда рядом уже есть кастомная подсказка (Tooltip), они не должны дублироваться. */
  hideNativeTitle?: boolean;
}

export function IconButton({
  label,
  type = "button",
  className = "",
  children,
  hideNativeTitle = false,
  ...props
}: PropsWithChildren<IconButtonProps>) {
  return (
    <button
      type={type}
      className={`icon-button ${className}`.trim()}
      aria-label={label}
      title={hideNativeTitle ? undefined : label}
      {...props}
    >
      {children}
    </button>
  );
}
