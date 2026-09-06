/** Тонкий клиент карточек; структуры ответов берутся из OpenAPI. */
import type { components } from "./generated/preparation";
import { request } from "./projects";

export type CardRead = components["schemas"]["CardRead"];
export type CardListRead = components["schemas"]["CardListRead"];
export type CardOverviewRead = components["schemas"]["CardOverviewRead"];
export type CardCreate = components["schemas"]["CardCreate"];
export type CardUpdate = components["schemas"]["CardUpdate"];
export type CardBulkWrite = components["schemas"]["CardBulkWrite"];
export type CardSessionCreate = components["schemas"]["CardSessionCreate"];
export type CardSessionRead = components["schemas"]["CardSessionRead"];
export type SessionProgressWrite = components["schemas"]["SessionProgressWrite"];
export type SessionReviewWrite = components["schemas"]["SessionReviewWrite"];
export type SessionDeferWrite = components["schemas"]["SessionDeferWrite"];
export type SessionRetryWrite = components["schemas"]["SessionRetryWrite"];
export type FragmentPrefillRead = components["schemas"]["FragmentPrefillRead"];

export interface CardFilters {
  query?: string;
  unitId?: string;
  state?: "active" | "suspended";
  source?: "none" | "fragment" | "reference";
  rating?: "unrated" | "hard" | "recalled" | "lost";
  includeDeleted?: boolean;
}

const projectPath = (projectId: string): string =>
  `/api/projects/${encodeURIComponent(projectId)}`;

export const getCardsOverview = (
  projectId: string,
  period: 7 | 30,
  signal?: AbortSignal,
): Promise<CardOverviewRead> =>
  request(`${projectPath(projectId)}/cards/overview?period=${period}`, { signal });

export const listCards = (
  projectId: string,
  filters: CardFilters = {},
  signal?: AbortSignal,
): Promise<CardListRead> => {
  const query = new URLSearchParams();
  if (filters.query) query.set("query", filters.query);
  if (filters.unitId) query.set("unit_id", filters.unitId);
  if (filters.state) query.set("state", filters.state);
  if (filters.source) query.set("source", filters.source);
  if (filters.rating) query.set("rating", filters.rating);
  if (filters.includeDeleted) query.set("include_deleted", "true");
  const suffix = query.size ? `?${query}` : "";
  return request(`${projectPath(projectId)}/cards${suffix}`, { signal });
};

export const createCard = (
  projectId: string,
  command: CardCreate,
): Promise<CardRead> =>
  request(`${projectPath(projectId)}/cards`, {
    method: "POST",
    body: JSON.stringify(command),
  });

export const updateCard = (
  projectId: string,
  cardId: string,
  command: CardUpdate,
): Promise<CardRead> =>
  request(`${projectPath(projectId)}/cards/${encodeURIComponent(cardId)}`, {
    method: "PATCH",
    body: JSON.stringify(command),
  });

export const bulkCards = (
  projectId: string,
  command: CardBulkWrite,
): Promise<CardListRead> =>
  request(`${projectPath(projectId)}/cards/bulk`, {
    method: "POST",
    body: JSON.stringify(command),
  });

export const getFragmentCardPrefill = (
  projectId: string,
  fragmentId: string,
  signal?: AbortSignal,
): Promise<FragmentPrefillRead> =>
  request(
    `${projectPath(projectId)}/cards/fragments/${encodeURIComponent(fragmentId)}/prefill`,
    { signal },
  );

export const createCardSession = (
  projectId: string,
  command: CardSessionCreate,
): Promise<CardSessionRead> =>
  request(`${projectPath(projectId)}/card-sessions`, {
    method: "POST",
    body: JSON.stringify(command),
  });

export const getActiveCardSession = (
  projectId: string,
  signal?: AbortSignal,
): Promise<CardSessionRead> =>
  request(`${projectPath(projectId)}/card-sessions/active`, { signal });

export const saveCardSessionProgress = (
  projectId: string,
  sessionId: string,
  command: SessionProgressWrite,
): Promise<CardSessionRead> =>
  request(`${projectPath(projectId)}/card-sessions/${sessionId}`, {
    method: "PATCH",
    body: JSON.stringify(command),
  });

export const openCardSessionUnit = (
  projectId: string,
  sessionId: string,
  expectedRevision: number,
): Promise<CardSessionRead> =>
  request(`${projectPath(projectId)}/card-sessions/${sessionId}/open`, {
    method: "POST",
    body: JSON.stringify({ expected_revision: expectedRevision }),
  });

export const reviewCard = (
  projectId: string,
  sessionId: string,
  cardId: string,
  command: SessionReviewWrite,
): Promise<CardSessionRead> =>
  request(`${projectPath(projectId)}/card-sessions/${sessionId}/cards/${cardId}/review`, {
    method: "POST",
    body: JSON.stringify(command),
  });

export const deferCard = (
  projectId: string,
  sessionId: string,
  cardId: string,
  command: SessionDeferWrite,
): Promise<CardSessionRead> =>
  request(`${projectPath(projectId)}/card-sessions/${sessionId}/cards/${cardId}/defer`, {
    method: "POST",
    body: JSON.stringify(command),
  });

export const finishCardSession = (
  projectId: string,
  sessionId: string,
  expectedRevision: number,
  action: "complete" | "cancel" = "complete",
): Promise<CardSessionRead> =>
  request(`${projectPath(projectId)}/card-sessions/${sessionId}/finish`, {
    method: "POST",
    body: JSON.stringify({ expected_revision: expectedRevision, action }),
  });

export const retryCardSession = (
  projectId: string,
  sessionId: string,
  expectedRevision: number,
): Promise<CardSessionRead> =>
  request(`${projectPath(projectId)}/card-sessions/${sessionId}/retry`, {
    method: "POST",
    body: JSON.stringify({ expected_revision: expectedRevision }),
  });
