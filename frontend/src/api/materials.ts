import { ProjectApiError, request, type ProgramChangeResult } from "./projects";
import type { AiPreflight, AiUsage } from "./ai";
import type { BackgroundJobStartRead } from "./backgroundJobs";

export type MaterialPurpose = "exam_structure" | "reference_answers" | "study_source";
export type ExamMaterialSlot =
  | "question_list"
  | "question_answers"
  | "task_list"
  | "task_answers";
export type MaterialState =
  | "ready_to_process"
  | "queued"
  | "processing"
  | "paused"
  | "ready"
  | "failed";
export type ParserMode = "fast";
export type PageQuality = "native" | "ocr" | "ocr_low";
export type RecognitionSource = "native" | "ocr" | "vl" | "manual";
export type SourceRole = "main" | "additional" | "reference";
export type MaterialSourceKind = "file" | "text" | "url" | "youtube" | "audio";

export interface ProcessingTaskRead {
  id: string;
  state: "queued" | "running" | "paused" | "failed" | "completed";
  stage: "queued" | "extract" | "segment" | "complete";
  parser_mode: ParserMode;
  done: number;
  total: number;
  diagnostics: string[];
  error: string | null;
  created_at: string;
  updated_at: string;
}

export interface MaterialRead {
  id: string;
  original_name: string;
  display_name: string;
  media_type: string;
  source_kind: MaterialSourceKind;
  source_url: string | null;
  retrieved_at: string | null;
  size_bytes: number;
  page_count: number | null;
  source_role: SourceRole;
  priority: number;
  instruction: string | null;
  purposes: MaterialPurpose[];
  exam_slot: ExamMaterialSlot | null;
  status: MaterialState;
  parser_mode: ParserMode | null;
  active_parse_revision: number;
  scan_page_count: number;
  ocr_low_page_count: number;
  estimated_seconds: number | null;
  outline: Array<{ level: number; title: string; page: number }>;
  diagnostics: string[];
  error: string | null;
  task: ProcessingTaskRead | null;
  attached_at: string;
  created_at: string;
  updated_at: string;
}

export type MaterialUpdateCommand = Partial<
  Pick<MaterialRead, "display_name" | "source_role" | "priority" | "instruction" | "purposes" | "exam_slot">
> & {
  replace_reference_answers?: boolean;
};

export interface MaterialFragmentRead {
  id: string;
  block_id: string;
  sort_order: number;
  text: string;
  bbox: number[];
  element_kind: string;
  has_asset: boolean;
  structure_level: number | null;
  degraded_structure: boolean;
  quality: PageQuality;
  recognition_source: RecognitionSource;
  confidence: number | null;
  /** Границы сегмента у расшифровки аудио и субтитров; у остальных — null. */
  time_from: number | null;
  time_to: number | null;
}

export interface MaterialBlockRead {
  id: string;
  sort_order: number;
  title: string | null;
  block_class: "content" | "service";
  service_reason: string | null;
  page_from: number;
  page_to: number;
}

export interface MaterialPageRead {
  id: string;
  page_number: number;
  width: number;
  height: number;
  text: string;
  markdown: string;
  quality: PageQuality;
  confidence: number | null;
  reviewed_at: string | null;
  diagnostics: string[];
  fragments: MaterialFragmentRead[];
  blocks: MaterialBlockRead[];
}

export interface MaterialAnswerImportResult {
  created: number;
  skipped_existing: number;
  unmatched_sections: string[];
  ambiguous_sections: string[];
  empty_sections: string[];
}

export interface LibraryUsageRead {
  project_id: string;
  project_name: string;
  project_status: string;
  display_name: string;
  source_role: SourceRole;
  purposes: MaterialPurpose[];
  exam_slot: ExamMaterialSlot | null;
}

export interface LibraryMaterialRead {
  id: string;
  original_name: string;
  media_type: string;
  source_kind: MaterialSourceKind;
  source_url: string | null;
  size_bytes: number;
  page_count: number | null;
  status: MaterialState;
  parser_mode: ParserMode | null;
  native_page_count: number;
  ocr_page_count: number;
  ocr_low_page_count: number;
  block_count: number;
  fragment_count: number;
  sha256: string;
  created_at: string;
  usage: LibraryUsageRead[];
}

