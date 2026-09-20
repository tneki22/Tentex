import type { AiRoleRead } from "../api/ai";

export interface AiRoleCategory {
  id: string;
  title: string;
  description: string;
  /** Ключи ролей бэкенда (`ROLE_SPECS`). Первая роль остаётся видимой в свёрнутой категории. */
  roles: readonly string[];
}

/**
 * Группировка функций в Параметрах ИИ. Порядок ролей внутри категории — порядок на экране:
 * первая показывается всегда, остальные раскрываются.
 */
export const AI_ROLE_CATEGORIES: readonly AiRoleCategory[] = [
  {
    id: "materials",
    title: "Материалы и покрытие",
    description: "Чтение страниц, расшифровка записей, уборка текста и разбор материала по программе.",
    roles: [
      "material_page_recognition",
      "material_audio_transcription",
      "material_text_cleanup",
      "coverage_overview",
      "coverage_research",
    ],
  },
  {
    id: "program",
    title: "Программа и вопросы",
    description: "Разбор списка вопросов, ответов и структуры учебника.",
    roles: [
      "exam_program_grouping",
      "exam_import_repair",
      "exam_answer_sections",
      "study_outline_extract",
      "study_program_assistant",
    ],
  },
  {
    id: "preparation",
    title: "План подготовки",
    description: "Нагрузка, учебные блоки, распределение по дням и рекомендация на сегодня.",
    roles: [
      "exam_preparation_estimate",
      "exam_preparation_phases",
      "exam_preparation_distribution",
      "exam_preparation_coach",
    ],
  },
  {
    id: "chat",
    title: "Чат и проверка ответов",
    description: "Экзаменатор, проверка ваших ответов и голосовой ввод.",
    roles: ["exam_chat_reply", "exam_answer_judge", "exam_chat_memory", "speech_transcription"],
  },
];

const OTHER_CATEGORY: Omit<AiRoleCategory, "roles"> = {
  id: "other",
  title: "Прочее",
  description: "Функции, которые пока не отнесены к категории.",
};

export interface AiRoleGroup extends Omit<AiRoleCategory, "roles"> {
  roles: AiRoleRead[];
}

/**
 * Раскладывает роли по категориям. Роль, которой нет в списке, попадает в «Прочее»:
 * новая функция бэкенда не должна пропасть с экрана, пока её не отнесли к категории.
 */
export function groupAiRoles(roles: readonly AiRoleRead[]): AiRoleGroup[] {
  const byKey = new Map(roles.map((role) => [role.role, role]));
  const placed = new Set<string>();
  const groups: AiRoleGroup[] = AI_ROLE_CATEGORIES.map(({ roles: keys, ...meta }) => {
    const items = keys.flatMap((key) => {
      const role = byKey.get(key);
      if (!role) return [];
      placed.add(key);
      return [role];
    });
    return { ...meta, roles: items };
  });
  const rest = roles.filter((role) => !placed.has(role.role));
  if (rest.length > 0) groups.push({ ...OTHER_CATEGORY, roles: rest });
  return groups.filter((group) => group.roles.length > 0);
}
