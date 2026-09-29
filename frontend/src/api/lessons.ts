import type { SourceRole } from "./materials";
import { request, type LatestUndoableAction } from "./projects";

export type LessonStatus = "draft" | "ready" | "archived";
export type LessonBlockKind = "source" | "note" | "media" | "activity";
export type LessonNoteVariant =
  | "text" | "heading" | "explanation" | "important" | "example" | "definition" | "warning";
export type LessonBlockOrigin = "manual" | "outline" | "model" | "mixed";
export type LessonBasis = "sources" | "sources_and_model" | "model_only";
/** Шаблон модельного урока — модуль промпта на бэкенде (`lessons/ai_prompts.py`). */
export type LessonTemplate = "explain" | "guide" | "practice" | "cheatsheet";
export type LessonLevel = "draft" | "standard" | "detailed";

/** Как собран модельный урок; у быстрого и ручного урока — `null`. */
export interface LessonBuildRead {
  template: LessonTemplate;
  level: LessonLevel;
  basis: LessonBasis;
  model_id: string | null;
  cost_usd: string | null;
}

export interface LessonSummaryRead {
  id: string;
  title: string;
  status: LessonStatus;
  duration_minutes: number | null;
  program_node_ids: string[];
  needs_review: boolean;
  completed_at: string | null;
  updated_at: string;
  build: LessonBuildRead | null;
  creation_type: "quick" | "manual" | "ai";
}

export interface LessonsOverviewRead {
  lessons: LessonSummaryRead[];
}

export interface LessonSourceRangeRead {
  material_id: string;
  source_name: string;
  source_role: SourceRole;
  priority: number;
  is_parsed: boolean;
  outline_page_from: number;
  outline_page_to: number;
  page_from: number;
  page_to: number;
  starts_at_heading: boolean;
  ends_mid_page: boolean;
  default_selected: boolean;
}

export interface LessonTopicSourcesRead {
  program_node_id: string;
  ranges: LessonSourceRangeRead[];
}

export interface LessonRefRead {
  id: string;
  role: "content" | "support";
  material_id: string | null;
  source_name: string;
  source_role: SourceRole | null;
  material_revision: number | null;
  page_from: number;
  page_to: number;
  from_fragment_id: string | null;
  to_fragment_id: string | null;
  /** Вырез страницы `[x0, y0, x1, y1]` в долях листа; у обычного куска — `null`. */
  region_bbox: number[] | null;
  always_pages: boolean;
  is_available: boolean;
  is_parsed: boolean;
  low_quality_pages: number[];
  /** Граница не нашла пары в новой ревизии и стала границей страницы: «Разрез сдвинут». */
  boundary_shifted: boolean;
  /** Листы, которые в режиме «Страницы» рисует именно эта ссылка — без дублей по уроку. */
  pages_shown: number[];
  /** У опоры пояснения модели: `[S3]` в тексте блока открывает эту ссылку. */
  citation_label: string | null;
  /** Урок пришёл файлом без своего материала: текст куска из файла уроков (Markdown). */
  snapshot_md?: string | null;
  /** Тот же файл материала теперь есть в проекте — кусок можно связать заново. */
  can_relink?: boolean;
}

export interface LessonBlockRead {
  id: string;
  sort_order: number;
  kind: LessonBlockKind;
  variant: LessonNoteVariant | null;
  body_md: string | null;
  origin: LessonBlockOrigin;
  basis: LessonBasis | null;
  bound_program_node_id: string | null;
  media_kind: "image" | "link" | null;
  /** Только у внешней ссылки; изображение — `lessonMediaUrl`. */
  media_url: string | null;
  /** Кусок свёрнут под пояснением строкой «В учебнике: …». */
  collapsed: boolean;
  refs: LessonRefRead[];
  /** Блок `activity`: задание с формой, ключом и последней попыткой. */
  task?: StudyTaskRead | null;
}

export interface LessonTopicRead {
  program_node_id: string;
  title_snapshot: string;
  current_title: string | null;
  needs_review: boolean;
}