/* ── Глобальная Библиотека. Общий материал не знает про проект: роли,
   назначения и привязки живут в `ProjectMaterial` и остаются проектными. ── */

export type MaterialPresentationKind =
  | "pdf"
  | "image"
  | "document"
  | "plain_text"
  | "web"
  | "youtube"
  | "audio";

export type OutlineSource = "embedded" | "recognized" | "none";

export type RevisionOrigin =
  | "imported"
  | "parse"
  | "manual_edit"
  | "ai_cleanup"
  | "source_refresh"
  | "restore";

export type ProcessingScope = "all" | "needs_review" | "range";

export interface LibraryMaterialCapabilities {
  can_compare: boolean;
  can_view_original: boolean;
  can_edit_text: boolean;
  can_run_ocr: boolean;
  can_refresh_source: boolean;
  has_outline: boolean;
  has_timeline: boolean;
}

export interface OutlineItem {
  level: number;
  title: string;
  page: number;
}

export interface PageStateRead {
  page_number: number;
  quality: PageQuality;
  reviewed_at: string | null;
}

export interface MaterialRevisionRead {
  revision: number;
  origin: RevisionOrigin;
  parser_mode: ParserMode | null;
  parent_revision: number | null;
  scope: Record<string, unknown>;
  summary: Record<string, unknown>;
  created_at: string;
  is_current: boolean;
}

export interface LibraryMaterialDetailRead extends LibraryMaterialRead {
  presentation_kind: MaterialPresentationKind;
  capabilities: LibraryMaterialCapabilities;
  outline: OutlineItem[];
  outline_source: OutlineSource;
  page_states: PageStateRead[];
  active_parse_revision: number;
  parser_mode: ParserMode | null;
  scan_page_count: number;
  estimated_seconds: number | null;
  diagnostics: string[];
  error: string | null;
  task: ProcessingTaskRead | null;
  retrieved_at: string | null;
  updated_at: string;
}

export interface LibrarySearchHit {
  fragment_id: string;
  page_number: number;
  block_title: string | null;
  bbox: number[];
  text: string;
  rank: number;
}

export interface LibrarySearchResult {
  query: string;
  revision: number;
  hits: LibrarySearchHit[];
}

export interface SourceRefreshResult {
  material: LibraryMaterialDetailRead;
  revision: number;
  changed: boolean;
}

export interface AffectedProjectPreview {
  project_id: string;
  project_name: string;
  nodes_losing_material: string[];
}

export interface MaterialDeletePreview {
  material: LibraryMaterialRead;
  active_task: boolean;
  reference_answer_count: number;
  binding_count: number;
  affected_projects: AffectedProjectPreview[];
}

/** Последствия удаления пачки. Для одного файла — пачка из одного. */
export interface MaterialsDeletePreview {
  materials: LibraryMaterialRead[];
  active_task_count: number;
  reference_answer_count: number;
  binding_count: number;
  affected_projects: AffectedProjectPreview[];
}

export interface PageCorrectionRead {
  page: MaterialPageRead;
  transferred_bindings: number;
  orphaned_binding_ids: string[];
}

export interface CleanupSuggestion {
  markdown: string;
  changes: string[];
  warnings: string[];
}

export interface CleanupPreflightRead {
  material_id: string;
  page_id: string;
  page_number: number;
  revision: number;
  source_hash: string;
  source_bytes: number;
  preflight: AiPreflight;
}

export interface CleanupRunRead {
  run_id: string;
  material_id: string;
  page_id: string;
  page_number: number;
  revision: number;
  source_hash: string;
  suggestion: CleanupSuggestion;
  usage: AiUsage;
  requested_model_id: string;
  actual_model_id: string;
  cached: boolean;
}

export interface ExamProgramPreview {
  material_id: string;
  material_name: string;
  counts: { tickets: number; questions: number; tasks: number; subpoints?: number };
  warnings: string[];
  has_duplicates: boolean;
  nodes: Array<{
    node_type: "section" | "topic" | "subpoint";
    exam_kind: "question" | "task" | "ticket";
    title: string;
    depth: number;
  }>;
}

