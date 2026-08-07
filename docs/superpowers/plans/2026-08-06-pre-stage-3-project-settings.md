# Pre-stage 3 Project Settings Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Сделать настоящий экран `/projects/:projectId/settings`, который атомарно сохраняет поддерживаемые настройки активного проекта и паспорт цели, переживает перезапуск и становится общим основанием этапа 3.

**Architecture:** FastAPI принимает один узкий `PUT` и в одной SQLAlchemy-транзакции обновляет `Project` и существующий `GoalPassport`; Alembic приводит цвет проекта к `int | null`. React загружает `ProjectDetail` через один небольшой клиент над `fetch`, держит локальный черновик формы и принимает успешный серверный ответ как новый baseline.

**Tech Stack:** FastAPI · Pydantic 2 · SQLAlchemy 2 · Alembic · SQLite WAL · React 19 · TypeScript 5.9 · React Router 8 · Radix UI · native `fetch`

## Global Constraints

- Не добавлять зависимости, новые сущности, глобальный store, optimistic update, toast или router blocker.
- Экран меняет только разрешённые поля Project, GoalPassport и шесть существующих `ModuleKey`; `template_key`, `workspace_variant`, `status`, `sort_order` неизменны.
- Только `active` редактируется: draft/unknown дают 404, archived/completed — readonly на GET и 409 на PUT.
- `/setup` остаётся глобальной областью моделей, бота, резервных копий и хранилища.
- Поздние проектные модели/лимиты, напоминания, шаблоны, экспорт и резервные копии не имитируются.
- Сохранять чужие несвязанные изменения грязного worktree; коммит не создавать.

---

### Task 1: Выровнять серверные контракты и добавить атомарное сохранение

**Files:**
- Create: `backend/migrations/versions/20260806_0002_project_color.py`
- Modify: `backend/app/models.py`
- Modify: `backend/app/projects/schemas.py`
- Modify: `backend/app/projects/service.py`
- Modify: `backend/app/projects/router.py`
- Modify: `backend/scripts/check_stage2.py`

**Interfaces:**
- Produces: `PUT /api/projects/{project_id}/settings` with `ProjectSettingsWrite` and `ProjectDetail` response.
- Preserves: existing `GET /api/projects/{project_id}` and wizard contracts, now with `color: int | null`.

- [x] Change `Project.color` and all API color fields to `int | null`, validate `1..8`, and add a narrow migration that maps non-null legacy values outside `1..8` to `1` before changing the SQLite column and adding a check constraint.
- [x] Add settings command schemas containing only editable project fields and `GoalPassportWrite`; normalize duplicate modules by `ModuleKey` enum order.
- [x] Add service method that returns 404 for missing/draft, 409 for archived/completed, then updates Project and GoalPassport in one `session.begin()` and returns the fresh `ProjectDetail`.
- [x] Register the single PUT route.
- [x] Extend `check_stage2.py` to save every field group, verify normalized modules and preserved status/template/variant/sort order, restart and GET the same values, then verify archived PUT = 409 and `PRAGMA foreign_key_check` is empty.
- [x] Run `python backend/scripts/check_stage2.py` and `cd backend && python -m ruff check .`.

### Task 2: Добавить общий клиент и единый словарь уровня цели

**Files:**
- Create: `frontend/src/api/projects.ts`
- Modify: `frontend/src/components/domain/GoalLevel.tsx`
- Modify: `frontend/src/screens/Program.tsx`
- Modify: `frontend/src/screens/UiKit.tsx`

**Interfaces:**
- Produces: `request<T>()`, `getProject(projectId)`, `updateProjectSettings(projectId, command)`, `ProjectDetail`, `ProjectSettingsCommand`, and typed API errors.
- Produces: `GoalLevelValue = "awareness" | "understanding" | "application" | "mastery"`.

- [x] Implement one native-fetch client that reads FastAPI `detail`, retains HTTP status for 404/409 handling, and contains only types needed by ProjectDetail/settings plus the three requested functions.
- [x] Replace the old `know/understand/apply/master` values in the shared goal-level widget and its Program/UI-kit consumers without changing Russian labels or effects.
- [x] Run `npm run typecheck`.

### Task 3: Реализовать экран и проектные переходы

**Files:**
- Create: `frontend/src/screens/ProjectSettings.tsx`
- Modify: `frontend/src/app/views.ts`
- Modify: `frontend/src/app/screens.ts`
- Modify: `frontend/src/screens/Program.tsx`
- Modify: `frontend/src/screens/ProjectWorkspace.tsx`
- Modify: `frontend/src/styles/layout.css`

**Interfaces:**
- Consumes: `getProject`, `updateProjectSettings`, existing UI primitives, `PROJECT_ICONS`, project color tokens.

- [x] Load the route project and render honest loading, generic error and 404 states; archived/completed render the same data readonly with no enabled save path.
- [x] Build one responsive form for editable Project fields, full GoalPassport, exam-only fields and six module switches; use accessible Radix/native radio groups for icon/color and existing UI-kit components elsewhere.
- [x] Validate trimmed name and numeric passport limits locally; disable save while unchanged, invalid or saving; keep entered values on server error; show inline `Сохранено` after the successful response becomes baseline.
- [x] Register the view and make Settings links active in Program plus both Workspace variants.
- [x] Add `beforeunload` only while dirty and no custom router blocker.
- [x] Run `npm run typecheck` and `npm run build`.

### Task 4: Проверить в браузере и зафиксировать только факты

**Files:**
- Modify after successful implementation checks: `SCREENS.md`
- Modify after successful implementation checks: `PLAN.md`
- Modify after successful implementation checks: `REQUIREMENTS.md`
- Modify after successful implementation checks: `docs/architecture/stage-2-core.md`

- [x] Run fresh: `python backend/scripts/check_stage2.py`, `cd backend && python -m ruff check .`, `npm run typecheck`, `npm run build`, `docker compose restart web`.
- [x] Open a real active UUID at `/projects/:projectId/settings`; verify save/reload, keyboard icon/color selection, light/dark themes, 404, readonly archived project, inline save error and native unsaved-change protection.
- [x] Update `SCREENS.md` with the five required points and the `/setup` distinction; update `PLAN.md` so stage 3 reuses this completed slice; resolve the §21 wording in `REQUIREMENTS.md`; record the actual PUT, migration and restart check in `stage-2-core.md`.
- [x] Re-run the full fresh command set after documentation changes and inspect `git diff` for unrelated edits.

## Self-review

- Coverage: server errors 404/409/422, atomic save, migration, client, route, navigation, all requested screen states, accessibility, restart and documentation are assigned to explicit steps.
- Placeholders: none; late settings are explicitly excluded instead of stubbed.
- Type consistency: project color is `int | null`; shared target values exactly match backend `TargetOutcome`; settings response is the existing `ProjectDetail`.
