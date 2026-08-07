# Exam Project Workspace Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the approved fake-data prototype of the exam project workspace at `/projects/:projectId` without implementing the linked project sections.

**Architecture:** Render the workspace as its own full-window shell because its question tree replaces the global Tentex navigation. Keep fake project data, workspace state, tabs, notes, and the minimal accessible resize behavior inside one screen component; keep visual rules in the existing screen stylesheet and use existing Radix-backed primitives for menus, popovers, and tooltips.

**Tech Stack:** React 19, TypeScript, React Router, Lucide icons, Tentex UI kit, CSS Grid, pointer events, localStorage.

## Global Constraints

- Russian interface copy and English identifiers.
- Implement only the workspace; Materials, Program, Plan, Cards, and Settings remain explicit disabled placeholders.
- Default state is an «Ответ» tab in the left editor group and an empty right group with open-or-close guidance.
- Project navigation lives below the question tree; there is no separate activity rail.
- No new dependency, backend request, or copied Virtex workspace abstraction.
- All visual values use tokens from `frontend/src/styles/tokens.css`.
- Reuse existing UI primitives where their behavior fits.
- The repository has no frontend test harness at stage 1; verify with typecheck, lint, build, container restart, and a browser walkthrough.

---

### Task 1: Align the screen contract and registry

**Files:**
- Modify: `SCREENS.md`
- Modify: `frontend/src/app/screens.ts`

**Interfaces:**
- Consumes: `docs/superpowers/specs/2026-08-01-exam-project-workspace-design.md`.
- Produces: screen metadata with id `workspace`, path `/projects/:projectId`, and the five required screen-contract sections.

- [x] **Step 1: Record the workspace and future screen sketches**

Add the approved blocks, actions, states, data, and transitions to `SCREENS.md`. Keep future Materials, Program, Plan, Cards, and Settings descriptions as functional sketches, not implemented layouts.

- [x] **Step 2: Rename the root project route in the registry**

Replace the old `coverage-map` metadata with:

```ts
{
  id: "workspace",
  path: "/projects/:projectId",
  navPath: `/projects/${DEMO_PROJECT_ID}`,
  title: "Рабочая область",
  summary: "Дерево вопросов и изменяемые панели ответа, материалов, конспекта и чата.",
  group: "Проект",
  icon: PanelsTopLeft,
  depth: "полностью",
}
```

- [x] **Step 3: Check documentation and metadata**

Run `rg -n "Рабочая область проекта|Эскизы следующих|id: \"workspace\"" SCREENS.md frontend/src/app/screens.ts`.

Expected: one detailed workspace section, one future-section sketch block, and one root workspace registry item.

### Task 2: Build the interactive workspace prototype

**Files:**
- Create: `frontend/src/screens/ProjectWorkspace.tsx`

**Interfaces:**
- Consumes: `Button`, `Checkbox`, `IconButton`, `Menu`, `Popover`, `StatusBadge`, `Tooltip`, and `TopicStatusBadge` from the existing kit.
- Produces: `ProjectWorkspace()` and screen-local types `DemoQuestion`, `WorkspaceTab`, `EditorGroup`, and `StoredWorkspaceState`.

- [x] **Step 1: Define believable exam data**

Create two sections and at least eight questions. Each question contains `id`, `number`, `title`, `status`, `hasMaterial`, `hasNote`, `answer`, `source`, and `conspect`. Include one missing answer and one active note so neutral and marked states are visible.

- [x] **Step 2: Restore the minimal local workspace state**

Read one project-scoped localStorage value containing:

```ts
interface StoredWorkspaceState {
  selectedQuestionId: string;
  treeWidth: number;
  groupWeights: number[];
  groups: EditorGroup[];
  expandedSectionIds: string[];
  notes: Record<string, string>;
  conspects: Record<string, string>;
}
```

Validate numeric ranges and group counts before using stored values; otherwise use the approved two-group default.

- [x] **Step 3: Render the tree and project navigation**

Render the projects exit before «Дерево вопросов», project context, search, filter popover, collapsible sections, active-question state, note/material signals, and disabled future-section buttons anchored to the bottom.

- [x] **Step 4: Render the selected-question toolbar**