export interface ExamCompositeDraftImportResult {
  change: ProgramChangeResult;
  counts: { questions: number; tasks: number; subpoints: number };
  warnings: string[];
}

const projectMaterialsPath = (projectId: string): string =>
  `/api/projects/${encodeURIComponent(projectId)}/materials`;

const materialPath = (projectId: string, materialId: string): string =>
  `${projectMaterialsPath(projectId)}/${encodeURIComponent(materialId)}`;

async function uploadResponse(response: Response): Promise<MaterialRead> {
  const payload: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    const record = payload && typeof payload === "object" ? payload as Record<string, unknown> : {};
    const detail = typeof record.detail === "string"
      ? record.detail
      : `Загрузка завершилась с ошибкой ${response.status}`;
    const context = record.context && typeof record.context === "object"
      ? record.context as Record<string, unknown>
      : {};
    throw new ProjectApiError(
      response.status,
      detail,
      typeof record.code === "string" ? record.code : null,
      context,
    );
  }
  return payload as MaterialRead;
}

/** POST через XHR вместо fetch: только у него есть событие прогресса отправки —
 *  для стомегабайтных файлов индикатор нужен, иначе окно выглядит зависшим. */
function uploadFormWithProgress<T>(
  url: string,
  form: FormData,
  onProgress?: (percent: number) => void,
): Promise<T> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", url);
    xhr.responseType = "json";
    xhr.setRequestHeader("Accept", "application/json");
    xhr.upload.onprogress = (event) => {
      if (onProgress && event.lengthComputable) {
        onProgress(Math.round((event.loaded / event.total) * 100));
      }
    };
    xhr.onerror = () => reject(new ProjectApiError(0, "Не удалось подключиться к серверу"));
    xhr.onload = () => {
      const payload = xhr.response as unknown;
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(payload as T);
        return;
      }
      const record = payload && typeof payload === "object" ? payload as Record<string, unknown> : {};
      const detail = typeof record.detail === "string"
        ? record.detail
        : `Загрузка завершилась с ошибкой ${xhr.status}`;
      const context = record.context && typeof record.context === "object"
        ? record.context as Record<string, unknown>
        : {};
      reject(new ProjectApiError(
        xhr.status,
        detail,
        typeof record.code === "string" ? record.code : null,
        context,
      ));
    };
    xhr.send(form);
  });
}

export const listMaterials = (projectId: string, signal?: AbortSignal): Promise<MaterialRead[]> =>
  request(projectMaterialsPath(projectId), { signal });

export async function uploadMaterial(
  projectId: string,
  file: File,
  sourceRole: SourceRole,
  purposes: MaterialPurpose[],
  examSlot?: ExamMaterialSlot | null,
): Promise<MaterialRead> {
  const form = new FormData();
  form.set("file", file);
  form.set("source_role", sourceRole);
  form.set("purposes", purposes.join(","));
  if (examSlot) form.set("exam_slot", examSlot);
  return uploadResponse(await fetch(projectMaterialsPath(projectId), {
    method: "POST",
    headers: { Accept: "application/json" },
    body: form,
  }));
}

export const createTextMaterial = (
  projectId: string,
  command: {
    name: string;
    text: string;
    source_role: SourceRole;
    purposes: MaterialPurpose[];
    exam_slot?: ExamMaterialSlot | null;
  },
): Promise<MaterialRead> => request(`${projectMaterialsPath(projectId)}/text`, {
  method: "POST",
  body: JSON.stringify(command),
});

export const createExternalMaterial = (
  projectId: string,
  command: {
    kind: "url" | "youtube";
    url: string;
    source_role: SourceRole;
    purposes: MaterialPurpose[];
    exam_slot?: ExamMaterialSlot | null;
  },
): Promise<MaterialRead> => request(`${projectMaterialsPath(projectId)}/external`, {
  method: "POST",
  body: JSON.stringify(command),
});

export const updateMaterial = (
  projectId: string,
  materialId: string,
  command: MaterialUpdateCommand,
): Promise<MaterialRead> => request(materialPath(projectId, materialId), {
  method: "PATCH",
  body: JSON.stringify(command),
});

