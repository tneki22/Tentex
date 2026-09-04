/** Клиент подготовки: DTO генерируются из серверного OpenAPI. */
import { request } from "./projects";
import type { components } from "./generated/preparation";
export type Schema = components["schemas"];
export type Overview = Schema["OverviewRead"];
export type Plan = Schema["PlanRead"];
export type Phase = Schema["Phase"];
export type PlanItem = Schema["PlanItem"];
export type Unit = Schema["UnitRead"];
export type Draft = Schema["DraftRead"];
export type DraftWrite = Schema["DraftWrite"];
export type Config = Schema["PreparationConfig"];
export type Activity = Schema["ActivityRead"];
export type Interval = Schema["TimeIntervalWrite"];
export type Queue = Schema["QueueRead"];
export type Coach = Schema["CoachRead"];
export type AiWrite = Schema["PreparationAiWrite"];
export type WorkKind = PlanItem["kind"];
const path = (id: string) =>
  `/api/projects/${encodeURIComponent(id)}/preparation`;
const body = (method: string, value: unknown) => ({
  method,
  body: JSON.stringify(value),
});
export const preparation = {
  overview: (
    id: string,
    start?: string,
    end?: string,
    signal?: AbortSignal,
  ): Promise<Overview> =>
    request(
      `${path(id)}?${new URLSearchParams({ ...(start ? { start } : {}), ...(end ? { end } : {}) })}`,
      { signal },
    ),
  settings: (
    id: string,
    value: Schema["SettingsWrite"],
  ): Promise<Schema["SettingsRead"]> =>
    request(`${path(id)}/settings`, body("PUT", value)),
  time: (id: string, intervals: Interval[]): Promise<Schema["TimeBatchRead"]> =>
    request(`${path(id)}/time`, body("POST", { intervals })),
  activity: (
    id: string,
    value: Schema["ManualActivityWrite"],
  ): Promise<Activity> =>
    request(`${path(id)}/activities/${value.id}`, body("PUT", value)),
  deleteActivity: (id: string, activity: string): Promise<void> =>
    request(`${path(id)}/activities/${activity}`, { method: "DELETE" }),
  understood: (id: string, unit_id: string, understood = true): Promise<void> =>
    request(`${path(id)}/understood`, body("POST", { unit_id, understood })),
  quality: (id: string, attempt: string, quality: number): Promise<void> =>
    request(
      `${path(id)}/attempts/${attempt}/quality`,
      body("PUT", { quality }),
    ),
  history: (
    id: string,
    filters: URLSearchParams,
    signal?: AbortSignal,
  ): Promise<Schema["HistoryRead"]> =>
    request(`${path(id)}/history?${filters}`, { signal }),
  draft: (id: string, value: DraftWrite): Promise<Draft> =>
    request(`${path(id)}/drafts`, body("POST", value)),
  getDraft: (id: string, draft: string, signal?: AbortSignal): Promise<Draft> =>
    request(`${path(id)}/drafts/${draft}`, { signal }),
  apply: (
    id: string,
    draft: string,
    value: Schema["ApplyDraftWrite"],
  ): Promise<Plan> =>
    request(`${path(id)}/drafts/${draft}/apply`, body("POST", value)),
  undo: (id: string, expected_revision: number): Promise<Plan> =>
    request(`${path(id)}/undo`, body("POST", { expected_revision })),
  queue: (
    id: string,
    date: string,
    start = false,
    signal?: AbortSignal,
  ): Promise<Queue> =>
    request(`${path(id)}/queue?on_date=${date}`, {
      method: start ? "POST" : "GET",
      signal,
    }),
  position: (
    id: string,
    date: string,
    value: Schema["QueuePositionWrite"],
  ): Promise<Queue> =>
    request(`${path(id)}/queue?on_date=${date}`, body("PUT", value)),
  preflight: (
    id: string,
    value: AiWrite,
  ): Promise<Schema["PreparationAiPreflightRead"]> =>
    request(`${path(id)}/ai/preflight`, body("POST", value)),
  ai: (id: string, value: AiWrite): Promise<Schema["AiStartRead"]> =>
    request(`${path(id)}/ai`, body("POST", value)),
};
export const workLabels: Record<WorkKind, string> = {
  learn: "Разобрать",
  answer: "Сдать ответ",
  review: "Повторить",
  gaps: "Разобрать пробелы",
  final: "Финальный прогон",
};
export const activityLabels: Record<string, string> = {
  view: "Просмотр вопроса",
  reading: "Чтение",
  material: "Материал",
  conspect: "Конспект",
  chat: "Чат",
  answer: "Ответ",
  manual: "Ручное занятие",
  understood: "Разобрался",
};
export const outcomeLabels: Record<string, string> = {
  passed: "Зачтено",
  partial: "Частично",
  failed: "Не зачтено",
  unscored: "Без оценки",
  pending: "Ожидает проверки",
};
/** Ревизии снимка проверяет сервер для каждого предложения. */
export const revisions = (overview: Overview) => ({
  expected_plan_revision: overview.plan.revision,
  expected_program_revision: overview.plan.program_revision,
  expected_settings_revision: overview.settings.revision,
});
export const errorText = (error: unknown) =>
  error instanceof Error
    ? error.message
    : "Не удалось сохранить. Повторите действие.";