export interface LessonRead {
  id: string;
  project_id: string;
  title: string;
  goal: string | null;
  status: LessonStatus;
  duration_minutes: number | null;
  revision: number;
  needs_review: boolean;
  /** Прохождение: где остановились и когда отметили «Урок пройден». */
  last_block_id: string | null;
  completed_at: string | null;
  /** Последнее действие журнала — создание этого урока: доступно «Отменить». */
  undo_sequence: number | null;
  topics: LessonTopicRead[];
  blocks: LessonBlockRead[];
  build: LessonBuildRead | null;
  created_at: string;
  updated_at: string;
}

export interface LessonUnbindOffer {
  program_node_id: string;
  topic_title: string;
  binding_ids: string[];
}

export interface LessonChangeResult {
  lesson: LessonRead;
  latest_undoable_action: LatestUndoableAction | null;
  /** Удалённый или перенесённый кусок оставил привязки к теме — предложить снять. */
  unbind_offer: LessonUnbindOffer | null;
}

const lessonsPath = (projectId: string): string =>
  `/api/projects/${encodeURIComponent(projectId)}/lessons`;

export const getLessonsOverview = (
  projectId: string,
  signal?: AbortSignal,
): Promise<LessonsOverviewRead> => request(`${lessonsPath(projectId)}/overview`, { signal });

export const getTopicSources = (
  projectId: string,
  nodeId: string,
  signal?: AbortSignal,
): Promise<LessonTopicSourcesRead> =>
  request(`${lessonsPath(projectId)}/sources?program_node_id=${encodeURIComponent(nodeId)}`, { signal });

export const getLesson = (
  projectId: string,
  lessonId: string,
  signal?: AbortSignal,
): Promise<LessonRead> => request(`${lessonsPath(projectId)}/${encodeURIComponent(lessonId)}`, { signal });

/** Без `materialIds` — «Быстрый урок»; со списком — «Из источников». */
export const createQuickLesson = (
  projectId: string,
  nodeId: string,
  materialIds?: string[],
): Promise<LessonChangeResult> => request(`${lessonsPath(projectId)}/quick`, {
  method: "POST",
  body: JSON.stringify({ program_node_id: nodeId, material_ids: materialIds ?? null }),
});

export const createManualLesson = (projectId: string, nodeId: string): Promise<LessonChangeResult> =>
  request(`${lessonsPath(projectId)}/manual`, {
    method: "POST", body: JSON.stringify({ program_node_id: nodeId }),
  });

/** Страница, отмеченная в поиске, — кусок «Урока из найденного». */
export interface FoundPage {
  material_id: string;
  page: number;
}

/** Отмеченные страницы — новым черновиком или в конец открытого урока. */
export const createLessonFromSearch = (
  projectId: string,
  command: { program_node_id: string; pages: FoundPage[]; lesson_id?: string; expected_revision?: number },
): Promise<LessonChangeResult> => request(`${lessonsPath(projectId)}/from-search`, {
  method: "POST",
  body: JSON.stringify(command),
});

export type LessonBlockOperation =
  | "add_note" | "add_page" | "add_outline" | "add_fragments" | "add_block" | "add_link"
  | "add_region"
  | "delete" | "move_up" | "move_down" | "split" | "merge"
  | "set_topic" | "add_topic" | "remove_topic" | "set_always_pages" | "set_collapsed"
  /** Куски-снимки из файла уроков — снова на материал проекта с тем же файлом. */
  | "relink";

export interface LessonBlockCommand {
  expected_revision: number;
  operation: LessonBlockOperation;
  block_id?: string;
  after_block_id?: string;
  /** Вставка перед блоком; задан — важнее `after_block_id`. */
  before_block_id?: string;
  material_id?: string;
  page_from?: number;
  page_to?: number;
  variant?: LessonNoteVariant;
  /** add_fragments — края выделения. */
  from_fragment_id?: string;
  to_fragment_id?: string;
  /** add_block — любой фрагмент блока; split — абзац, после которого разрез. */
  fragment_id?: string;
  split_after_page?: number;
  insert_note?: boolean;
  program_node_id?: string;
  always_pages?: boolean;
  collapsed?: boolean;
  media_url?: string;
  caption?: string;
  /** add_region — доля страницы `[x0, y0, x1, y1]`. */
  region_bbox?: number[];
}

export const editLessonBlocks = (
  projectId: string, lessonId: string, command: LessonBlockCommand,
): Promise<LessonChangeResult> => request(`${lessonsPath(projectId)}/${encodeURIComponent(lessonId)}/blocks`, {
  method: "POST", body: JSON.stringify(command),
});

