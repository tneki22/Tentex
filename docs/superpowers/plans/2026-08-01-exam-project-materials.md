# Exam Project Materials Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the approved stage-1 Materials screen on three interactive mock scenarios and expose it from the exam project workspace.

**Architecture:** Keep all fake domain data and screen-specific state in one `Materials.tsx` because the project has no API at stage 1. Reuse existing UI and domain widgets; extract only the resize separator already used by ProjectWorkspace because Materials is its second consumer. Put screen styling in the existing `layout.css` to follow the current project convention.

**Tech Stack:** React 19, TypeScript 5.9, React Router 8, Radix wrappers, lucide-react, token-only CSS.

## Global Constraints

- Stage 1 uses hand-written mock data and no API calls.
- Interface copy is Russian; identifiers are English.
- Colors and dimensions use existing design tokens.
- `native`, `ocr`, and `ocr_low` are rendered with `QualityBadge`.
- Machine bindings use `MachineMark` and can be undone in one action.
- Material coverage below 100% is neutral and never rendered as progress-to-100.
- Project instructions deliberately disable TDD at this stage; verify with typecheck, build, and browser interaction.

---

### Task 1: Shared panel resize handle

**Files:**
- Create: `frontend/src/components/ui/PanelResizeHandle.tsx`
- Modify: `frontend/src/components/ui/index.ts`
- Modify: `frontend/src/screens/ProjectWorkspace.tsx`

**Interfaces:**
- Produces: `PanelResizeHandle({ label, value, min, max, className?, onDelta, onReset })`.
- Consumes: existing `.workspace-resize-handle` behavior and styles.

- [ ] **Step 1: Move the existing local resize behavior into the shared component**

```tsx
<PanelResizeHandle
  label="Изменить ширину каталога"
  value={catalogWidth}
  min={240}
  max={360}
  onDelta={(delta) => setCatalogWidth((value) => clamp(value + delta, 240, 360))}
  onReset={() => setCatalogWidth(280)}
/>
```

- [ ] **Step 2: Replace both local `ResizeHandle` uses in ProjectWorkspace**

Remove its local prop interface and implementation, import `PanelResizeHandle`, and preserve pointer, keyboard, double-click, and ARIA behavior unchanged.

- [ ] **Step 3: Run the frontend typecheck**

Run: `npm run typecheck`
Expected: exit code 0.

### Task 2: Materials mock screen

**Files:**
- Create: `frontend/src/screens/Materials.tsx`

**Interfaces:**
- Produces: named export `Materials` for `SCREEN_VIEWS`.
- Consumes: `Button`, `Checkbox`, `ConfirmDialog`, `Dialog`, `IconButton`, `Menu`, `Popover`, `SegmentedTabs`, `StatusBadge`, `Tooltip`, `CostEstimate`, `MachineMark`, `OfflineNotice`, `QualityBadge`, `TaskRow`, `PanelResizeHandle`.

- [ ] **Step 1: Define the three mock materials and role-specific view models**

```ts
type MaterialKind = "answers" | "source" | "scan";
type ViewMode = "original" | "text";
type InspectorTab = "questions" | "answers" | "bindings" | "processing" | "file";

interface DemoMaterial {
  id: string;
  name: string;
  kind: MaterialKind;
  roles: string[];
  pages: number;
  quality: PageQuality;
}
```

Use only `Ответы по базам данных.pdf`, `Методические указания.pdf`, and `Фото страницы 47.jpg`.

- [ ] **Step 2: Build the left catalog**

Add project back navigation, add dialog, filters, role groups, active row, row menu, remove-with-consequences dialog, and project navigation. File selection changes the document and selects the correct default inspector tab.

- [ ] **Step 3: Build the document toolbar and canvas**

Implement original/text mode, page navigation, zoom, fit width, search, markers toggle, inspector toggle, continuous mock pages, searchable highlighted text, selectable bound fragments, and the separate marker rail.

- [ ] **Step 4: Build the role-specific inspector tabs**

Implement question import summary; answer tree with confirm, change, and manual-answer dialog; binding summary with cost confirmation, confirm/remove/undo, and selected-fragment actions; processing with `TaskRow`, OCR actions and offline notice; file metadata and roles.

- [ ] **Step 5: Make screen state demonstrable**

The answer file opens on «Ответы», the methodical source opens on «Привязки» with visible markers, and the image opens on «Обработка» with `ocr_low`. Buttons change local mock state or open an explanatory dialog; no primary control is a dead hover-only affordance.

### Task 3: Route, navigation, and styles

**Files:**
- Modify: `frontend/src/app/views.ts`
- Modify: `frontend/src/screens/ProjectWorkspace.tsx`
- Modify: `frontend/src/styles/layout.css`

**Interfaces:**
- Consumes: route metadata already present as `materials` in `screens.ts`.
- Produces: working `/projects/demo/materials` navigation.

- [ ] **Step 1: Register the screen**

```ts
import { Materials } from "../screens/Materials";

export const SCREEN_VIEWS = {
  // existing entries
  materials: Materials,
};
```

- [ ] **Step 2: Enable the Materials link in ProjectWorkspace**

Render the Materials row as a `Link` to `/projects/${projectId}/materials`; keep unfinished project sections disabled.

- [ ] **Step 3: Add token-only screen styles**

Create the three-column desktop grid, compact toolbar, paper pages, fragment states, marker rail, inspector tabs, responsive collapse behavior, visible focus states, and reduced-motion-safe transitions. Do not add another stylesheet or dependency.

- [ ] **Step 4: Run static verification**

Run: `npm run typecheck`
Expected: exit code 0.

Run: `npm run build`
Expected: exit code 0.

### Task 4: Browser verification

**Files:**
- Verify: `frontend/src/screens/Materials.tsx`
- Verify: `frontend/src/styles/layout.css`

**Interfaces:**
- Consumes: `http://localhost:5173/projects/demo/materials`.
- Produces: a visually checked stage-1 screen.

- [ ] **Step 1: Restart the web container after frontend changes**

Run: `docker compose restart web`
Expected: `web` restarts successfully.

- [ ] **Step 2: Verify the answer-file scenario**

Open the route, select the answer PDF, switch original/text, navigate pages, search, select an answer, confirm it, and open the manual-answer dialog.

- [ ] **Step 3: Verify the source scenario**

Select the methodical PDF, click marker-rail entries, select a highlighted fragment, confirm and remove a machine binding, undo it, and open the cost dialog.

- [ ] **Step 4: Verify the OCR scenario and responsive behavior**

Select the image, use processing actions, collapse both side panels, check keyboard focus, and inspect the layout at desktop and narrow widths.

- [ ] **Step 5: Re-run checks after browser fixes**

Run: `npm run typecheck && npm run build`
Expected: both commands exit 0.
