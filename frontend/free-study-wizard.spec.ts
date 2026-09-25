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
  /** Внешние модели включены — чат программы можно вызвать. */
  aiEnabled?: boolean;
  /** Активный свободный проект уже с программой — для раздела «Программа». */
  initialNodes?: Array<Record<string, unknown>>;
}

const PROVIDER = "66666666-6666-4666-8666-666666666666";
const SEARCH_SESSION = "55555555-5555-4555-8555-555555555555";
const TOPIC = "99999999-9999-4999-8999-999999999999";
const EXTERNAL_MATERIAL = "99999999-9999-4999-8999-999999999999";

function aiSettings(enabled: boolean) {
  return {
    external_models_enabled: enabled,
    daily_limit_usd: null,
    operation_limit_usd: null,
    confirm_cost_usd: null,
    confirm_input_tokens: 100000,
    usd_rub_rate: null,
    usd_rub_rate_date: null,
    default_text: { provider_id: PROVIDER, model_id: "test/model" },
    default_speech: null,
    chat_preset: null,
    providers: [{
      id: PROVIDER, label: "OpenRouter", catalog_profile: "openrouter", base_url: "https://openrouter.ai/api/v1",
      has_api_key: true, is_favorite: true, model_count: 1, last_test_status: null, last_tested_at: null,
      last_catalog_refresh_at: null, updated_at: NOW,
    }],
    roles: [{
      role: "study_program_assistant", title: "Составление программы", description: "", modality: "text",
      enabled: true, provider_override_id: null, model_override: null, resolved_provider_id: PROVIDER,
      resolved_model: "test/model", model_source: "default", required_capabilities: ["structured_output"], parameters: {},
    }, {
      role: "source_web_search", title: "Поиск материалов в интернете", description: "", modality: "text",
      enabled: true, provider_override_id: null, model_override: null, resolved_provider_id: PROVIDER,
      resolved_model: "test/model", model_source: "default", required_capabilities: ["structured_output"], parameters: {},
    }],
    models: [{
      provider_id: PROVIDER, model_id: "test/model", display_name: "Test model", context_length: 128000,
      max_completion_tokens: 8000, supported_parameters: ["response_format"], input_modalities: ["text"],
      output_modalities: ["text"], reasoning: {}, default_parameters: {}, manual_overrides: {},
      prompt_price_usd: "0.000001", completion_price_usd: "0.000002", knowledge_cutoff: null, expiration_date: null,
      pricing_snapshot_at: NOW, catalog_snapshot_at: NOW, is_manually_added: false, favorite_order: 1, is_available: true,
    }],
    today_usage: { input_tokens: 0, output_tokens: 0, actual_cost_usd: "0", actual_cost_rub: "0", cache_hits: 0 },
  };
}

const SEARCH_RESULT = {
  summary: "Нашлась лекция по рынку, каталог файлов и видео.",
  searches: [{ query: "рынок и цены лекция", category: "general", language: "ru", node_ids: [TOPIC], found: 8 }],
  items: [
    {
      url: "https://lectures.example/market", title: "Лекция: рынок и цены", host: "lectures.example", kind: "lecture",
      why: "Объясняет равновесие спроса и предложения", gist: "Кривые спроса и предложения, равновесная цена",
      level: "beginner", volume: { kind: "html", words: 1800, minutes: 10, pages: null, size_bytes: null, file_links: 0 },
      author: null, node_ids: [TOPIC],
    },
    {
      url: "https://files.example/micro", title: "Все лекции по микроэкономике", host: "files.example", kind: "catalog",
      why: "Лекции курса одним архивом", gist: "Страница со ссылками на PDF лекций", level: null,
      volume: { kind: "html", words: 90, minutes: 1, pages: null, size_bytes: null, file_links: 14 }, author: null, node_ids: [],
    },
    {
      url: "https://www.youtube.com/watch?v=abc", title: "Видеолекция о ценах", host: "youtube.com", kind: "video",
      why: "Разбор на графиках", gist: "Как меняется цена при сдвиге спроса", level: null,
      volume: { kind: "video", duration: "40:46" }, author: "Кафедра", node_ids: [TOPIC],
    },
  ],
  candidate_count: 12,
  hidden_attached: 1,
  hidden_seen: 0,
  unresponsive_engines: ["google"],
  follow_ups: ["Найди задачи по рынку и ценам"],
};