export const updateLessonNote = (
  projectId: string, lessonId: string, blockId: string,
  command: { expected_revision: number; body_md: string; variant?: LessonNoteVariant },
): Promise<LessonChangeResult> => request(
  `${lessonsPath(projectId)}/${encodeURIComponent(lessonId)}/blocks/${encodeURIComponent(blockId)}`,
  { method: "PATCH", body: JSON.stringify(command) },
);

export const uploadLessonImage = (
  projectId: string, lessonId: string,
  command: { file: File; expected_revision: number; after_block_id?: string; caption?: string },
): Promise<LessonChangeResult> => {
  const form = new FormData();
  form.append("file", command.file);
  form.append("expected_revision", String(command.expected_revision));
  if (command.after_block_id) form.append("after_block_id", command.after_block_id);
  if (command.caption) form.append("caption", command.caption);
  return request(`${lessonsPath(projectId)}/${encodeURIComponent(lessonId)}/media`, { method: "POST", body: form });
};

export const lessonMediaUrl = (projectId: string, lessonId: string, blockId: string): string =>
  `${lessonsPath(projectId)}/${encodeURIComponent(lessonId)}/media/${encodeURIComponent(blockId)}`;

/** «Подтвердить»: снимки тем по текущей программе, пометки сдвинутых разрезов снимаются. */
export const confirmLesson = (projectId: string, lessonId: string, expectedRevision: number): Promise<LessonChangeResult> =>
  request(`${lessonsPath(projectId)}/${encodeURIComponent(lessonId)}/confirm`, {
    method: "POST", body: JSON.stringify({ expected_revision: expectedRevision }),
  });

export const unbindLessonBindings = (projectId: string, lessonId: string, bindingIds: string[]): Promise<LessonChangeResult> =>
  request(`${lessonsPath(projectId)}/${encodeURIComponent(lessonId)}/unbind`, {
    method: "POST", body: JSON.stringify({ binding_ids: bindingIds }),
  });

export type LessonBulkAction = "quick" | "manual";

export interface LessonBulkResult {
  lessons: LessonSummaryRead[];
  latest_undoable_action: LatestUndoableAction | null;
}

/** Массовая подготовка: «пропустить» не присылается, всё остальное — одной транзакцией. */
export const createBulkLessons = (
  projectId: string,
  items: Array<{ program_node_id: string; action: LessonBulkAction }>,
): Promise<LessonBulkResult> => request(`${lessonsPath(projectId)}/bulk`, {
  method: "POST", body: JSON.stringify({ items }),
});

/** Позиция чтения: ни ревизии, ни записи в журнал проекта. */
export const saveLessonPosition = (
  projectId: string, lessonId: string, lastBlockId: string | null,
): Promise<LessonChangeResult> => request(
  `${lessonsPath(projectId)}/${encodeURIComponent(lessonId)}/progress`,
  { method: "POST", body: JSON.stringify({ last_block_id: lastBlockId }) },
);

/** «Урок пройден» — отметка и запись занятия в «Историю»; снятие убирает обе. */
export const setLessonCompleted = (
  projectId: string, lessonId: string, completed: boolean,
): Promise<LessonChangeResult> => request(
  `${lessonsPath(projectId)}/${encodeURIComponent(lessonId)}/completion`,
  { method: "POST", body: JSON.stringify({ completed }) },
);

export const updateLesson = (
  projectId: string,
  lessonId: string,
  command: { title?: string; status?: LessonStatus; expected_revision: number },
): Promise<LessonChangeResult> => request(`${lessonsPath(projectId)}/${encodeURIComponent(lessonId)}`, {
  method: "PATCH",
  body: JSON.stringify(command),
});

/** Привязки урока остаются фактами проекта: удаляется сам урок. */
export const deleteLesson = (projectId: string, lessonId: string): Promise<void> =>
  request(`${lessonsPath(projectId)}/${encodeURIComponent(lessonId)}`, { method: "DELETE" });

export const LESSON_STATUS_LABELS: Record<LessonStatus, string> = {
  draft: "Черновик",
  ready: "Готов",
  archived: "В архиве",
};

