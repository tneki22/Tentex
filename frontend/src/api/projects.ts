export type ProjectStatus = "draft" | "active" | "archived" | "completed";
export type WorkspaceVariant = "exam" | "textbook";
export type TemplateKey = "exam" | "textbook" | "free";
export type ModuleKey = "plan" | "lessons" | "cards" | "repetitions" | "oral_answers" | "sql";
export type GoalPurpose = "exam" | "work" | "interview" | "interest";
export type GoalScope = "whole" | "goal";
export type StartingLevel = "beginner" | "familiar" | "refreshing";
export type TargetOutcome = "awareness" | "understanding" | "application" | "mastery";
export type StudyFormat = "theory" | "theory_and_practice" | "practice";
export type ExamFormat = "questions" | "questions_tasks" | "tickets" | "unknown";
export type NodeType = "section" | "topic" | "subpoint";
export type ExamKind = "question" | "task" | "ticket";
export type GoalRole = "target" | "prerequisite" | "related";
export type ProjectIconName =
  | "graduation-cap"
  | "book-open"
  | "database"
  | "sigma"
  | "atom"
  | "code"
  | "globe"
  | "scale"
  | "flask";

export interface ProjectRead {
  id: string;
  template_key: TemplateKey;
  workspace_variant: WorkspaceVariant;
  status: ProjectStatus;
  name: string | null;
  description: string | null;
  icon: ProjectIconName | null;
  color: number | null;
  sort_order: number;
  deadline: string | null;
  enabled_modules: ModuleKey[];
  status_changed_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface ProjectSummary {
  id: string;
  template_key: TemplateKey;
  workspace_variant: WorkspaceVariant;
  status: Exclude<ProjectStatus, "draft">;
  name: string;
  description: string | null;
  icon: ProjectIconName | null;
  color: number | null;
  sort_order: number;
  deadline: string | null;
  status_changed_at: string | null;
  updated_at: string;
}

/**
 * Сводка для карточки проекта. `null` — метрика не считается для этого типа
 * проекта: по FR-P3 она не показывается и не заменяется нулём. Ноль здесь
 * означает настоящий ноль.
 */
export interface ProjectStats {
  project_id: string;
  program_nodes: number | null;
  reference_answers: number | null;
  materials: number;
  material_pages: number | null;
  last_activity_at: string | null;
}

export interface GoalPassportWrite {
  subject: string | null;
  purpose: GoalPurpose | null;
  scope: GoalScope | null;
  starting_level: StartingLevel | null;
  current_knowledge: string | null;
  target_outcome: TargetOutcome | null;
  goal: string | null;
  success_criterion: string | null;
  important: string | null;
  excluded: string | null;
  study_format: StudyFormat | null;
  minutes_per_day: number | null;
  days_per_week: number | null;
  session_minutes: number | null;
  exam_format: ExamFormat | null;
  expected_item_count: number | null;
  instructor_requirements: string | null;
}

export interface GoalPassportRead extends GoalPassportWrite {
  project_id: string;
  updated_at: string;
}

export interface ProgramNodeRead {
  id: string;
  project_id: string;
  parent_id: string | null;
  node_type: NodeType;
  exam_kind: ExamKind | null;
  sort_order: number;
  title: string;
  section_purpose: string | null;
  goal_role: GoalRole | null;
  target_level: TargetOutcome | null;
  is_in_current_program: boolean;
  needs_material: boolean;
  is_archived: boolean;
  origin_kind: "manual" | "import" | "outline" | "pass1" | "catalog" | "model";
  origin_note: string | null;
  origin_material_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface ProgramState {
  nodes: ProgramNodeRead[];
  revision: number;
}

export interface LatestUndoableAction {
  sequence: number;
  action_type: string;
  target_title: string;
  created_at: string;
}

export type WorkspaceTab = "answer" | "source" | "lesson" | "conspect" | "history" | "chat" | "summary";

export interface WorkspaceLayout {
  selected_node_id: string | null;
  expanded_node_ids: string[];
  tree_width: number;
  groups: Array<{ id: string; tabs: WorkspaceTab[]; active_tab: WorkspaceTab | null }>;
  group_weights: number[];
}

export interface WorkspaceStateRead {
  project_id: string;
  schema_version: 1;
  layout: WorkspaceLayout;
  updated_at: string;
}

export interface ProjectDetail {
  project: ProjectRead;
  goal_passport: GoalPassportRead | null;
  program: ProgramState;
  workspace_state: WorkspaceStateRead | null;
  latest_undoable_action: LatestUndoableAction | null;
}

export interface WizardDraftSummary {
  project_id: string;
  template_key: TemplateKey;
  workspace_variant: WorkspaceVariant;
  name: string | null;
  current_step: number;
  max_completed_step: number;
  revision: number;
  updated_at: string;
}

export interface WizardDraftDetail {
  project: ProjectRead;
  draft: {
    project_id: string;
    current_step: number;
    max_completed_step: number;
    revision: number;
    schema_version: number;
    state: Record<string, unknown>;
    updated_at: string;
  };
  goal_passport: GoalPassportRead | null;
  program: ProgramState;
  latest_undoable_action: LatestUndoableAction | null;
}

export interface ProjectSettingsCommand {
  project: {
    name: string;
    description: string | null;
    icon: ProjectIconName | null;
    color: number | null;
    deadline: string | null;
    enabled_modules: ModuleKey[];
  };
  goal_passport: GoalPassportWrite;
}

export interface ProjectSettingsResult {
  project: ProjectRead;
  goal_passport: GoalPassportRead;
}

export interface WizardDraftCommand {
  expected_revision: number;
  current_step: number;
  max_completed_step: number;
  schema_version: number;
  project: {
    name: string | null;
    description: string | null;
    icon: ProjectIconName | null;
    color: number | null;
    deadline: string | null;
    enabled_modules: ModuleKey[];
  };
  goal_passport: GoalPassportWrite | null;
  state: Record<string, unknown>;
}

export interface ProgramChangeResult {
  changed_node: ProgramNodeRead | null;
  program: ProgramState;
  latest_undoable_action: LatestUndoableAction | null;
  draft_revision: number | null;
}

export interface ProgramGroupingItem {
  title: string;
  rationale: string;
  node_ids: string[];
}

export interface ProgramGroupingPreflightRead {
  program_revision: number;
  source_hash: string;
  node_count: number;
  preflight: import("./ai").AiPreflight;
}

export interface ProgramGroupingRunRead {
  run_id: string;
  program_revision: number;
  source_hash: string;
  suggestion: { groups: ProgramGroupingItem[] };
  usage: import("./ai").AiUsage;
  requested_model_id: string;
  actual_model_id: string;
  cached: boolean;
}

export interface ProgramImportRepairPreflightRead {
  program_revision: number;
  source_hash: string;
  node_count: number;
  has_tickets: boolean;
  preflight: import("./ai").AiPreflight;
}

export interface RepairedQuestion {
  kind: "question" | "task";
  title: string;
  subpoints: string[];
  source_indices: number[];
}

export interface RepairedTicket {
  kind: "ticket";
  title: string;
  source_indices: number[];
  items: RepairedQuestion[];
}

export type RepairedItem = RepairedQuestion | RepairedTicket;

export interface DroppedItem {
  source_indices: number[];
  reason: string;
}

export interface ProgramImportRepairRunRead {
  run_id: string;
  program_revision: number;
  source_hash: string;
  has_tickets: boolean;
  source_texts: string[];
  items: RepairedItem[];
  dropped: DroppedItem[];
  changes: string[];
  warnings: string[];
  usage: import("./ai").AiUsage;
  requested_model_id: string;
  actual_model_id: string;
  cached: boolean;
}

export interface ActionUndoResult {
  undone_action_type: string;
  program: ProgramState | null;
  draft_revision: number | null;
  latest_undoable_action: LatestUndoableAction | null;
}

export interface ExamImportResult {
  revision: number;
  counts: { tickets: number; questions: number; tasks: number };
  warnings: string[];
  program: ProgramState;
  latest_undoable_action: LatestUndoableAction | null;
}

export type ReferenceAnswerStatus = "missing" | "auto_matched" | "confirmed" | "needs_review" | "manual";

export interface ReferenceAnswerRead {
  project_id: string;
  program_node_id: string;
  text: string;
  origin_kind: "manual" | "import";
  match_method: "manual" | "exact_title";
  matched_title: string | null;
  is_confirmed: boolean;
  is_active: boolean;
  revision: number;
  source_label: string | null;
  source_material_id: string | null;
  source_page_from: number | null;
  source_page_to: number | null;
  source_only: boolean;
  created_at: string;
  updated_at: string;
}

export interface ReferenceAnswerSlot {
  project_id: string;
  node_id: string;
  node_title: string;
  status: ReferenceAnswerStatus;
  answer: ReferenceAnswerRead | null;
}

export interface CoverageMapRow {
  node_id: string;
  parent_id: string | null;
  node_type: NodeType;
  exam_kind: ExamKind | null;
  title: string;
  sort_order: number;
  is_in_current_program: boolean;
  target_level: TargetOutcome | null;
  answer_status: ReferenceAnswerStatus | null;
  answer_preview: string | null;
  answer_revision: number | null;
}

export interface CoverageMapRead {
  project_id: string;
  program_revision: number;
  rows: CoverageMapRow[];
  totals: {
    study_nodes: number;
    with_answer: number;
    confirmed: number;
    needs_review: number;
    missing: number;
  };
}

export interface ReferenceAnswerImportIssue {
  heading: string;
  preview: string | null;
  candidate_node_ids: string[];
}

export interface ReferenceAnswerImportResult {
  created: number;
  skipped_existing: string[];
  ambiguous: ReferenceAnswerImportIssue[];
  unmatched_sections: ReferenceAnswerImportIssue[];
  empty_sections: string[];
  coverage_map: CoverageMapRead;
}

export class ProjectApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
    public readonly code: string | null = null,
    public readonly context: Record<string, unknown> = {},
  ) {
    super(message);
    this.name = "ProjectApiError";
  }
}

