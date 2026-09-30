/** Свободное изучение, Уроки: тема без оглавления получает урок из найденного на подставленном API. */
import { expect, test, type Page, type Route } from "@playwright/test";

const BASE = process.env.TENTEX_TEST_URL ?? "http://localhost:5173";
const PROJECT = "11111111-1111-4111-8111-111111111111";
const MATERIAL = "22222222-2222-4222-8222-222222222222";
const TOPIC = "33333333-3333-4333-8333-333333333333";
const LESSON = "44444444-4444-4444-8444-444444444444";
const NOW = "2026-09-23T10:00:00Z";

const topic = {
  id: TOPIC,
  project_id: PROJECT,
  parent_id: null,
  node_type: "topic",
  exam_kind: null,
  sort_order: 0,
  title: "Операция свёртки",
  section_purpose: null,
  goal_role: "prerequisite",
  target_level: "understanding",
  is_in_current_program: true,
  needs_material: true,
  is_archived: false,
  origin_kind: "model",
  basis_kind: "custom",
  origin_note: null,
  origin_material_id: null,
  material_search_queries: ["операция свёртки"],
  material_kind: "lecture",
  source_page_ranges: [],
  created_at: NOW,
  updated_at: NOW,
};

const material = {
  id: MATERIAL,
  original_name: "cnn.pdf",
  display_name: "Свёрточные сети — конспект",
  library_display_name: "Свёрточные сети — конспект",
  project_display_name: null,
  media_type: "application/pdf",
  source_kind: "file",
  presentation_kind: "pdf",
  source_url: null,
  retrieved_at: null,
  size_bytes: 1024,
  page_count: 20,
  source_role: "main",
  priority: 0,
  instruction: null,
  purposes: ["study_source"],
  exam_slot: null,
  status: "ready",
  parser_mode: "fast",
  active_parse_revision: 1,
  scan_page_count: 0,
  ocr_low_page_count: 0,
  estimated_seconds: null,
  outline: [],
  diagnostics: [],
  error: null,
  task: null,
  attached_at: NOW,
  created_at: NOW,
  updated_at: NOW,
};

function searchPage(page: number, text: string) {
  return { page_number: page, fragment_ids: [`f-${page}`], quality: "native", text, highlights: [], already_bound: false };
}

async function installStub(page: Page) {
  const created: Array<Record<string, unknown>> = [];
  let lessons: Array<Record<string, unknown>> = [];

  await page.route((url) => url.pathname.startsWith("/api/"), async (route: Route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    const method = request.method();
    const json = (value: unknown, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(value) });

    if (path === `/api/projects/${PROJECT}` && method === "GET") {
      return json({
        project: {
          id: PROJECT, template_key: "free", workspace_variant: "textbook", status: "active", name: "Нейросети",
          description: null, icon: "book-open", color: 4, sort_order: 0, deadline: null,
          enabled_modules: ["plan", "lessons", "repetitions"], status_changed_at: NOW, created_at: NOW, updated_at: NOW,
        },
        goal_passport: null,
        program: { revision: 1, nodes: [topic] },
        workspace_state: null,
        latest_undoable_action: null,
      });
    }
    if (path === `/api/projects/${PROJECT}/lessons/overview`) return json({ lessons });
    if (path === `/api/projects/${PROJECT}/lessons/sources`) return json({ program_node_id: TOPIC, ranges: [] });
    if (path === `/api/projects/${PROJECT}/materials` && method === "GET") return json([material]);
    if (path === `/api/projects/${PROJECT}/search`) {
      return json({
        terms: ["операция", "свёртка"],
        prefix: null,
        results: [{
          fragment_ids: ["f-4", "f-9"], material_id: MATERIAL, material_name: material.display_name, presentation_kind: "pdf",
          block_id: "b-1", block_title: "Свёртка", page_from: 4, page_to: 9, quality: "native",
          text: "Ядро скользит по изображению", highlights: [], matched_forms: [], already_bound: false,
          pages: [searchPage(4, "Ядро скользит по изображению"), searchPage(9, "Пулинг уменьшает карту признаков")],
        }],
      });
    }
    if (path === `/api/projects/${PROJECT}/lessons/from-search` && method === "POST") {
      created.push(request.postDataJSON());
      const lesson = {
        id: LESSON, project_id: PROJECT, title: topic.title, goal: null, status: "draft", duration_minutes: null,
        revision: 1, needs_review: false, last_block_id: null, completed_at: null, undo_sequence: 7,
        topics: [{ program_node_id: TOPIC, title_snapshot: topic.title, current_title: topic.title, needs_review: false }],
        blocks: [], created_at: NOW, updated_at: NOW,
      };
      lessons = [{
        id: LESSON, title: topic.title, status: "draft", duration_minutes: null, program_node_ids: [TOPIC],
        needs_review: false, completed_at: null, updated_at: NOW,
      }];
      return json({ lesson, latest_undoable_action: null, unbind_offer: null }, 201);
    }
    if (path === `/api/projects/${PROJECT}/lessons/${LESSON}`) {
      return json({
        id: LESSON, project_id: PROJECT, title: topic.title, goal: null, status: "draft", duration_minutes: null,
        revision: 1, needs_review: false, last_block_id: null, completed_at: null, undo_sequence: 7,
        topics: [{ program_node_id: TOPIC, title_snapshot: topic.title, current_title: topic.title, needs_review: false }],
        blocks: [], created_at: NOW, updated_at: NOW,
      });
    }
    if (path.endsWith(`/topics/${TOPIC}/evidence`)) {
      return json({ coverage_revision: 0, topic_id: TOPIC, topic_title: topic.title, best_evidence_id: null, starter: [], explanations: [], practice: [], depth: [], mentions: [], hidden: [], legacy: [] });
    }
    if (path === "/api/settings/ai") return json({ external_models_enabled: false, providers: [], roles: [], models: [] });
    return json([]);
  });
  return { created };
}

test("тема без оглавления: отмеченные в поиске страницы становятся уроком одной командой", async ({ page }) => {
  const state = await installStub(page);
  await page.goto(`${BASE}/projects/${PROJECT}/lessons?topic=${TOPIC}`);
  await expect(page.getByRole("heading", { name: "У темы пока нет материала из оглавления" })).toBeVisible();
  await page.getByRole("button", { name: "Найти в материалах проекта" }).click();
  await expect(page.getByText("Отметьте подходящие страницы — из них соберётся урок темы.")).toBeVisible();

  const results = page.locator(".lessons-search-results li");
  await expect(results).toHaveCount(2);
  await results.nth(1).getByText("Отметить").click();
  await results.nth(0).getByText("Отметить").click();
  await expect(page.getByText("Отмечено страниц: 2")).toBeVisible();
  await page.getByRole("button", { name: "Создать урок из отмеченного" }).click();

  await expect(page).toHaveURL(new RegExp(`lesson=${LESSON}`));
  expect(state.created).toEqual([{
    program_node_id: TOPIC,
    pages: [{ material_id: MATERIAL, page: 9 }, { material_id: MATERIAL, page: 4 }],
  }]);
});

test("ссылка «Искать в материалах проекта» сразу открывает поиск панели", async ({ page }) => {
  await installStub(page);
  await page.goto(`${BASE}/projects/${PROJECT}/lessons?topic=${TOPIC}&panel=search`);
  await expect(page.getByRole("searchbox", { name: "Поиск по материалам" })).toHaveValue("Операция свёртки");
  await expect(page.locator(".lessons-search-results li")).toHaveCount(2);
});
