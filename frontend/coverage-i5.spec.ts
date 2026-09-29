/**
 * Сквозные действия И5 на подставленном API: серверные инварианты отдельно
 * проверяет pytest, здесь остаются навигация, точный ручной выбор и доступность.
 */
import { expect, test, type Page } from "@playwright/test";

const BASE = process.env.TENTEX_TEST_URL ?? "http://localhost:5173";
const PROJECT = "11111111-1111-4111-8111-111111111111";
const TOPIC = "22222222-2222-4222-8222-222222222222";
const MATERIAL = "33333333-3333-4333-8333-333333333333";
const BLOCK = "44444444-4444-4444-8444-444444444444";
const FRAGMENT_A = "55555555-5555-4555-8555-555555555555";
const FRAGMENT_B = "66666666-6666-4666-8666-666666666666";
const EVIDENCE_A = "first-explanation";
const EVIDENCE_B = "second-explanation";

const node = {
  id: TOPIC, project_id: PROJECT, parent_id: null, node_type: "topic", exam_kind: null,
  sort_order: 0, title: "Планирование процессов", section_purpose: null,
  goal_role: "required", target_level: "understand", is_in_current_program: true,
  needs_material: true, is_archived: false, origin_kind: "manual", basis_kind: "custom",
  origin_note: null, origin_material_id: null, source_page_ranges: [],
  created_at: "2026-09-19T00:00:00Z", updated_at: "2026-09-19T00:00:00Z",
};

const projectDetail = {
  project: {
    id: PROJECT, name: "Операционные системы", template_key: "textbook",
    workspace_variant: "textbook", status: "active", color: "1",
    enabled_modules: ["materials", "program", "lessons"], program_revision: 7,
    exam_date: null, deadline: null, created_at: "2026-09-19T00:00:00Z",
    updated_at: "2026-09-19T00:00:00Z",
  },
  goal_passport: null,
  program: { revision: 7, nodes: [node] },
  workspace_state: null,
  latest_undoable_action: null,
};

const distribution = {
  linked: 2, outside_program: 1, service: 0, mixed_resolved: 0,
  unresolved: 0, pending: 0, processing: 0, error: 0, stale: 0,
};

const overview = {
  coverage_revision: 4, program_revision: 7, source_revisions: { [MATERIAL]: 1 },
  partial: false, total: 3, distribution,
  topics: { total: 1, with_content: 1, reading_basis: 1, legacy: 0 },
  content_titles: [node.title], reading_titles: [node.title],
  material_ratio: { numerator: 2, denominator: 3, value: 2 / 3, label: "Среди разобранных", mixed: 0 },
  findings: 0, latest_run_id: null, latest_run_state: null,
  sources: [{
    id: MATERIAL, name: "Таненбаум.pdf", revision: 1, total: 3, distribution,
    diagnostics: {}, known_limits: [], in_latest_run: true,
    researched_at: "2026-09-19T00:00:00Z", run_state: null,
  }],
};

function summary(id: string, binding: string, fragment: string, quote: string, page: number) {
  return {
    id, binding_id: binding, binding_ids: [binding], member_ids: [id], topic_id: TOPIC,
    material_id: MATERIAL, material_name: "Таненбаум.pdf", title: null, page_from: page, page_to: page,
    from_fragment_id: fragment, to_fragment_id: fragment, fragment_ids: [fragment], fragment_count: 1,
    quote, description: "",
    roles: ["explanation"], semantic_kind: "content", status: "machine",
    mechanism: "coverage", quality: "native", available: true, stale: false,
    hidden: false, preferred: id === EVIDENCE_A, legacy: false,
  };
}

const first = summary(EVIDENCE_A, "77777777-7777-4777-8777-777777777777", FRAGMENT_A, "Сначала выбирается готовый процесс.", 42);
const second = summary(EVIDENCE_B, "88888888-8888-4888-8888-888888888888", FRAGMENT_B, "Второе объяснение показывает очередь планировщика.", 43);
const groups = {
  coverage_revision: 4, topic_id: TOPIC, topic_title: node.title,
  best_evidence_id: EVIDENCE_A, starter: [first], explanations: [second],
  practice: [], depth: [], mentions: [], hidden: [], legacy: [],
};

