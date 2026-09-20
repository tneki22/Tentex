/** Свободное изучение на подставленном API: мастер не зависит от состояния локальной Библиотеки. */
import { expect, test, type Page, type Route } from "@playwright/test";

const BASE = process.env.TENTEX_TEST_URL ?? "http://localhost:5173";
const PROJECT = "11111111-1111-4111-8111-111111111111";
const MATERIAL = "22222222-2222-4222-8222-222222222222";
const NOW = "2026-09-20T10:00:00Z";

interface StubOptions {
  library?: Array<Record<string, unknown>>;
  initialMaterials?: Array<Record<string, unknown>>;
  outline?: Array<{ level: number; title: string; page: number }>;
  attachedDisplayName?: string;
  /** Черновик виден на посадочной странице мастера: проверяем «Продолжить». */
  listDraft?: boolean;
}

function libraryMaterial(overrides: Record<string, unknown> = {}) {
  return {
    id: MATERIAL,
    original_name: "economics.pdf",
    display_name: "Экономика — глобальное имя",
    subject: "Экономика",
    media_type: "application/pdf",
    source_kind: "file",
    source_url: null,
    size_bytes: 1024,
    page_count: 120,
    status: "ready",
    parser_mode: "fast",
    native_page_count: 120,
    ocr_page_count: 0,
    ocr_low_page_count: 0,
    block_count: 24,
    fragment_count: 80,
    has_outline: true,
    sha256: "a".repeat(64),
    created_at: NOW,
    usage: [],
    ...overrides,
  };
}

function projectMaterial(overrides: Record<string, unknown> = {}) {
  return {
    id: MATERIAL,
    original_name: "economics.pdf",
    display_name: "Экономика — глобальное имя",
    library_display_name: "Экономика — глобальное имя",
    project_display_name: null,
    media_type: "application/pdf",
    source_kind: "file",
    presentation_kind: "pdf",
    source_url: null,
    retrieved_at: null,
    size_bytes: 1024,
    page_count: 120,
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
    outline: [{ level: 1, title: "Основы экономики", page: 5 }],
    diagnostics: [],
    error: null,
    task: null,
    attached_at: NOW,
    created_at: NOW,
    updated_at: NOW,
    ...overrides,
  };
}

function programNode(id: string, title: string, nodeType: "section" | "topic", parentId: string | null) {
  return {
    id,
    project_id: PROJECT,
    parent_id: parentId,
    node_type: nodeType,
    exam_kind: null,
    sort_order: 0,
    title,
    section_purpose: null,
    goal_role: "target",
    target_level: "understanding",
    is_in_current_program: true,
    needs_material: false,
    is_archived: false,
    origin_kind: "outline",
    basis_kind: "outline",
    origin_note: null,
    origin_material_id: MATERIAL,
    source_page_ranges: [{
      material_id: MATERIAL,
      source_name_snapshot: "Экономика — глобальное имя",
      outline_item_key: `${MATERIAL}:embedded:0:5:1`,
      page_from: 5,
      page_to: 5,
    }],
    created_at: NOW,
    updated_at: NOW,
  };
}