function errorPayload(payload: unknown, status: number): {
  message: string;
  code: string | null;
  context: Record<string, unknown>;
} {
  if (payload && typeof payload === "object") {
    const record = payload as Record<string, unknown>;
    const code = typeof record.code === "string" ? record.code : null;
    const context = record.context && typeof record.context === "object"
      ? record.context as Record<string, unknown>
      : {};
    if (typeof record.detail === "string") return { message: record.detail, code, context };
    if (Array.isArray(record.detail)) {
      const message = record.detail
        .map((item) => item && typeof item === "object" && "msg" in item ? String(item.msg) : "")
        .filter(Boolean)
        .join(". ");
      if (message) return { message, code, context };
    }
  }
  return { message: `Запрос завершился с ошибкой ${status}`, code: null, context: {} };
}

export async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set("Accept", "application/json");
  // FormData сам проставляет multipart-границу: свой Content-Type её ломает.
  if (typeof init.body === "string") headers.set("Content-Type", "application/json");
  const response = await fetch(path, { ...init, headers });
  const payload: unknown = response.status === 204 ? null : await response.json().catch(() => null);
  if (!response.ok) {
    const error = errorPayload(payload, response.status);
    throw new ProjectApiError(response.status, error.message, error.code, error.context);
  }
  return payload as T;
}