export const SOURCE_ROLE_LABELS: Record<SourceRole, string> = {
  main: "основной",
  additional: "дополнительный",
  reference: "справочный",
};

export const LESSON_TEMPLATE_LABELS: Record<LessonTemplate, string> = {
  explain: "Объяснение с нуля",
  guide: "Путеводитель",
  practice: "Через практику",
  cheatsheet: "Шпаргалка",
};

/** Способ создания урока для выбора и экспорта. */
export function lessonTypeLabel(lesson: Pick<LessonSummaryRead, "build" | "creation_type">): string {
  if (lesson.build) return LESSON_TEMPLATE_LABELS[lesson.build.template];
  return lesson.creation_type === "quick" ? "Быстрый урок" : "Вручную";
}

/** Длительность и состояние урока после подписи типа. */
export function lessonCaption(lesson: Pick<LessonSummaryRead, "duration_minutes" | "status">): string {
  return [
    lesson.duration_minutes ? `≈${lesson.duration_minutes} мин` : null,
    LESSON_STATUS_LABELS[lesson.status],
  ].filter(Boolean).join(" · ");
}

export const LESSON_LEVEL_LABELS: Record<LessonLevel, string> = {
  draft: "Черновик",
  standard: "Обычный",
  detailed: "Подробный",
};

export const LESSON_BASIS_LABELS: Record<LessonBasis, string> = {
  sources_and_model: "Материалы + знания модели",
  sources: "Только материалы",
  model_only: "Только знания модели",
};

/** Кусок, выбранный человеком: диапазон фрагментов одного материала (`EvidenceSummary`). */
export interface LessonPinnedRange {
  material_id: string;
  from_fragment_id: string;
  to_fragment_id: string;
}

/** Что пользователь выбрал в диалоге «Собрать урок с ИИ». */
export interface LessonAiOrder {
  program_node_id: string;
  template: LessonTemplate;
  level: LessonLevel;
  basis: LessonBasis;
  /** `null` — материалы по умолчанию: с диапазоном темы, иначе все не справочные. */
  material_ids: string[] | null;
  minutes: number | null;
  wishes: string;
  /** `null` — конспект учитывается, если он не пуст. */
  use_conspect: boolean | null;
  model: { provider_id: string; model_id: string } | null;
  /** Выбранные куски в порядке книги; они обязательны и идут первыми. */
  pinned?: LessonPinnedRange[];
  /** По умолчанию `true`: при `pinned` урок строится из них одних. */
  pinned_only?: boolean;
}

export interface LessonAiMaterialRead {
  material_id: string;
  name: string;
  role: SourceRole;
  priority: number;
  instruction: string | null;
  kind: string;
  is_parsed: boolean;
  page_from: number | null;
  page_to: number | null;
  selected: boolean;
}

export interface LessonAiLevelRead {
  level: LessonLevel;
  calls: number;
  input_tokens: number;
  output_tokens: number;
  /** Верхняя граница: весь предел ответа каждого вызова; `null` — цена модели неизвестна. */
  cost_usd: string | null;
  available: boolean;
  unavailable_reason: string | null;
}

export interface LessonAiPreflightRead {
  program_node_id: string;
  topic_title: string;
  materials: LessonAiMaterialRead[];
  candidates: number;
  candidate_tokens: number;
  material_state: string;
  notes: string[];
  sources_available: boolean;
  default_minutes: number | null;
  conspect_words: number;
  use_conspect: boolean;
  models_available: boolean;
  models_unavailable_reason: string | null;
  provider_id: string | null;
  model_id: string | null;
  model_label: string | null;
  price_known: boolean;
  prices_from: string | null;
  levels: LessonAiLevelRead[];
  /** «Что увидит модель» — тот же паспорт урока, что уйдёт в промпт. */
  brief_text: string;
}

/** Итог задачи сборки: `lesson_id` пуст, если сборку отменили во время вызова. */
export interface LessonAiBuildResult {
  lesson_id: string | null;
  dropped: string[];
  cost_usd: string | null;
}

export const previewLessonAi = (
  projectId: string, order: LessonAiOrder, signal?: AbortSignal,
): Promise<LessonAiPreflightRead> => request(`${lessonsPath(projectId)}/ai/preflight`, {
  method: "POST", body: JSON.stringify(order), signal,
});