function searchMessage(sequence: number, role: "user" | "assistant", text: string, payload: Record<string, unknown> = {}) {
  return {
    id: `44444444-4444-4444-8444-44444444444${sequence}`,
    session_id: SEARCH_SESSION,
    sequence,
    role,
    text,
    stream_state: "complete",
    payload_kind: Object.keys(payload).length ? "tool_result" : "none",
    payload,
    context_snapshot: {},
    skill: null,
    ai_run_id: null,
    attempt_id: null,
    grade_attempt_id: null,
    created_at: NOW,
    updated_at: NOW,
  };
}

const CHAT_SESSION = "77777777-7777-4777-8777-777777777777";

function chatMessage(sequence: number, role: "user" | "assistant", text: string, payload: Record<string, unknown> = {}) {
  return {
    id: `88888888-8888-4888-8888-88888888888${sequence}`,
    session_id: CHAT_SESSION,
    sequence,
    role,
    text,
    stream_state: "complete",
    payload_kind: Object.keys(payload).length ? "program_diff" : "none",
    payload,
    context_snapshot: {},
    skill: null,
    ai_run_id: null,
    attempt_id: null,
    grade_attempt_id: null,
    created_at: NOW,
    updated_at: NOW,
  };
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
    material_search_queries: [],
    material_kind: null,
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
  let programNodes: Array<Record<string, unknown>> = [...(options.initialNodes ?? [])];
  let modelRequests = 0;
  let chatMessages: Array<Record<string, unknown>> = [];
  // Чат «Поиск в интернете» в Материалах.
  let searchCreated = false;
  let searchMessages: Array<Record<string, unknown>> = [];
  let searchFlags: Record<string, boolean> = {
    profile: true, program: true, topic_queries: true, attached_materials: true, only_missing: true, english_sources: false,
  };
  let searchScope: string | null = null;
  let searchDraft = "";
  const searchSent: string[] = [];
  const searchContextPatches: Array<Record<string, unknown>> = [];
  let chatCreated = false;
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

    if (path === "/api/settings/ai") return json(aiSettings(options.aiEnabled ?? false));
    if (path === `/api/projects/${PROJECT}/material-suggestions` && method === "POST") {
      const body = request.postDataJSON();
      const candidate = library[0];
      const suggestion = candidate && !materials.some((item) => item.id === candidate.id) ? {
        items: [{
          material_id: candidate.id,
          display_name: candidate.display_name,
          subject: candidate.subject ?? null,
          page_count: candidate.page_count ?? null,
          has_outline: candidate.has_outline ?? false,
          subject_match: true,
          hit_count: 3,
          signals: ["lexical", "semantic"],
          block_title: "Основы экономики",
          page_from: 5,
          page_to: 7,
          excerpt: "Экономика изучает, как общество распределяет ограниченные ресурсы.",
        }],
      } : { items: [] };
      if (body.query) return json({ by_query: { query: body.query, words_only: false, ...suggestion }, by_node: {} });
      return json({
        by_query: null,
        by_node: Object.fromEntries((body.node_ids as string[]).map((id) => [id, { query: id, words_only: true, ...suggestion }])),
      });
    }
    const chatBase = `/api/projects/${PROJECT}/program-chat`;
    const chatDetail = () => ({
      id: CHAT_SESSION, project_id: PROJECT, section_scope_node_id: null, title: "Программа",
      model_override: null, model_parameters: {},
      context_flags: { profile: true, primary_sources: true, secondary_sources: true, reference_sources: false },
      draft_text: "", created_at: NOW, updated_at: NOW, messages: chatMessages,
    });
    if (path === `${chatBase}/sessions` && method === "GET") {
      return json(chatCreated
        ? [{ id: CHAT_SESSION, project_id: PROJECT, title: "Программа", updated_at: NOW, message_count: chatMessages.length }]
        : []);
    }
    if (path === `${chatBase}/sessions` && method === "POST") {
      chatCreated = true;
      return json(chatDetail(), 201);
    }
    if (path === `${chatBase}/sessions/${CHAT_SESSION}` && method === "GET") return json(chatDetail());
    if (path === `${chatBase}/sessions/${CHAT_SESSION}/context`) {
      return json({ session_id: CHAT_SESSION, manifest: [], fingerprint: "f", total_bytes: 0 });
    }
    if (path === `${chatBase}/sessions/${CHAT_SESSION}/draft`) return json(chatDetail());
    if (path === `${chatBase}/sessions/${CHAT_SESSION}/messages` && method === "POST") {
      modelRequests += 1;
      const body = request.postDataJSON();
      chatMessages = [
        chatMessage(1, "user", body.text),
        chatMessage(2, "assistant", "Черновик программы от цели", {
          summary: "Черновик программы от цели",
          pros: [],
          cons: [],
          operations: [{
            op: "add", parent_node_id: null, after_node_id: null, at_start: false, node_type: "topic",
            title: "Операция свёртки", rationale: "Ядро цели", outline_ref: null, goal_role: "prerequisite",
            search_queries: ["операция свёртки", "свёрточный слой"], material_kind: "lecture", children: [],
          }],
          operation_states: ["pending"],
          rejected: false,
        }),
      ];
      return json(chatMessages[1]);
    }
    if (path.startsWith(`${chatBase}/proposals/`) && path.endsWith("/apply") && method === "POST") {
      programNodes = [{
        ...programNode("99999999-9999-4999-8999-999999999999", "Операция свёртки", "topic", null),
        goal_role: "prerequisite",
        needs_material: true,
        origin_kind: "model",
        basis_kind: "custom",
        origin_material_id: null,
        source_page_ranges: [],
        material_search_queries: ["операция свёртки", "свёрточный слой"],
        material_kind: "lecture",
      }];
      programRevision += 1;
      chatMessages = chatMessages.map((message) => message.payload_kind === "program_diff"
        ? { ...message, payload: { ...(message.payload as Record<string, unknown>), operation_states: ["applied"] } }
        : message);
      return json({
        changed_node: null,
        program: { revision: programRevision, nodes: programNodes },
        latest_undoable_action: null,
        draft_revision: null,
      });
    }
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
    if (path === `/api/projects/${PROJECT}/conspects`) return json({ entries: [] });
    const searchBase = `/api/projects/${PROJECT}/source-search-chat/sessions`;
    const searchDetail = () => ({
      id: SEARCH_SESSION, project_id: PROJECT, section_scope_node_id: searchScope, title: "Поиск",
      model_override: null, model_parameters: {}, context_flags: searchFlags,
      draft_text: searchDraft, created_at: NOW, updated_at: NOW, messages: searchMessages,
    });
    if (path === searchBase && method === "GET") {
      return json(searchCreated
        ? [{ id: SEARCH_SESSION, project_id: PROJECT, title: "Поиск", updated_at: NOW, message_count: searchMessages.length }]
        : []);
    }
    if (path === searchBase && method === "POST") {
      searchCreated = true;
      return json(searchDetail(), 201);
    }
    if (path === `${searchBase}/${SEARCH_SESSION}` && method === "GET") return json(searchDetail());
    if (path === `${searchBase}/${SEARCH_SESSION}/draft`) {
      searchDraft = request.postDataJSON().text;
      return json(searchDetail());
    }
    if (path === `${searchBase}/${SEARCH_SESSION}/context` && method === "GET") {
      const entry = (kind: string, flag: string, count: number | null) => ({
        kind, id: PROJECT, included: searchFlags[flag], truncated: false, bytes: 200, count,
        reason: searchFlags[flag] ? null : "excluded_by_user", flag_key: flag, label: null,
      });
      return json({ session_id: SEARCH_SESSION, fingerprint: "f", total_bytes: 800, manifest: [
        entry("profile", "profile", null),
        entry("program_tree", "program", 1),
        entry("topic_queries", "topic_queries", 1),
        entry("attached_materials", "attached_materials", 0),
      ] });
    }
    if (path === `${searchBase}/${SEARCH_SESSION}/context` && method === "PUT") {
      const body = request.postDataJSON();
      searchContextPatches.push(body);
      if (body.context_flags) searchFlags = { ...searchFlags, ...body.context_flags };
      if ("section_scope_node_id" in body) searchScope = body.section_scope_node_id;
      return json(searchDetail());
    }
    if (path === `${searchBase}/${SEARCH_SESSION}/messages/stream` && method === "POST") {
      const text = request.postDataJSON().text;
      searchSent.push(text);
      const sequence = searchMessages.length + 1;
      searchMessages = [
        ...searchMessages,
        searchMessage(sequence, "user", text),
        searchMessage(sequence + 1, "assistant", SEARCH_RESULT.summary, {
          tool_key: "search_external_sources", output_kind: "source_search_results", state: "succeeded",
          query: "", input: { searches: SEARCH_RESULT.searches }, result: SEARCH_RESULT,
        }),
      ];
      const frame = (event: string, data: unknown) => `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`;
      return route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        body: frame("progress", { stage: "planning" }) + frame("completed", { message: searchMessages.at(-1) }),
      });
    }
    if (path === `/api/projects/${PROJECT}/materials/external` && method === "POST") {
      const body = request.postDataJSON();
      const created = projectMaterial({
        id: EXTERNAL_MATERIAL, display_name: "Свёртка простыми словами", original_name: body.url,
        source_kind: body.kind, presentation_kind: "html", source_url: body.url, status: "processing",
        source_role: body.source_role, outline: [],
      });
      materials.push(created);
      return json(created, 201);
    }
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

  return {
    modelRequests: () => modelRequests,
    searchSent,
    searchContextPatches,
  };
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

