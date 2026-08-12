# Textbook Wizard Cleanup Implementation Plan

> **For agentic workers:** Execute this plan inline and preserve unrelated changes in the dirty worktree. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Repair draft deletion and make all five textbook-wizard steps concise, understandable and visually consistent.

**Architecture:** Reuse the existing draft DELETE endpoint, `ConfirmDialog`, material processing API and UI primitives. Delete one landing draft immediately, delete all visible drafts only after confirmation, and change only presentation/copy around the existing local `fast` parser.

**Tech Stack:** React, TypeScript, Radix-based Tentex primitives, existing CSS tokens, Playwright CLI.

## Global Constraints

- Keep confirmation for deleting the active draft and for deleting all drafts; omit it only for each landing-card trash button as requested.
- Preserve optimistic revision checks and show API failures without hiding a draft that was not deleted.
- Do not add a fake parser-mode selector: the only available mode is the existing local `fast` parser.
- Keep all existing draft, material, program and activation API contracts.
- Use concise Russian copy and native table/form semantics.

---

### Task 1: Draft management on the landing page

**Files:**
- Modify: `frontend/src/screens/ProjectWizard.tsx`
- Modify: `frontend/src/styles/layout.css`

- [x] Replace the broken state-only trash action with immediate API deletion and a busy state.
- [x] Add a heading row with `Удалить все черновики` aligned to the right.
- [x] Add one destructive confirmation dialog for bulk deletion and refresh partial failures safely.
- [x] Keep the active-draft confirmation unchanged.

### Task 2: Textbook wizard copy and summaries

**Files:**
- Modify: `frontend/src/screens/TextbookWizard.tsx`
- Modify: `frontend/src/screens/ProjectWizard.tsx`
- Modify: `frontend/src/styles/layout.css`
- Modify: `SCREENS.md`

- [x] Rename textbook progress steps to `Источники`, `Профиль`, `Проверка`, `Программы`, `Итог`.
- [x] Remove the repeated `Учебник · шаг N из 5` eyebrow from every textbook page.
- [x] Rename `Разобрать` to `Подготовить текст`, remove the waiting badge and time estimate, and match the trash-button height.
- [x] Replace the technical analysis sentence and dot-separated counters with a plain-language explanation and a semantic table.
- [x] Apply the requested profile copy and conditional required/optional field labels.
- [x] Review steps 3–5 for duplicate or implementation-facing wording and record the final behavior in `SCREENS.md`.

### Task 3: Browser and regression verification

- [x] Restart `web` and verify immediate single deletion plus the bulk-delete confirmation in Playwright; the shared DELETE path is covered by the successful single deletion without destroying all user drafts.
- [x] Walk all five textbook steps, including both profile scope variants and the material card at wide and narrow widths.
- [x] Verify accessible names, keyboard focus, confirmation focus trap and zero browser console errors/warnings.
- [x] Run typecheck, production build, lint, backend Ruff and affected stage smoke checks.