export const detachMaterial = (projectId: string, materialId: string): Promise<void> =>
  request(materialPath(projectId, materialId), { method: "DELETE" });

export const startMaterialProcessing = (
  projectId: string,
  materialId: string,
  parserMode: ParserMode,
): Promise<MaterialRead> => request(`${materialPath(projectId, materialId)}/processing`, {
  method: "POST",
  body: JSON.stringify({ parser_mode: parserMode }),
});

export const controlMaterialProcessing = (
  projectId: string,
  materialId: string,
  action: "pause" | "resume" | "retry" | "cancel",
): Promise<MaterialRead> => request(`${materialPath(projectId, materialId)}/processing/${action}`, {
  method: "POST",
});

export const getMaterialPage = (
  projectId: string,
  materialId: string,
  page: number,
  signal?: AbortSignal,
  taskId?: string,
): Promise<MaterialPageRead> => request(
  `${materialPath(projectId, materialId)}/pages/${page}`
    + (taskId ? `?task_id=${encodeURIComponent(taskId)}` : ""),
  { signal },
);

export const updateMaterialPageText = (
  projectId: string,
  materialId: string,
  page: number,
  text: string,
  expected?: { revision: number; sourceHash?: string },
): Promise<PageCorrectionRead> => request(
  `${materialPath(projectId, materialId)}/pages/${page}`,
  {
    method: "PUT",
    body: JSON.stringify({
      text,
      expected_revision: expected?.revision,
      expected_source_hash: expected?.sourceHash,
    }),
  },
);

export const preflightMaterialPageCleanup = (
  projectId: string,
  materialId: string,
  page: number,
  instruction: string,
  signal?: AbortSignal,
): Promise<CleanupPreflightRead> => request(
  `${materialPath(projectId, materialId)}/pages/${page}/ai-cleanup/preflight`,
  { method: "POST", body: JSON.stringify({ instruction }), signal },
);

export const runMaterialPageCleanup = (
  projectId: string,
  materialId: string,
  page: number,
  command: {
    instruction: string;
    expected_revision: number;
    expected_source_hash: string;
    confirmed: boolean;
  },
  signal?: AbortSignal,
): Promise<BackgroundJobStartRead> => request(
  `${materialPath(projectId, materialId)}/pages/${page}/ai-cleanup`,
  { method: "POST", body: JSON.stringify(command), signal },
);

export const applyMaterialPageCleanup = (
  projectId: string,
  materialId: string,
  page: number,
  command: {
    run_id: string;
    expected_revision: number;
    expected_source_hash: string;
    markdown: string;
  },
  signal?: AbortSignal,
): Promise<PageCorrectionRead> => request(
  `${materialPath(projectId, materialId)}/pages/${page}/ai-cleanup/apply`,
  { method: "POST", body: JSON.stringify(command), signal },
);

export const materialPageImageUrl = (
  projectId: string,
  materialId: string,
  page: number,
): string => `${materialPath(projectId, materialId)}/pages/${page}/image`;

/** Картинка, вынутая из PDF или DOCX: показывается на своём месте в тексте. */
export const materialFragmentAssetUrl = (
  projectId: string,
  materialId: string,
  fragmentId: string,
): string => `${materialPath(projectId, materialId)}/fragments/${encodeURIComponent(fragmentId)}/asset`;

export const importMaterialReferenceAnswers = (
  projectId: string,
  materialId: string,
): Promise<MaterialAnswerImportResult> => request(
  `${materialPath(projectId, materialId)}/reference-answer-import`,
  { method: "POST" },
);

export const listLibraryMaterials = (signal?: AbortSignal): Promise<LibraryMaterialRead[]> =>
  request("/api/materials", { signal });

export const getMaterialDeletePreview = (
  materialId: string,
  signal?: AbortSignal,
): Promise<MaterialDeletePreview> => request(
  `/api/materials/${encodeURIComponent(materialId)}/delete-preview`,
  { signal },
);

export const deleteLibraryMaterial = (materialId: string): Promise<void> => request(
  `/api/materials/${encodeURIComponent(materialId)}`,
  { method: "DELETE" },
);