test("пустой вход в мастер не создаёт черновик, ввод цели создаёт", async ({ page }) => {
  await installStub(page);
  let created = 0;
  page.on("request", (request) => {
    if (request.method() === "POST" && new URL(request.url()).pathname === "/api/wizard-drafts") created += 1;
  });
  await openFreeWizard(page);
  await page.goto(`${BASE}/projects/new`);
  expect(created).toBe(0);

  await openFreeWizard(page);
  await page.getByRole("textbox", { name: "Цель", exact: true }).fill("Изучить экономику");
  await expect.poll(() => created).toBe(1);
});

test("цель без предмета и материалов создаёт проект и открывает общую Программу", async ({ page }) => {
  await installStub(page);
  await openFreeWizard(page);
  await enterGoal(page);
  await expect(page.getByText("В Библиотеке пока ничего нет.")).toBeVisible();
  await page.getByRole("button", { name: "К программе" }).click();
  await expect(page.getByRole("heading", { name: "Соберите программу" })).toBeVisible();
  await page.getByRole("button", { name: "Продолжить без программы" }).click();
  await expect(page.getByText("Пока без материалов — для свободного изучения это нормально.")).toBeVisible();
  await expect(page.getByText("Программа пока пуста.")).toBeVisible();
  await page.getByRole("button", { name: "Создать проект" }).click();
  await page.getByRole("button", { name: "Открыть программу" }).click();
  await expect(page).toHaveURL(new RegExp(`/projects/${PROJECT}/program$`));
  await expect(page.getByRole("heading", { name: "Программа" })).toBeVisible();
});

