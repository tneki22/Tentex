# Provider-aware AI Settings Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the modality-bound AI settings with provider-aware connections, model catalogs, defaults, function overrides, nested AI navigation, limits, and usage views.

**Architecture:** Persist provider connections independently from modality and identify every model by `(provider_id, model_id)`. `ModelGateway` continues to own resolution, preflight, transport, caching, limits, and runs; consumers receive a reusable provider/model selection contract. The React settings screen becomes a route-like shell whose nested subsection is stored in `section=ai&subsection=…`.

**Tech Stack:** FastAPI, SQLAlchemy 2, Alembic, SQLite WAL, Pydantic 2, OpenAI-compatible Python client, React 19, TypeScript, React Router, Radix primitives, plain CSS tokens.

## Global Constraints

- Keep one OpenAI-compatible completion transport; provider profiles may normalize catalog metadata but do not create vendor-specific completion adapters.
- Keep API keys encrypted with the existing installation secret and never return key material to the client.
- Preserve global/role switches, preflight, exact cache, prompt versions, token/cost accounting, and deterministic offline paths.
- A model identity is always the pair `provider_id + model_id`; never resolve a bare model id across providers.
- Favorites are plural shortcuts; one explicit provider/model pair per modality is the default.
- No automatic provider fallback, catalog-wide paid test, background refresh, benchmark ranking, arbitrary HTTP headers, or prompt/response logging.
- Russian interface copy, English identifiers, existing UI primitives, token-only CSS, and no Tailwind/CSS-in-JS.
- The visual change is user-approved and must be recorded in `SCREENS.md` and `docs/ui/stage-1-interface-baseline.md`.
- Project policy overrides generic TDD guidance: add focused tests after the contract is implemented, then run them before each commit.

---

### Task 1: Provider-aware persistence and migration

**Files:**
- Create: `backend/migrations/versions/20260814_0015_ai_providers.py`
- Modify: `backend/app/models.py`
- Modify: `backend/tests/conftest.py`
- Test: `backend/tests/test_ai_settings.py`

**Interfaces:**
- Produces: `AiProviderConnection`, provider-scoped `AiModelCatalogEntry`, provider-aware `AiRoleSetting`, `AiSettings` defaults, and provider snapshots on `AiRun`.
- Preserves: existing encrypted keys, current text/speech defaults, catalog rows, role overrides, runs, and cache foreign keys.

- [ ] **Step 1: Define provider-aware ORM rows**

Use these stable fields:

```python
class AiProviderConnection(Base):
    id: Mapped[UUID]
    label: Mapped[str]
    catalog_profile: Mapped[str]  # openrouter | openai_compatible
    base_url: Mapped[str]
    api_key_ciphertext: Mapped[bytes | None]
    is_favorite: Mapped[bool]
    last_test_status: Mapped[str | None]
    last_tested_at: Mapped[datetime | None]
    last_catalog_refresh_at: Mapped[datetime | None]
    updated_at: Mapped[datetime]

class AiModelCatalogEntry(Base):
    provider_id: Mapped[UUID]  # composite PK with model_id
    model_id: Mapped[str]
    display_name: Mapped[str]
    context_length: Mapped[int | None]
    max_completion_tokens: Mapped[int | None]
    supported_parameters: Mapped[list[str]]
    input_modalities: Mapped[list[str]]
    output_modalities: Mapped[list[str]]
    reasoning: Mapped[dict[str, object]]
    default_parameters: Mapped[dict[str, object]]
    manual_overrides: Mapped[dict[str, object]]
    prompt_price_usd: Mapped[Decimal | None]
    completion_price_usd: Mapped[Decimal | None]
    knowledge_cutoff: Mapped[str | None]
    expiration_date: Mapped[str | None]
    is_manually_added: Mapped[bool]
    favorite_order: Mapped[int | None]
    is_available: Mapped[bool]
```

Add `default_text_provider_id/default_text_model_id`, `default_speech_provider_id/default_speech_model_id`, and `confirm_cost_usd` to `AiSettings`; add `provider_override_id` to `AiRoleSetting`; add nullable `provider_id` plus non-null `provider_label_snapshot` to `AiRun`.

