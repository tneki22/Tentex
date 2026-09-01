import {
  CalendarDays,
  Files,
  FileSearch,
  FolderOpen,
  GraduationCap,
  Layers,
  Library,
  ListTree,
  PanelsTopLeft,
  Palette,
  Settings,
  SlidersHorizontal,
  Sparkles,
  Target,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";

/**
 * Пятнадцать проектных и два глобальных экрана из §21 требований
 * плюс служебная витрина UI-кита.
 * Это единственный список экранов в проекте: навигация, роутинг и заглушки
 * строятся отсюда. Добавляешь экран — добавляешь строку здесь.
 *
 * `depth` — требуемая глубина перед реализацией. Оставшийся экран сначала
 * описывается в SCREENS.md и верстается, затем получает настоящий вертикальный срез.
 */

export type ScreenGroup = "Проект" | "Материал" | "Занятия" | "Служебное";

export interface ScreenMeta {
  id: string;
  /** Шаблон пути для роутера. */
  path: string;
  /** Путь для глобальной ссылки; проектные шаблоны не открываются без настоящего project id. */
  navPath: string;
  title: string;
  /** Формулировка из §21 требований. */
  summary: string;
  group: ScreenGroup;
  icon: LucideIcon;
  depth: "полностью" | "эскизом" | "служебный";
}

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
    id: "workspace",
    path: "/projects/:projectId",
    navPath: "/projects/:projectId",
    title: "Рабочая область",
    summary:
      "Дерево программы и изменяемые панели источника, ответа, конспекта и инструментов темы.",
    group: "Проект",
    icon: PanelsTopLeft,
    depth: "полностью",
  },
  {
    id: "coverage-map",
    path: "/projects/:projectId/coverage-map",
    navPath: "/projects/:projectId/coverage-map",
    title: "Карта покрытия",
    summary: "Аналитическая таблица программы со статусами, источниками и фильтрами.",
    group: "Проект",
    icon: Target,
    depth: "полностью",
  },
  {
    id: "program",
    path: "/projects/:projectId/program",
    navPath: "/projects/:projectId/program",
    title: "Программа / вопросы экзамена",
    summary:
      "Общий редактор программы: дерево, ручные правки, источники и подтверждаемый диф изменений.",
    group: "Проект",
    icon: ListTree,
    depth: "полностью",
  },
  {
    id: "materials",
    path: "/projects/:projectId/materials",
    navPath: "/projects/:projectId/materials",
    title: "Материалы",
    summary: "Список файлов, прогресс разбора, качество распознавания, дельта.",
    group: "Материал",
    icon: Files,
    depth: "полностью",
  },
  {
    id: "source-viewer",
    path: "/projects/:projectId/materials/:materialId",
    navPath: "/projects/:projectId/materials/:materialId",
    title: "Просмотрщик источника",
    summary: "Страница с подсветкой фрагментов и привязок, ручная привязка выделением.",
    group: "Материал",
    icon: FileSearch,
    depth: "полностью",
  },
  {
    id: "lessons",
    path: "/projects/:projectId/lessons",
    navPath: "/projects/:projectId/lessons",
    title: "Уроки",
    summary: "Одиночное и массовое создание Уроков по Темам Программы.",
    group: "Занятия",
    icon: GraduationCap,
    depth: "полностью",
  },
  {
    id: "session",
    path: "/projects/:projectId/session",
    navPath: "/projects/:projectId/session",
    title: "Сессия занятия",
    summary: "Единый каркас под все виды активностей, включая редактор SQL и разбор ответа.",
    group: "Занятия",
    icon: GraduationCap,
    depth: "полностью",
  },
  {
    id: "cards",
    path: "/projects/:projectId/cards",
    navPath: "/projects/:projectId/cards",
    title: "Карточки",
    summary: "Банк, фильтры, редактор, режим повторения.",
    group: "Занятия",
    icon: Layers,
    depth: "эскизом",
  },
  {
    id: "plan",
    path: "/projects/:projectId/plan",
    navPath: "/projects/:projectId/plan",
    title: "План подготовки",
    summary: "Календарь до дедлайна: первичный проход, повторения, резерв и прогноз готовности.",
    group: "Занятия",
    icon: CalendarDays,
    depth: "эскизом",
  },
  {
    id: "settings",
    path: "/projects/:projectId/settings",
    navPath: "/projects/:projectId/settings",
    title: "Настройки",
    summary: "Параметры проекта, паспорт цели и включённые учебные модули.",
    group: "Служебное",
    icon: Settings,
    depth: "полностью",
  },
  {
    id: "library",
    path: "/library",
    navPath: "/library",
    title: "Библиотека",
    summary: "Общие материалы установки: качество, какие проекты используют, последствия удаления.",
    group: "Служебное",
    icon: Library,
    depth: "полностью",
  },
  {
    id: "library-material",
    path: "/library/:materialId",
    navPath: "/library/:materialId",
    title: "Рабочая область материала",
    summary: "Исходник и подготовленный текст рядом, оглавление, обработка, версии и файл.",
    group: "Материал",
    icon: FileSearch,
    depth: "полностью",
  },
  {
    id: "setup",
    path: "/setup",
    navPath: "/setup",
    title: "Параметры",
    summary: "Внешние модели и лимиты, бот, резервные копии, хранилище.",
    group: "Служебное",
    icon: SlidersHorizontal,
    depth: "эскизом",
  },
  {
    id: "ui-kit",
    path: "/ui-kit",
    navPath: "/ui-kit",
    title: "Дизайн-система",
    summary: "Витрина токенов, примитивов кита и доменных виджетов. В продукт не входит.",
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
