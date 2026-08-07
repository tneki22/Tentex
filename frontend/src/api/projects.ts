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
  node_type: "section" | "topic" | "subpoint";
  exam_kind: "question" | "task" | "ticket" | null;
  sort_order: number;
  title: string;
  section_purpose: string | null;
  goal_role: "target" | "prerequisite" | "related" | null;
  target_level: TargetOutcome | null;
  is_in_current_program: boolean;
  needs_material: boolean;
  is_archived: boolean;
  origin_kind: "manual" | "import" | "outline" | "pass1" | "catalog" | "model";
  origin_note: string | null;
  created_at: string;
  updated_at: string;
}

export interface ProjectDetail {
  project: ProjectRead;
  goal_passport: GoalPassportRead | null;
  program_nodes: ProgramNodeRead[];
  workspace_state: {
    project_id: string;
    schema_version: 1;
    layout: Record<string, unknown>;
    updated_at: string;
  } | null;
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

export class ProjectApiError extends Error {
  constructor(public readonly status: number, message: string) {
    super(message);
    this.name = "ProjectApiError";
  }
}

function errorMessage(payload: unknown, status: number): string {
  if (payload && typeof payload === "object" && "detail" in payload) {
    const detail = (payload as { detail: unknown }).detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) {
      return detail
        .map((item) => item && typeof item === "object" && "msg" in item ? String(item.msg) : "")
        .filter(Boolean)
        .join(". ");
    }
  }
  return `Запрос завершился с ошибкой ${status}`;
}

export async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set("Accept", "application/json");
  if (init.body) headers.set("Content-Type", "application/json");
  const response = await fetch(path, { ...init, headers });
  const payload: unknown = await response.json().catch(() => null);
  if (!response.ok) throw new ProjectApiError(response.status, errorMessage(payload, response.status));
  return payload as T;
}

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

function requireProjectUuid(projectId: string): void {
  if (!UUID_PATTERN.test(projectId)) {
    throw new ProjectApiError(404, "Этот демо-проект ещё не подключён к API");
  }
}

export async function getProject(projectId: string, signal?: AbortSignal): Promise<ProjectDetail> {
  requireProjectUuid(projectId);
  return request(`/api/projects/${encodeURIComponent(projectId)}`, { signal });
}

export async function updateProjectSettings(
  projectId: string,
  command: ProjectSettingsCommand,
): Promise<ProjectDetail> {
  requireProjectUuid(projectId);
  return request(`/api/projects/${encodeURIComponent(projectId)}/settings`, {
    method: "PUT",
    body: JSON.stringify(command),
  });
}
