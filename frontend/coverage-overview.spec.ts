/**
 * Покрытие → Обзор на подставленном API: экран имеет много состояний, а поднимать
 * реальный проект с прогоном модели ради каждого из них дорого и не воспроизводимо.
 */
import { test, expect, type Page } from "@playwright/test";

const BASE = process.env.TENTEX_TEST_URL ?? "http://localhost:5173";
const PROJECT = "11111111-1111-4111-8111-111111111111";
const MATERIAL = "22222222-2222-4222-8222-222222222222";
const RUN = "33333333-3333-4333-8333-333333333333";

const projectDetail = {
  project: {
    id: PROJECT,
    name: "Операционные системы",
    template_key: "textbook",
    workspace_variant: "textbook",
    status: "active",
    color: "1",
    enabled_modules: ["materials", "program", "lessons"],
    program_revision: 7,
    exam_date: null,
    created_at: "2026-09-18T00:00:00Z",
    updated_at: "2026-09-18T00:00:00Z",
  },
  goal_passport: null,
  program: { revision: 7, nodes: [] },
  workspace_state: null,
  latest_undoable_action: null,
};

const distribution = (over: Record<string, number> = {}) => ({
  linked: 0,
  outside_program: 0,
  service: 0,
  mixed_resolved: 0,
  unresolved: 0,
  pending: 0,
  processing: 0,
  error: 0,
  stale: 0,
  ...over,
});

const filledOverview = {
  coverage_revision: 4,
  program_revision: 7,
  source_revisions: { [MATERIAL]: 1 },
  partial: true,
  total: 100,
  distribution: distribution({ linked: 58, mixed_resolved: 9, outside_program: 14, service: 12, unresolved: 3, pending: 4 }),
  topics: { total: 24, with_content: 17, reading_basis: 11, legacy: 0 },
  content_titles: ["Вытесняющая многозадачность", "Планирование процессов", "Страничная память"],
  reading_titles: ["Планирование процессов", "Страничная память"],
  material_ratio: { numerator: 67, denominator: 81, value: 67 / 81, label: "Среди разобранных", mixed: 9 },
  findings: 0,
  latest_run_id: RUN,
  latest_run_state: "running",
  sources: [{
    id: MATERIAL,
    name: "Операционные системы.docx",
    revision: 1,
    total: 100,
    distribution: distribution({ linked: 58, mixed_resolved: 9, outside_program: 14, service: 12, unresolved: 3, pending: 4 }),
    diagnostics: {},
    known_limits: ["docx_tables_not_enumerated", "bbox_reliability_not_preserved"],
    in_latest_run: true,
    researched_at: null,
    run_state: "running",
  }],
};

const emptyOverview = {
  ...filledOverview,
  partial: false,
  total: 0,
  distribution: distribution(),
  topics: { total: 0, with_content: 0, reading_basis: 0, legacy: 0 },
  content_titles: [],
  reading_titles: [],
  material_ratio: { numerator: 0, denominator: 0, value: null, label: "Среди разобранных", mixed: 0 },
  latest_run_id: null,
  latest_run_state: null,
  sources: [],
};

const run = {
  id: RUN,
  job_id: "44444444-4444-4444-8444-444444444444",
  state: "running",
  execution_generation: 1,
  stop_reason: null,
  snapshot: { sources: [], context_sources: [] },
  stale: false,
  primary: { total: 100, pending: 4, processing: 0, inspected: 96, error: 0 },
  outcomes: { linked: 58, outside_program: 14, service: 12, mixed_resolved: 9, unresolved: 3 },
  research: { discovered: 0, finished: 0 },
  pending_synthesis: 0,
  costs: { calls: 12, tokens: 84000, cost_usd: 0.31, uncertain_calls: 0 },
  limits: { max_calls: 81, max_total_tokens: 400000, max_cost_usd: 1 },
  pause_requested: false,
};

/** Запуск, остановленный не деньгами, а выведенным пределом токенов. */
const budgetStopped = {
  ...run,
  state: "paused",
  stop_reason: "budget_tokens",
  primary: { total: 100, pending: 4, processing: 0, inspected: 96, error: 0 },
};

const issues = {
  items: [{
    block_id: "55555555-5555-4555-8555-555555555555",
    material_id: MATERIAL,
    revision: 1,
    bucket: "unresolved",
    has_content: false,
    result_id: null,
    title: "Планировщик реального времени",
    page_from: 84,
    page_to: 85,
    material_name: "Операционные системы.docx",
    reason: "invalid_decision:evidence_not_found",
  }],
  total: 3,
  next_offset: null,
  distribution: { unresolved: 3 },
};

const materials = [{
  id: MATERIAL,
  original_name: "Операционные системы.docx",
  display_name: "Операционные системы",
  source_role: "reference",
  status: "ready",
  purposes: ["study_source"],
  page_count: 184,
  parser_mode: "fast",
  ocr_low_page_count: 0,
  outline: [],
  diagnostics: [],
}];

const preflight = {
  fingerprint: "snapshot-1",
  snapshot: { sources: [], context_sources: [] },
  blocks: 424,
  execution_available: true,
  execution_issue: null,
  model_roles: {
    overview: { provider_id: "p", model_id: "openai/gpt-обзор", model_source: "role_override", context_length: 128000, prompt_version: "verified-07" },
    research: { provider_id: "p", model_id: "openai/gpt-углубление", model_source: "role_override", context_length: 128000, prompt_version: "verified-07" },
  },
  limits: { max_cost_usd: null },
  packets_at_least: 27,
  prompt_overhead_tokens: 19000,
  packet_input_tokens: 16000,
};