const detail = (item: ReturnType<typeof summary>) => ({
  ...item, key: item.id, ref: item.fragment_ids[0], repair: "exact", start: 0,
  end: item.quote.length, original_ref: null, origin: "coverage", applied: true,
  locator: {}, topic_title: node.title, text: item.quote,
  linked_topics: [{ topic_id: TOPIC, title: node.title }],
});

const lesson = {
  id: "99999999-9999-4999-8999-999999999999", project_id: PROJECT,
  title: "Планирование процессов", goal: null, status: "draft", duration_minutes: null,
  revision: 1, needs_review: false, last_block_id: null, completed_at: null,
  undo_sequence: 12, topics: [{ program_node_id: TOPIC, title_snapshot: node.title, current_title: node.title, needs_review: false }],
  blocks: [], created_at: "2026-09-19T00:00:00Z", updated_at: "2026-09-19T00:00:00Z",
};

const materialPage = (page: number, fragmentId: string, text: string) => ({
  id: `page-${page}`, page_number: page, width: 1000, height: 1400,
  text, markdown: text, quality: "native", confidence: null, parser_mode: "fast",
  reviewed_at: null, diagnostics: [], blocks: [],
  fragments: [{
    id: fragmentId, block_id: BLOCK, sort_order: 0, text, bbox: [0, 0, 1, 1],
    element_kind: "paragraph", has_asset: false, structure_level: null,
    degraded_structure: false, quality: "native", recognition_source: "native",
    confidence: null, time_from: null, time_to: null,
  }],
});

interface StubState {
  searchCalls: number;
  inserted: Record<string, unknown> | null;
  decision: Record<string, unknown> | null;
  undoCalls: number;
  resolvedOutside: boolean;
}

async function stub(page: Page): Promise<StubState> {
  const state: StubState = { searchCalls: 0, inserted: null, decision: null, undoCalls: 0, resolvedOutside: false };
  await page.route((url) => url.pathname.startsWith("/api/"), async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    let json: unknown = [];

    if (path.endsWith("/coverage/overview")) json = overview;
    else if (path.endsWith("/coverage/issues")) json = { coverage_revision: 4, items: [], total: 0, next_offset: null, distribution: {} };
    else if (path.endsWith("/coverage/topics")) json = { coverage_revision: 4, items: [{ node_id: TOPIC, title: node.title, parent_title: null, evidence_count: 2, mention_count: 0, hidden_count: 0, legacy_count: 0, best_evidence_id: EVIDENCE_A }], total: 1, next_offset: null };
    else if (path.endsWith(`/coverage/topics/${TOPIC}/evidence`)) json = groups;
    else if (path.endsWith(`/coverage/evidence/${EVIDENCE_A}`)) json = detail(first);
    else if (path.endsWith(`/coverage/evidence/${EVIDENCE_B}`)) json = detail(second);
    else if (path.endsWith("/coverage/blocks") && url.searchParams.get("view") === "needs_action") json = {
      coverage_revision: 4, items: [], total: 0, next_offset: null, distribution: {},
    };
    else if (path.endsWith("/coverage/blocks")) json = {
      coverage_revision: 4,
      items: state.resolvedOutside ? [] : [{ block_id: BLOCK, material_id: MATERIAL, revision: 1, bucket: "outside_program", has_content: false, result_id: null, title: "Предметный указатель", page_from: 80, page_to: 80, material_name: "Таненбаум.pdf", reason: null }],
      total: state.resolvedOutside ? 0 : 1, next_offset: null, distribution: state.resolvedOutside ? {} : { outside_program: 1 },
    };
    else if (path.endsWith("/coverage/decisions")) {
      state.decision = JSON.parse(request.postData() ?? "{}");
      state.resolvedOutside = true;
      json = { request_key: "request", action: state.decision?.action, coverage_revision: 5, action_sequence: 15, binding_ids: [], message: "Блок отмечен как служебный." };
    } else if (path.endsWith("/actions/undo")) {
      state.undoCalls += 1;
      state.resolvedOutside = false;
      json = { undone_action_type: "coverage_decision", program: null, draft_revision: null, latest_undoable_action: null };
    } else if (path.endsWith("/search")) {
      state.searchCalls += 1;
      json = { terms: ["планирование"], prefix: null, results: [] };
    } else if (path.endsWith("/lessons/overview")) json = { lessons: [] };
    else if (path.endsWith("/lessons/manual")) json = { lesson, latest_undoable_action: null, unbind_offer: null };
    else if (path.endsWith(`/lessons/${lesson.id}/blocks`)) {
      state.inserted = JSON.parse(request.postData() ?? "{}");
      json = { lesson: { ...lesson, revision: 2 }, latest_undoable_action: null, unbind_offer: null };
    } else if (path.includes(`/materials/${MATERIAL}/pages/42`)) json = materialPage(42, FRAGMENT_A, first.quote);
    else if (path.includes(`/materials/${MATERIAL}/pages/43`)) json = materialPage(43, FRAGMENT_B, second.quote);
    else if (path.endsWith("/bindings/summary") || path.endsWith("/bindings")) json = [];
    else if (path.endsWith("/workspace-state")) json = { project_id: PROJECT, schema_version: 1, layout: JSON.parse(request.postData() ?? "{}").layout, updated_at: "2026-09-19T00:00:00Z" };
    else if (path.endsWith(`/projects/${PROJECT}`)) json = projectDetail;

    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(json) });
  });
  return state;
}

