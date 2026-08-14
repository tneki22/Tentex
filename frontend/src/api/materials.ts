import { ProjectApiError, request, type ProgramChangeResult } from "./projects";
import type { AiPreflight, AiUsage } from "./ai";

export type MaterialPurpose = "exam_structure" | "reference_answers" | "study_source";
export type MaterialState =
  | "ready_to_process"
  | "queued"
  | "processing"
  | "paused"
  | "ready"
  | "failed";
export type ParserMode = "fast" | "textbook";
export type PageQuality = "native" | "ocr" | "ocr_low";
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
  Pick<MaterialRead, "display_name" | "source_role" | "priority" | "instruction" | "purposes">
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
  diagnostics: string[];
  fragments: MaterialFragmentRead[];
  blocks: MaterialBlockRead[];
}

export interface MaterialCapabilities {
  fast_available: boolean;
  fast_label: string;
  textbook_available: boolean;
  textbook_reason: string;
  cloud_reason: string;
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
  native_page_count: number;
  ocr_page_count: number;
  ocr_low_page_count: number;
  block_count: number;
  fragment_count: number;
  sha256: string;
  created_at: string;
  usage: LibraryUsageRead[];
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
  counts: { tickets: number; questions: number; tasks: number };
  warnings: string[];
  nodes: Array<{
    node_type: "section" | "topic" | "subpoint";
    exam_kind: "question" | "task" | "ticket";
    title: string;
    depth: number;
  }>;
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

export const listMaterials = (projectId: string, signal?: AbortSignal): Promise<MaterialRead[]> =>
  request(projectMaterialsPath(projectId), { signal });

export async function uploadMaterial(
  projectId: string,
  file: File,
  sourceRole: SourceRole,
  purposes: MaterialPurpose[],
): Promise<MaterialRead> {
  const form = new FormData();
  form.set("file", file);
  form.set("source_role", sourceRole);
  form.set("purposes", purposes.join(","));
  return uploadResponse(await fetch(projectMaterialsPath(projectId), {
    method: "POST",
    headers: { Accept: "application/json" },
    body: form,
  }));
}

export const createTextMaterial = (
  projectId: string,
  command: { name: string; text: string; source_role: SourceRole; purposes: MaterialPurpose[] },
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
  action: "pause" | "resume" | "retry",
): Promise<MaterialRead> => request(`${materialPath(projectId, materialId)}/processing/${action}`, {
  method: "POST",
});

export const getMaterialPage = (
  projectId: string,
  materialId: string,
  page: number,
  signal?: AbortSignal,
): Promise<MaterialPageRead> => request(
  `${materialPath(projectId, materialId)}/pages/${page}`,
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
): Promise<CleanupRunRead> => request(
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

export const getMaterialCapabilities = (signal?: AbortSignal): Promise<MaterialCapabilities> =>
  request("/api/material-capabilities", { signal });

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
): Promise<ProgramChangeResult> => request(
  `${materialPath(projectId, materialId)}/exam-program-import`,
  { method: "POST", body: JSON.stringify({ expected_program_revision: expectedProgramRevision }) },
);

export const importExamDraftProgramFromMaterial = (
  projectId: string,
  materialId: string,
  expectedDraftRevision: number,
  expectedProgramRevision: number,
): Promise<ProgramChangeResult> => request(
  `${materialPath(projectId, materialId)}/exam-draft-import`,
  {
    method: "POST",
    body: JSON.stringify({
      expected_draft_revision: expectedDraftRevision,
      expected_program_revision: expectedProgramRevision,
    }),
  },
);
