# Reference Answer Consistency and Import Feedback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make answer-file matching produce an active, readable reference answer for every question it reports as covered, and show an honest running state plus a structured result on both entry surfaces.

**Architecture:** Keep bindings and reference answers as different domain objects, but make their relationship explicit. `bindings/answers_link.py` remains responsible for detecting sections and binding fragments; a new project-domain lifecycle module becomes the only place that decides whether an imported answer is created, updated, restored, left unchanged, or preserved. The API reports heading matches and available reference answers separately, and both frontend surfaces consume one shared run-state/report component.

**Tech Stack:** FastAPI, SQLAlchemy, SQLite, Pydantic, React, TypeScript, Radix primitives, ordinary CSS with Tentex tokens.

## Global Constraints

- Work in a dedicated worktree and branch based on `codex/fix-workspace-zones`; do not touch the conflicted root worktree.
- Before implementation, integrate the current exam-material-slot work because it already changes `backend/app/bindings/answers_link.py` and `backend/tests/test_answers_link.py`.
- Russian interface copy; English identifiers.
- Router stays thin; business rules stay in services. Use `ProjectDomainError`, not `HTTPException`.
- Preserve active manual answers and active confirmed imports. An inactive row is a tombstone, not an answer, and an explicit answer-file match may replace and reactivate it.
- Preserve question-level manual attachments when a tombstone is reactivated; they are user assets, not imported file fragments.
- Do not add a database migration unless implementation discovers a schema change is genuinely necessary. The confirmed defect is lifecycle policy, not missing columns.
- Do not auto-repair every inactive answer in a migration: some were intentionally removed. Repair through the explicit matching command using the same lifecycle policy as future runs.
- Do not fake a percentage. The current synchronous operation has no observable per-section checkpoints, so show an indeterminate running state with precise copy; the completed report contains exact counts.
- Coverage below 100% is not colored as a defect (FR-D17). Use warning/error tone only for a failed operation or a contradiction that requires attention.

---

## Confirmed Root Cause

The working database contains 42 current study nodes in `ТВИМС-Тест — экзамен`. All 42 have active `answers_file` bindings, but only 40 have active `ReferenceAnswer` rows. Questions 10 and 12 have inactive, confirmed, manual rows (`is_active = false`, no `source_material_id`).

`_fill_answers()` currently protects a row when `not ours or answer.is_confirmed or same_import`. It does not first distinguish an active answer from an inactive tombstone. Therefore the two inactive manual rows are counted as `kept_answers`, never reactivated, while `linked_node_ids` is calculated only from detected sections. The UI renders `42 из 42` from `linked_node_ids`, but the answer slot correctly computes `missing` from `is_active = false`.

This also explains the apparent contradiction in the editor: `answerScanGroups()` includes pages from active bindings even when the reference answer is missing. Those pages are evidence/source material, not by themselves an active reference answer.

## Target Invariants

1. `ReferenceAnswerStatus.MISSING` means there is no active reference answer, regardless of whether a tombstone row or source bindings exist.
2. A matched section and an available reference answer are reported as separate facts.
3. After an explicit answer-file match, every detected section with answer content ends in exactly one recorded disposition: `created`, `updated`, `restored`, `unchanged`, or `preserved`.
4. Inactive rows are eligible for `restored`; active manual answers and active confirmed imports are `preserved`.
5. A run is shown as fully successful only when every expected study node has an active reference answer and there are no unresolved/ambiguous sections.
6. Source pages may remain visible without an active answer, but the UI must call them linked pages and explicitly say that the reference answer is not yet created.

---

### Task 1: Lock the lifecycle regression with focused backend tests

**Files:**
- Modify: `backend/tests/test_answers_link.py`
- Modify: `backend/tests/test_answer_sections.py`

**Interfaces:**
- Consumes: existing `link_answers_material(session, project_id, material_id)` and `get_reference_answer(...)`.
- Produces: regression expectations for tombstone restoration and result accounting.

- [ ] **Step 1: Add a failing regression for the exact database state**

Create an answer-file material for one node, insert an inactive confirmed manual `ReferenceAnswer`, run matching, and assert that the row becomes an active import from that material:

```python
def test_relink_restores_inactive_manual_tombstone(session: Session) -> None:
    project, nodes = _program(session, 1)
    material = _answers_material(
        session,
        project,
        [(nodes[0].title, [("Imported body", "paragraph", None)])],
    )
    session.add(
        ReferenceAnswer(
            project_id=project.id,
            program_node_id=nodes[0].id,
            text="Old manual text",
            origin_kind=ReferenceAnswerOrigin.MANUAL,
            match_method=ReferenceAnswerMatchMethod.MANUAL,
            is_confirmed=True,
            is_active=False,
            revision=3,
        )
    )
    session.commit()

    result = link_answers_material(session, project.id, material.id)
    answer = session.get(ReferenceAnswer, (project.id, nodes[0].id))

    assert answer is not None
    assert answer.is_active is True
    assert answer.text == "Imported body"
    assert answer.origin_kind == ReferenceAnswerOrigin.IMPORT
    assert answer.source_material_id == material.id
    assert answer.revision == 4
    assert result.restored_answers == 1
    assert result.available_node_ids == [nodes[0].id]
    assert result.unavailable_node_ids == []
```

- [ ] **Step 2: Add the preservation counterexample**

Create the same manual row with `is_active=True`; assert its text/provenance/revision remain unchanged and the result records `preserved_answers == 1` while still counting the node as available.

- [ ] **Step 3: Add an accounting test for a match that does not produce an answer**

Use a detected heading with no bindable body fragments. Assert the node may be in `matched_node_ids`, is not in `available_node_ids`, is in `unavailable_node_ids`, and prevents `complete=True` in the response projection.

- [ ] **Step 4: Preserve image-only behavior**

Extend `test_image_only_answer_creates_empty_text_reference` to assert the node is available and the slot has `source_only=True`; empty text from an image section is a valid active reference answer, not an unavailable outcome.

- [ ] **Step 5: Run the focused tests and capture the expected failures**

Run:

```bash
cd backend
python -m pytest tests/test_answers_link.py tests/test_answer_sections.py -q
```

Expected before implementation: the tombstone remains inactive and the new result fields do not exist.

- [ ] **Step 6: Commit the regression tests**

```bash
git add backend/tests/test_answers_link.py backend/tests/test_answer_sections.py
git commit -m "test(answers): cover inactive slots during file matching"
```

---

### Task 2: Centralize reference-answer lifecycle policy

**Files:**
- Create: `backend/app/projects/answer_lifecycle.py`
- Modify: `backend/app/projects/answers.py`
- Modify: `backend/app/bindings/answers_link.py`

**Interfaces:**
- Produces: `ImportedAnswerCandidate`, `AnswerImportAction`, `AnswerImportOutcome`, `apply_imported_answer(session, candidate)`.
- Consumes: `ReferenceAnswer`, `ReferenceAnswerOrigin`, `ReferenceAnswerMatchMethod`, and `utc_now()`.

- [ ] **Step 1: Define one explicit imported-answer command and outcome**

```python
class AnswerImportAction(StrEnum):
    CREATED = "created"
    UPDATED = "updated"
    RESTORED = "restored"
    UNCHANGED = "unchanged"
    PRESERVED = "preserved"


@dataclass(frozen=True, slots=True)
class ImportedAnswerCandidate:
    project_id: UUID
    node_id: UUID
    text: str
    match_method: ReferenceAnswerMatchMethod
    matched_title: str
    source_label: str
    source_material_id: UUID
    source_page_from: int
    source_page_to: int


@dataclass(frozen=True, slots=True)
class AnswerImportOutcome:
    node_id: UUID
    action: AnswerImportAction
    is_available: bool
```

- [ ] **Step 2: Implement the lifecycle decision table in one function**

Use this exact precedence:

```text
no row                                      -> create active imported answer
inactive row                                -> replace fields, reactivate, revision + 1
active manual row                           -> preserve
active confirmed imported row               -> preserve
active unconfirmed import from other file   -> preserve
active unconfirmed import from same file,
  identical candidate                       -> unchanged
active unconfirmed import from same file,
  changed candidate                         -> update, revision + 1
```

Every created/restored/updated row must set all provenance fields together: `text`, `origin_kind`, `match_method`, `matched_title`, `is_confirmed`, `is_active`, `source_label`, `source_material_id`, `source_page_from`, `source_page_to`, and timestamps. Do not leave manual provenance attached to imported text.

- [ ] **Step 3: Delegate `_fill_answers()` to the lifecycle module**

`bindings/answers_link.py` should only convert detected sections into `ImportedAnswerCandidate` values and collect outcomes. Remove the duplicated direct field mutation from `_fill_answers()`.

- [ ] **Step 4: Reuse the same availability predicate in read paths**

Expose `is_reference_answer_available(answer) -> bool` and use it in `reference_answer_status`, slot projection, coverage totals, and exam checking where raw `is_active` checks currently drift. Keep `source_only` as an available active answer with no text and a source material.

- [ ] **Step 5: Run focused tests**

Run:

