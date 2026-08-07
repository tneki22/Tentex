import type { CSSProperties } from "react";
import {
  Atom,
  BookOpen,
  Code,
  Database,
  FlaskConical,
  Globe,
  GraduationCap,
  Scale,
  Sigma,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";

/** Восемь иконок предметов. Больше не нужно: это опознавательный знак, не аватар. */
export const PROJECT_ICONS: Record<string, LucideIcon> = {
  "graduation-cap": GraduationCap,
  "book-open": BookOpen,
  database: Database,
  sigma: Sigma,
  atom: Atom,
  code: Code,
  globe: Globe,
  scale: Scale,
  flask: FlaskConical,
};

export type ProjectIconName = keyof typeof PROJECT_ICONS;
/** Номер пресета из tokens.css: --project-color-1…8. */
export type ProjectColor = 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8;

interface ProjectChipProps {
  icon: ProjectIconName;
  color: ProjectColor;
  size?: "sm" | "md" | "lg";
}

/**
 * Опознавательный знак проекта: цвет и иконка. Один и тот же в панели, в
 * карточке, в архиве, в поиске — по нему проект узнаётся раньше, чем прочитано
 * название (а названия у двух проектов одного предмета похожи по определению).
 *
 * Цвета проектов — отдельная группа токенов, разнесённая с акцентом и тонами
 * статусов: иначе фиолетовый проект читался бы как статус.
 */
export function ProjectChip({ icon, color, size = "md" }: ProjectChipProps) {
  const Icon = PROJECT_ICONS[icon] ?? GraduationCap;
  const iconSize = size === "lg" ? 20 : size === "sm" ? 13 : 16;

  return (
    <span
      className={`project-chip is-${size}`}
      style={{ "--proj": `var(--project-color-${color})` } as CSSProperties}
      aria-hidden="true"
    >
      <Icon size={iconSize} />
    </span>
  );
}
