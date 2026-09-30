/** Компактный учебниковый план; экзаменационный контракт остаётся отдельным. */
import { request } from "./projects";

export interface LessonPlanItem {
  id: string;
  lesson_id: string;
  title: string;
  on_date: string;
  minutes: number;
  origin: "manual" | "local";
}

export interface LessonCandidate {
  id: string;
  title: string;
  minutes: number;
  completed_at: string | null;
  eligible: boolean;
}

export interface LessonTimeInterval {
  id: string;
  session_id: string;
  lesson_id: string;
  started_at: string;
  ended_at: string;
}

export interface LessonPlanningOverview {
  revision: number;
  today: string;
  deadline: string | null;
  daily_minutes: number;
  days_per_week: number;
  readonly: boolean;
  lessons: LessonCandidate[];
  items: LessonPlanItem[];
  unassigned_ids: string[];
  unavailable_ids: string[];
  estimated_finish: string | null;
  outside_deadline_count: number;
  today_seconds: number;
  today_by_lesson: Array<{ lesson_id: string | null; title: string; seconds: number }>;
}

export interface LessonDistribution {
  base_revision: number;
  items: LessonPlanItem[];
  unassigned_ids: string[];
  estimated_finish: string | null;
}

const path = (projectId: string) =>
  `/api/projects/${encodeURIComponent(projectId)}/lesson-planning`;
const json = (method: string, value: unknown) => ({
  method,
  body: JSON.stringify(value),
});

export const lessonPlanning = {
  overview: (projectId: string, signal?: AbortSignal): Promise<LessonPlanningOverview> =>
    request(path(projectId), { signal }),
  preview: (projectId: string, mode: "append" | "rebuild_future"): Promise<LessonDistribution> =>
    request(`${path(projectId)}/preview`, json("POST", { mode })),
  save: (projectId: string, expected_revision: number, items: LessonPlanItem[]): Promise<LessonPlanningOverview> =>
    request(`${path(projectId)}/plan`, json("PUT", { expected_revision, items })),
  time: (projectId: string, intervals: LessonTimeInterval[]): Promise<{ accepted_ids: string[]; ignored_ids: string[] }> =>
    request(`${path(projectId)}/time`, json("POST", { intervals })),
};
