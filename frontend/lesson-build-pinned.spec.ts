/**
 * «Собрать с ИИ» из выбранных кусков на подставленном API: серверный отбор и ошибки диапазона
 * проверяет pytest, здесь — что диалог получает куски в порядке книги, даёт снять любой и
 * отправляет их в заказ, а из Рабочей области уводит к задаче в «Уроках».
 */
import { expect, test, type Page } from "@playwright/test";

const BASE = process.env.TENTEX_TEST_URL ?? "http://localhost:5173";
const PROJECT = "11111111-1111-4111-8111-111111111111";
const TOPIC = "22222222-2222-4222-8222-222222222222";
const MATERIAL = "33333333-3333-4333-8333-333333333333";
const BLOCK = "44444444-4444-4444-8444-444444444444";
const PROVIDER = "55555555-5555-4555-8555-555555555555";
const LESSON = "66666666-6666-4666-8666-666666666666";
const JOB = "77777777-7777-4777-8777-777777777777";
const NOW = "2026-09-29T10:00:00Z";
const DEFINITION = ["a1000000-0000-4000-8000-000000000001", "a1000000-0000-4000-8000-000000000002"];
const ALGORITHM = ["b2000000-0000-4000-8000-000000000001", "b2000000-0000-4000-8000-000000000002"];

const node = {
  id: TOPIC, project_id: PROJECT, parent_id: null, node_type: "topic", exam_kind: null,
  sort_order: 0, title: "СКНФ и СДНФ", section_purpose: null, goal_role: "target",
  target_level: "understanding", is_in_current_program: true, needs_material: true,
  is_archived: false, origin_kind: "manual", basis_kind: "custom", origin_note: null,
  origin_material_id: null, material_search_queries: [], material_kind: null,
  source_page_ranges: [], created_at: NOW, updated_at: NOW,
};

function passage(id: string, range: string[], title: string, pages: [number, number], quote: string) {
  return {
    id, binding_id: `bind-${id}`, binding_ids: [`bind-${id}`], member_ids: [id], topic_id: TOPIC,
    material_id: MATERIAL, material_name: "Афанасьев.pdf", title, page_from: pages[0], page_to: pages[1],
    from_fragment_id: range[0], to_fragment_id: range[1], fragment_ids: range, fragment_count: 2,
    quote, description: "", roles: ["explanation"], semantic_kind: "content", status: "machine",
    mechanism: "pass_two", quality: "native", available: true, stale: false, hidden: false,
    preferred: false, legacy: false,
  };
}

// Куски лежат в списке не по порядку книги: алгоритм (стр. 27–29) стоит в «С чего начать»,
// а определение (стр. 26–27) — ниже, среди «Объяснений».
const algorithm = passage("algorithm", ALGORITHM, "1.14. Способы построения", [27, 29], "Строим СДНФ по таблице истинности.");
const definition = passage("definition", DEFINITION, "1.13. Совершенные формы", [26, 27], "СДНФ — единственная форма для функции.");
const groups = {
  coverage_revision: 4, topic_id: TOPIC, topic_title: node.title, best_evidence_id: algorithm.id,
  starter: [algorithm], explanations: [definition], practice: [], depth: [], mentions: [],
  hidden: [], legacy: [],
};

const detail = (item: ReturnType<typeof passage>) => ({
  ...item, key: item.id, ref: item.fragment_ids[0], repair: "exact", start: 0, end: item.quote.length,
  original_ref: null, origin: "coverage", applied: true, locator: {}, topic_title: node.title,
  text: item.quote, linked_topics: [{ topic_id: TOPIC, title: node.title }],
});

const materialPage = (number: number) => ({
  id: `page-${number}`, page_number: number, width: 1000, height: 1400, text: "Текст", markdown: "Текст",
  quality: "native", confidence: null, parser_mode: "fast", reviewed_at: null, diagnostics: [], blocks: [],
  fragments: [{
    id: `frag-${number}`, block_id: BLOCK, sort_order: 0, text: "Текст", bbox: [0, 0, 1, 1],
    element_kind: "paragraph", has_asset: false, structure_level: null, degraded_structure: false,
    quality: "native", recognition_source: "native", confidence: null, time_from: null, time_to: null,
  }],
});