const projectPath = (projectId: string): string => `/api/projects/${encodeURIComponent(projectId)}`;
const draftPath = (projectId: string): string => `/api/wizard-drafts/${encodeURIComponent(projectId)}`;

export const getProject = (projectId: string, signal?: AbortSignal): Promise<ProjectDetail> =>
  request(projectPath(projectId), { signal });

export const listProjects = (signal?: AbortSignal): Promise<ProjectSummary[]> =>
  request("/api/projects", { signal });

export const listProjectStats = (signal?: AbortSignal): Promise<ProjectStats[]> =>
  request("/api/projects/stats", { signal });

export const saveProjectOrder = (projectIds: string[]): Promise<ProjectSummary[]> =>
  request("/api/projects/order", { method: "PUT", body: JSON.stringify({ project_ids: projectIds }) });

export const archiveProject = (projectId: string): Promise<ProjectSummary> =>
  request(`${projectPath(projectId)}/archive`, { method: "POST" });

export const restoreProject = (projectId: string): Promise<ProjectSummary> =>
  request(`${projectPath(projectId)}/restore`, { method: "POST" });

export const deleteProject = (projectId: string): Promise<void> =>
  request(projectPath(projectId), { method: "DELETE" });

export const getCoverageMap = (projectId: string, signal?: AbortSignal): Promise<CoverageMapRead> =>
  request(`${projectPath(projectId)}/coverage-map`, { signal });

