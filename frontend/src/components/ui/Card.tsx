import type { ButtonHTMLAttributes, PropsWithChildren } from "react";

interface CardProps {
  /** Карточка ведёт куда-то: становится кнопкой и приподнимается под курсором. */
  onClick?: ButtonHTMLAttributes<HTMLButtonElement>["onClick"];
  className?: string;
}

/**
 * Базовая поверхность: рамка, скругление, фон бумаги. На ней стоят списки
 * проектов, тем, материалов — то есть почти всё, что будет на экранах.
 */
export function Card({ onClick, className = "", children }: PropsWithChildren<CardProps>) {
  const classes = `card ${onClick ? "is-interactive" : ""} ${className}`.replace(/\s+/g, " ").trim();

  if (onClick) {
    return (
      <button type="button" className={classes} onClick={onClick}>
        {children}
      </button>
    );
  }

  return <div className={classes}>{children}</div>;
}
