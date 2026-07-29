import type { ButtonHTMLAttributes, PropsWithChildren } from "react";

type ButtonVariant = "primary" | "secondary" | "ghost";

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
}

export function Button({
  variant = "primary",
  type = "button",
  className = "",
  children,
  ...props
}: PropsWithChildren<ButtonProps>) {
  const variantClass = variant === "primary"
    ? "primary-button"
    : variant === "secondary"
      ? "secondary-button"
      : "text-button";
  return (
    <button type={type} className={`${variantClass} ${className}`.trim()} {...props}>
      {children}
    </button>
  );
}
