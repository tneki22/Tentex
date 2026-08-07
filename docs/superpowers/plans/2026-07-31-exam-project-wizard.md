# Exam Project Wizard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a polished, interactive fake-data prototype of the exam branch of the project creation wizard at `/projects/new`.

**Architecture:** Keep all wizard draft state and step rendering in one screen component because this is a stage-1 prototype with no API. Reuse existing Tentex UI primitives and add only screen-specific CSS; teach `AppLayout` to render this route without the global sidebar and top bar.

**Tech Stack:** React 19, TypeScript, React Router, Lucide icons, existing Tentex UI kit, plain token-based CSS.

## Global Constraints

- Russian interface copy; English identifiers.
- No new dependency and no backend/API work.
- Colors, spacing, radii, typography, and motion use existing tokens from `frontend/src/styles/tokens.css`.
- Reuse existing `Button`, `Card`, `RadioCards`, `Checkbox`, `SegmentedTabs`, `Field`, `Progress`, and `StatusBadge` primitives where they fit.
- `/projects/new` is full-screen and does not show the global sidebar or top bar.
- Prototype must preserve entered values when moving backward.
- The repository currently has no frontend test harness; verification is typecheck, lint, production build, and a real-browser walkthrough after restarting `web`.

---

### Task 1: Record the passport clarification

**Files:**
- Modify: `SCREENS.md`

**Interfaces:**
- Consumes: the approved five-step exam flow.
- Produces: passport fields `teacherNotes`, `startingLevel`, and `startingNotes` for the screen prototype.

- [ ] **Step 1: Extend the passport specification**

Document the optional teacher notes and the two starting-level inputs: a preset and an optional free-form description of remembered topics, skills, and gaps.

- [ ] **Step 2: Confirm the data list matches the form**

Run:

```powershell
rg -n "преподавател|стартов|свободное описание" SCREENS.md
```

Expected: the passport description and data section both contain the new values.

### Task 2: Build the interactive wizard screen

**Files:**
- Create: `frontend/src/screens/ProjectWizard.tsx`
- Modify: `frontend/src/styles/layout.css`

**Interfaces:**
- Consumes: existing UI primitives from `frontend/src/components/ui/index.ts`.
- Produces: `ProjectWizard(): JSX.Element`, a self-contained route view holding a `WizardDraft` in React state.

- [ ] **Step 1: Define the minimum draft model and fake parsing result**

Use string unions for `Track`, `ExamFormat`, `InputMode`, `StartingLevel`, `GoalLevel`, and `StudyFormat`. Keep one `WizardDraft` state containing selections, pasted text, selected file names, subject/date/count, focus, teacher notes, starting preset/notes, goal, study format, and minutes per day.

- [ ] **Step 2: Implement the track landing**

Render the approved hero copy and three cards. The exam card advances; textbook and free-study cards stay visible with a “Скоро” treatment. Each card always shows a summary and reveals “Что понадобится / Что получится” on hover and focus.

- [ ] **Step 3: Implement steps 1–3**

Render exam format as four radio cards, optional materials as selectable cards, and role-based upload panels. File inputs may store only browser-provided file metadata; pasted text is local state. Show believable detected counts and OCR/library annotations without parsing.

- [ ] **Step 4: Implement the goal passport**

Split the form into “Об экзамене” and “О подготовке”. Include subject, date, expected count, focus, optional teacher notes, starting-level presets plus free-form knowledge description, desired outcome, study format, and daily minutes.

- [ ] **Step 5: Implement review and creation feedback**

Render the project summary, detected structure preview, role-grouped sources, a count warning, and a local/OCR/model processing plan. “Создать проект” changes the prototype to a success state with a clear next-step button; it does not call an API.

- [ ] **Step 6: Add responsive and interaction styling**

Append a single `project-wizard` section to `layout.css`: centered full-screen shell, progress rail, selection cards, upload zones, passport grid, review layout, hover/focus/active states, and mobile collapse. Use only existing tokens and explicit transitioned properties.

- [ ] **Step 7: Run static checks**

Run:

```powershell
npm run typecheck
npm run lint
npm run build
```

Expected: all three commands exit 0.

### Task 3: Wire the route and entry point

**Files:**
- Modify: `frontend/src/app/views.ts`
- Modify: `frontend/src/app/AppLayout.tsx`
- Modify: `frontend/src/screens/Projects.tsx`

**Interfaces:**
- Consumes: `ProjectWizard` and the existing `project-new` registry entry in `frontend/src/app/screens.ts`.
- Produces: reachable `/projects/new` route and a working “Новый проект” entry.

- [ ] **Step 1: Register the view**

Import `ProjectWizard` in `views.ts` and map `"project-new"` to it.

- [ ] **Step 2: Render the wizard without the application chrome**

In `AppLayout`, read `useLocation()` and return a full-screen `<Outlet />` inside `TooltipProvider` when `pathname === "/projects/new"`; retain the current shell for every other route.

- [ ] **Step 3: Enable the dashboard entry**

Replace the disabled button with a React Router link styled as `primary-button` and pointing to `/projects/new`.

- [ ] **Step 4: Restart and verify in a real browser**

Run:

```powershell
docker compose restart web
```

Open `http://localhost:5173/projects/new` and verify: all five steps, backward navigation with preserved data, file/text modes, passport variants, review, success state, keyboard focus, light/dark themes, and a narrow viewport.

- [ ] **Step 5: Inspect the final diff**

Run:

```powershell
git diff -- SCREENS.md docs/superpowers/plans/2026-07-31-exam-project-wizard.md frontend/src/screens/ProjectWizard.tsx frontend/src/styles/layout.css frontend/src/app/views.ts frontend/src/app/AppLayout.tsx frontend/src/screens/Projects.tsx
```

Expected: only the approved wizard specification and prototype changes are present.