```bash
cd backend
python -m pytest tests/test_answers_link.py tests/test_answer_sections.py tests/test_exam_checking.py tests/test_exam_chat.py -q
python -m ruff check app/projects/answer_lifecycle.py app/projects/answers.py app/bindings/answers_link.py tests/test_answers_link.py tests/test_answer_sections.py
```

Expected: all pass; active manual content is preserved and inactive tombstones are restored.

- [ ] **Step 6: Commit the lifecycle seam**

```bash
git add backend/app/projects/answer_lifecycle.py backend/app/projects/answers.py backend/app/bindings/answers_link.py backend/tests/test_answers_link.py backend/tests/test_answer_sections.py
git commit -m "fix(answers): restore inactive slots from matched files"
```

---

### Task 3: Make the matching report describe both matching and usable answers

**Files:**
- Modify: `backend/app/bindings/answers_link.py`
- Modify: `backend/app/bindings/schemas.py`
- Modify: `backend/app/bindings/router.py`
- Modify: `backend/app/materials/worker.py`
- Modify: `backend/tests/test_answers_link.py`
- Modify: `docs/architecture/materials-viewer-and-answers-autolink.md`
- Modify: `docs/architecture/stage-4-reference-answers.md`

**Interfaces:**
- Produces response fields: `matched_node_ids`, `available_node_ids`, `unavailable_node_ids`, `created_answers`, `updated_answers`, `restored_answers`, `unchanged_answers`, `preserved_answers`, and derived `complete`.
- Keeps `linked_fragments`, unresolved headings, ambiguous sections/pages, and suggestions unchanged.

- [ ] **Step 1: Replace the overloaded `linked_node_ids` meaning**

Build `matched_node_ids` from detected sections. After lifecycle application, query/project the final active answer state for every expected node to build `available_node_ids` and `unavailable_node_ids`. `complete` is true only when:

```python
complete = (
    not missing_node_ids
    and not ambiguous_sections
    and not unavailable_node_ids
    and len(available_node_ids) == expected_questions
)
```

- [ ] **Step 2: Report every disposition separately**

Do not keep `kept_answers`, which currently combines three incompatible facts. Count `unchanged_answers` and `preserved_answers` separately, and add `restored_answers` for the confirmed bug.

- [ ] **Step 3: Update the Pydantic and TypeScript-facing contract documentation**

Document that matching a heading, binding source fragments, and having an active reference answer are three distinct outcomes. Update the old stage-4 sentence “including a softly deleted slot, import never overwrites” to the new explicit-import rule.

- [ ] **Step 4: Log the final invariant in the worker path**

When `_link_answers_projects()` runs after material parsing, log ids and metrics only: expected, matched, available, restored, preserved, unresolved. Do not log answer text.

- [ ] **Step 5: Add API-level assertions**

Extend the existing link-answer route tests so serialized fields and `complete` cannot regress independently of the service dataclass.

- [ ] **Step 6: Run backend verification**

```bash
cd backend
python -m pytest tests/test_answers_link.py tests/test_answer_sections.py -q
python scripts/check_stage4.py
python scripts/check_stage5.py
python scripts/check_manual_binding.py
python -m ruff check .
```

- [ ] **Step 7: Commit the truthful report contract**

```bash
git add backend/app/bindings backend/app/materials/worker.py backend/tests/test_answers_link.py docs/architecture/materials-viewer-and-answers-autolink.md docs/architecture/stage-4-reference-answers.md
git commit -m "refactor(answers): separate matches from available answers"
```

---

### Task 4: Share one frontend run state and structured result

**Files:**
- Modify: `frontend/src/api/bindings.ts`
- Create: `frontend/src/hooks/useAnswerAutoMatch.ts`
- Create: `frontend/src/components/domain/AnswerMatchStatus.tsx`
- Modify: `frontend/src/components/domain/index.ts`
- Modify: `frontend/src/screens/Materials.tsx`
- Modify: `frontend/src/screens/CoverageMap.tsx`
- Modify: `frontend/src/styles/domain.css`
- Modify: `frontend/src/screens/UiKit.tsx`

**Interfaces:**
- Produces: `useAnswerAutoMatch(projectId, materialId, onCompleted)` and `AnswerMatchStatus`.
- Consumes: the new `AnswersLinkRead` contract and existing `linkAnswersMaterial()`.

- [ ] **Step 1: Model the complete UI state instead of a string notice**

```ts
export type AnswerAutoMatchState =
  | { status: "idle" }
  | { status: "running"; label: string }
  | { status: "complete"; result: AnswersLinkRead }
  | { status: "attention"; result: AnswersLinkRead }
  | { status: "error"; message: string };
```

