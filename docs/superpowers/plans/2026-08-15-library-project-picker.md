# Library Project Picker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an explicit “Выбрать из Библиотеки” action to every project material intake point and connect existing global materials without copying or reprocessing them.

**Architecture:** Create one domain dialog that lists global materials, owns selection and calls the existing `attachLibraryMaterial` API. Each screen supplies the project, fixed or editable purpose, role policy, and its existing post-attach refresh behavior. Keep the inverse Library-to-project dialog separate because it selects a project rather than a material, but align its wording and purpose/role rules.

**Tech Stack:** React, TypeScript, existing Radix-based UI primitives, ordinary token-based CSS, existing FastAPI endpoints.

## Global Constraints

- Preserve the stage-1 visual baseline: add secondary actions without reordering the existing blocks.
- A selected Library material creates only `ProjectMaterial`; never copy the file or restart completed processing.
- Use Russian interface copy and English identifiers.
- Use only existing design tokens and Lucide icons.
- Do not introduce a toast; refresh the visible list and announce the result inline.
- The frontend has no test runner; verification is typecheck, build, browser scenarios, and the existing Library workspace check.

---

### Task 1: Shared Library material picker

**Files:**
- Create: `frontend/src/components/domain/LibraryMaterialPickerDialog.tsx`
- Modify: `frontend/src/components/domain/index.ts`
- Modify: `frontend/src/styles/domain.css`
- Modify: `frontend/src/screens/UiKit.tsx`

**Interfaces:**
- Consumes: `listLibraryMaterials()`, `attachLibraryMaterial(materialId, command)`, `LibraryMaterialRead`, `MaterialPurpose`, and `SourceRole` from `frontend/src/api/materials.ts`.
- Produces: `LibraryMaterialPickerDialog` with `open`, `projectId`, `title`, `purpose`, `multiple`, `existingStudySourceCount`, optional `allowPurposeSelection`, optional replacement callback, `onOpenChange`, `onAttached`, and `onCreateNew`.

- [ ] **Step 1: Implement picker state and loading**

Create a dialog that loads `listLibraryMaterials` only while open, filters by a case-insensitive Russian name query, sorts by `ready → queued/processing/paused/ready_to_process → failed`, and derives “already attached” from `material.usage`.

- [ ] **Step 2: Implement accessible rows and selection**

Use checkbox rows for multiple selection and radio-like single selection. Show original name, source kind, page count, status, and project usage. Keep already attached rows visible and disabled with “Уже в проекте”.

- [ ] **Step 3: Implement attachment commands**

For fixed `exam_structure` and `reference_answers`, send `source_role: "reference"`. For fixed `study_source`, assign `main` only when the project has no current study source and use `additional` for following selections. In editable mode, expose purpose and expose role only for `study_source`.

- [ ] **Step 4: Implement partial failure and answer replacement**

Attach selected items sequentially so each command receives the correct study-source index. Remove successful rows from the pending selection, keep failed rows selected with their error, call `onAttached(ids)` after each successful batch, and show the existing confirmation before replacing an answer material.

- [ ] **Step 5: Add domain styles and UI-kit example**

Add compact search, scrollable row list, selected state, metadata wrapping, and narrow-window behavior to `domain.css`. Export the component and add a closed/static demonstration entry to `/ui-kit` without making network calls.

- [ ] **Step 6: Verify and commit**

Run `npm run typecheck` and fix all errors. Commit only the four Task 1 files:

```powershell
git add -- frontend/src/components/domain/LibraryMaterialPickerDialog.tsx frontend/src/components/domain/index.ts frontend/src/styles/domain.css frontend/src/screens/UiKit.tsx
git commit -m "feat: add reusable library material picker"
```

---

### Task 2: Project creation wizards

**Files:**
- Modify: `frontend/src/screens/project-wizard/ExamMaterialUploadPanel.tsx`
- Modify: `frontend/src/screens/project-wizard/ExamWizard.tsx`
- Modify: `frontend/src/screens/TextbookWizard.tsx`

**Interfaces:**
- Consumes: `LibraryMaterialPickerDialog` from Task 1.
- Produces: explicit Library actions in exam and textbook onboarding while keeping existing upload and drag-and-drop behavior.

- [ ] **Step 1: Extend the exam upload panel**

Add an optional `onChooseLibrary: () => void` prop. Render a secondary `Выбрать из Библиотеки` button beside `Выбрать файлы` only in file mode and only while the single-file panel is not at its limit.

- [ ] **Step 2: Connect the exam wizard**

Track the active `MaterialPurpose`, open one picker for the three upload panels, use single selection for structure/answers and multiple selection for study sources, refresh `useProjectMaterials` after attachment, and start fast processing only for newly attached `exam_structure` materials in `ready_to_process`.

