/** Готовая ИИ-уборка должна переживать переход из фоновых задач и закрытие диалога. */
import { expect, test, type Page, type Route } from "@playwright/test";

const BASE = process.env.TENTEX_TEST_URL ?? "http://localhost:5173";
const MATERIAL = "22222222-2222-4222-8222-222222222222";
const JOB = "33333333-3333-4333-8333-333333333333";
const NOW = "2026-09-25T10:00:00Z";
const source = "Исходный текст страницы";
const suggestion = "Исправленный текст страницы";

const material = {
  id: MATERIAL, original_name: "source.pdf", display_name: "Учебник.pdf", subject: null,
  media_type: "application/pdf", source_kind: "file", source_url: null, size_bytes: 1234,
  page_count: 1, status: "ready", parser_mode: "fast", native_page_count: 1,
  ocr_page_count: 0, ocr_low_page_count: 0, block_count: 1, fragment_count: 1,
  has_outline: false, sha256: "hash", created_at: NOW, usage: [],
  presentation_kind: "pdf", capabilities: {
    can_compare: true, can_view_original: true, can_edit_text: true, can_run_ocr: true,
    can_refresh_source: false, has_outline: false, has_timeline: false,
  },
  outline: [], outline_source: "none", page_states: [{ page_number: 1, quality: "native", reviewed_at: null }],
  active_parse_revision: 1, scan_page_count: 0, estimated_seconds: null, diagnostics: [], error: null,
  task: null, retrieved_at: null, updated_at: NOW, storage_path: "source.pdf", raster_token: "raster", typst: null,
};
const materialPage = {
  id: "page-1", page_number: 1, width: 900, height: 1200, text: source, markdown: source,
  quality: "native", confidence: null, parser_mode: "fast", reviewed_at: null,
  diagnostics: [], fragments: [], blocks: [],
};
const job = {
  id: JOB, kind: "ai_cleanup", state: "completed", material_id: MATERIAL, project_id: null,
  subject: material.display_name, model_label: "test/model", page_number: 1, source_revision: 1,
  deadline_seconds: null, max_attempts: 2, progress_unit: "", needs_review: true,
  stage: null, parser_mode: null, done: 1, total: 1, diagnostics: [], error: null,
  pause_requested: false, control_action: null, created_at: NOW, updated_at: NOW,
  completed_at: NOW, reviewed_at: null,
};
const result = {
  run_id: "44444444-4444-4444-8444-444444444444", material_id: MATERIAL, page_id: materialPage.id,
  page_number: 1, revision: 1, source_hash: "source-hash",
  suggestion: { markdown: suggestion, changes: ["Исправлено оформление"], warnings: [] },
  usage: { input_tokens: 10, output_tokens: 8, actual_cost_usd: "0.001", actual_cost_rub: null },
  requested_model_id: "test/model", actual_model_id: "test/model", cached: false,
};

async function installStub(page: Page) {
  let resolved = 0;
  let applied = 0;
  await page.route((url) => url.pathname.startsWith("/api/"), (route: Route) => {
    const path = new URL(route.request().url()).pathname;
    const method = route.request().method();
    const json = (value: unknown) => route.fulfill({ contentType: "application/json", body: JSON.stringify(value) });
    if (path === `/api/materials/${MATERIAL}`) return json(material);
    if (path === `/api/materials/${MATERIAL}/revisions`) return json([]);
    if (path === `/api/materials/${MATERIAL}/pages/1` && method === "GET") return json(materialPage);
    if (path === "/api/materials/subjects") return json([]);
    if (path === "/api/settings/ocr") return json({ default_mode: "fast", engines: [], speech: [], cloud: null });
    if (path === `/api/background-jobs/${JOB}`) return json(job);
    if (path === `/api/background-jobs/${JOB}/result`) return json(result);
    if (path === `/api/background-jobs/${JOB}/resolve`) { resolved += 1; return json({ ...job, needs_review: false, reviewed_at: NOW }); }
    if (path === `/api/materials/${MATERIAL}/pages/1/ai-cleanup/apply`) { applied += 1; return json({ page: { ...materialPage, markdown: suggestion, text: suggestion }, transferred_bindings: 0, orphaned_binding_ids: [] }); }
    if (path === "/api/background-jobs") return json([job]);
    return json([]);
  });
  return { counts: () => ({ resolved, applied }) };
}

test("переход из фоновых задач открывает сравнение; закрытие сохраняет предложение", async ({ page }) => {
  const state = await installStub(page);
  await page.goto(`${BASE}/library/${MATERIAL}?job=${JOB}&page=1`);
  const dialog = page.getByRole("dialog", { name: "Прибрать текст страницы 1" });
  await expect(dialog.getByText("Предложение готово")).toBeVisible();
  await expect(dialog.getByRole("button", { name: "Применить" })).toBeEnabled();
  await expect(dialog.getByRole("button", { name: "Отказаться" })).toBeEnabled();
  await dialog.getByRole("button", { name: "Закрыть" }).click();
  await page.getByRole("button", { name: "Прибрать текст с ИИ" }).click();
  await expect(dialog.getByText("Предложение готово")).toBeVisible();
  await expect(dialog.getByRole("button", { name: "Применить" })).toBeEnabled();
  expect(state.counts()).toEqual({ resolved: 0, applied: 0 });
});

test("отказ от готового предложения снимает его с проверки", async ({ page }) => {
  const state = await installStub(page);
  await page.goto(`${BASE}/library/${MATERIAL}?job=${JOB}&page=1`);
  const dialog = page.getByRole("dialog", { name: "Прибрать текст страницы 1" });
  await dialog.getByRole("button", { name: "Отказаться" }).click();
  await expect(dialog).not.toBeVisible();
  expect(state.counts()).toEqual({ resolved: 1, applied: 0 });
});

test("применение готового предложения сохраняет текст и снимает задачу с проверки", async ({ page }) => {
  const state = await installStub(page);
  await page.goto(`${BASE}/library/${MATERIAL}?job=${JOB}&page=1`);
  const dialog = page.getByRole("dialog", { name: "Прибрать текст страницы 1" });
  await dialog.getByRole("button", { name: "Применить" }).click();
  await expect(dialog).not.toBeVisible();
  expect(state.counts()).toEqual({ resolved: 1, applied: 1 });
});