/** Только серверные пути: glob по «api» поймал бы и модули Vite из `src/api`. */
const isApi = (url: URL) => url.pathname.startsWith("/api/");

async function stub(page: Page, overview: unknown, issuePage: unknown, runRow: unknown = run) {
  await page.route(isApi, (route) => {
    const url = route.request().url();
    const json = url.includes("/coverage/overview") ? overview
      : url.includes("/coverage/issues") ? issuePage
        : url.includes("/coverage/topics") ? { coverage_revision: 4, items: [], total: 0, next_offset: null }
          : url.includes("/coverage/blocks") ? { coverage_revision: 4, items: [], total: 0, next_offset: null, distribution: {} }
        : url.includes("/coverage/runs/") ? runRow
          : url.includes("/coverage/preflight") ? preflight
            : url.includes("/materials") ? materials
              : url.includes(`/projects/${PROJECT}`) ? projectDetail
                : [];
    return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(json) });
  });
}

test("обзор показывает распределение, обе метрики и проблемные блоки", async ({ page }) => {
  await stub(page, filledOverview, issues);
  await page.goto(`${BASE}/projects/${PROJECT}/coverage`);

  await expect(page.getByRole("heading", { name: "Обзор", level: 1 })).toBeVisible();
  await expect(page.getByText("96 из 100", { exact: true })).toBeVisible();
  await expect(page.getByLabel("Распределение всех блоков материала")).toBeVisible();
  // Знаменатель метрики — только разобранные: (58 + 9) / (58 + 9 + 14) = 83%.
  await expect(page.getByText("83%")).toBeVisible();
  await expect(page.getByText("67 из 81")).toBeVisible();
  await expect(page.getByText("17 из 24 тем")).toBeVisible();
  await expect(page.getByText("Таблицы DOCX")).toBeVisible();
  // Лента проблем короткая, но знаменатель честный.
  await expect(page.getByText("Планировщик реального времени")).toBeVisible();
  await expect(page.getByText("всего требуют внимания 3")).toBeVisible();
  // Темы названы: одно число «17 тем» не говорит, каких именно.
  await expect(page.getByText("Вытесняющая многозадачность · Планирование процессов · Страничная память")).toBeVisible();
  await expect(page.getByText("ждут уточнения — 3.")).toBeVisible();
  await page.screenshot({ path: "output/coverage-overview.png", fullPage: true });
});

test("пустой проект объясняет отсутствие текста и программы вместо нулевой полосы", async ({ page }) => {
  await stub(page, emptyOverview, { items: [], total: 0, next_offset: null, distribution: {} });
  await page.goto(`${BASE}/projects/${PROJECT}/coverage`);

  await expect(page.getByRole("heading", { name: "В проекте нет источников" })).toBeVisible();
  await expect(page.getByLabel("Распределение всех блоков материала")).toHaveCount(0);
  await expect(page.getByText("Программа пуста")).toBeVisible();
  await expect(page.getByText("Ошибок и нерешённых блоков нет.")).toBeVisible();
});

test("запуск открывается из Обзора и не создаёт задачу при отмене", async ({ page }) => {
  await stub(page, filledOverview, issues);
  let started = 0;
  await page.route((url) => url.pathname.endsWith("/coverage/runs"), (route) => {
    started += 1;
    return route.fulfill({ status: 202, contentType: "application/json", body: JSON.stringify(run) });
  });
  await page.goto(`${BASE}/projects/${PROJECT}/coverage`);

  await page.getByRole("button", { name: "Исследовать материалы" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  // Справочный источник остаётся в выборе, модели и предел расхода видны до оплаты.
  await expect(dialog.getByRole("checkbox", { name: "Операционные системы" })).toBeChecked();
  await expect(dialog.getByText("справочный")).toBeVisible();
  await expect(dialog.getByText("openai/gpt-обзор")).toBeVisible();
  await expect(dialog.getByRole("button", { name: /Начать обзор · 424 бл\./ })).toBeEnabled();
  await dialog.getByLabel("Предел расхода, $").fill("0");
  await expect(dialog.getByRole("button", { name: /Начать обзор/ })).toBeDisabled();
  await dialog.getByLabel("Предел расхода, $").fill("2.50");
  await expect(dialog.getByRole("button", { name: /Начать обзор/ })).toBeEnabled();
  await page.screenshot({ path: "output/coverage-launch-dialog.png" });
  await page.getByRole("button", { name: "Отменить" }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  expect(started).toBe(0);
});

test("остановка по пределу объясняется числами и продолжается новым потолком", async ({ page }) => {
  await stub(page, filledOverview, issues, budgetStopped);
  let sent: Record<string, unknown> | null = null;
  await page.route((url) => url.pathname.endsWith("/control"), (route) => {
    sent = JSON.parse(route.request().postData() ?? "{}");
    return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(run) });
  });
  await page.goto(`${BASE}/projects/${PROJECT}/coverage`);

  await expect(page.getByText("Достигнут предел по токенам запуска")).toBeVisible();
  await expect(page.getByText(/84\s000 из 400\s000 токенов/)).toBeVisible();
  await page.getByRole("button", { name: "Продолжить с новым пределом" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByText("12 из 81")).toBeVisible();
  await dialog.getByRole("button", { name: "Продолжить обзор" }).click();
  await expect.poll(() => sent?.limits).toBeTruthy();
  expect((sent?.limits as { max_total_tokens: number }).max_total_tokens).toBeGreaterThan(400000);
});