test("чтение сохраняет контекст, поиск остаётся ручным, кусок попадает в урок", async ({ page }) => {
  const state = await stub(page);
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto(`${BASE}/projects/${PROJECT}/coverage?view=reading`);

  await expect(page.getByRole("tab", { name: "К чтению" })).toHaveAttribute("aria-selected", "true");
  await page.getByRole("button", { name: /Второе объяснение/ }).click();
  await expect(page).toHaveURL(new RegExp(`evidence=${EVIDENCE_B}`));
  await page.getByRole("link", { name: "Читать в Рабочей области" }).click();

  await expect(page.getByRole("heading", { name: node.title, level: 1 })).toBeVisible();
  await expect(page.getByText(second.quote).first()).toBeVisible();
  expect(state.searchCalls).toBe(0);
  await page.getByRole("button", { name: "Найти ещё" }).click();
  await page.getByRole("button", { name: "Найти", exact: true }).click();
  await expect.poll(() => state.searchCalls).toBe(1);
  await page.getByRole("tab", { name: "Вместе" }).click();
  await page.getByRole("button", { name: "Добавить в урок" }).click();

  const dialog = page.getByRole("dialog", { name: "Добавить кусок в урок" });
  await expect(dialog).toContainText("Новый ручной черновик");
  await dialog.getByRole("button", { name: "Добавить в урок" }).click();
  await expect.poll(() => state.inserted).not.toBeNull();
  expect(state.inserted).toMatchObject({
    operation: "add_fragments", from_fragment_id: FRAGMENT_B,
    to_fragment_id: FRAGMENT_B, program_node_id: TOPIC,
  });
  await expect(page.getByRole("status")).toContainText("Кусок добавлен в урок");

  await page.screenshot({ path: "output/coverage-i5-workspace-light-1440.png", fullPage: true });

  await page.getByRole("link", { name: "Вернуться в Покрытие" }).click();
  await expect(page).toHaveURL(new RegExp(`view=reading.*evidence=${EVIDENCE_B}`));
  await expect(page.getByRole("button", { name: /Второе объяснение/ })).toHaveAttribute("aria-pressed", "true");
});

test("нераспределённый блок получает решение и undo, а И7 не притворяется готовым", async ({ page }) => {
  const state = await stub(page);
  await page.setViewportSize({ width: 1120, height: 820 });
  await page.addInitScript(() => localStorage.setItem("tentex:theme", "dark"));
  await page.goto(`${BASE}/projects/${PROJECT}/coverage?view=outside`);

  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  const disabled = page.getByRole("button", { name: "Создать новую тему" });
  await expect(disabled).toBeDisabled();
  await page.getByRole("button", { name: "Служебный блок" }).click();
  await expect.poll(() => state.decision?.action).toBe("service");
  await page.getByRole("button", { name: "Отменить" }).click();
  await expect.poll(() => state.undoCalls).toBe(1);
  await expect(page.getByText("Предметный указатель").first()).toBeVisible();

  const readingTab = page.getByRole("tab", { name: "К чтению" });
  await readingTab.focus();
  await readingTab.press("End");
  await expect(page.getByRole("tab", { name: "Требует решения" })).toHaveAttribute("aria-selected", "true");
  await page.screenshot({ path: "output/coverage-i5-dark-1120.png", fullPage: true });
});