async function installStub(page: Page, options: StubOptions = {}) {
  const library = options.library ?? [];
  const materials = [...(options.initialMaterials ?? [])];
  const outline = options.outline ?? [{ level: 1, title: "Основы экономики", page: 5 }];
  let revision = 0;
  let programRevision = 0;
  let programNodes: Array<Record<string, unknown>> = [];
  let modelRequests = 0;
  let project = {
    id: PROJECT,
    template_key: "free",
    workspace_variant: "textbook",
    status: "draft",
    name: null,
    description: null,
    icon: null,
    color: null,
    sort_order: 0,
    deadline: null,
    enabled_modules: [],
    status_changed_at: null,
    created_at: NOW,
    updated_at: NOW,
  };
  let passport: Record<string, unknown> | null = null;
  let draft = {
    project_id: PROJECT,
    current_step: 1,
    max_completed_step: 1,
    revision,
    schema_version: 1,
    state: {},
    updated_at: NOW,
  };
  const wizardDetail = () => ({
    project,
    draft,
    goal_passport: passport,
    program: { revision: programRevision, nodes: programNodes },
    latest_undoable_action: null,
  });
  const activeDetail = () => ({
    project: { ...project, status: "active" },
    goal_passport: passport,
    program: { revision: programRevision, nodes: programNodes },
    workspace_state: null,
    latest_undoable_action: null,
  });

  await page.route((url) => url.pathname.startsWith("/api/"), async (route: Route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    const method = request.method();
    const json = (value: unknown, status = 200) => route.fulfill({
      status,
      contentType: "application/json",
      body: JSON.stringify(value),
    });

    if (path.includes("/program/chat") || path.includes("/program/ai-")) {
      modelRequests += 1;
      return json([]);
    }
    if (path === "/api/wizard-drafts" && method === "GET") {
      return json(options.listDraft ? [{
        project_id: PROJECT,
        template_key: project.template_key,
        workspace_variant: project.workspace_variant,
        name: project.name,
        current_step: draft.current_step,
        max_completed_step: draft.max_completed_step,
        revision: draft.revision,
        updated_at: NOW,
      }] : []);
    }
    if (path === "/api/wizard-drafts" && method === "POST") return json(wizardDetail(), 201);
    if (path === `/api/wizard-drafts/${PROJECT}` && method === "GET") return json(wizardDetail());
    if (path === `/api/wizard-drafts/${PROJECT}` && method === "PUT") {
      const body = request.postDataJSON();
      revision += 1;
      project = { ...project, ...body.project, updated_at: NOW };
      passport = body.goal_passport ? { project_id: PROJECT, ...body.goal_passport, updated_at: NOW } : null;
      draft = {
        ...draft,
        current_step: body.current_step,
        max_completed_step: body.max_completed_step,
        revision,
        state: body.state,
      };
      return json(wizardDetail());
    }
    if (path === `/api/wizard-drafts/${PROJECT}/activate` && method === "POST") {
      project = { ...project, status: "active", status_changed_at: NOW };
      return json(activeDetail());
    }
    if (path === `/api/projects/${PROJECT}` && method === "GET") return json(activeDetail());
    if (path === `/api/projects/${PROJECT}/materials` && method === "GET") return json(materials);
    if (path === "/api/materials" && method === "GET") return json(library);
    if (path === `/api/materials/${MATERIAL}/project-links` && method === "POST") {
      if (!materials.some((item) => item.id === MATERIAL)) {
        materials.push(projectMaterial({
          display_name: options.attachedDisplayName ?? library[0]?.display_name,
          library_display_name: library[0]?.display_name,
          project_display_name: options.attachedDisplayName ?? null,
          status: library[0]?.status,
          outline: library[0]?.has_outline === false ? [] : outline,
          active_parse_revision: library[0]?.status === "ready" ? 1 : 0,
          task: library[0]?.status === "processing" ? {
            id: "33333333-3333-4333-8333-333333333333",
            state: "running",
            stage: "extract",
            parser_mode: "fast",
            done: 1,
            total: 10,
            diagnostics: [],
            error: null,
            created_at: NOW,
            updated_at: NOW,
          } : null,
        }));
      }
      return json(library[0] ?? libraryMaterial(), 201);
    }
    if (path === `/api/projects/${PROJECT}/materials/${MATERIAL}` && method === "PATCH") {
      const body = request.postDataJSON();
      const index = materials.findIndex((item) => item.id === MATERIAL);
      if (index >= 0) materials[index] = { ...materials[index], ...body };
      return json(materials[index]);
    }
    if (path === `/api/projects/${PROJECT}/materials/${MATERIAL}/outline`) {
      return json({
        material_id: MATERIAL,
        source: outline.length ? "embedded" : "none",
        items: outline,
        source_pages: outline.length ? [5] : [],
        review_pages: outline.length ? [5] : [],
        review_needs_check: false,
        available_sources: ["embedded", "printed", "recognized"],
        found_sources: outline.length ? ["embedded"] : [],
      });
    }
    if (path.endsWith("/program/import-outlines") && method === "POST") {
      const body = request.postDataJSON();
      const selected = body.sources[0].items.filter((item: { selected: boolean }) => item.selected);
      const sectionId = "44444444-4444-4444-8444-444444444444";
      programNodes = selected.map((item: { title: string; level: number }, index: number) =>
        programNode(index === 0 ? sectionId : `55555555-5555-4555-8555-55555555555${index}`, item.title, item.level === 1 ? "section" : "topic", item.level === 1 ? null : sectionId));
      programRevision += 1;
      revision += 1;
      draft = { ...draft, revision };
      return json({ changed_node: null, program: { revision: programRevision, nodes: programNodes }, latest_undoable_action: null, draft_revision: revision });
    }
    const nodeMatch = path.match(new RegExp(`/api/projects/${PROJECT}/program-nodes/([^/]+)$`));
    if (nodeMatch && method === "PATCH") {
      const body = request.postDataJSON();
      programNodes = programNodes.map((node) => node.id === nodeMatch[1] ? { ...node, ...body, updated_at: NOW } : node);
      programRevision += 1;
      const changed = programNodes.find((node) => node.id === nodeMatch[1]) ?? null;
      return json({ changed_node: changed, program: { revision: programRevision, nodes: programNodes }, latest_undoable_action: null, draft_revision: revision });
    }
    if (path.includes("/pages/") && path.endsWith("/image")) {
      return route.fulfill({ status: 200, contentType: "image/png", body: "" });
    }
    if (path === "/api/background-jobs" || path === "/api/projects/stats") return json([]);
    return json([]);
  });

  return { modelRequests: () => modelRequests };
}