test("подбор под цель подключает материал, его оглавление импортируется и попадает в сводку", async ({ page }) => {
  await installStub(page, {
    library: [libraryMaterial()],
    outline: [
      { level: 1, title: "Основы экономики", page: 5 },
      { level: 2, title: "Спрос и предложение", page: 12 },
    ],
  });
  await openFreeWizard(page);
  await enterGoal(page, "Экономика");
  const suggestions = page.getByRole("region", { name: "Подходит к вашей цели" });
  await expect(suggestions.getByText("Экономика — глобальное имя")).toBeVisible();
  await expect(suggestions.getByText("предмет совпадает")).toBeVisible();
  await expect(suggestions.getByText("ограниченные ресурсы")).toBeVisible();
  await suggestions.getByRole("button", { name: "Подключить" }).click();
  await expect(page.getByText("Основа программы")).toBeVisible();
  await expect(page.getByText("Оглавление найдено.")).toBeVisible();
  await page.getByRole("button", { name: "К программе" }).click();
  await page.getByRole("button", { name: "Импортировать оглавление", exact: true }).first().click();
  await page.getByRole("button", { name: "Импортировать 2 пункта" }).click();
  await page.getByRole("treeitem").filter({ hasText: "Основы экономики" }).dblclick();
  const title = page.getByLabel("Формулировка «Основы экономики»");
  await title.fill("Введение в экономику");
  await title.press("Enter");
  await page.getByRole("button", { name: "К проверке" }).click();
  await expect(page.getByText("Введение в экономику")).toBeVisible();
  await expect(page.getByText("По оглавлению — 1")).toBeVisible();
});

