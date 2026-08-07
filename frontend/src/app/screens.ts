import {
  CalendarDays,
  Files,
  FileSearch,
  FolderOpen,
  GraduationCap,
  Inbox,
  Layers,
  Library,
  ListChecks,
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
export const DEMO_TEXTBOOK_PROJECT_ID = "vector-indexes";
const DEMO_MATERIAL_ID = "demo-material";

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
    navPath: `/projects/${DEMO_PROJECT_ID}`,
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
    navPath: `/projects/${DEMO_PROJECT_ID}/coverage-map`,
    title: "Карта покрытия",
    summary: "Аналитическая таблица программы со статусами, источниками и фильтрами.",
    group: "Проект",
    icon: Target,
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
    id: "lessons",
    path: "/projects/:projectId/lessons",
    navPath: `/projects/${DEMO_TEXTBOOK_PROJECT_ID}/lessons`,
    title: "Уроки",
    summary: "Одиночное и массовое создание Уроков по Темам Программы.",
    group: "Занятия",
    icon: GraduationCap,
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
    summary: "Календарь до дедлайна: первичный проход, повторения, резерв и прогноз готовности.",
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
    summary: "Параметры проекта, паспорт цели и включённые учебные модули.",
    group: "Служебное",
    icon: Settings,
    depth: "полностью",
  },
  {
    id: "library",
    path: "/library",
    navPath: "/library",
    title: "Материалы",
    summary: "Файлы установки: качество, какие проекты используют, последствия удаления.",
    group: "Служебное",
    icon: Library,
    depth: "эскизом",
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
