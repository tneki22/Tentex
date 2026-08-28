# Exam Wizard Separate Inputs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Объединить пользовательские треки вопросов и задач, дать каждому списку и его ответам отдельный материал, поддержать подпункты `N.M` и исключить перекрёстную автопривязку.

**Architecture:** Широкие назначения материала остаются прежними, а на связи `ProjectMaterial` появляется узкий `exam_slot`. Составной импорт читает до двух структурных материалов и атомарно строит одно дерево «вопросы → задачи»; автопривязка фильтрует дерево по слоту файла ответов. Мастер хранит независимое состояние четырёх экзаменационных входов и использует один переиспользуемый загрузочный компонент.

**Tech Stack:** FastAPI, SQLAlchemy 2, Alembic, SQLite, Pydantic, pytest, React, TypeScript, Vite, Radix `Disclosure`, обычный CSS на токенах.

## Global Constraints

- Интерфейсные тексты — по-русски, идентификаторы — по-английски.
- Существующие `ExamFormat.QUESTIONS` и `ExamFormat.QUESTIONS_TASKS` и материалы без слота остаются совместимыми.
- Один активный материал на каждый из слотов `question_list`, `question_answers`, `task_list`, `task_answers`.
- Поддерживается только один уровень подпунктов с маркером `N.M`, `N.M.` или `N.M)`.
- В Программе вопросы и их подпункты всегда предшествуют задачам и их подпунктам.
- Цвета, размеры и отступы берутся только из `frontend/src/styles/tokens.css`.
- TDD не является проектным требованием; тесты добавляются для хрупкой логики разбора, порядка и автопривязки.

---

### Task 1: Экзаменационные слоты материалов

**Files:**
- Modify: `backend/app/models.py`
- Modify: `backend/app/materials/schemas.py`
- Modify: `backend/app/materials/service.py`
- Modify: `backend/app/materials/library.py`
- Modify: `backend/app/materials/router.py`
- Create: `backend/migrations/versions/20260828_0025_exam_material_slots.py`
- Modify: `frontend/src/api/materials.ts`
- Modify: `frontend/src/hooks/useProjectMaterials.ts`
- Test: `backend/tests/test_materials_api.py`

**Interfaces:**
- Produces: `ExamMaterialSlot(StrEnum)` with `QUESTION_LIST`, `QUESTION_ANSWERS`, `TASK_LIST`, `TASK_ANSWERS`.
- Produces: nullable `ProjectMaterial.exam_slot: str | None` and `MaterialRead.exam_slot: ExamMaterialSlot | None`.
- Produces: `exam_slot` support in upload, text creation, update and Library attachment commands.
- Produces: `MaterialRead.exam_slot` and `ExamMaterialSlot` in the frontend API.

- [x] **Step 1: Add the model and migration**

Add the enum and nullable indexed column:

```python
class ExamMaterialSlot(StrEnum):
    QUESTION_LIST = "question_list"
    QUESTION_ANSWERS = "question_answers"
    TASK_LIST = "task_list"
    TASK_ANSWERS = "task_answers"

exam_slot: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
```

Migration `20260828_0025` uses the current Alembic head as `down_revision`, adds the
column and a non-unique index, and leaves existing rows `NULL`.

- [x] **Step 2: Carry the slot through API schemas and reads**

Add `exam_slot: ExamMaterialSlot | None = None` to `TextMaterialCreate`, external/create
inputs that attach to a project, `MaterialUpdate`, Library attach input and `MaterialRead`.
Pass it through `_attach()`, `update_material()`, Library attachment and `_read()`.

- [x] **Step 3: Enforce slot invariants**

Add a shared guard with this contract:

```python
def guard_exam_slot(
    session: Session,
    project_id: UUID,
    exam_slot: ExamMaterialSlot | None,
    material_id: UUID | None,
) -> None:
    """Reject a second material in the same non-null exam slot."""
```

Question/task list slots require `exam_structure`; answer slots require
`reference_answers`. Replace the old project-wide single-answer guard with one answer
per explicit slot while preserving the legacy rule for `exam_slot is None`.

- [x] **Step 4: Update frontend material calls**