Show the section breadcrumb, number, question text, topic status, «Открыть», split, note popover, disabled «Проверить себя», and rare actions.

- [x] **Step 5: Render editor groups and tabs**

Support answer, source, conspect, chat, and empty content. Start with:

```ts
[
  { id: "primary", tabs: ["answer"], activeTab: "answer" },
  { id: "secondary", tabs: [], activeTab: null },
]
```

Opening content activates a tab in the active group. Splitting adds an empty group up to three. Closing the final tab leaves an empty group; an empty group can be removed while at least one remains.

- [x] **Step 6: Add screen-local accessible resizing**

Use CSS Grid fractional columns for editor groups and pixels for the tree. Pointer movement changes adjacent group weights; ArrowLeft and ArrowRight move a separator; Home, End, and double click restore safe limits or defaults. Do not import the Virtex layout hook.

- [x] **Step 7: Save interactive fake state**

Persist selected question, expanded sections, group tabs, widths, note text, and per-question conspect. Search remains ephemeral.

### Task 3: Style the full-window workspace

**Files:**
- Modify: `frontend/src/styles/layout.css`

**Interfaces:**
- Consumes: the `project-workspace`, `workspace-tree-*`, `workspace-editor-*`, `workspace-panel-*`, and `workspace-note-*` classes.
- Produces: a viewport-height IDE-like layout using only existing tokens.

- [x] **Step 1: Add shell and tree styles**

Append a full-height grid, paper sidebar, quiet header, scrollable tree, active row, and bottom navigation separated by a line.

- [x] **Step 2: Add toolbar, tabs, and content styles**

Style a compact toolbar, tab bars, readable answer/source text, borderless full-height conspect editor, neutral empty panel, and quiet unavailable chat state.

- [x] **Step 3: Add resize and responsive states**

Give separators a large hit target, focus treatment, col-resize cursor, and reduced-motion compatibility. Below 900px, hide inactive editor groups instead of pretending to be a mobile application.

### Task 4: Wire routing and existing transitions

**Files:**
- Modify: `frontend/src/app/views.ts`
- Modify: `frontend/src/app/AppLayout.tsx`
- Modify: `frontend/src/screens/Projects.tsx`
- Modify: `frontend/src/screens/ProjectWizard.tsx`

**Interfaces:**
- Consumes: `ProjectWorkspace`, registry id `workspace`, and `DEMO_PROJECT_ID`.
- Produces: a reachable workspace from the dashboard and wizard success state.

- [x] **Step 1: Register the view**

Import `ProjectWorkspace` and add `workspace: ProjectWorkspace` to `SCREEN_VIEWS`.

- [x] **Step 2: Give the workspace its own shell**

In `AppLayout`, keep the wizard exception and match only project-root URLs:

```ts
const isProjectWorkspace = /^\/projects\/[^/]+\/?$/.test(location.pathname);
```

For that route return `<Outlet />` inside `TooltipProvider`; retain the global shell elsewhere.

- [x] **Step 3: Connect project cards and wizard success**

Link «Продолжить изучение» to `/projects/${project.id}`. Change the wizard primary success action to «Открыть проект» at `/projects/${DEMO_PROJECT_ID}`. Leave repetition outside scope.

### Task 5: Verify the prototype

**Files:**
- Inspect: all files listed above.

**Interfaces:**
- Consumes: the completed workspace route.
- Produces: fresh static and browser evidence.

- [x] **Step 1: Run static checks**

Run `npm run typecheck`, `npm run lint`, and `npm run build` from the repository root.

Expected: all three commands exit 0.

- [x] **Step 2: Restart the frontend container**

Run `docker compose restart web`.

Expected: the `web` service restarts successfully.

- [x] **Step 3: Walk through the screen**

Open `http://localhost:5173/projects/db-exam` and verify selection, expansion, search, filters, changing answers, empty-right guidance, opening content, splitting to three groups, closing tabs and groups, resizing, notes, conspect persistence, placeholders, exit, keyboard focus, and a narrow viewport.

- [x] **Step 4: Inspect scoped changes**

Run `git diff --check` and a path-limited `git diff` over the files in this plan.

Expected: no whitespace errors and no implementation of future project sections.