export const startLessonAiBuild = (
  projectId: string,
  command: LessonAiOrder & {
    max_cost_usd: string | null;
    confirm_unknown_price: boolean;
    /** Правленый план: сборка по нему, а не «Черновик» и не план внутри задачи. */
    plan?: LessonAiPlanWrite;
  },
): Promise<{ job_id: string }> => request(`${lessonsPath(projectId)}/ai/build`, {
  method: "POST", body: JSON.stringify(command),
});

export type LessonPlanStepKind =
  | "intro" | "prerequisites" | "concept" | "overview" | "example" | "errors" | "summary"
  | "check" | "reading";

export const LESSON_STEP_KIND_LABELS: Record<LessonPlanStepKind, string> = {
  intro: "Вступление",
  prerequisites: "Предпосылки",
  concept: "Объяснение",
  overview: "Как работает целиком",
  example: "Пример",
  errors: "Ошибки",
  summary: "Итог",
  check: "Проверь себя",
  reading: "Чтение учебника",
};

/** Шаг плана урока — как его предложила модель и как его правят в редакторе плана. */
export interface LessonAiPlanStep {
  kind: LessonPlanStepKind;
  title: string;
  intent: string;
  /** Метки кусков карты плана: `C4`. */
  sources: string[];
  collapsed: boolean | null;
  introduces: string[];
}

export interface LessonAiCandidateRead {
  label: string;
  material_name: string;
  title: string | null;
  page_from: number;
  page_to: number;
  tokens: number;
  signals: string[];
}

/** Итог задачи плана: сам план, карта кусков для замены опор и цена сборки по нему. */
export interface LessonAiPlanRead {
  program_node_id: string;
  title: string;
  goal: string;
  concepts: string[];
  steps: LessonAiPlanStep[];
  candidates: LessonAiCandidateRead[];
  template: LessonTemplate;
  level: LessonLevel;
  basis: LessonBasis;
  minutes: number | null;
  dropped: string[];
  step_cost_usd: string | null;
  fixed_cost_usd: string | null;
  fixed_calls: number;
}

export interface LessonAiPlanWrite {
  job_id: string;
  title: string;
  goal: string;
  concepts: string[];
  steps: LessonAiPlanStep[];
}

export const startLessonAiPlan = (
  projectId: string,
  command: LessonAiOrder & { max_cost_usd: string | null; confirm_unknown_price: boolean },
): Promise<{ job_id: string }> => request(`${lessonsPath(projectId)}/ai/plan`, {
  method: "POST", body: JSON.stringify(command),
});

/** Продолжить упавшую сборку с места сбоя; готовые шаги не пересчитываются. */
export const resumeLessonAiBuild = (
  projectId: string, jobId: string, maxCostUsd: string | null,
): Promise<{ job_id: string }> => request(
  `${lessonsPath(projectId)}/ai/jobs/${encodeURIComponent(jobId)}/resume`,
  { method: "POST", body: JSON.stringify({ max_cost_usd: maxCostUsd }) },
);

export type LessonEnrichDepth = "economy" | "full";
export type LessonEnrichOpKind = "insert_note" | "rewrite_note" | "set_collapsed" | "rename_lesson" | "set_goal" | "insert_task";

/** Что выбрано в окне «Дополнить с ИИ». */
export interface LessonEnrichOrder {
  basis: LessonBasis;
  depth: LessonEnrichDepth;
  request: string;
  /** Выбран блок — просьба касается только его. */
  block_id: string | null;
  model: { provider_id: string; model_id: string } | null;
}

export interface LessonEnrichPreflightRead {
  portions: number;
  calls: number;
  input_tokens: number;
  cost_usd: string | null;
  models_available: boolean;
  models_unavailable_reason: string | null;
  model_label: string | null;
  price_known: boolean;
}

export interface LessonProposalOp {
  id: string;
  op: LessonEnrichOpKind;
  block_id: string | null;
  /** Вставка внутрь куска: разрез после этого фрагмента. */
  after_fragment_id: string | null;
  variant: LessonNoteVariant | null;
  body_md: string | null;
  supports: string[];
  basis: LessonBasis | null;
  collapsed: boolean | null;
  text: string | null;
  reason: string;
  /** insert_task: задание с ключом; `block_id` — после какого блока, null — в конец. */
  task?: StudyTaskDraftRead | null;
}

