# Textbook Wizard Completion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore the stage-1 textbook wizard flow on live APIs so a resumed draft can become an active project even when its program is empty.

**Architecture:** Keep the existing `WizardChrome` and stage-1-derived textbook layout. Fix the draft lifecycle at the existing controller boundary, reuse the activation path already used by the exam wizard, and relax only the obsolete activation invariant that requires a study node.

**Tech Stack:** React 19, TypeScript, React Router, FastAPI, SQLAlchemy, SQLite, Playwright CLI.

**Status:** Implemented and verified on 2026-08-11. Browser smoke created active textbook project `6bdace89-06e1-4336-9473-1fbd81cc2acd`; all commands in Task 5 completed with exit code 0.

## Global Constraints

- Preserve the `ui-stage-1-baseline` visual hierarchy and all current live material/program actions.
- Keep Russian interface copy and English identifiers.
- Do not add dependencies, model calls, pass 1/pass 2, embeddings, lessons, cards, or new material/binding work.
- Preserve draft deletion, autosave, optimistic-concurrency errors, undo, and project material links.

---

### Task 1: Repair the textbook draft lifecycle

**Files:**
- Modify: `frontend/src/screens/TextbookWizard.tsx`

**Interfaces:**
- Consumes: `WizardDraftController.status`, `ensureDraft()`, `queueSave()`, `activate()`.
- Produces: a textbook wizard that creates a draft only from `idle`, resumes the requested draft without replacement, and reports activation through `onActivated(ProjectDetail)`.

- [ ] Guard the eager `ensureDraft()` effect with `controller.status === "idle"` so a loading resumed draft cannot be replaced.
- [ ] Allow step 4 to advance when `nodes.length === 0`, with explicit copy that the program can be created later.
- [ ] Add `activate()` mirroring the established exam-wizard activation sequence: save step 5, call `controller.activate()`, then call `onActivated`.
- [ ] Replace the step-5 draft-only action and stale copy with `Создать проект` and the real active-project outcome.
- [ ] Render actual `materials.materials` rows with display name, role, priority, and processing status in the summary.

### Task 2: Reuse the project-wizard success route

**Files:**
- Modify: `frontend/src/screens/ProjectWizard.tsx`

**Interfaces:**
- Consumes: `TextbookWizard.onActivated(ProjectDetail)` and `ProjectDetail.project.workspace_variant`.
- Produces: success copy and destination appropriate to exam or textbook projects.

- [ ] Pass `setActivatedProject` into the textbook branch.
- [ ] Send an activated textbook project to `/projects/:projectId/program` and label the primary action `Открыть программу`.
- [ ] Keep the existing exam success route and the draft deletion controls unchanged.

### Task 3: Permit activation without a program and retain a regression check

**Files:**
- Modify: `backend/app/projects/service.py`
- Modify: `backend/scripts/check_stage4.py`

**Interfaces:**
- Consumes: `POST /api/wizard-drafts/{project_id}/activate` with a complete project name and `GoalPassport`.
- Produces: an active textbook project whose `program.nodes` may be empty.

- [ ] Remove the study-node activation invariant; passport and project-name validation remain mandatory.
- [ ] Change the textbook smoke scenario to activate the saved draft without creating a `ProgramNode` and assert the active response contains an empty program.
- [ ] Run `python backend/scripts/check_stage4.py` and confirm the empty-program activation succeeds.

### Task 4: Align factual documentation

**Files:**
- Modify: `AGENTS.md`
- Modify: `SCREENS.md`
- Modify: `REQUIREMENTS.md`
- Modify: `docs/architecture/stage-3-live-projects.md`
- Modify: `docs/architecture/stage-5-material-pipeline.md`
- Modify: `docs/ui/stage-1-interface-baseline.md`

**Interfaces:**
- Consumes: the implemented live wizard contract.
- Produces: one consistent statement: exam and textbook projects may activate with an empty program, and the program can be filled later.

- [ ] Update the current-stage summaries and the real-screen boundary without rewriting the historical stage-3 limitation as if it had never existed.
- [ ] Record the user-approved deviation from the original baseline requirement that a program already exist.
- [ ] Keep pass 1 and pass 2 assigned to their existing later stages.

### Task 5: Browser and repository verification

**Files:**
- No production file changes expected.

**Interfaces:**
- Consumes: the running Docker services at ports `8000` and `5173`.
- Produces: one active textbook project created through the visible five-step wizard.

- [ ] Restart `api` and `web` so browser verification uses the changed backend and frontend.
- [ ] Resume or create a textbook draft, reach step 4 with no nodes, continue to step 5, verify actual material rows, and click `Создать проект`.
- [ ] Open the new active project's Program screen and confirm its empty state offers manual node creation.
- [ ] Run `npm run typecheck`, `npm run build`, `npm run lint`, `python -m ruff check .`, and the relevant stage smoke checks; report any unrelated pre-existing failures separately.

## Self-Review

- Spec coverage: resume, deletion preservation, baseline layout, empty-program continuation, truthful summary, activation, navigation, docs, and browser verification are covered.
- Placeholder scan: no implementation placeholders remain.
- Type consistency: `onActivated` uses the existing `ProjectDetail` type and controller activation contract.
