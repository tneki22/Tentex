import type { ReactNode } from "react";
import { Link } from "react-router";
import {
  CalendarDays,
  Files,
  GraduationCap,
  Layers,
  ListTree,
  Settings,
  Target,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import type { ModuleKey } from "../../api/projects";
import { Tooltip } from "../ui";
import { usePreparationInvitation } from "../../hooks/usePreparationInvitation";

export type ProjectNavKey = "materials" | "program" | "answers" | "lessons" | "plan" | "cards" | "settings";

interface NavEntry {
  key: ProjectNavKey;
  to: string;
  icon: LucideIcon;
  label: string;
  disabledReason?: string;
}

interface ProjectNavProps {
  projectId: string;
  /** Опущено на самой Рабочей области: её самой в списке нет. */
  active?: ProjectNavKey;
  textbook?: boolean;
  /** Отсутствует у экранов-эскизов (План, Карточки): тогда считаем все модули включёнными. */
  modules?: ModuleKey[];
  counts?: Partial<Record<ProjectNavKey, ReactNode>>;
  className?: string;
}

/**
 * Единый список разделов проекта: одни и те же шесть пунктов от «Материалов»
 * до «Настроек» на всех экранах проекта, а не урезанный подбор по месту.
 */
export function ProjectNav({ projectId, active, textbook = false, modules, counts = {}, className = "" }: ProjectNavProps) {
  const hasModule = (key: ModuleKey) => (modules ? modules.includes(key) : true);
  const invite = usePreparationInvitation(projectId, !textbook && hasModule("plan"));

  const entries: NavEntry[] = [
    { key: "materials", to: `/projects/${projectId}/materials`, icon: Files, label: "Материалы" },
    {
      key: "program",
      to: `/projects/${projectId}/program${textbook ? "?mode=textbook" : ""}`,
      icon: ListTree,
      label: textbook ? "Программа" : "Вопросы экзамена",
    },
    ...(!textbook
      ? [{ key: "answers" as const, to: `/projects/${projectId}/coverage-map`, icon: Target, label: "Ответы" }]
      : []),
    ...(hasModule("lessons")
      ? [{ key: "lessons" as const, to: `/projects/${projectId}/lessons`, icon: GraduationCap, label: "Уроки" }]
      : []),
    ...(!textbook && hasModule("plan")
      ? [{ key: "plan" as const, to: `/projects/${projectId}/plan`, icon: CalendarDays, label: "Моя подготовка" }]
      : []),
    ...(textbook
      ? [{
        key: "cards" as const,
        to: `/projects/${projectId}/cards`,
        icon: Layers,
        label: "Карточки",
        disabledReason: "Учебная конфигурация Карточек будет спроектирована отдельно",
      }]
      : hasModule("cards")
        ? [{ key: "cards" as const, to: `/projects/${projectId}/cards`, icon: Layers, label: "Карточки" }]
        : []),
    { key: "settings", to: `/projects/${projectId}/settings`, icon: Settings, label: "Настройки" },
  ];

  return (
    <nav className={`workspace-project-nav ${className}`.trim()} aria-label="Разделы проекта">
      {entries.map((entry) => {
        const Icon = entry.icon;
        const count = counts[entry.key];
        if (entry.disabledReason) {
          return (
            <Tooltip label={entry.disabledReason} side="right" key={entry.key}>
              <span><button type="button" disabled><Icon size={15} /><span>{entry.label}</span><small>позже</small></button></span>
            </Tooltip>
          );
        }
        if (entry.key === active) {
          return (
            <span className={`workspace-project-link is-active${entry.key === "plan" && invite ? " is-inviting" : ""}`} key={entry.key}>
              <Icon size={15} /><span>{entry.label}</span>{count !== undefined && <small>{count}</small>}
            </span>
          );
        }
        return (
          <Link className={`workspace-project-link${entry.key === "plan" && invite ? " is-inviting" : ""}`} to={entry.to} key={entry.key}>
            <Icon size={15} /><span>{entry.label}</span>{count !== undefined && <small>{count}</small>}
          </Link>
        );
      })}
    </nav>
  );
}