export interface LessonProposalSource {
  label: string;
  block_id: string;
  source_name: string;
  page_from: number;
  page_to: number;
}

/** Итог задачи «Дополнить урок» или «Добавить практику»: изменения ждут решения человека. */
export interface LessonProposalRead {
  kind: "enrich" | "practice";
  lesson_id: string;
  program_node_id: string;
  lesson_revision: number;
  summary: string;
  basis: LessonBasis;
  ops: LessonProposalOp[];
  sources: LessonProposalSource[];
  dropped: string[];
  cost_usd: string | null;
}

export interface LessonProposalApplyResult extends LessonChangeResult {
  /** Выбранные изменения, которые урок уже не принимает: блок пропал, разрез не лёг. */
  conflicts: string[];
}

export const previewLessonEnrich = (
  projectId: string, lessonId: string, order: LessonEnrichOrder, signal?: AbortSignal,
): Promise<LessonEnrichPreflightRead> => request(
  `${lessonsPath(projectId)}/${encodeURIComponent(lessonId)}/ai/enrich/preflight`,
  { method: "POST", body: JSON.stringify(order), signal },
);

export const startLessonEnrich = (
  projectId: string, lessonId: string,
  command: LessonEnrichOrder & { expected_revision: number; max_cost_usd: string | null; confirm_unknown_price: boolean },
): Promise<{ job_id: string }> => request(
  `${lessonsPath(projectId)}/${encodeURIComponent(lessonId)}/ai/enrich`,
  { method: "POST", body: JSON.stringify(command) },
);

export const applyLessonProposal = (
  projectId: string, lessonId: string, jobId: string, command: { op_ids: string[]; expected_revision: number },
): Promise<LessonProposalApplyResult> => request(
  `${lessonsPath(projectId)}/${encodeURIComponent(lessonId)}/proposals/${encodeURIComponent(jobId)}/apply`,
  { method: "POST", body: JSON.stringify(command) },
);

// --- задания урока -------------------------------------------------------------------

export type StudyTaskForm =
  | "single_choice" | "multiple_choice" | "fill_blanks" | "numeric" | "ordering" | "matching" | "open_answer";
export type StudyTaskDifficulty = "remember" | "understand" | "apply";

export const STUDY_TASK_FORM_LABELS: Record<StudyTaskForm, string> = {
  single_choice: "Выбор одного",
  multiple_choice: "Несколько верных",
  fill_blanks: "Пропуски",
  numeric: "Числовой ответ",
  ordering: "Порядок шагов",
  matching: "Сопоставление",
  open_answer: "Открытый ответ",
};

/**
 * Условие по форме: `options` у выбора, `blanks` — число пропусков `{{1}}…`,
 * `unit` у числа, `items` — шаги вперемешку, `left`/`right` — части пар.
 */
export interface StudyTaskPayload {
  options?: string[];
  blanks?: number;
  unit?: string | null;
  items?: string[];
  left?: string[];
  right?: string[];
}

/** Ключ по форме: `correct` у выбора, `answers` у пропусков, `value` у числа, `order`, `match`, `points`. */
export interface StudyTaskKey {
  correct?: number[];
  answers?: string[][];
  value?: number;
  tolerance?: number;
  relative?: boolean;
  order?: number[];
  match?: number[];
  points?: string[];
}

export interface StudyTaskDraftRead {
  form: StudyTaskForm;
  prompt_md: string;
  payload: StudyTaskPayload;
  answer_key: StudyTaskKey;
  reference_md: string | null;
  explanation_md: string;
  hint_md: string | null;
  difficulty: StudyTaskDifficulty;
  basis: LessonBasis;
  supports: string[];
}

/** Ответ по форме; у открытого ответа — `text` попытки. */
export interface StudyTaskAnswer {
  choice?: number;
  choices?: number[];
  blanks?: string[];
  value?: string;
  order?: number[];
  pairs?: Array<number | null>;
}

export type AttemptOutcome = "passed" | "partial" | "failed" | "unscored";

export interface StudyTaskAttemptRead {
  id: string;
  activity_id: string;
  ordinal: number;
  answer: StudyTaskAnswer | { text: string } | null;
  text: string | null;
  /** null — открытый ответ сохранён, но ещё не проверен. */
  outcome: AttemptOutcome | null;
  method: string | null;
  score: number | null;
  items: boolean[];
  summary: string;
  credited: string[];
  missed: string[];
  wrong: string[];
  pending_reason: string | null;
  created_at: string;
}