async function openFreeWizard(page: Page) {
  await page.goto(`${BASE}/projects/new?track=free`);
  await expect(page.getByRole("heading", { name: "Какая у вас цель?" })).toBeVisible();
}

async function enterGoal(page: Page, subject?: string) {
  await page.getByRole("textbox", { name: "Цель", exact: true }).fill("Разобраться в основах экономики");
  if (subject) await page.getByRole("combobox", { name: "Предмет или область" }).fill(subject);
  await page.getByRole("button", { name: "К материалам" }).click();
  await expect(page.getByRole("heading", { name: "Подберите материалы" })).toBeVisible();
}

test("цель без предмета и материалов создаёт проект и открывает общую Программу", async ({ page }) => {
  await installStub(page);
  await openFreeWizard(page);
  await enterGoal(page);
  await expect(page.getByText("В Библиотеке пока ничего нет.")).toBeVisible();
  await page.getByRole("button", { name: "К проверке" }).click();
  await expect(page.getByText("Пока без материалов — для свободного изучения это нормально.")).toBeVisible();
  await expect(page.getByText("Программа пока пуста.")).toBeVisible();
  await page.getByRole("button", { name: "Создать проект" }).click();
  await page.getByRole("button", { name: "Открыть программу" }).click();
  await expect(page).toHaveURL(new RegExp(`/projects/${PROJECT}/program$`));
  await expect(page.getByRole("heading", { name: "Программа" })).toBeVisible();
});