export const previewMaterialsDelete = (
  materialIds: string[],
  signal?: AbortSignal,
): Promise<MaterialsDeletePreview> => request("/api/materials/delete-preview", {
  method: "POST",
  body: JSON.stringify({ material_ids: materialIds }),
  signal,
});

export const deleteLibraryMaterials = (materialIds: string[]): Promise<void> => request(
  "/api/materials/bulk-delete",
  { method: "POST", body: JSON.stringify({ material_ids: materialIds }) },
);

/* ── Глобальные операции над общим материалом ── */

const libraryPath = (materialId: string): string =>
  `/api/materials/${encodeURIComponent(materialId)}`;

export const getLibraryMaterial = (
  materialId: string,
  signal?: AbortSignal,
): Promise<LibraryMaterialDetailRead> => request(libraryPath(materialId), { signal });

export function uploadLibraryMaterial(
  file: File,
  onProgress?: (percent: number) => void,
): Promise<LibraryMaterialDetailRead> {
  const form = new FormData();
  form.set("file", file);
  return uploadFormWithProgress<LibraryMaterialDetailRead>("/api/materials/upload", form, onProgress);
}

export const createLibraryTextMaterial = (
  command: { name: string; text: string },
): Promise<LibraryMaterialDetailRead> => request("/api/materials/text", {
  method: "POST",
  body: JSON.stringify(command),
});

export const createLibraryExternalMaterial = (
  command: { kind: "url" | "youtube"; url: string },
): Promise<LibraryMaterialDetailRead> => request("/api/materials/external", {
  method: "POST",
  body: JSON.stringify(command),
});

export const attachLibraryMaterial = (
  materialId: string,
  command: {
    project_id: string;
    display_name?: string | null;
    source_role: SourceRole;
    purposes: MaterialPurpose[];
    exam_slot?: ExamMaterialSlot | null;
  },
): Promise<LibraryMaterialDetailRead> => request(`${libraryPath(materialId)}/project-links`, {
  method: "POST",
  body: JSON.stringify(command),
});

export const getLibraryPage = (
  materialId: string,
  page: number,
  options: { revision?: number; taskId?: string; signal?: AbortSignal } = {},
): Promise<MaterialPageRead> => {
  const query = new URLSearchParams();
  if (options.revision !== undefined) query.set("revision", String(options.revision));
  if (options.taskId) query.set("task_id", options.taskId);
  const suffix = query.size ? `?${query.toString()}` : "";
  return request(`${libraryPath(materialId)}/pages/${page}${suffix}`, { signal: options.signal });
};

export const libraryPageImageUrl = (materialId: string, page: number): string =>
  `${libraryPath(materialId)}/pages/${page}/image`;

export const libraryFragmentAssetUrl = (materialId: string, fragmentId: string): string =>
  `${libraryPath(materialId)}/fragments/${encodeURIComponent(fragmentId)}/asset`;

export const librarySourceUrl = (materialId: string, revision?: number): string =>
  revision === undefined
    ? `${libraryPath(materialId)}/source`
    : `${libraryPath(materialId)}/source?revision=${revision}`;

export const searchLibraryMaterial = (
  materialId: string,
  query: string,
  options: { revision?: number; limit?: number; signal?: AbortSignal } = {},
): Promise<LibrarySearchResult> => {
  const params = new URLSearchParams({ q: query });
  if (options.revision !== undefined) params.set("revision", String(options.revision));
  if (options.limit !== undefined) params.set("limit", String(options.limit));
  return request(`${libraryPath(materialId)}/search?${params.toString()}`, {
    signal: options.signal,
  });
};

export const listMaterialRevisions = (
  materialId: string,
  signal?: AbortSignal,
): Promise<MaterialRevisionRead[]> => request(`${libraryPath(materialId)}/revisions`, { signal });

export const restoreMaterialRevision = (
  materialId: string,
  revision: number,
): Promise<LibraryMaterialDetailRead> => request(
  `${libraryPath(materialId)}/revisions/${revision}/restore`,
  { method: "POST" },
);

export const startLibraryProcessing = (
  materialId: string,
  command: {
    parser_mode: ParserMode;
    scope: ProcessingScope;
    page_from?: number | null;
    page_to?: number | null;
  },
): Promise<LibraryMaterialDetailRead> => request(`${libraryPath(materialId)}/processing`, {
  method: "POST",
  body: JSON.stringify(command),
});

