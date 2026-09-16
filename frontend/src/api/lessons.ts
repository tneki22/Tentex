import type { SourceRole } from "./materials";
import { request, type LatestUndoableAction } from "./projects";

export type LessonStatus = "draft" | "ready" | "archived";
export type LessonBlockKind = "source" | "note" | "media" | "activity";
export type LessonNoteVariant =
  | "text" | "heading" | "explanation" | "important" | "example" | "definition" | "warning";
export type LessonBlockOrigin = "manual" | "outline" | "model" | "mixed";

export interface LessonSummaryRead {
  id: string;
  title: string;
  status: LessonStatus;
  duration_minutes: number | null;
  program_node_ids: string[];
  needs_review: boolean;
  completed_at: string | null;
  updated_at: string;
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
}

export interface LessonBlockRead {
  id: string;
  sort_order: number;
  kind: LessonBlockKind;
  variant: LessonNoteVariant | null;
  body_md: string | null;
  origin: LessonBlockOrigin;
  basis: "sources" | "sources_and_model" | "model_only" | null;
  bound_program_node_id: string | null;
  media_kind: "image" | "link" | null;
  /** Только у внешней ссылки; изображение — `lessonMediaUrl`. */
  media_url: string | null;
  refs: LessonRefRead[];
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

export type LessonBlockOperation =
  | "add_note" | "add_page" | "add_outline" | "add_fragments" | "add_block" | "add_link"
  | "add_region"
  | "delete" | "move_up" | "move_down" | "split" | "merge"
  | "set_topic" | "add_topic" | "remove_topic" | "set_always_pages";

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