test("подходящее оглавление импортируется, правится и попадает в сводку", async ({ page }) => {
  await installStub(page, {
    library: [libraryMaterial()],
    outline: [
      { level: 1, title: "Основы экономики", page: 5 },
      { level: 2, title: "Спрос и предложение", page: 12 },
    ],
  });
  await openFreeWizard(page);
  await enterGoal(page, "Экономика");
  await expect(page.getByText("В Библиотеке есть материалы по предмету «Экономика». Выберите один как основу программы или продолжайте без него.")).toBeVisible();
  await page.getByRole("button", { name: "Из Библиотеки" }).click();
  await page.getByRole("button", { name: /Экономика — глобальное имя/ }).click();
  await expect(page.getByText("Совпадает предмет · есть оглавление · текст готов")).toBeVisible();
  await page.getByRole("button", { name: "Подключить", exact: true }).click();
  await expect(page.getByText("Оглавление найдено.")).toBeVisible();
  await page.getByRole("button", { name: "Импортировать оглавление", exact: true }).first().click();
  await page.getByRole("button", { name: "Импортировать 2 пункта" }).click();
  await page.getByRole("treeitem").filter({ hasText: "Основы экономики" }).dblclick();
  const title = page.getByLabel("Формулировка «Основы экономики»");
  await title.fill("Введение в экономику");
  await title.press("Enter");
  await page.getByRole("button", { name: "К проверке" }).click();
  await expect(page.getByText("Введение в экономику")).toBeVisible();
  await expect(page.getByText("Начальная программа собрана из оглавления «Экономика — глобальное имя».")).toBeVisible();
});

test("обрабатываемый материал без оглавления не блокирует мастер", async ({ page }) => {
  await installStub(page, {
    library: [libraryMaterial({ status: "processing", has_outline: false })],
    outline: [],
  });
  await openFreeWizard(page);
  await enterGoal(page, "Экономика");
  await page.getByRole("button", { name: "Из Библиотеки" }).click();
  await page.getByRole("button", { name: /Экономика — глобальное имя/ }).click();
  await page.getByRole("button", { name: "Подключить", exact: true }).click();
  await expect(page.getByText("Материал добавлен, но оглавление пока недоступно.")).toBeVisible();
  await page.getByRole("button", { name: "К проверке" }).click();
  await expect(page.getByRole("button", { name: "Создать проект" })).toBeEnabled();
});

test("вкладка С ИИ у свободного проекта показывает заглушку без модельного запроса", async ({ page }) => {
  const state = await installStub(page);
  await page.goto(`${BASE}/projects/${PROJECT}/program`);
  await page.getByRole("tab", { name: "С ИИ" }).click();
  await expect(page.getByRole("heading", { name: "Составление по цели появится здесь" })).toBeVisible();
  await expect.poll(state.modelRequests).toBe(0);
});

test("в Библиотеке видно глобальное имя, а в проекте — его псевдоним", async ({ page }) => {
  await installStub(page, {
    library: [libraryMaterial()],
    attachedDisplayName: "Экономика — имя в проекте",
  });
  await openFreeWizard(page);
  await enterGoal(page, "Экономика");
  await page.getByRole("button", { name: "Из Библиотеки" }).click();
  await expect(page.getByText("Экономика — глобальное имя", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: /Экономика — глобальное имя/ }).click();
  await page.getByRole("button", { name: "Подключить", exact: true }).click();
  await expect(page.getByText("Экономика — имя в проекте", { exact: true })).toBeVisible();
  await expect(page.getByText("economics.pdf", { exact: true })).toHaveCount(0);
});

test("шаг назад и сохранённый черновик возвращают введённое", async ({ page }) => {
  await installStub(page, { listDraft: true });
  await openFreeWizard(page);
  await enterGoal(page, "Экономика");
  await page.getByRole("button", { name: "Назад" }).click();
  await expect(page.getByRole("heading", { name: "Какая у вас цель?" })).toBeVisible();
  await expect(page.getByRole("textbox", { name: "Цель", exact: true })).toHaveValue("Разобраться в основах экономики");
  /* Имя подставляется из предмета, пока его не правили руками. */
  await expect(page.getByRole("textbox", { name: "Название проекта" })).toHaveValue("Экономика");

  await page.goto(`${BASE}/projects/new`);
  await page.getByRole("button", { name: "Продолжить" }).click();
  await expect(page.getByRole("textbox", { name: "Цель", exact: true })).toHaveValue("Разобраться в основах экономики");
  await expect(page.getByRole("combobox", { name: "Предмет или область" })).toHaveValue("Экономика");
});
