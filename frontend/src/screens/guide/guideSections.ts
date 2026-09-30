import {
  Compass,
  Files,
  FolderOpen,
  GraduationCap,
  LifeBuoy,
  PanelsTopLeft,
  SlidersHorizontal,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";

/**
 * Оглавление руководства. Текст страницы лежит в `pages/<slug>.md`; страница без
 * файла остаётся в дереве и показывает «раздел пишется» — так видна вся
 * структура, пока наполнение идёт по частям.
 */
export interface GuidePage {
  slug: string;
  title: string;
  children?: GuidePage[];
}

export interface GuideGroup {
  id: string;
  title: string;
  icon: LucideIcon;
  pages: GuidePage[];
}

export const GUIDE_TREE: GuideGroup[] = [
  {
    id: "start",
    title: "Начало",
    icon: Compass,
    pages: [
      { slug: "welcome", title: "Знакомство" },
      { slug: "concepts", title: "Основные понятия" },
    ],
  },
  {
    id: "projects",
    title: "Проекты",
    icon: FolderOpen,
    pages: [
      { slug: "projects", title: "Проекты" },
      {
        slug: "create",
        title: "Создание проекта",
        children: [
          { slug: "create-exam", title: "Подготовка к экзамену" },
          { slug: "create-textbook", title: "Изучение по учебнику" },
          { slug: "create-free", title: "Свободное изучение" },
        ],
      },
      { slug: "program", title: "Программа" },
    ],
  },
  {
    id: "materials",
    title: "Подготовка материалов",
    icon: Files,
    pages: [
      { slug: "library", title: "Библиотека и Материалы" },
      { slug: "add-material", title: "Добавление материалов" },
      { slug: "prepare-text", title: "Подготовка текста" },
      { slug: "outline", title: "Оглавление и проверка" },
      { slug: "web-search", title: "Поиск в интернете" },
    ],
  },
  {
    id: "work",
    title: "Работа над проектом",
    icon: PanelsTopLeft,
    pages: [
      { slug: "workspace", title: "Рабочая область" },
      { slug: "answers", title: "Ответы и привязки" },
      { slug: "chat", title: "Чат" },
      { slug: "conspects", title: "Конспекты" },
      { slug: "coverage", title: "Покрытие" },
    ],
  },
  {
    id: "lessons",
    title: "Занятия",
    icon: GraduationCap,
    pages: [
      { slug: "lessons", title: "Уроки" },
      { slug: "preparation", title: "Моя подготовка" },
      { slug: "cards", title: "Карточки" },
      { slug: "lesson-planning", title: "Планирование занятий" },
    ],
  },
  {
    id: "setup",
    title: "Параметры установки",
    icon: SlidersHorizontal,
    pages: [
      {
        slug: "setup-ai",
        title: "Настройка ИИ",
        children: [
          { slug: "setup-ai-providers", title: "Провайдеры" },
          { slug: "setup-ai-models", title: "Модели" },
          { slug: "setup-ai-defaults", title: "Модели по умолчанию" },
          { slug: "setup-ai-functions", title: "Функции" },
          { slug: "setup-ai-limits", title: "Расходы и лимиты" },
          { slug: "setup-ai-usage", title: "История запросов" },
        ],
      },
      {
        slug: "setup-ocr",
        title: "Настройка распознавания",
        children: [
          { slug: "setup-ocr-modes", title: "Режимы" },
          { slug: "setup-ocr-install", title: "Установка моделей" },
          { slug: "setup-ocr-quality", title: "Качество" },
        ],
      },
      {
        slug: "setup-search",
        title: "Настройка поиска",
        children: [
          { slug: "setup-search-models", title: "Модели эмбеддингов" },
          { slug: "setup-search-index", title: "Индекс" },
          { slug: "setup-search-quality", title: "Качество и пресеты" },
        ],
      },
      { slug: "setup-bot", title: "Настройка бота" },
      {
        slug: "setup-storage",
        title: "Хранилище и копии",
        children: [
          { slug: "setup-storage-backups", title: "Резервные копии" },
          { slug: "setup-storage-projects", title: "Перенос проектов" },
          { slug: "setup-storage-maintenance", title: "Обслуживание" },
        ],
      },
      { slug: "setup-background", title: "Задний фон" },
      { slug: "status-jobs", title: "Состояние и фоновые задачи" },
    ],
  },
  {
    id: "help",
    title: "Справка",
    icon: LifeBuoy,
    pages: [
      { slug: "troubleshooting", title: "Частые проблемы" },
      { slug: "hotkeys", title: "Горячие клавиши" },
      { slug: "data-location", title: "Где лежат данные" },
    ],
  },
];

export const DEFAULT_GUIDE_PAGE = "welcome";

export interface FlatGuidePage {
  page: GuidePage;
  group: GuideGroup;
  parent: GuidePage | null;
}

/** Все страницы в порядке чтения: родитель, затем его дети. */
export const FLAT_GUIDE_PAGES: FlatGuidePage[] = GUIDE_TREE.flatMap((group) =>
  group.pages.flatMap((page) => [
    { page, group, parent: null },
    ...(page.children ?? []).map((child) => ({ page: child, group, parent: page })),
  ]),
);

export function findGuidePage(slug: string | null | undefined): FlatGuidePage | null {
  return FLAT_GUIDE_PAGES.find((item) => item.page.slug === slug) ?? null;
}