`run()` sets `running` before the request, awaits the API, classifies by `result.complete`, then invokes refresh callbacks. It must ignore updates after abort/unmount.

- [ ] **Step 2: Render an honest running state at the result location**

While the request is active, render a compact `role="status"` / `aria-live="polite"` surface directly under “Сопоставить автоматически” (Materials) and below the Answer page header actions (Answers):

```text
Сопоставляем ответы
Ищем заголовки, обновляем привязки и проверяем, что эталоны доступны.
```

Use a restrained rotating `LoaderCircle` and `aria-busy="true"`. Do not use the determinate `Progress` primitive or show a fabricated `N из 42` while the server exposes no checkpoints.

- [ ] **Step 3: Render the completed summary as a scan-friendly domain card**

Primary line:

```text
Готово: эталоны доступны у 42 из 42 вопросов
```

Secondary metrics, only when non-zero:

```text
Создано 0 · Обновлено 0 · Восстановлено 2 · Сохранено ручных 0
```

Attention state example:

```text
Требуется проверка: сопоставлено 42, эталоны доступны у 40 из 42
2 ответа не созданы · 1 заголовок нужно выбрать вручную
```

Use full Russian templates with plural helpers; do not build prose by concatenating fragments. Success tone is allowed only for `result.complete`; incomplete coverage stays neutral/warning, never danger solely because a count is below 100%.

- [ ] **Step 4: Remove duplicate report assembly**

Delete the separate `parts` arrays in `Materials.linkAnswers()` and `CoverageMap.runHeadingsMatch()`. Both surfaces render `AnswerMatchStatus` and keep their own post-success refresh/suggestion behavior.

- [ ] **Step 5: Keep the result visible and retryable**

Disable the start button during the run, preserve the completed card until the next run or explicit dismiss, and keep “Сопоставить снова” available after completion. An error card says “Не удалось сопоставить ответы” and offers “Повторить”.

- [ ] **Step 6: Add the component to the UI kit**

Show running, complete, attention, and error states in `UiKit.tsx`, using only existing tokens and `lucide-react` icons.

- [ ] **Step 7: Run frontend static verification**

```bash
npm run typecheck
npm run build
npm run lint
```

- [ ] **Step 8: Commit the shared feedback UI**

```bash
git add frontend/src/api/bindings.ts frontend/src/hooks/useAnswerAutoMatch.ts frontend/src/components/domain/AnswerMatchStatus.tsx frontend/src/components/domain/index.ts frontend/src/screens/Materials.tsx frontend/src/screens/CoverageMap.tsx frontend/src/styles/domain.css frontend/src/screens/UiKit.tsx
git commit -m "feat(answers): show matching progress and result summary"
```

---

### Task 5: Make answer and source-page states impossible to confuse

**Files:**
- Modify: `frontend/src/components/domain/answerPages.ts`
- Modify: `frontend/src/screens/CoverageMap.tsx`
- Modify: `frontend/src/screens/ProjectWorkspace.tsx`
- Modify: `frontend/src/components/domain/ReferenceAnswerBadge.tsx`
- Modify: `SCREENS.md`

**Interfaces:**
- Consumes: active answer slot, active bindings, and `answerScanGroups()`.
- Produces: explicit UI distinction between an active reference answer and linked source pages.

- [ ] **Step 1: Name source-page data for what it is**

Rename local variables/copy so `scanGroups` is not treated as proof of an answer. Keep the helper's behavior (bindings plus an active answer's own page range), but document that groups can exist while the slot is missing.

- [ ] **Step 2: Add the contradiction-safe empty state in Answers**

When `slot.status === "missing"` and linked pages exist, show above the pages:

```text
Связанные страницы найдены, но эталон ещё не создан.
Сопоставьте файл ответов ещё раз или добавьте эталон вручную.
```

The badge remains “Нет ответа”; pages are labeled as linked source pages. When the lifecycle fix restores the answer, this notice disappears.

- [ ] **Step 3: Add the corresponding Workspace state**

If the active answer is missing but `sourceBindings` is non-empty, replace the generic “Ответ пока не найден” copy with:

```text
Для вопроса есть связанные материалы, но нет эталонного ответа.
Откройте «Ответы», чтобы создать или сопоставить эталон.
```

Keep the generic empty state only when both answer and bindings are absent.

- [ ] **Step 4: Audit every consumer of `ReferenceAnswerSlot`**

Verify `CoverageMap`, `ProjectWorkspace`, project stats, coverage totals, chat checking, and badges all use the same availability rule. No surface may infer answer availability from bindings or from the mere presence of a soft-deleted row.

