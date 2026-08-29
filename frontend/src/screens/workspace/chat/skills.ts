/**
 * Презентация команд палитры чата — заголовки, описания, группы и `/команда`.
 * Доступность и причину недоступности решает backend (`capabilities`,
 * AI-CHATS.md §21.4): здесь только соответствие command key ↔ отображение.
 */

export type PaletteGroup = "exam" | "materials" | "research";

export const PALETTE_GROUP_LABELS: Record<PaletteGroup, string> = {
  exam: "Экзамен",
  materials: "Материалы",
  research: "Исследование",
};

export const PALETTE_GROUP_ORDER: PaletteGroup[] = ["exam", "materials", "research"];

export interface PaletteCommandDef {
  /** Совпадает с ключом capability (skill или tool) на сервере. */
  key: string;
  kind: "skill" | "tool";
  command: string;
  label: string;
  description: string;
  group: PaletteGroup;
}

export const PALETTE_COMMANDS: PaletteCommandDef[] = [
  {
    key: "answer", kind: "skill", command: "/ответ", label: "Сдать ответ",
    description: "Открыть форму ответа на текущий вопрос.", group: "exam",
  },
  {
    key: "ask_question", kind: "skill", command: "/вопрос", label: "Попросить вопрос",
    description: "Экзаменатор сформулирует один тренировочный вопрос по теме.", group: "exam",
  },
  {
    key: "hint", kind: "skill", command: "/подсказка", label: "Получить подсказку",
    description: "Одна наводка без готового ответа; следующая — сильнее.", group: "exam",
  },
  {
    key: "task", kind: "skill", command: "/задание", label: "Получить задание",
    description: "Мини-кейс с условием и ожидаемым форматом ответа.", group: "exam",
  },
  {
    key: "accuracy", kind: "skill", command: "/точность", label: "Проверить точность",
    description: "Найти фактические неточности во введённом тексте.", group: "exam",
  },
  {
    key: "ticket", kind: "skill", command: "/билет", label: "Вытянуть билет",
    description: "Несколько вопросов подряд с общим итогом.", group: "exam",
  },
  {
    key: "search_project_materials", kind: "tool", command: "/материалы", label: "Найти в материалах",
    description: "Лексический поиск по уже обработанным материалам проекта.", group: "materials",
  },
  {
    key: "search_external_sources", kind: "tool", command: "/источники", label: "Найти источники",
    description: "Поиск статей, видео и публикаций во внешнем интернете.", group: "research",
  },
  {
    key: "import_found_source", kind: "tool", command: "/сохранить", label: "Сохранить оригинал",
    description: "Загрузить найденный источник в Материалы проекта.", group: "research",
  },
  {
    key: "summarize_found_source", kind: "tool", command: "/сводка", label: "Сделать сводку",
    description: "Краткая сводка по уже сохранённому источнику.", group: "research",
  },
];