export const getReferenceAnswer = (
  projectId: string,
  nodeId: string,
  signal?: AbortSignal,
): Promise<ReferenceAnswerSlot> => request(
  `${projectPath(projectId)}/program-nodes/${encodeURIComponent(nodeId)}/reference-answer`,
  { signal },
);

export const putReferenceAnswer = (
  projectId: string,
  nodeId: string,
  command: { expected_revision: number | null; text: string; source_label?: string | null },
): Promise<ReferenceAnswerSlot> => request(
  `${projectPath(projectId)}/program-nodes/${encodeURIComponent(nodeId)}/reference-answer`,
  { method: "PUT", body: JSON.stringify(command) },
);

export const confirmReferenceAnswer = (
  projectId: string,
  nodeId: string,
  expectedRevision: number,
): Promise<ReferenceAnswerSlot> => request(
  `${projectPath(projectId)}/program-nodes/${encodeURIComponent(nodeId)}/reference-answer/confirm`,
  { method: "POST", body: JSON.stringify({ expected_revision: expectedRevision }) },
);

export const deleteReferenceAnswer = (
  projectId: string,
  nodeId: string,
  expectedRevision: number,
): Promise<ReferenceAnswerSlot> => request(
  `${projectPath(projectId)}/program-nodes/${encodeURIComponent(nodeId)}/reference-answer?expected_revision=${expectedRevision}`,
  { method: "DELETE" },
);

export interface ReferenceAnswerAttachment {
  id: string;
  program_node_id: string;
  file_name: string;
  media_type: string;
  size_bytes: number;
  created_at: string;
}

export const listAnswerAttachments = (
  projectId: string,
  nodeId: string,
  signal?: AbortSignal,
): Promise<ReferenceAnswerAttachment[]> => request(
  `${projectPath(projectId)}/reference-answers/${encodeURIComponent(nodeId)}/attachments`,
  { signal },
);

export const addAnswerAttachment = async (
  projectId: string,
  nodeId: string,
  file: File,
): Promise<ReferenceAnswerAttachment> => {
  const body = new FormData();
  body.append("file", file);
  return request(
    `${projectPath(projectId)}/reference-answers/${encodeURIComponent(nodeId)}/attachments`,
    { method: "POST", body },
  );
};

export const deleteAnswerAttachment = (
  projectId: string,
  attachmentId: string,
): Promise<void> => request(
  `${projectPath(projectId)}/attachments/${encodeURIComponent(attachmentId)}`,
  { method: "DELETE" },
);

export const answerAttachmentUrl = (projectId: string, attachmentId: string): string =>
  `${projectPath(projectId)}/attachments/${encodeURIComponent(attachmentId)}/file`;