export interface StudyTaskRead {
  activity_id: string;
  form: StudyTaskForm;
  prompt_md: string;
  payload: StudyTaskPayload;
  answer_key: StudyTaskKey;
  reference_md: string | null;
  explanation_md: string | null;
  hint_md: string | null;
  difficulty: StudyTaskDifficulty;
  basis: LessonBasis;
  sources: Array<{ source_name: string; page_from: number; page_to: number }>;
  attempts: number;
  last_attempt: StudyTaskAttemptRead | null;
}

const taskPath = (projectId: string, lessonId: string, activityId: string) =>
  `${lessonsPath(projectId)}/${encodeURIComponent(lessonId)}/tasks/${encodeURIComponent(activityId)}`;

export const submitStudyTaskAttempt = (
  projectId: string, lessonId: string, activityId: string,
  command: { answer?: StudyTaskAnswer; text?: string; active_seconds?: number | null },
): Promise<StudyTaskAttemptRead> => request(`${taskPath(projectId, lessonId, activityId)}/attempts`, {
  method: "POST", body: JSON.stringify(command),
});

export const checkStudyTaskAttempt = (
  projectId: string, lessonId: string, activityId: string, attemptId: string,
): Promise<StudyTaskAttemptRead> => request(
  `${taskPath(projectId, lessonId, activityId)}/attempts/${encodeURIComponent(attemptId)}/check`,
  { method: "POST" },
);

/** «Добавить практику»: сколько заданий, на чём основаны, какой моделью. */
export interface LessonPracticeOrder {
  basis: LessonBasis;
  count: number;
  request: string;
  model: { provider_id: string; model_id: string } | null;
}

export const previewLessonPractice = (
  projectId: string, lessonId: string, order: LessonPracticeOrder, signal?: AbortSignal,
): Promise<LessonEnrichPreflightRead> => request(
  `${lessonsPath(projectId)}/${encodeURIComponent(lessonId)}/ai/practice/preflight`,
  { method: "POST", body: JSON.stringify(order), signal },
);

export const startLessonPractice = (
  projectId: string, lessonId: string,
  command: LessonPracticeOrder & { expected_revision: number; max_cost_usd: string | null; confirm_unknown_price: boolean },
): Promise<{ job_id: string }> => request(
  `${lessonsPath(projectId)}/${encodeURIComponent(lessonId)}/ai/practice`,
  { method: "POST", body: JSON.stringify(command) },
);

// --- массовая сборка с ИИ ---------------------------------------------------------------

/** «с ИИ» в таблице массовой подготовки: шаблон и основа на все темы, уровень «Черновик». */
export interface LessonAiBulkOrder {
  program_node_ids: string[];
  template: LessonTemplate;
  basis: LessonBasis;
  model: { provider_id: string; model_id: string } | null;
}

export interface LessonAiBulkPreflightRead {
  topics: Array<{ program_node_id: string; title: string; candidates: number; sources_available: boolean }>;
  calls: number;
  cost_usd: string | null;
  models_available: boolean;
  models_unavailable_reason: string | null;
  model_label: string | null;
  price_known: boolean;
}

/** Итог задачи массовой сборки: черновики по темам в порядке программы. */
export interface LessonAiBulkResult {
  kind: "bulk";
  lessons: Array<{ program_node_id: string; topic_title: string; lesson_id: string | null; skipped: string | null; dropped: string[] }>;
  cost_usd: string | null;
}

export const previewLessonAiBulk = (
  projectId: string, order: LessonAiBulkOrder, signal?: AbortSignal,
): Promise<LessonAiBulkPreflightRead> => request(`${lessonsPath(projectId)}/ai/bulk/preflight`, {
  method: "POST", body: JSON.stringify(order), signal,
});

export const startLessonAiBulk = (
  projectId: string, command: LessonAiBulkOrder & { max_cost_usd: string | null; confirm_unknown_price: boolean },
): Promise<{ job_id: string }> => request(`${lessonsPath(projectId)}/ai/bulk`, {
  method: "POST", body: JSON.stringify(command),
});
