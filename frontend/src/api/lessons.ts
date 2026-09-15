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
  region_bbox: number[] | null;
  always_pages: boolean;
  is_available: boolean;
  is_parsed: boolean;
  low_quality_pages: number[];
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
  /** Последнее действие журнала — создание этого урока: доступно «Отменить». */
  undo_sequence: number | null;
  topics: LessonTopicRead[];
  blocks: LessonBlockRead[];
  created_at: string;
  updated_at: string;
}

export interface LessonChangeResult {
  lesson: LessonRead;
  latest_undoable_action: LatestUndoableAction | null;
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

export interface LessonBlockCommand {
  expected_revision: number;
  operation: "add_note" | "add_page" | "add_outline" | "delete" | "move_up" | "move_down";
  block_id?: string;
  after_block_id?: string;
  material_id?: string;
  page_from?: number;
  page_to?: number;
  variant?: LessonNoteVariant;
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

export const updateLesson = (
  projectId: string,
  lessonId: string,
  command: { title?: string; status?: LessonStatus; expected_revision: number },
): Promise<LessonChangeResult> => request(`${lessonsPath(projectId)}/${encodeURIComponent(lessonId)}`, {
  method: "PATCH",
  body: JSON.stringify(command),
});

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