export const importReferenceAnswers = (
  projectId: string,
  command: { raw_text: string; source_label?: string | null },
): Promise<ReferenceAnswerImportResult> => request(
  `${projectPath(projectId)}/reference-answers/import`,
  { method: "POST", body: JSON.stringify(command) },
);

export const updateProjectSettings = (
  projectId: string,
  command: ProjectSettingsCommand,
): Promise<ProjectSettingsResult> => request(`${projectPath(projectId)}/settings`, {
  method: "PUT",
  body: JSON.stringify(command),
});

export const createWizardDraft = (templateKey: TemplateKey): Promise<WizardDraftDetail> =>
  request("/api/wizard-drafts", { method: "POST", body: JSON.stringify({ template_key: templateKey }) });

export const listWizardDrafts = (signal?: AbortSignal): Promise<WizardDraftSummary[]> =>
  request("/api/wizard-drafts", { signal });

export const getWizardDraft = (projectId: string, signal?: AbortSignal): Promise<WizardDraftDetail> =>
  request(draftPath(projectId), { signal });

export const saveWizardDraft = (
  projectId: string,
  command: WizardDraftCommand,
): Promise<WizardDraftDetail> => request(draftPath(projectId), {
  method: "PUT",
  body: JSON.stringify(command),
});

export const discardWizardDraft = (projectId: string, expectedRevision: number): Promise<void> =>
  request(`${draftPath(projectId)}?expected_revision=${expectedRevision}`, { method: "DELETE" });

export const activateWizardDraft = (projectId: string, expectedRevision: number): Promise<ProjectDetail> =>
  request(`${draftPath(projectId)}/activate`, {
    method: "POST",
    body: JSON.stringify({ expected_revision: expectedRevision }),
  });

export const importExamProgram = (
  projectId: string,
  command: {
    expected_revision: number;
    expected_program_revision: number;
    exam_format: Exclude<ExamFormat, "unknown">;
    raw_text: string;
  },
): Promise<ExamImportResult> => request(`${draftPath(projectId)}/exam-import`, {
  method: "POST",
  body: JSON.stringify(command),
});

interface ProgramCommandBase { expected_program_revision: number }

export const createProgramNode = (
  projectId: string,
  command: ProgramCommandBase & {
    parent_id?: string | null;
    position?: number | null;
    node_type: NodeType;
    exam_kind?: ExamKind | null;
    title: string;
    section_purpose?: string | null;
    goal_role?: GoalRole | null;
    target_level?: TargetOutcome | null;
    needs_material?: boolean;
  },
): Promise<ProgramChangeResult> => request(`${projectPath(projectId)}/program-nodes`, {
  method: "POST",
  body: JSON.stringify(command),
});

export const updateProgramNode = (
  projectId: string,
  nodeId: string,
  command: ProgramCommandBase & Partial<Pick<ProgramNodeRead, "title" | "node_type" | "exam_kind" | "section_purpose" | "goal_role" | "needs_material">>,
): Promise<ProgramChangeResult> => request(`${projectPath(projectId)}/program-nodes/${encodeURIComponent(nodeId)}`, {
  method: "PATCH",
  body: JSON.stringify(command),
});

export const moveProgramNode = (
  projectId: string,
  nodeId: string,
  command: ProgramCommandBase & { parent_id: string | null; position: number | null },
): Promise<ProgramChangeResult> => request(`${projectPath(projectId)}/program-nodes/${encodeURIComponent(nodeId)}/move`, {
  method: "POST",
  body: JSON.stringify(command),
});

export const swapProgramNodes = (
  projectId: string,
  nodeId: string,
  command: ProgramCommandBase & { target_node_id: string },
): Promise<ProgramChangeResult> => request(`${projectPath(projectId)}/program-nodes/${encodeURIComponent(nodeId)}/swap`, {
  method: "POST",
  body: JSON.stringify(command),
});