Extend `MaterialRead`, `uploadMaterial`, `createTextMaterial`, `updateMaterial` and
Library attachment calls with optional `exam_slot`. Extend the material hook mutation
arguments without changing callers that omit the field.

- [x] **Step 5: Test and verify the slot contract**

Add API tests for round-trip serialization, two different answer slots, rejection of a
duplicate slot, purpose/slot mismatch and an unchanged legacy answer file. Run:

```powershell
cd backend
python -m pytest tests/test_materials_api.py -q
python -m ruff check app/models.py app/materials tests/test_materials_api.py migrations/versions/20260828_0025_exam_material_slots.py
```

- [x] **Step 6: Commit Task 1**

```powershell
git add backend/app/models.py backend/app/materials backend/migrations/versions/20260828_0025_exam_material_slots.py backend/tests/test_materials_api.py frontend/src/api/materials.ts frontend/src/hooks/useProjectMaterials.ts
git commit -m "feat: add exam material slots"
```

### Task 2: Составной импорт и подпункты

**Files:**
- Modify: `backend/app/projects/importer.py`
- Modify: `backend/app/projects/schemas.py`
- Modify: `backend/app/materials/schemas.py`
- Modify: `backend/app/materials/service.py`
- Modify: `backend/app/materials/router.py`
- Modify: `frontend/src/api/materials.ts`
- Test: `backend/tests/test_exam_importer.py`
- Test: `backend/tests/test_numbered_series.py`
- Test: `backend/tests/test_materials_api.py`

**Interfaces:**
- Produces: `parse_exam_list(raw_text, default_kind, expected_item_count=None)` used by the composite service.
- Produces: `ExamCompositeDraftImportWrite` with revisions, optional question/task material ids and `dedupe_duplicates`.
- Produces: `ExamProgramPreview.subpoints` and `ExamImportCounts.subpoints`.
- Consumes: `ProjectMaterial.exam_slot` from Task 1.

- [x] **Step 1: Parse deterministic subpoints**

Add a strict marker:

```python
SUBPOINT_RE = re.compile(
    r"^\s*(?P<parent>\d{1,4})\.(?P<child>\d{1,3})(?:[.)])?\s+(?P<text>\S.*?)\s*$"
)
```

When a marker follows its matching top-level number, create `ParsedNode` with
`node_type=SUBPOINT`, `parent_index` pointing to the parent and the parent's
`exam_kind`. Reject deeper decimal forms as continuation text and emit a warning for a
parent mismatch. Keep top-level question/task counts separate from `subpoints`.

- [x] **Step 2: Extract a list parser with explicit default kind**

Introduce:

```python
def parse_exam_list(
    raw_text: str,
    default_kind: ExamKind,
    *,
    expected_item_count: int | None = None,
) -> ParsedExamProgram:
    ...
```

`parse_exam_program()` delegates flat legacy formats to it. `QUESTIONS_TASKS` legacy
input still honours `Вопросы` and `Задачи` section headers.

- [x] **Step 3: Add atomic composite material import**

Add request shape:

```python
class ExamCompositeDraftImportWrite(ApiModel):
    expected_draft_revision: int = Field(ge=0)
    expected_program_revision: int = Field(ge=0)
    question_material_id: UUID | None = None
    task_material_id: UUID | None = None
    dedupe_duplicates: bool = False
```

The service validates at least one id and its slot/purpose/readiness, reads active page
text, parses questions with `ExamKind.QUESTION` and tasks with `ExamKind.TASK`, rebases
task parent indexes after question nodes, merges warnings/duplicates and calls the
existing draft-program replacement once. Expose it as
`POST /projects/{project_id}/materials/exam-composite-draft-import`.

- [x] **Step 4: Update API counts and frontend call**

Add `subpoints` to preview/import counts with default `0` for compatibility. Add
`importCompositeExamDraftProgram(projectId, command)` to `frontend/src/api/materials.ts`.

- [x] **Step 5: Test parsing and composite order**

Cover `1.1`, `1.2`, `N.M)`, parent mismatch, one-level limit, top-level counts,
question-only, task-only, both materials, duplicate handling and the single revision
increment. Run:

```powershell
cd backend
python -m pytest tests/test_exam_importer.py tests/test_numbered_series.py tests/test_materials_api.py -q
python -m ruff check app/projects/importer.py app/materials tests/test_exam_importer.py tests/test_numbered_series.py tests/test_materials_api.py
```

- [x] **Step 6: Commit Task 2**

```powershell
git add backend/app/projects/importer.py backend/app/projects/schemas.py backend/app/materials backend/tests/test_exam_importer.py backend/tests/test_numbered_series.py backend/tests/test_materials_api.py frontend/src/api/materials.ts
git commit -m "feat: import separate question and task lists"
```

### Task 3: Раздельная автопривязка ответов

**Files:**
- Modify: `backend/app/bindings/answers_link.py`
- Modify: `backend/app/materials/worker.py`
- Test: `backend/tests/test_answers_link.py`

**Interfaces:**
- Consumes: `ProjectMaterial.exam_slot` and `ExamMaterialSlot` from Task 1.
- Produces: `_ordered_study_nodes(session, project_id, exam_kind=None)`.
- Preserves: legacy answer materials without a slot see the full depth-first tree.

- [x] **Step 1: Scope answer nodes by slot**

Change the ordered-node helper to accept `ExamKind | None`. In
`link_answers_material()`, map `question_answers → QUESTION`,
`task_answers → TASK`, and `None → no filter`. Keep parent-before-subpoint depth-first
order inside each filtered set.

- [x] **Step 2: Keep replacement and worker behaviour slot-aware**

Ensure parsing each ready answer material links only its scoped nodes. Reprocessing one
answer material removes and recreates only bindings sourced from that material; answers
from the other slot remain intact.

- [x] **Step 3: Test independent numbering and subpoint headings**

Create a project with question #1, its subpoint, task #1 and its subpoint. Verify that
two answer files both numbered from one link to their own kind, exact subpoint headings
create subpoint answers, and a legacy unslotted file still sees all nodes.

Run:

```powershell
cd backend
python -m pytest tests/test_answers_link.py -q
python -m ruff check app/bindings/answers_link.py app/materials/worker.py tests/test_answers_link.py
```

- [x] **Step 4: Commit Task 3**

```powershell
git add backend/app/bindings/answers_link.py backend/app/materials/worker.py backend/tests/test_answers_link.py
git commit -m "feat: scope answer linking by exam slot"
```

### Task 4: Объединённый мастер и инструкция перед файлами

**Files:**
- Modify: `frontend/src/screens/project-wizard/ExamWizard.tsx`
- Modify: `frontend/src/screens/project-wizard/ExamMaterialUploadPanel.tsx`
- Create: `frontend/src/screens/project-wizard/ExamImportGuide.tsx`
- Modify: `frontend/src/hooks/useWizardDraft.ts`
- Modify: `frontend/src/api/projects.ts`
- Modify: `frontend/src/styles/layout.css`

**Interfaces:**
- Consumes: material `exam_slot` and composite import from Tasks 1–2.
- Produces: `ExamImportGuide`, a default-open existing `Disclosure` with static copy.
- Preserves: tickets and unknown-list paths; legacy drafts remain finishable.

- [x] **Step 1: Split wizard form state into four inputs**

Replace `rawText`, `answersText`, `hasAnswers`, `primaryMode`, `answersMode` with slot
records for `question_list`, `question_answers`, `task_list`, `task_answers`. Restore new
keys when present and map legacy keys to a legacy path. Derive `ExamFormat` as
`questions_tasks` when the task list is selected, otherwise `questions`.

- [x] **Step 2: Replace the format and material cards**

Offer only three format cards. The combined card uses the exact requested title and
description. On step 2 render the five-card grid from the specification, require one
list, disable dependent answer cards until their list is selected, and use concise
inline recovery text.

- [x] **Step 3: Add the guide before upload panels**

Create `ExamImportGuide.tsx` using the existing `Disclosure`. Render it immediately
after the step-3 intro and before the first `ExamMaterialUploadPanel`. Use the full copy
and example from the design document, with `defaultOpen`/local state so it starts open.

- [x] **Step 4: Render and upload slot panels in fixed order**