test("обрабатываемый материал без оглавления не блокирует мастер", async ({ page }) => {
  await installStub(page, {
    library: [libraryMaterial({ status: "processing", has_outline: false })],
    outline: [],
  });
  await openFreeWizard(page);
  await enterGoal(page, "Экономика");
  await page.getByRole("button", { name: "Вся Библиотека" }).click();
  await page.getByRole("button", { name: /Экономика — глобальное имя/ }).click();
  await page.getByRole("button", { name: "Подключить", exact: true }).click();
  await expect(page.getByText("Материал добавлен, но оглавление пока недоступно.")).toBeVisible();
  await page.getByRole("button", { name: "К программе" }).click();
  await page.getByRole("button", { name: "Продолжить без программы" }).click();
  await expect(page.getByRole("button", { name: "Создать проект" })).toBeEnabled();
});

test("вкладка С ИИ составляет программу по цели и подсказывает, где искать материал", async ({ page }) => {
  const state = await installStub(page, { aiEnabled: true });
  await page.goto(`${BASE}/projects/${PROJECT}/program`);
  await page.getByRole("tab", { name: "С ИИ" }).click();
  await expect(page.getByRole("heading", { name: "Составьте программу вместе с ИИ" })).toBeVisible();
  await page.getByRole("button", { name: "Составь программу по моей цели" }).click();
  await expect(page.getByText("необходимая основа")).toBeVisible();
  await expect(page.getByText("знания модели")).toBeVisible();
  await expect(page.getByText("лекция или конспект")).toBeVisible();
  await page.getByRole("button", { name: /Принять выбранное/ }).click();
  await expect(page.getByText("Применено")).toBeVisible();
  await page.getByRole("tab", { name: "Вручную" }).click();
  await expect(page.getByRole("treeitem").filter({ hasText: "Операция свёртки" })).toContainText("Предложено ИИ");
  await expect.poll(state.modelRequests).toBe(1);
});

test("без внешних моделей вкладка С ИИ объясняет причину и ведёт в ручной режим", async ({ page }) => {
  const state = await installStub(page, { aiEnabled: false });
  await page.goto(`${BASE}/projects/${PROJECT}/program`);
  await page.getByRole("tab", { name: "С ИИ" }).click();
  await expect(page.getByText("Внешние модели выключены")).toBeVisible();
  await expect(page.getByRole("button", { name: "Составь программу по моей цели" })).toHaveCount(0);
  await page.getByRole("button", { name: "Собрать вручную" }).click();
  await expect(page.getByRole("tab", { name: "Вручную" })).toHaveAttribute("aria-selected", "true");
  await expect.poll(state.modelRequests).toBe(0);
});

