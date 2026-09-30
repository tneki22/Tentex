import { PARSER_MODE_TITLES, type MaterialPurpose, type MaterialRead, type SourceRole } from "../../api/materials";

export const SOURCE_ROLE_OPTIONS: Array<{ value: SourceRole; label: string; description: string }> = [
  { value: "main", label: "Основной", description: "Главный источник для изучения" },
  { value: "additional", label: "Дополнительный", description: "Расширяет основной материал" },
  { value: "reference", label: "Справочный", description: "Для ответов и пояснений" },
];

export const SOURCE_ROLE_LABEL = Object.fromEntries(
  SOURCE_ROLE_OPTIONS.map((option) => [option.value, option.label]),
) as Record<SourceRole, string>;

export const PURPOSE_LABEL: Record<MaterialPurpose, string> = {
  exam_structure: "Список вопросов",
  reference_answers: "Ответы",
  study_source: "Учебный источник",
};

/** Файл экзамена (вопросы, ответы) описывается назначением, учебный источник — ролью. */
export function materialRoleText(material: MaterialRead): string {
  const exam = material.purposes.filter((purpose) => purpose !== "study_source");
  return exam.length ? exam.map((purpose) => PURPOSE_LABEL[purpose]).join(", ") : SOURCE_ROLE_LABEL[material.source_role];
}

/** Как материал был разобран. У записи режимы называются по-своему: это Whisper и модель речи. */
export function parseModeLabel(material: MaterialRead): string {
  if (material.source_kind === "audio") {
    if (material.parser_mode === "cloud") return "Облако — внешняя модель речи";
    return material.parser_mode === "fast" ? "Локально — Whisper" : "Не запускалась";
  }
  const mode = material.last_parse?.parser_mode ?? material.parser_mode;
  if (!mode) return "Не запускался";
  const model = material.last_parse?.model_id;
  return model ? `${PARSER_MODE_TITLES[mode]} · ${model}` : PARSER_MODE_TITLES[mode];
}

/** Короткая подпись для строки списка: режим последней версии и модель без префикса провайдера. */
export function parseModeShort(material: MaterialRead): { mode: string; model: string | null } | null {
  const mode = material.last_parse?.parser_mode ?? (material.active_parse_revision ? material.parser_mode : null);
  if (!mode) return null;
  if (material.source_kind === "audio" && mode === "fast") return { mode: "Whisper", model: null };
  const model = material.last_parse?.model_id?.split("/").pop() ?? null;
  return { mode: PARSER_MODE_TITLES[mode], model };
}

/** Колонка «Используется»: «12 тем», пусто — прочерк. */
export function topicsLabel(count: number): string {
  if (!count) return "—";
  const mod100 = count % 100;
  const mod10 = count % 10;
  if (mod100 >= 11 && mod100 <= 14) return `${count} тем`;
  if (mod10 === 1) return `${count} тема`;
  if (mod10 >= 2 && mod10 <= 4) return `${count} темы`;
  return `${count} тем`;
}

/** Состояние с ходом разбора: «Разбирается · 12/85». Очередь и готовый файл — без счёта. */
export function progressSuffix(material: MaterialRead): string {
  const task = material.task;
  if (!task || task.total <= 0) return "";
  if (material.status !== "processing" && material.status !== "paused") return "";
  return ` · ${task.done}/${task.total}`;
}

/** Колонка «Страницы»: диапазон последнего запуска или сколько страниц он перечитал. */
export function pagesSummary(material: MaterialRead): { value: string; note: string | null } {
  const total = material.page_count;
  const parse = material.last_parse;
  if (parse?.scope === "range" && parse.page_from && parse.page_to) {
    return {
      value: parse.page_from === parse.page_to ? `с. ${parse.page_from}` : `${parse.page_from}–${parse.page_to}`,
      note: total ? `из ${total}` : null,
    };
  }
  if (parse?.parsed_pages && total && parse.parsed_pages < total) {
    return { value: String(total), note: `перечитано ${parse.parsed_pages}` };
  }
  return { value: total ? String(total) : "—", note: null };
}