- [ ] **Step 2: Write migration `20260814_0015`**

Create provider/model replacement tables, insert one provider for each meaningful legacy connection, copy encrypted key/status/catalog/default data, translate role overrides to the matching modality provider, add settings/run columns through SQLite batch operations, and only then drop `ai_connections` and the legacy catalog table. Assign OpenRouter profile when normalized base URL equals `https://openrouter.ai/api/v1`; otherwise assign `openai_compatible`.

- [ ] **Step 3: Update the shared AI fixture**

Seed one `AiProviderConnection`, one provider-scoped structured model, text defaults on `AiSettings`, and the encrypted test key. Return a selection object containing both ids rather than a bare model id.

- [ ] **Step 4: Add persistence assertions**

Verify composite model identity allows the same `model_id` under two providers, provider deletion is restricted while referenced by a default or role, and secret bytes remain absent from SQLite.

- [ ] **Step 5: Run focused persistence checks**

Run: `cd backend && python -m pytest -q tests/test_ai_settings.py`

Expected: all provider identity, migration-facing service, URL, secret, and resolution tests pass.

- [ ] **Step 6: Commit**

```bash
git add backend/migrations/versions/20260814_0015_ai_providers.py backend/app/models.py backend/tests/conftest.py backend/tests/test_ai_settings.py
git commit -m "feat: add provider-aware AI persistence"
```

### Task 2: Provider, model, default, favorite, and role API

**Files:**
- Modify: `backend/app/ai/schemas.py`
- Modify: `backend/app/ai/settings.py`
- Modify: `backend/app/ai/catalog.py`
- Modify: `backend/app/ai/provider.py`
- Modify: `backend/app/ai/router.py`
- Modify: `backend/app/ai/roles.py`
- Test: `backend/tests/test_ai_settings.py`

**Interfaces:**
- Consumes: ORM types from Task 1.
- Produces: safe settings snapshot and CRUD endpoints used by the React panels.

- [ ] **Step 1: Replace modality connection schemas**

Define `AiProviderRead/Write`, `AiModelRead/Write`, `AiModelSelection`, `AiDefaultWrite`, provider/model favorite commands, provider-aware `AiRoleRead/Write`, and `AiModelTestRead`. Include provider/model ids on preflight, run, and usage projections while keeping ciphertext excluded.

- [ ] **Step 2: Implement provider settings services**

Implement these exact service boundaries:

```python
create_provider(session, command) -> AiSettingsRead
update_provider(session, provider_id, command) -> AiSettingsRead
delete_provider(session, provider_id) -> AiSettingsRead
delete_credential(session, provider_id) -> None
set_provider_favorites(session, provider_ids) -> AiSettingsRead
set_model_favorites(session, selections) -> AiSettingsRead
set_default_model(session, modality, selection | None) -> AiSettingsRead
upsert_manual_model(session, provider_id, command) -> AiSettingsRead
update_role(session, role, command) -> AiSettingsRead
resolve_model(session, role, request_override=None) -> ResolvedModel
```

Reject unknown provider/model pairs, incompatible defaults, provider deletion with dependency context, and cross-provider role selections. Resolve request override → role pair → modality default pair.

- [ ] **Step 3: Normalize richer catalog metadata**

Extend `ProviderModel` and `OpenAITransport.list_models()` with `reasoning`, `default_parameters`, `max_completion_tokens`, `knowledge_cutoff`, and `expiration_date`. Refresh only the selected provider, preserve `favorite_order` and `manual_overrides`, mark disappeared rows unavailable, and never infer missing values from the model name.

- [ ] **Step 4: Add provider/model HTTP routes**

Expose:

```text
POST   /api/settings/ai/providers
PUT    /api/settings/ai/providers/{provider_id}
DELETE /api/settings/ai/providers/{provider_id}
DELETE /api/settings/ai/providers/{provider_id}/credential
POST   /api/settings/ai/providers/{provider_id}/test
POST   /api/settings/ai/providers/{provider_id}/models/refresh
PUT    /api/settings/ai/providers/{provider_id}/models/manual
POST   /api/settings/ai/providers/{provider_id}/models/test
PUT    /api/settings/ai/provider-favorites
PUT    /api/settings/ai/model-favorites
PUT    /api/settings/ai/defaults/{text|speech}
PUT    /api/settings/ai/roles/{role}
```