export const setProgramTargetLevel = (
  projectId: string,
  nodeId: string,
  command: ProgramCommandBase & { target_level: TargetOutcome; include_descendants: boolean },
): Promise<ProgramChangeResult> => request(`${projectPath(projectId)}/program-nodes/${encodeURIComponent(nodeId)}/target-level`, {
  method: "POST",
  body: JSON.stringify(command),
});

const revisionCommand = (
  suffix: "remove" | "restore",
  projectId: string,
  nodeId: string,
  expectedProgramRevision: number,
): Promise<ProgramChangeResult> => request(`${projectPath(projectId)}/program-nodes/${encodeURIComponent(nodeId)}/${suffix}`, {
  method: "POST",
  body: JSON.stringify({ expected_program_revision: expectedProgramRevision }),
});

export const removeProgramNode = (projectId: string, nodeId: string, revision: number) =>
  revisionCommand("remove", projectId, nodeId, revision);

export const restoreProgramNode = (projectId: string, nodeId: string, revision: number) =>
  revisionCommand("restore", projectId, nodeId, revision);

export const undoProjectAction = (
  projectId: string,
  expectedActionSequence: number,
): Promise<ActionUndoResult> => request(`${projectPath(projectId)}/actions/undo`, {
  method: "POST",
  body: JSON.stringify({ expected_action_sequence: expectedActionSequence }),
});

export const preflightProgramGrouping = (
  projectId: string,
  signal?: AbortSignal,
): Promise<ProgramGroupingPreflightRead> => request(`${projectPath(projectId)}/program/ai-grouping/preflight`, {
  method: "POST",
  body: JSON.stringify({}),
  signal,
});

export const runProgramGrouping = (
  projectId: string,
  command: {
    expected_program_revision: number;
    expected_source_hash: string;
    confirmed: boolean;
  },
  signal?: AbortSignal,
): Promise<ProgramGroupingRunRead> => request(`${projectPath(projectId)}/program/ai-grouping`, {
  method: "POST",
  body: JSON.stringify(command),
  signal,
});

export const applyProgramGrouping = (
  projectId: string,
  command: {
    run_id: string;
    expected_program_revision: number;
    expected_source_hash: string;
    groups: ProgramGroupingItem[];
  },
  signal?: AbortSignal,
): Promise<ProgramChangeResult> => request(`${projectPath(projectId)}/program/ai-grouping/apply`, {
  method: "POST",
  body: JSON.stringify(command),
  signal,
});

export const preflightProgramImportRepair = (
  projectId: string,
  signal?: AbortSignal,
): Promise<ProgramImportRepairPreflightRead> =>
  request(`${projectPath(projectId)}/program/ai-import-repair/preflight`, {
    method: "POST",
    body: JSON.stringify({}),
    signal,
  });

export const runProgramImportRepair = (
  projectId: string,
  command: {
    instruction: string;
    expected_program_revision: number;
    expected_source_hash: string;
    confirmed: boolean;
  },
  signal?: AbortSignal,
): Promise<ProgramImportRepairRunRead> => request(`${projectPath(projectId)}/program/ai-import-repair`, {
  method: "POST",
  body: JSON.stringify(command),
  signal,
});

export const applyProgramImportRepair = (
  projectId: string,
  command: {
    run_id: string;
    expected_program_revision: number;
    expected_source_hash: string;
    items: RepairedItem[];
  },
  signal?: AbortSignal,
): Promise<ProgramChangeResult> => request(`${projectPath(projectId)}/program/ai-import-repair/apply`, {
  method: "POST",
  body: JSON.stringify(command),
  signal,
});

export const saveWorkspaceState = (
  projectId: string,
  layout: WorkspaceLayout,
): Promise<WorkspaceStateRead> => request(`${projectPath(projectId)}/workspace-state`, {
  method: "PUT",
  body: JSON.stringify({ schema_version: 1, layout }),
});