const levels = (["draft", "standard", "detailed"] as const).map((level, index) => ({
  level, calls: index + 1, input_tokens: 800, output_tokens: 400, cost_usd: "0.002", available: true,
  unavailable_reason: null,
}));

const preflight = {
  program_node_id: TOPIC, topic_title: node.title,
  materials: [{
    material_id: MATERIAL, name: "Афанасьев.pdf", role: "main", priority: 0, instruction: null,
    kind: "pdf", is_parsed: true, page_from: null, page_to: null, selected: true,
  }],
  candidates: 2, candidate_tokens: 300, material_state: "куски выбраны человеком: 2", notes: [],
  sources_available: true, default_minutes: null, conspect_words: 0, use_conspect: false,
  models_available: true, models_unavailable_reason: null, provider_id: PROVIDER,
  model_id: "test/model", model_label: "Test model", price_known: true, prices_from: null,
  levels, brief_text: "Паспорт урока",
};

const lessonDetail = {
  id: LESSON, project_id: PROJECT, title: node.title, goal: null, status: "draft", duration_minutes: null,
  revision: 1, needs_review: false, last_block_id: null, completed_at: null, undo_sequence: 3,
  topics: [{ program_node_id: TOPIC, title_snapshot: node.title, current_title: node.title, needs_review: false }],
  blocks: [], created_at: NOW, updated_at: NOW,
};

interface StubState {
  preflights: Array<Record<string, unknown>>;
  build: Record<string, unknown> | null;
}

async function stub(page: Page): Promise<StubState> {
  const state: StubState = { preflights: [], build: null };
  await page.route((url) => url.pathname.startsWith("/api/"), async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    const method = request.method();
    const json = (value: unknown, status = 200) =>
      route.fulfill({ status, contentType: "application/json", body: JSON.stringify(value) });

    if (path === `/api/projects/${PROJECT}` && method === "GET") {
      return json({
        project: {
          id: PROJECT, name: "Математическая логика", template_key: "textbook",
          workspace_variant: "textbook", status: "active", color: 1,
          enabled_modules: ["materials", "program", "lessons"], program_revision: 7,
          exam_date: null, deadline: null, created_at: NOW, updated_at: NOW,
        },
        goal_passport: null, program: { revision: 7, nodes: [node] }, workspace_state: null,
        latest_undoable_action: null,
      });
    }
    if (path === "/api/settings/ai") {
      return json({
        external_models_enabled: true, providers: [{
          id: PROVIDER, label: "Test", catalog_profile: "openai_compatible", base_url: "https://example.test",
          has_api_key: true, is_favorite: false, model_count: 1, last_test_status: null,
          last_tested_at: null, last_catalog_refresh_at: null, updated_at: NOW,
        }],
        roles: [{
          role: "lesson_builder", title: "Сборка урока", description: "", modality: "text", enabled: true,
          provider_override_id: null, model_override: null, resolved_provider_id: PROVIDER,
          resolved_model: "test/model", model_source: "default", required_capabilities: [], parameters: {},
        }],
        models: [],
      });
    }
    if (path.endsWith(`/coverage/topics/${TOPIC}/evidence`)) return json(groups);
    if (path.endsWith("/coverage/evidence/algorithm")) return json(detail(algorithm));
    if (path.endsWith("/coverage/evidence/definition")) return json(detail(definition));
    if (path.includes(`/materials/${MATERIAL}/pages/`)) {
      return json(materialPage(Number(path.split("/").pop())));
    }
    if (path.endsWith("/lessons/overview")) {
      return json({ lessons: [{
        id: LESSON, title: node.title, status: "draft", duration_minutes: null,
        program_node_ids: [TOPIC], needs_review: false, completed_at: null, updated_at: NOW,
      }] });
    }
    if (path === `/api/projects/${PROJECT}/lessons/${LESSON}`) return json(lessonDetail);
    if (path.endsWith("/lessons/sources")) return json({ program_node_id: TOPIC, ranges: [] });
    if (path === `/api/projects/${PROJECT}/materials` && method === "GET") return json([]);
    if (path.endsWith("/lessons/ai/preflight")) {
      state.preflights.push(request.postDataJSON());
      return json(preflight);
    }
    if (path.endsWith("/lessons/ai/build")) {
      state.build = request.postDataJSON();
      return json({ job_id: JOB }, 202);
    }
    return json([]);
  });
  return state;
}