Keep `GET/PUT /api/settings/ai`, `/runs`, and `/usage`; expand run/usage filters with provider and model.

- [ ] **Step 5: Register the model-test role**

Add `settings_model_test` to `ROLE_SPECS` with `visible=False`, text modality, no cache, prompt version `settings-model-test-v1`, `max_output_tokens=8`, and request pair override allowed. Hidden roles must not appear in the Functions panel.

- [ ] **Step 6: Test safe CRUD and catalog behavior**

Cover multiple providers, secret rotation/deletion, provider test vs model test, catalog refresh preservation, manual overrides, defaults, ordered favorites, role compatibility, hidden test role, deletion dependency codes, and safe HTTP serialization.

- [ ] **Step 7: Run settings checks**

Run: `cd backend && python -m pytest -q tests/test_ai_settings.py`

Expected: provider/model HTTP and service tests pass without network access.

- [ ] **Step 8: Commit**

```bash
git add backend/app/ai/schemas.py backend/app/ai/settings.py backend/app/ai/catalog.py backend/app/ai/provider.py backend/app/ai/router.py backend/app/ai/roles.py backend/tests/test_ai_settings.py
git commit -m "feat: expose provider and model settings API"
```

### Task 3: Provider-aware gateway, preflight, tests, and check script

**Files:**
- Modify: `backend/app/ai/gateway.py`
- Modify: `backend/app/ai/provider.py`
- Modify: `backend/tests/test_ai_gateway.py`
- Modify: `backend/tests/test_ai_cleanup.py`
- Modify: `backend/tests/test_ai_program_grouping.py`
- Modify: `backend/tests/test_exam_chat.py`
- Modify: `backend/tests/test_exam_attempts.py`
- Modify: `backend/scripts/check_ai_gateway.py`

**Interfaces:**
- Consumes: `ResolvedModel(provider, model_id, source, parameters)` and provider-scoped catalog.
- Produces: provider-aware `AiPreflight`, `AiRun`, exact-cache key, structured completion, stream, and paid model test.

- [ ] **Step 1: Carry provider selection through gateway requests**

Change request override to `AiModelSelection | None`; resolve credentials and production transport from `provider_id`; fetch catalog rows by `(provider_id, model_id)`; include provider id in cache canonical JSON and run snapshots.

- [ ] **Step 2: Apply parameter precedence**

Merge provider/model default parameters → manual model request defaults → role parameters → request parameters. Pass supported `temperature`, `top_p`, and normalized `reasoning` through transport; keep `max_output_tokens` as the gateway limit. Reject a parameter absent from the model's supported set unless it is the internal output limit.

- [ ] **Step 3: Implement paid model test through ModelGateway**

Use hidden role `settings_model_test`, fixed message `Ответь одним словом: работает`, selected provider/model override, eight output tokens, normal preflight/limits/unknown-price confirmation, and regular `AiRun`. Return actual model, duration, usage, and cost without storing response text.

- [ ] **Step 4: Update gateway tests and consumers**

Assert provider id changes cache identity, runs preserve provider snapshots, structured and stream calls use the selected provider transport, reasoning reaches fake transport request capture, model test is logged, and existing cleanup/grouping/chat consumers continue to work through defaults.

- [ ] **Step 5: Update end-to-end fake scenario**

Make `check_ai_gateway.py` create a provider, refresh its catalog, assign text default, run cleanup/cache/grouping/undo, exercise paid model test, operation limit, global off, and `PRAGMA foreign_key_check`.

- [ ] **Step 6: Run gateway regression**

Run:

```bash
cd backend
python -m pytest -q tests/test_ai_gateway.py tests/test_ai_cleanup.py tests/test_ai_program_grouping.py tests/test_exam_chat.py tests/test_exam_attempts.py
python scripts/check_ai_gateway.py
```