export const controlLibraryProcessing = (
  materialId: string,
  action: "pause" | "resume" | "retry" | "cancel",
): Promise<LibraryMaterialDetailRead> => request(
  `${libraryPath(materialId)}/processing/${action}`,
  { method: "POST" },
);

export const updateLibraryPageText = (
  materialId: string,
  page: number,
  text: string,
  expected?: { revision: number; sourceHash?: string },
): Promise<PageCorrectionRead> => request(`${libraryPath(materialId)}/pages/${page}`, {
  method: "PUT",
  body: JSON.stringify({
    text,
    expected_revision: expected?.revision,
    expected_source_hash: expected?.sourceHash,
  }),
});

export const confirmLibraryPageReview = (
  materialId: string,
  page: number,
): Promise<LibraryMaterialDetailRead> => request(
  `${libraryPath(materialId)}/pages/${page}/confirm-review`,
  { method: "POST" },
);

export const refreshLibrarySource = (materialId: string): Promise<SourceRefreshResult> =>
  request(`${libraryPath(materialId)}/source/refresh`, { method: "POST" });

export const preflightLibraryPageCleanup = (
  materialId: string,
  page: number,
  instruction: string,
  signal?: AbortSignal,
): Promise<CleanupPreflightRead> => request(
  `${libraryPath(materialId)}/pages/${page}/ai-cleanup/preflight`,
  { method: "POST", body: JSON.stringify({ instruction }), signal },
);

export const runLibraryPageCleanup = (
  materialId: string,
  page: number,
  command: {
    instruction: string;
    expected_revision: number;
    expected_source_hash: string;
    confirmed: boolean;
  },
  signal?: AbortSignal,
): Promise<BackgroundJobStartRead> => request(
  `${libraryPath(materialId)}/pages/${page}/ai-cleanup`,
  { method: "POST", body: JSON.stringify(command), signal },
);

export const applyLibraryPageCleanup = (
  materialId: string,
  page: number,
  command: {
    run_id: string;
    expected_revision: number;
    expected_source_hash: string;
    markdown: string;
  },
  signal?: AbortSignal,
): Promise<PageCorrectionRead> => request(
  `${libraryPath(materialId)}/pages/${page}/ai-cleanup/apply`,
  { method: "POST", body: JSON.stringify(command), signal },
);

export const previewExamProgram = (
  projectId: string,
  materialId: string,
  signal?: AbortSignal,
): Promise<ExamProgramPreview> => request(
  `${materialPath(projectId, materialId)}/exam-program-preview`,
  { signal },
);

export const importExamProgramFromMaterial = (
  projectId: string,
  materialId: string,
  expectedProgramRevision: number,
  dedupeDuplicates = false,
): Promise<ProgramChangeResult> => request(
  `${materialPath(projectId, materialId)}/exam-program-import`,
  {
    method: "POST",
    body: JSON.stringify({
      expected_program_revision: expectedProgramRevision,
      dedupe_duplicates: dedupeDuplicates,
    }),
  },
);

export const importExamDraftProgramFromMaterial = (
  projectId: string,
  materialId: string,
  expectedDraftRevision: number,
  expectedProgramRevision: number,
  dedupeDuplicates = false,
): Promise<ProgramChangeResult> => request(
  `${materialPath(projectId, materialId)}/exam-draft-import`,
  {
    method: "POST",
    body: JSON.stringify({
      expected_draft_revision: expectedDraftRevision,
      expected_program_revision: expectedProgramRevision,
      dedupe_duplicates: dedupeDuplicates,
    }),
  },
);

export const importCompositeExamDraftProgram = (
  projectId: string,
  command: {
    expected_draft_revision: number;
    expected_program_revision: number;
    question_material_id?: string | null;
    task_material_id?: string | null;
    dedupe_duplicates?: boolean;
  },
): Promise<ExamCompositeDraftImportResult> => request(
  `${projectMaterialsPath(projectId)}/exam-composite-draft-import`,
  { method: "POST", body: JSON.stringify(command) },
);
