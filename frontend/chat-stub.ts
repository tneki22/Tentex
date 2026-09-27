/** Подставленный API общего чата свободного проекта для Playwright-сценариев чата. */
import type { Page, Route } from "@playwright/test";

export const BASE = process.env.TENTEX_TEST_URL ?? "http://localhost:5173";
export const PROJECT = "11111111-1111-4111-8111-111111111111";
export const SESSION = "55555555-5555-4555-8555-555555555555";
export const MATERIAL = "22222222-2222-4222-8222-222222222222";
export const NOW = "2026-09-27T10:00:00Z";

export interface StubSource {
  id: string;
  material: string;
  material_id: string;
  locator: string;
  page: number | null;
  text: string;
  block_title?: string | null;
  warning?: string | null;
}

export function source(id: string, text: string, extra: Partial<StubSource> = {}): StubSource {
  return {
    id, material: "Лекции по базам данных", material_id: MATERIAL, locator: "стр. 12", page: 12, text,
    block_title: "Нормальные формы", warning: null, ...extra,
  };
}

let sequence = 0;
export function message(role: "user" | "examiner", text: string, sources: StubSource[] = [], id?: string) {
  sequence += 1;
  return {
    id: id ?? `m-${sequence}`, session_id: SESSION, sequence, role, text, stream_state: "complete",
    payload_kind: "none", payload: {}, context_snapshot: sources.length ? { retrieval_sources: sources } : {},
    skill: null, ai_run_id: null, attempt_id: null, grade_attempt_id: null, created_at: NOW, updated_at: NOW,
  };
}

export function sse(frames: Array<[string, unknown]>): string {
  return frames.map(([event, data]) => `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`).join("");
}

export interface ChatStubOptions {
  messages?: ReturnType<typeof message>[];
  /** Ответ на POST …/messages: готовое тело SSE или JSON-ошибка. */
  onSend?: (body: Record<string, unknown>) => { status?: number; sse?: string; json?: unknown };
}

export async function installChatStub(page: Page, options: ChatStubOptions = {}) {
  const sent: Array<Record<string, unknown>> = [];
  const messages = options.messages ?? [];
  await page.route((url) => url.pathname.startsWith("/api/"), async (route: Route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    const method = request.method();
    const json = (value: unknown, status = 200) =>
      route.fulfill({ status, contentType: "application/json", body: JSON.stringify(value) });
    const chat = `/api/projects/${PROJECT}/chat`;

    if (path === `/api/projects/${PROJECT}` && method === "GET") {
      return json({
        project: {
          id: PROJECT, template_key: "free", workspace_variant: "textbook", status: "active", name: "Базы данных",
          description: null, icon: "book-open", color: 4, sort_order: 0, deadline: null,
          enabled_modules: ["plan", "lessons"], status_changed_at: NOW, created_at: NOW, updated_at: NOW,
        },
        goal_passport: null,
        program: { revision: 1, nodes: [] },
        workspace_state: null,
        latest_undoable_action: null,
      });
    }
    if (path === `${chat}/sessions` && method === "GET") {
      return json([{
        id: SESSION, project_id: PROJECT, program_node_id: null, title: "Чат проекта", updated_at: NOW,
        message_count: messages.length, last_outcome: null,
      }]);
    }
    if (path === `${chat}/sessions/${SESSION}` && method === "GET") {
      return json({
        id: SESSION, project_id: PROJECT, program_node_id: null, section_scope_node_id: null, title: "Чат проекта",
        mode: "study", persona: "calm_teacher", strictness: "normal", model_override: null, model_parameters: {},
        context_flags: { profile: true, reference: true, fragments: true, attempts: false, section_memory: false },
        draft_text: "", created_at: NOW, updated_at: NOW, messages,
      });
    }
    if (path === `${chat}/sessions/${SESSION}/messages` && method === "POST") {
      const body = request.postDataJSON() as Record<string, unknown>;
      sent.push(body);
      const reply = options.onSend?.(body) ?? { sse: sse([]) };
      if (reply.sse !== undefined) {
        return route.fulfill({ status: reply.status ?? 200, contentType: "text/event-stream", body: reply.sse });
      }
      return json(reply.json, reply.status ?? 200);
    }
    if (path === `${chat}/sessions/${SESSION}/context`) {
      return json({
        session_id: SESSION, node_id: null, question: "", persona: "calm_teacher", strictness: "normal",
        model_source: "auto", model_id: "test/model", manifest: [], fingerprint: "f", total_bytes: 0,
      });
    }
    if (path === `${chat}/sessions/${SESSION}/draft`) return json({ text: "", updated_at: NOW });
    if (path === `${chat}/capabilities`) {
      return json({
        modes: [{ key: "study", title: "Разобраться", available: true, unavailable_reason: null }],
        skills: [], tools: [],
      });
    }
    if (path === "/api/settings/ai") {
      return json({ external_models_enabled: true, providers: [], roles: [], models: [] });
    }
    return json([]);
  });
  return { sent };
}