- [ ] **Step 5: Update screen contracts**

Update the Answers, Materials, and Workspace sections in `SCREENS.md` with the running/result states and the source-pages-without-answer state.

- [ ] **Step 6: Run static verification and commit**

```bash
npm run typecheck
npm run build
npm run lint
git add frontend/src/components/domain/answerPages.ts frontend/src/screens/CoverageMap.tsx frontend/src/screens/ProjectWorkspace.tsx frontend/src/components/domain/ReferenceAnswerBadge.tsx SCREENS.md
git commit -m "fix(ui): distinguish answer availability from source bindings"
```

---

### Task 6: Repair and verify the real project through the public workflow

**Files:**
- No product-code files expected.
- Optional diagnostic script only if repeatable manual inspection is otherwise impossible: `backend/scripts/check_reference_answer_consistency.py`.

**Interfaces:**
- Consumes: the public match endpoint and read APIs.
- Produces: verified 42/42 active reference answers in `ТВИМС-Тест — экзамен` without direct SQL mutation.

- [ ] **Step 1: Back up the real SQLite database before the repair run**

Use SQLite's online backup API or a stopped-service copy. Do not copy a live WAL database with a plain filesystem copy.

- [ ] **Step 2: Run the same heading-based match command from the UI**

Do not patch rows directly. The explicit command must restore questions 10 and 12 through `apply_imported_answer`, proving future runs use the same path as the repair.

- [ ] **Step 3: Verify database invariants read-only**

For the 42 current study nodes, assert:

```text
answers_file bindings present: 42
active reference answers: 42
inactive reference answers blocking matched nodes: 0
available_node_ids returned by the run: 42
unavailable_node_ids returned by the run: 0
restored_answers returned by the first fixed run: 2
```

- [ ] **Step 4: Verify both previously broken questions**

Question 10 and question 12 must show text/images and document pages in Answers, and the Answer tab in Workspace must no longer show the generic missing state.

- [ ] **Step 5: Verify the preservation case in the real flow**

Temporarily use a disposable project or database copy: create an active manual answer, run matching, and confirm the manual text remains active and is reported as preserved.

---

### Task 7: Full verification and browser acceptance

**Files:**
- Modify only if verification uncovers a scoped defect in the changes above.

- [ ] **Step 1: Run the complete backend suite**

```bash
cd backend
python -m pytest
python -m ruff check .
python scripts/check_stage4.py
python scripts/check_stage5.py
python scripts/check_manual_binding.py
python scripts/check_exam_chat.py
```

- [ ] **Step 2: Run the complete frontend checks**

```bash
npm run typecheck
npm run build
npm run lint
```

- [ ] **Step 3: Restart both services before browser verification**

```bash
docker compose restart api web
```

- [ ] **Step 4: Walk the Materials flow**

Open the answer file, choose `Привязки` → `Сопоставить автоматически` → `на основе заголовков`, and verify the running state appears exactly where the result card later replaces it. Check keyboard focus, disabled start action, success, attention, error, retry, and narrow inspector width.

- [ ] **Step 5: Walk the Answers flow**

Run the same operation from `Ответы` → `Из файла ответов`; confirm the same component/copy appears, question 10 is available immediately after refresh, and “Текст и картинки” plus “Страницы документа” agree about availability.

- [ ] **Step 6: Walk the Workspace flow**

Open question 10 directly in the Workspace, verify the active reference answer and page mode, then verify the linked-source-without-answer state on a disposable manually bound question.

- [ ] **Step 7: Capture screenshots**

Capture the running state, complete 42/42 result, an attention result, question 10 in text mode, and question 10 in document-page mode.

- [ ] **Step 8: Commit any verification-only adjustments and report exact command results**

```bash
git status --short
git log --oneline --decorate -7
```

Expected final state: only intentional commits on `codex/fix-reference-answer-consistency`; no edits in the root worktree.

---

## Self-Review

- **Spec coverage:** root cause, lifecycle refactor, truthful report, shared progress/result UI, source-page distinction, real-data repair, docs, tests, service restart, and browser screenshots are all assigned to tasks.
- **No silent repair:** inactive rows change only during an explicit match operation.
- **No fake progress:** running feedback is indeterminate until the synchronous API exposes real checkpoints.
- **Type consistency:** backend and frontend use the same result names; `matched_node_ids` is not reused as answer availability.
- **Integration risk:** the active exam-wizard work already touches answer matching for question/task file slots; integrate it before Task 1 so lifecycle work is applied once to the final function shape.