- [ ] **Step 3: Connect the textbook wizard**

Place `Выбрать из Библиотеки` beside `Добавить материал`, open the picker in multiple `study_source` mode, preserve first-main/remaining-additional role assignment, and refresh the existing source list after attachment.

- [ ] **Step 4: Verify and commit**

Run `npm run typecheck`. Commit only the three wizard files:

```powershell
git add -- frontend/src/screens/project-wizard/ExamMaterialUploadPanel.tsx frontend/src/screens/project-wizard/ExamWizard.tsx frontend/src/screens/TextbookWizard.tsx
git commit -m "feat: select library materials during project setup"
```

---

### Task 3: Program import and project Materials

**Files:**
- Modify: `frontend/src/screens/Program.tsx`
- Modify: `frontend/src/screens/Materials.tsx`
- Modify: `frontend/src/styles/layout.css`

**Interfaces:**
- Consumes: `LibraryMaterialPickerDialog` from Task 1 and existing `useProjectMaterials.refresh()`.
- Produces: explicit Library selection in the late exam import and the full project Materials surface.

- [ ] **Step 1: Add Library selection to Program import**

Add `Выбрать из Библиотеки` beside both `Загрузить список вопросов` and `Загрузить другой материал`. Attach one `exam_structure` material with role `reference`, refresh project materials, select the attached id, and let the existing effect load a preview when status is `ready`.

- [ ] **Step 2: Add the Materials catalog action**

Extend `MaterialCatalog` and `MaterialOverview` with `onChooseLibrary`. Render `Из Библиотеки` beside `Добавить`, including the empty overview action group.

- [ ] **Step 3: Connect editable purpose and replacement**

Open the shared picker from `MaterialSurface` with editable purpose. Reuse `releaseAnswersMaterial` and the current answer replacement copy, refresh the store after attachment, and navigate to the first successfully attached material.

- [ ] **Step 4: Keep layout stable**

Add only the button-group wrapping needed by the catalog, empty overview, Program import, and wizard dropzones. Preserve the baseline ordering and existing responsive breakpoints.

- [ ] **Step 5: Verify and commit**

Run `npm run typecheck`. Commit only Task 3 files:

```powershell
git add -- frontend/src/screens/Program.tsx frontend/src/screens/Materials.tsx frontend/src/styles/layout.css
git commit -m "feat: attach library materials inside projects"
```

---

### Task 4: Align inverse Library workflow and documentation

**Files:**
- Modify: `frontend/src/screens/library/AddToProjectDialog.tsx`
- Modify: `frontend/src/screens/library/LibraryMaterialFilePanel.tsx`
- Modify: `SCREENS.md`
- Modify: `docs/ui/stage-1-interface-baseline.md`

**Interfaces:**
- Consumes: existing `AddToProjectDialog` and the selected design spec.
- Produces: consistent “Подключить” wording and documented actions across all five entry points.

- [ ] **Step 1: Align inverse dialog wording and role rules**

Rename the action and dialog to `Подключить к проекту` / `Подключить`. When purpose is `exam_structure` or `reference_answers`, force and hide role `reference`; for `study_source`, keep the three role choices.

- [ ] **Step 2: Update screen and baseline documentation**

Document the two explicit actions in both wizard branches, Program import, project Materials, and Library workspace. Record that the new secondary buttons are an explicitly approved additive change that preserves block order.

- [ ] **Step 3: Verify and commit**

Run `npm run typecheck`. Commit only Task 4 files:

```powershell
git add -- frontend/src/screens/library/AddToProjectDialog.tsx frontend/src/screens/library/LibraryMaterialFilePanel.tsx SCREENS.md docs/ui/stage-1-interface-baseline.md
git commit -m "docs: align library connection workflow"
```

---

### Task 5: Full verification

**Files:**
- No planned source changes; fix only defects discovered by verification and commit those exact files separately.

**Interfaces:**
- Consumes: completed Tasks 1–4.
- Produces: verified feature in the running application.

- [ ] **Step 1: Run static verification**

Run:

```powershell
npm run typecheck
npm run build
python backend/scripts/check_library_workspace.py
```

Expected: all commands exit with code 0.

- [ ] **Step 2: Restart the frontend container**

Run `docker compose restart web` and wait for the service to become available at `http://localhost:5173`.

- [ ] **Step 3: Verify browser scenarios**

Check exam wizard single/multiple selection, textbook multiple selection, Program import, Materials editable purpose, inverse Library attachment, already-attached disabled rows, empty/error states, keyboard focus, both themes, and the approximately 900 px layout. Save screenshots under `output/playwright/library-project-picker/`; do not commit them.

- [ ] **Step 4: Inspect final repository state**

Run `git status --short` and confirm that every implementation file is committed while unrelated pre-existing changes remain untouched.