Expected: all selected tests and the fake-provider check pass with no network or paid calls.

- [ ] **Step 7: Commit**

```bash
git add backend/app/ai/gateway.py backend/app/ai/provider.py backend/tests/test_ai_gateway.py backend/tests/test_ai_cleanup.py backend/tests/test_ai_program_grouping.py backend/tests/test_exam_chat.py backend/tests/test_exam_attempts.py backend/scripts/check_ai_gateway.py
git commit -m "feat: route model gateway through providers"
```

### Task 4: Typed frontend client and reusable provider/model picker

**Files:**
- Modify: `frontend/src/api/ai.ts`
- Create: `frontend/src/components/domain/ProviderModelPicker.tsx`
- Modify: `frontend/src/components/domain/index.ts`
- Modify: `frontend/src/screens/UiKit.tsx`
- Create: `frontend/src/styles/ai-settings.css`
- Modify: `frontend/src/main.tsx`

**Interfaces:**
- Consumes: Task 2 HTTP schemas.
- Produces: typed API functions and `ProviderModelPicker` reused by defaults and roles.

- [ ] **Step 1: Mirror safe API types**

Replace connections with providers, provider-scoped models, pair defaults, favorite order, reasoning metadata, model test result, provider/model ids on roles/runs, and the new stable error codes. Add typed CRUD, test, refresh, default, favorite, manual model, run, and usage functions.

- [ ] **Step 2: Build `ProviderModelPicker`**

Implement two native linked selects with props for provider/model value, modality, required capabilities, inheritance label, disabled state, unavailable current selection, and `onChange(AiModelSelection | null)`. Sort favorites first and never accept free text.

- [ ] **Step 3: Add picker to the domain kit**

Export it from `components/domain/index.ts`, add a self-contained demo with two providers to `/ui-kit`, and style focus, helper copy, paired layout, and narrow stacking only through existing tokens.

- [ ] **Step 4: Typecheck the client boundary**

Run: `npm run typecheck`

Expected: the API client and picker compile before screen consumers are migrated.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api/ai.ts frontend/src/components/domain/ProviderModelPicker.tsx frontend/src/components/domain/index.ts frontend/src/screens/UiKit.tsx frontend/src/styles/ai-settings.css frontend/src/main.tsx
git commit -m "feat: add provider model picker"
```

### Task 5: Nested AI settings navigation and all panels

**Files:**
- Modify: `frontend/src/screens/Setup.tsx`
- Replace: `frontend/src/screens/AiSettingsSection.tsx`
- Create: `frontend/src/screens/ai-settings/AiSettingsContext.tsx`
- Create: `frontend/src/screens/ai-settings/AiOverview.tsx`
- Create: `frontend/src/screens/ai-settings/AiProviders.tsx`
- Create: `frontend/src/screens/ai-settings/AiModels.tsx`
- Create: `frontend/src/screens/ai-settings/AiDefaults.tsx`
- Create: `frontend/src/screens/ai-settings/AiRoles.tsx`
- Create: `frontend/src/screens/ai-settings/AiLimits.tsx`
- Create: `frontend/src/screens/ai-settings/AiUsage.tsx`
- Create: `frontend/src/screens/ai-settings/format.ts`
- Modify: `frontend/src/styles/ai-settings.css`

**Interfaces:**
- Consumes: Task 4 client and picker.
- Produces: `/setup?section=ai&subsection=overview|providers|models|defaults|roles|limits|usage`.

- [ ] **Step 1: Add nested navigation to `Setup`**

Render the seven indented children only while `section=ai`. Parent click opens `overview`; absent/invalid subsection normalizes to overview; every child preserves URL and browser history. On narrow screens render children as the second horizontal navigation row.

- [ ] **Step 2: Centralize safe settings state**

`AiSettingsContext` loads the safe snapshot once, exposes `settings`, `runs`, `loading`, `error`, `refresh`, and `acceptSettings`, dispatches `tentex:ai-settings-updated`, and renders shared Loading/Error/Retry states without rebuilding response objects in panels.

- [ ] **Step 3: Implement Overview and Providers**

Overview renders the global switch, resolved text/speech defaults, today's usage, inheritance explanation, offline warning, and privacy disclosure. Providers renders the specified table, add/edit dialog, secret replacement/deletion, favorites, connection test, catalog refresh, dependency-aware delete, and `Модели` navigation with provider id.

- [ ] **Step 4: Implement Models and Defaults**

Models renders provider selector, search/filters, provider-scoped table, metadata dialog, manual model dialog, favorite toggle, refresh, unavailable rows, and paid test confirmation/result. Defaults renders text/speech pair pickers and ordered chat favorites with up/down/remove controls.

- [ ] **Step 5: Implement Roles, Limits, and Usage**

Roles renders every visible registry role with switch, inherit/override mode, provider/model picker, supported reasoning selector, source label, and local warning. Limits keeps current money/course fields and adds confirmation cost. Usage renders honest empty state, 1/7/30-day period controls, grouping selector, filters, aggregates, and recent safe runs.

- [ ] **Step 6: Complete responsive and accessible styles**

Use a wider AI content column for tables, preserve readable text width inside headers, provide labelled stacked row layout below 760 px, keep nested navigation scrollable, ensure actions wrap, mark active child with text and background, and announce async save/test states through `aria-live`.

- [ ] **Step 7: Run frontend checks**

Run:

```bash
npm run typecheck
npm run build
```

Expected: both commands succeed with all seven panels compiled.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/screens/Setup.tsx frontend/src/screens/AiSettingsSection.tsx frontend/src/screens/ai-settings frontend/src/styles/ai-settings.css
git commit -m "feat: redesign AI settings navigation"
```