Give `ExamMaterialUploadPanel` an `examSlot` prop and pass it into file/text creation.
Render selected panels in order: questions, question answers, tasks, task answers,
study materials. After required materials are ready, call composite import, show counts
including subpoints, and preserve duplicate resolution behaviour.

- [x] **Step 5: Polish spacing without inventing tokens**

Make step-2 cards content-height, keep the study card wide, and set exactly one existing
spacing token between `.wizard-material-grid` and `.wizard-context-note`. Style the
guide as a structural surface using existing paper/line/accent tokens. Check focus,
hover, open and closed states and the existing 900px breakpoint.

- [x] **Step 6: Verify frontend compile**

Run:

```powershell
npm run typecheck
npm run build
```

- [x] **Step 7: Commit Task 4**

```powershell
git add frontend/src/screens/project-wizard frontend/src/hooks/useWizardDraft.ts frontend/src/api frontend/src/styles/layout.css
git commit -m "feat: unify question and task wizard inputs"
```

### Task 5: Контракты, полная проверка и браузер

**Files:**
- Modify: `SCREENS.md`
- Modify: `docs/architecture/exam-wizard-material-onboarding.md`
- Modify: `docs/superpowers/specs/2026-08-28-exam-wizard-separate-inputs-design.md`
- Modify: `docs/superpowers/plans/2026-08-28-exam-wizard-separate-inputs.md`

**Interfaces:**
- Documents: final file format, slots, subpoints, ordering, UI states and compatibility.

- [x] **Step 1: Update documentation to factual behaviour**

Replace the old four-card and single-answer descriptions in `SCREENS.md`; document the
new material slot/API contract in the architecture file. Mark this design `implemented`
and check completed plan boxes only after the corresponding evidence exists.

- [x] **Step 2: Run full backend verification**

```powershell
cd backend
python -m ruff check .
python -m pytest
python scripts/check_stage3.py
python scripts/check_stage4.py
python scripts/check_stage5.py
```

Expected: every command exits `0`; pytest reports no failures.

- [x] **Step 3: Run full frontend verification**

```powershell
cd ..
npm run typecheck
npm run build
npm run lint
```

Expected: every command exits `0`.

- [x] **Step 4: Restart and inspect the live wizard**

```powershell
docker compose restart api web
```

Open `http://localhost:5173`, create an exam draft and verify steps 1–3 at desktop and
narrow desktop widths, guide open/closed and keyboard focus, independent selection of
lists and answers, spacing before the system opinion, light/dark themes, and the upload
order. Save screenshots under `output/playwright/`.

**Deviation:** this worktree has no `docker-compose.yml`/`data/` (both are
gitignored and only exist in the main checkout, not copied into `.worktrees/`).
Ran `backend` (uvicorn on a scratch port) and `frontend` (`vite` dev server)
directly instead, against a freshly migrated database. Verified live: format
step shows three cards; materials step renders the five-slot grid, requires at
least one list before continuing, and disables the dependent answer card with
an explanatory reason until its list is picked; upload step shows the
guide open by default, collapsible via click (state toggle confirmed both
directions), panels in the fixed slot order; composite import of a pasted
question list (with a `1.1`/`1.2` subpoint) and task list produced one Program
with questions before tasks, the subpoint under the right parent, and
`3 вопроса · 2 задачи · 2 подпункта`; after activating the project, a question-
answers file and a task-answers file — both with identical per-node headings —
auto-linked strictly to their own kind, verified against
`ReferenceAnswer.source_material_id` directly in the database (no cross-slot
bleed). Supplementary pass at 768×1024 with dark color-scheme emulation: no
horizontal overflow, dark tokens applied, disabled-card background distinct
from enabled. No screenshots saved (this session's browser pane could not
render `computer` screenshots), so `output/playwright/` was not populated.

- [ ] **Step 5: Review the final diff and commit documentation**

```powershell
git diff --check
git status --short
git add SCREENS.md docs/architecture/exam-wizard-material-onboarding.md docs/superpowers
git commit -m "docs: document separate exam inputs"
git status --short --branch
```

Expected: clean worktree on `codex/merge-exam-inputs`.
