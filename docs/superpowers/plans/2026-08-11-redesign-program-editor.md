# Program Editor Redesign Implementation Plan

> **For agentic workers:** Execute this plan inline and keep the existing dirty worktree intact. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make manual program creation fully usable on textbook wizard step 4 and make hierarchical editing faster on the project Program screen.

**Status:** Implemented and verified on 2026-08-11.

**Architecture:** Keep the existing program CRUD API and revision/conflict/undo flow. Restore the stage-1 editor hierarchy, remove the overflowing creation controls, and expose the same node operations through visible controls plus the existing Radix-based `ContextMenu` primitive.

**Tech Stack:** React, TypeScript, Radix UI, existing Tentex UI primitives, CSS tokens, FastAPI program contracts, Playwright CLI.

## Global Constraints

- Preserve `program_revision`, conflict reload, undo, soft removal/restoration, drag-and-drop and draft persistence.
- Program depth remains limited to four levels by the current API.
- Do not add dependencies or implement stage-7 assistant/generation features.
- Use Russian interface copy, existing tokens and existing UI primitives.
- Preserve unrelated user changes in the dirty worktree.

---

### Task 1: Textbook wizard step 4

**Files:**
- Modify: `frontend/src/screens/TextbookWizard.tsx`
- Modify: `frontend/src/styles/layout.css`

**Interfaces:**
- Consumes: `WizardDraftController.enqueueProgramCommand`, `createProgramNode`, `updateProgramNode`, `moveProgramNode`, `removeProgramNode`, `ContextMenu`.
- Produces: an editor where the first root, children and siblings can be created and then renamed, retyped, moved, duplicated or removed.

- [x] Remove the redundant step-4 `PageHead` so the full-window editor uses the visual hierarchy from `ui-stage-1-baseline`.
- [x] Replace the clipped type/parent selects with visible frequent actions: add root section, add child and add sibling.
- [x] Add an actionable empty state with `Добавить первый раздел` and `Добавить тему без раздела`.
- [x] Make every row selectable by keyboard and expose rename, type change, move, indent/outdent, duplicate and remove.
- [x] Wrap rows in the existing `ContextMenu` so right click and the keyboard context-menu key expose the same operations.
- [x] Reflow the toolbar at wide and narrow widths without placing controls behind the assistant.

### Task 2: Active Program screen hierarchy editing

**Files:**
- Modify: `frontend/src/screens/Program.tsx`
- Modify: `frontend/src/styles/layout.css`

**Interfaces:**
- Consumes: current `runCommand`, `siblingInfo`, `move`, `indent`, `outdent`, `duplicate`, `changeKind`, `ContextMenu`.
- Produces: placement presets `{ parentId, position, label }` used by the existing add dialog.

- [x] Replace the numeric global-position field with a readable location selector for top-level adds.
- [x] Allow context actions to open the add dialog preset to `inside`, `before` or `after` the clicked node.
- [x] Add the complete node menu: add inside/before/after, rename, duplicate, type, move up/down, indent/outdent, open in workspace and remove.
- [x] Keep visible move buttons and the inspector so right click is an accelerator, not the only path.
- [x] Add a short discovery hint for right click / `Shift+F10`.

### Task 3: Contract and verification

**Files:**
- Modify: `SCREENS.md`
- Modify: this plan

- [x] Record the explicit empty-state actions and context-menu behavior in the Program and textbook-wizard screen contracts.
- [x] Restart `web`, then use Playwright at 1536×1189 to prove the add button is inside the program panel and receives pointer hit-testing.
- [x] In the wizard create a section, child topic and nested subpoint; rename, retype, move, duplicate, remove and undo; continue to step 5 and verify truthful counts.
- [x] In an active textbook project use right click and `Shift+F10` to add inside/before/after and verify the inspector, removal and restoration still work.
- [x] Run `npm run typecheck`, `npm run build`, `npm run lint`, backend Ruff and the existing stage checks affected by program CRUD.

## Self-review

- Spec coverage: first-node creation, hierarchy CRUD, project-screen context menu, existing functions and API contracts are all assigned.
- Scope: no unrelated TODO item or stage-7 feature is included.
- Type consistency: both editors continue sending the existing `ProgramNodeCreate`, `ProgramMove` and `ProgramNodeUpdate` shapes.