### Task 6: Documentation, full verification, and visual acceptance

**Files:**
- Modify: `SCREENS.md`
- Modify: `docs/ui/stage-1-interface-baseline.md`
- Modify: `docs/architecture/ai-model-gateway.md`
- Modify: `PLAN.md`

**Interfaces:**
- Consumes: verified behavior from Tasks 1–5.
- Produces: current target screen contract, approved baseline deviation, and factual architecture record.

- [ ] **Step 1: Update screen and baseline contracts**

Describe the nested AI subsections, direct URLs, actions, states, data, transitions, table behavior, favorites/default distinction, and approved change from the 12 August long page.

- [ ] **Step 2: Update factual architecture**

Document migration `0015`, provider-scoped identity, catalog normalization, resolution order, model test, parameter precedence, HTTP routes, run snapshots, and intentional no-fallback boundary. Mark the vertical complete in `PLAN.md` only after every verification below succeeds.

- [ ] **Step 3: Run complete automated verification**

Run:

```bash
npm run typecheck
npm run build
npm run lint
cd backend
python -m pytest -q
python scripts/check_ai_gateway.py
python scripts/check_exam_chat.py
```

Expected: every command exits 0; fake-provider tests use no network or paid key.

- [ ] **Step 4: Restart and inspect the live application**

Run: `docker compose restart web api`

Inspect all subsection URLs, provider→models transition, browser back/forward, empty state, global off, unavailable provider/model, unknown price confirmation, keyboard order, light/dark themes, desktop width, and 390 px. Capture a final screenshot after the container restart.

- [ ] **Step 5: Commit documentation and any verified visual corrections**

```bash
git add SCREENS.md docs/ui/stage-1-interface-baseline.md docs/architecture/ai-model-gateway.md PLAN.md
git commit -m "docs: record provider-aware AI settings"
```

## Plan self-review

- Spec coverage: nested navigation, providers, models, metadata, model test, defaults, favorites, roles, reasoning, limits, usage, privacy, migration, error states, docs, and visual verification each map to a task.
- Scope: one coherent vertical through the existing model gateway; deferred fallback, benchmarks, arbitrary headers, and other universal LLM-console features remain excluded.
- Type consistency: every selection uses `AiModelSelection(provider_id, model_id)`; providers use UUID ids; model storage and gateway lookup use `(provider_id, model_id)`.
- Placeholder scan: the plan contains no deferred implementation markers or unspecified error/testing steps.