const range = (fragments: string[]) => ({
  material_id: MATERIAL, from_fragment_id: fragments[0], to_fragment_id: fragments[1],
});
const BOOK_ORDER = [range(DEFINITION), range(ALGORITHM)];

test("из Источника: куски идут в заказ в порядке книги, любой можно снять, задача открывается в «Уроках»", async ({ page }) => {
  const state = await stub(page);
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto(`${BASE}/projects/${PROJECT}?topic=${TOPIC}&tab=source`);

  // Отмечены в обратном порядке: первым — кусок из «С чего начать» (стр. 27–29).
  await page.getByLabel("Выбрать «1.14. Способы построения»").check();
  await page.getByLabel("Выбрать «1.13. Совершенные формы»").check();
  await page.getByRole("button", { name: "Собрать с ИИ" }).click();

  const dialog = page.getByRole("dialog", { name: "Собрать урок с ИИ" });
  await expect(dialog).toContainText("Выбранные куски · 2");
  await expect.poll(() => state.preflights.at(-1)?.pinned).toEqual(BOOK_ORDER);
  await page.screenshot({ path: "output/lesson-build-pinned-light-1440.png" });

  await dialog.getByRole("button", { name: "Снять кусок «1.14. Способы построения»" }).click();
  await expect(dialog).toContainText("Выбранные куски · 1");
  await expect.poll(() => state.preflights.at(-1)?.pinned).toEqual([BOOK_ORDER[0]]);
  await dialog.getByRole("button", { name: "Отмена" }).click();

  // Диалог открывается заново со всем выбором: снятые куски не «застревают».
  await page.getByRole("button", { name: "Собрать с ИИ" }).click();
  await expect(dialog).toContainText("Выбранные куски · 2");
  await expect.poll(() => state.preflights.at(-1)?.pinned).toEqual(BOOK_ORDER);
  await dialog.getByRole("button", { name: "Собрать урок" }).click();

  await expect.poll(() => state.build?.pinned).toEqual(BOOK_ORDER);
  expect(state.build).toMatchObject({ program_node_id: TOPIC, level: "draft" });
  await expect(page).toHaveURL(new RegExp(`/projects/${PROJECT}/lessons`));
  await expect(page.getByRole("dialog", { name: "Собрать урок с ИИ" })).toContainText("Урок собирается фоном");
});

test("из «Предложено» в Уроках: тот же заказ, диалог остаётся на своей задаче", async ({ page }) => {
  const state = await stub(page);
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto(`${BASE}/projects/${PROJECT}/lessons?topic=${TOPIC}&lesson=${LESSON}`);

  const panel = page.locator(".lessons-panel");
  await panel.getByLabel("Выбрать «1.14. Способы построения»").check();
  await panel.getByLabel("Выбрать «1.13. Совершенные формы»").check();
  await panel.getByRole("button", { name: "Собрать с ИИ" }).click();

  const dialog = page.getByRole("dialog", { name: "Собрать урок с ИИ" });
  await expect(dialog).toContainText("Выбранные куски · 2");
  await expect.poll(() => state.preflights.at(-1)?.pinned).toEqual(BOOK_ORDER);
  await dialog.getByRole("button", { name: "Собрать урок" }).click();

  await expect.poll(() => state.build?.pinned).toEqual(BOOK_ORDER);
  await expect(page).toHaveURL(new RegExp(`/projects/${PROJECT}/lessons`));
  await expect(dialog).toContainText("Урок собирается фоном");
});

test("без внешних моделей кнопка «Собрать с ИИ» недоступна и говорит почему", async ({ page }) => {
  await stub(page);
  await page.route("**/api/settings/ai", (route) => route.fulfill({
    status: 200, contentType: "application/json",
    body: JSON.stringify({ external_models_enabled: false, providers: [], roles: [], models: [] }),
  }));
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto(`${BASE}/projects/${PROJECT}?topic=${TOPIC}&tab=source`);

  await page.getByLabel("Выбрать «1.13. Совершенные формы»").check();
  const build = page.getByRole("button", { name: "Собрать с ИИ" });
  await expect(build).toBeDisabled();
  await expect(build).toHaveAttribute("title", /Внешние модели выключены/);
});
