import {
  BookOpen,
  CalendarDays,
  Files,
  FileSearch,
  FolderOpen,
  GraduationCap,
  Inbox,
  Layers,
  ListChecks,
  ListTree,
  Map,
  Palette,
  Settings,
  Sparkles,
  Target,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";

/**
 * Четырнадцать экранов из §21 требований плюс служебная витрина UI-кита.
 * Это единственный список экранов в проекте: навигация, роутинг и заглушки
 * строятся отсюда. Добавляешь экран — добавляешь строку здесь.
 *
 * `depth` — из PLAN.md, этап 1: девять экранов сквозного сценария проектируются
 * до состояния «по ним можно кодить», остальные пять — эскизом.
 */

export type ScreenGroup = "Проект" | "Материал" | "Занятия" | "Служебное";

export interface ScreenMeta {
  id: string;
  /** Шаблон пути для роутера. */
  path: string;
  /** Путь для ссылки в навигации: параметры подставлены демонстрационными значениями. */
  navPath: string;
  title: string;
  /** Формулировка из §21 требований. */
  summary: string;
  group: ScreenGroup;
  icon: LucideIcon;
  depth: "полностью" | "эскизом" | "служебный";
}

/** Пока проектов нет, все ссылки ведут на этот идентификатор. */
export const DEMO_PROJECT_ID = "demo";
const DEMO_MATERIAL_ID = "demo-material";
const DEMO_TOPIC_ID = "demo-topic";

export const SCREENS: ScreenMeta[] = [
  {
    id: "projects",
    path: "/projects",
    navPath: "/projects",
    title: "Проекты",
    summary: "Список с прогрессом, создание по шаблону.",
    group: "Проект",
    icon: FolderOpen,
    depth: "полностью",
  },
  {
    id: "project-new",
    path: "/projects/new",
    navPath: "/projects/new",
    title: "Мастер создания проекта",
    summary: "Шаблон, материалы, паспорт цели, способ получения программы.",
    group: "Проект",
    icon: Sparkles,
    depth: "полностью",
  },
  {
    id: "coverage-map",
    path: "/projects/:projectId",
    navPath: `/projects/${DEMO_PROJECT_ID}`,
    title: "Карта покрытия",
    summary:
      "Главный экран проекта: таблица программы со статусами и фильтрами, вкладка статистики.",
    group: "Проект",
    icon: Map,
    depth: "полностью",
  },
  {
    id: "coverage",
    path: "/projects/:projectId/coverage",
    navPath: `/projects/${DEMO_PROJECT_ID}/coverage`,
    title: "Покрытие",
    summary: "Два таба: «Пробелы» и «Неразобранное».",
    group: "Проект",
    icon: Target,
    depth: "полностью",
  },
  {
    id: "program",
    path: "/projects/:projectId/program",
    navPath: `/projects/${DEMO_PROJECT_ID}/program`,
    title: "Программа",
    summary:
      "Редактор дерева, массовый ввод, импорт, уровни цели пачкой, экран пересборки с дифом.",
    group: "Проект",
    icon: ListTree,
    depth: "полностью",
  },
  {
    id: "materials",
    path: "/projects/:projectId/materials",
    navPath: `/projects/${DEMO_PROJECT_ID}/materials`,
    title: "Материалы",
    summary: "Список файлов, прогресс разбора, качество распознавания, дельта.",
    group: "Материал",
    icon: Files,
    depth: "полностью",
  },
  {
    id: "source-viewer",
    path: "/projects/:projectId/materials/:materialId",
    navPath: `/projects/${DEMO_PROJECT_ID}/materials/${DEMO_MATERIAL_ID}`,
    title: "Просмотрщик источника",
    summary: "Страница с подсветкой фрагментов и привязок, ручная привязка выделением.",
    group: "Материал",
    icon: FileSearch,
    depth: "полностью",
  },
  {
    id: "suggestions",
    path: "/projects/:projectId/suggestions",
    navPath: `/projects/${DEMO_PROJECT_ID}/suggestions`,
    title: "Очередь предложений",
    summary: "Быстрый разбор неоднозначных привязок клавиатурой.",
    group: "Материал",
    icon: ListChecks,
    depth: "эскизом",
  },
  {
    id: "topic",
    path: "/projects/:projectId/topics/:topicId",
    navPath: `/projects/${DEMO_PROJECT_ID}/topics/${DEMO_TOPIC_ID}`,
    title: "Среда темы",
    summary: "Материал, эталон, карточки, конспект, история, свободный вопрос.",
    group: "Занятия",
    icon: BookOpen,
    depth: "полностью",
  },
  {
    id: "session",
    path: "/projects/:projectId/session",
    navPath: `/projects/${DEMO_PROJECT_ID}/session`,
    title: "Сессия занятия",
    summary: "Единый каркас под все виды активностей, включая редактор SQL и разбор ответа.",
    group: "Занятия",
    icon: GraduationCap,
    depth: "полностью",
  },
  {
    id: "cards",
    path: "/projects/:projectId/cards",
    navPath: `/projects/${DEMO_PROJECT_ID}/cards`,
    title: "Карточки",
    summary: "Банк, фильтры, редактор, режим повторения.",
    group: "Занятия",
    icon: Layers,
    depth: "эскизом",
  },
  {
    id: "plan",
    path: "/projects/:projectId/plan",
    navPath: `/projects/${DEMO_PROJECT_ID}/plan`,
    title: "План подготовки",
    summary: "Календарь до дедлайна, прогноз готовности.",
    group: "Занятия",
    icon: CalendarDays,
    depth: "эскизом",
  },
  {
    id: "inbox",
    path: "/projects/:projectId/inbox",
    navPath: `/projects/${DEMO_PROJECT_ID}/inbox`,
    title: "Инбокс",
    summary: "Что прислали через бота.",
    group: "Занятия",
    icon: Inbox,
    depth: "эскизом",
  },
  {
    id: "settings",
    path: "/projects/:projectId/settings",
    navPath: `/projects/${DEMO_PROJECT_ID}/settings`,
    title: "Настройки",
    summary: "Модули проекта, паспорт цели, модели и лимиты, напоминания, бот, экспорт.",
    group: "Служебное",
    icon: Settings,
    depth: "эскизом",
  },
  {
    id: "ui-kit",
    path: "/ui-kit",
    navPath: "/ui-kit",
    title: "UI-кит",
    summary: "Витрина перенесённых из virtex компонентов. В продукт не входит.",
    group: "Служебное",
    icon: Palette,
    depth: "служебный",
  },
];

export const SCREEN_GROUPS: ScreenGroup[] = ["Проект", "Материал", "Занятия", "Служебное"];

export function screenById(id: string): ScreenMeta {
  const screen = SCREENS.find((candidate) => candidate.id === id);
  if (!screen) throw new Error(`Экран «${id}» не описан в SCREENS`);
  return screen;
}