test("в Библиотеке видно глобальное имя, а в проекте — его псевдоним", async ({ page }) => {
  await installStub(page, {
    library: [libraryMaterial()],
    attachedDisplayName: "Экономика — имя в проекте",
  });
  await openFreeWizard(page);
  await enterGoal(page, "Экономика");
  await page.getByRole("button", { name: "Вся Библиотека" }).click();
  await expect(page.getByRole("dialog").getByText("Экономика — глобальное имя", { exact: true })).toBeVisible();
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

test("с моделью шаг программы мастера открывается чатом с быстрым стартом", async ({ page }) => {
  await installStub(page, { aiEnabled: true });
  await openFreeWizard(page);
  await enterGoal(page);
  await page.getByRole("button", { name: "К программе" }).click();
  await expect(page.getByRole("tab", { name: "С ИИ" })).toHaveAttribute("aria-selected", "true");
  await expect(page.getByRole("button", { name: "Составь программу по моей цели" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Что нужно знать заранее, чтобы достичь цели?" })).toBeVisible();
});

test("темы без материала: «Без материала» открывает подбор из Библиотеки по теме", async ({ page }) => {
  await installStub(page, {
    library: [libraryMaterial()],
    initialNodes: [{
      ...programNode("99999999-9999-4999-8999-999999999999", "Рынок и цены", "topic", null),
      origin_kind: "model",
      basis_kind: "custom",
      needs_material: true,
      origin_material_id: null,
      source_page_ranges: [],
      material_search_queries: ["спрос и предложение"],
      material_kind: "textbook",
    }],
  });
  await page.goto(`${BASE}/projects/${PROJECT}/program`);
  await page.getByRole("button", { name: "Без материала: 1" }).click();
  const dialog = page.getByRole("dialog", { name: "Материалы к темам" });
  await dialog.getByRole("button", { name: /Рынок и цены/ }).click();
  await expect(dialog.getByText("глава учебника")).toBeVisible();
  await expect(dialog.getByText("Экономика — глобальное имя")).toBeVisible();
  await dialog.getByRole("button", { name: "Подключить" }).click();
  await expect(dialog.getByText("Материал в проекте.")).toBeVisible();
  await expect(dialog.getByRole("link", { name: "соберите урок из найденного" })).toHaveAttribute("href", /lessons\?topic=/);
});


test("шаг материалов без поиска в интернете, а на проверке программа — дерево с отступами", async ({ page }) => {
  await installStub(page, {
    initialNodes: [
      programNode("11111111-aaaa-4aaa-8aaa-111111111111", "Рынок", "section", null),
      programNode("22222222-aaaa-4aaa-8aaa-222222222222", "Цены и равновесие", "topic", "11111111-aaaa-4aaa-8aaa-111111111111"),
    ],
  });
  await openFreeWizard(page);
  await enterGoal(page);
  await expect(page.getByText("Пока вы можете добавить материалы из Библиотеки.", { exact: false })).toBeVisible();
  await expect(page.getByRole("button", { name: "Найти в интернете" })).toHaveCount(0);
  await page.getByRole("button", { name: "К программе" }).click();
  await page.getByRole("button", { name: "К проверке" }).click();
  const section = page.locator(".program-review-row.is-section");
  const topic = page.locator(".program-review-row.is-topic");
  await expect(topic).toContainText("Цены и равновесие");
  const indent = async (row: typeof section) => row.evaluate((node) => parseFloat(getComputedStyle(node).paddingLeft));
  expect(await indent(topic)).toBeGreaterThan(await indent(section));
});

test("Материалы: поиск в интернете свёрнут, кнопка раскрывает чат, ход даёт карточки источников", async ({ page }) => {
  const state = await installStub(page, {
    aiEnabled: true,
    initialNodes: [{
      ...programNode(TOPIC, "Рынок и цены", "topic", null),
      origin_kind: "model", basis_kind: "custom", needs_material: true, origin_material_id: null,
      source_page_ranges: [], material_search_queries: ["рынок и цены лекция"], material_kind: "lecture",
    }],
  });
  await page.goto(`${BASE}/projects/${PROJECT}/materials`);
  const add = page.getByRole("button", { name: "Добавить материал" });
  const online = page.getByRole("button", { name: "Найти в интернете" }).first();
  await expect(online).toBeVisible();
  // Три действия шапки — в одну строку.
  expect(Math.round((await online.boundingBox())!.y)).toBe(Math.round((await add.boundingBox())!.y));

  const block = page.getByRole("region", { name: "Поиск в интернете" });
  const toggle = block.getByRole("button", { name: /Поиск в интернете/ });
  await expect(toggle).toHaveAttribute("aria-expanded", "false");
  await expect(page.getByText("Найдём материалы в интернете")).toHaveCount(0);

  await online.click();
  await expect(toggle).toHaveAttribute("aria-expanded", "true");
  await expect(block.getByRole("heading", { name: "Найдём материалы в интернете" })).toBeInViewport();
  await expect(block.getByRole("textbox")).toBeFocused();

  // Быстрая просьба только подставляется в поле — отправляет пользователь.
  await block.getByRole("button", { name: "Видеолекции" }).click();
  await expect(block.getByRole("textbox")).toHaveValue("Найди видеолекции по темам программы");
  expect(state.searchSent).toEqual([]);
  await block.getByRole("textbox").press("Enter");
  await expect(block.getByText("Нашлась лекция по рынку, каталог файлов и видео.")).toBeVisible();
  const lecture = block.getByRole("link", { name: "Лекция: рынок и цены" });
  await expect(lecture).toHaveAttribute("href", "https://lectures.example/market");
  await expect(block.getByText("Объясняет равновесие спроса и предложения")).toBeVisible();
  await expect(block.getByText("Кривые спроса и предложения, равновесная цена")).toBeVisible();
  await expect(block.getByText("lectures.example · ≈ 10 мин чтения · для начинающих")).toBeVisible();
  await expect(block.getByText("Страница со ссылками на файлы")).toBeVisible();
  await expect(block.getByText("ссылок на файлы: 14", { exact: false })).toBeVisible();
  await expect(block.getByText("youtube.com · видео · 40:46 · Кафедра")).toBeVisible();
  await expect(block.getByRole("list", { name: "Темы программы" }).first()).toContainText("1 Рынок и цены");
  await expect(block.getByText("Уже в проекте: 1.", { exact: false })).toBeVisible();
  await expect(block.getByRole("button", { name: /^Добавить/ })).toHaveCount(0);

  await block.getByRole("button", { name: "Найди задачи по рынку и ценам" }).click();
  await expect.poll(() => state.searchSent).toEqual([
    "Найди видеолекции по темам программы",
    "Найди задачи по рынку и ценам",
  ]);

  await block.getByText("Контекст и поиск", { exact: false }).click();
  await block.getByRole("switch", { name: "Искать и на английском" }).click();
  await expect.poll(() => state.searchContextPatches).toContainEqual({ context_flags: { english_sources: true } });
});

test("«Найти в интернете» у темы открывает чат с готовой просьбой по этой теме", async ({ page }) => {
  const state = await installStub(page, {
    aiEnabled: true,
    initialNodes: [{
      ...programNode(TOPIC, "Рынок и цены", "topic", null),
      origin_kind: "model", basis_kind: "custom", needs_material: true, origin_material_id: null,
      source_page_ranges: [], material_search_queries: ["рынок и цены лекция"], material_kind: "lecture",
    }],
  });
  await page.goto(`${BASE}/projects/${PROJECT}/program`);
  await page.getByRole("button", { name: "Без материала: 1" }).click();
  const dialog = page.getByRole("dialog", { name: "Материалы к темам" });
  await dialog.getByRole("button", { name: /Рынок и цены/ }).click();
  await dialog.getByRole("link", { name: "Найти в интернете" }).click();

  await expect(page).toHaveURL(`${BASE}/projects/${PROJECT}/materials?search=1&topic=${TOPIC}`);
  const block = page.getByRole("region", { name: "Поиск в интернете" });
  await expect(block.getByRole("textbox")).toHaveValue("Найди материалы по теме 1 «Рынок и цены»");
  expect(state.searchSent).toEqual([]);
});
