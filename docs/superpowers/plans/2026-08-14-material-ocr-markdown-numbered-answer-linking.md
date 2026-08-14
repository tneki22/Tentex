# Material OCR Markdown and Numbered Answer Linking Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Preserve complex PDF layout as Markdown, parse the intended numbered exam-question series, and link numbered answer sections to the current program without unsafe guesses.

**Architecture:** Add one local PDF-layout adapter for the existing `ParsedPage` contract and one reusable numbered-series parser shared by exam import and answer linking. Keep exact/fuzzy heading matching as the first linking path, then use ordinal linking only when numbering and current-program order pass explicit fail-closed checks. Surface the same model in the existing Materials inspector as an OCR section; no new route or external AI role is introduced.

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy/Alembic, PyMuPDF, PyMuPDF4LLM, pytest, React 19, TypeScript, Vite, existing Tentex UI primitives and CSS tokens.

## Global Constraints

- Only `Быстро · локально` is available; `Учебник`, `Облако`, `Максимум`, and `Эксперт` remain disabled.
- PyMuPDF4LLM must not run its own OCR; scanned pages continue through the existing local PP-OCRv5 path.
- A layout-parser failure affects one page only and falls back to the current native parser with an explicit diagnostic.
- Preamble text and later numbering resets must never silently become exam questions.
- Ordinal answer linking must fail closed on duplicate, missing, out-of-order, or ambiguous top-level numbering.
- Manual and confirmed reference answers must never be overwritten.
- `numbered_order` answers remain unconfirmed until the user reviews them.
- Do not read or snapshot the user's document content in tests; use generated fixtures.
- Preserve the stage-1 Materials layout except for the OCR section and copy changes explicitly approved on 2026-08-14.
- Do not stage or modify unrelated AI-provider, Projects, navigation, or design-system work already present in the working tree.

---

### Task 1: Reusable Numbered-Series Parser

**Files:**
- Create: `backend/app/projects/numbered_series.py`
- Modify: `backend/app/projects/importer.py`
- Modify: `backend/app/materials/service.py`
- Test: `backend/tests/test_exam_wizard_materials.py`
- Test: `backend/tests/test_numbered_series.py`

**Interfaces:**
- Produces: `NumberedItem(number: int, text: str, source_index: int)` and `select_numbered_series(lines: Sequence[str], expected_count: int | None) -> NumberedSeriesSelection`.
- Produces: `NumberedSeriesSelection.items`, `.ignored_before`, `.ignored_after`, `.warnings`, and `.ambiguous`.
- Changes: `parse_exam_program(raw_text, exam_format, *, expected_item_count=None)`; ticket parsing remains unchanged.
- Consumes: `GoalPassport.expected_item_count` in `_parsed_exam_from_material` and the material import service.

- [ ] **Step 1: Write the failing numbered-series tests**

```python
def test_selects_main_series_and_ignores_preamble_and_trailing_reset():
    result = select_numbered_series(
        ["Preparation title", "1. First", "2. Second", "3. Third", "1. Appendix"],
        expected_count=3,
    )
    assert [item.number for item in result.items] == [1, 2, 3]
    assert result.ignored_before == ["Preparation title"]
    assert result.ignored_after == ["1. Appendix"]


def test_rejects_two_equally_valid_series():
    result = select_numbered_series(
        ["1. A", "2. B", "1. C", "2. D"], expected_count=2
    )
    assert result.ambiguous is True
```

- [ ] **Step 2: Run the tests and confirm the old flat parser fails**

Run: `docker compose exec api pytest tests/test_numbered_series.py tests/test_exam_wizard_materials.py -q`

Expected: FAIL because `select_numbered_series` and the `expected_item_count` keyword do not exist.

- [ ] **Step 3: Implement consecutive-series selection**

```python
@dataclass(frozen=True, slots=True)
class NumberedItem:
    number: int
    text: str
    source_index: int


def select_numbered_series(
    lines: Sequence[str], expected_count: int | None = None
) -> NumberedSeriesSelection:
    """Choose one unique 1..N run; never merge across a reset or a gap."""
```

Use a strict top-level marker regex accepting `1.`, `1)` and `1 `, append unnumbered continuation lines to the current item, close a run on reset/gap, rank exact `expected_count` first, and return `ambiguous=True` when the best candidate is not unique. Warnings must say how many preamble/trailing lines were ignored without echoing document content.

- [ ] **Step 4: Integrate selection into flat exam import**

```python
def parse_exam_program(
    raw_text: str,
    exam_format: ExamFormat,
    *,
    expected_item_count: int | None = None,
) -> ParsedExamProgram:
    ...
```

For `QUESTIONS` and the question part of `QUESTIONS_TASKS`, turn the selected items into `ParsedNode`s. Raise `ExamImportError` on ambiguity and include count-only warnings for ignored text. Pass the goal passport's expected count from material import; keep pasted-text callers compatible with the default.

- [ ] **Step 5: Run focused tests**

Run: `docker compose exec api pytest tests/test_numbered_series.py tests/test_exam_wizard_materials.py -q`

Expected: PASS, including a regression for tickets and a case equivalent to `1..16` followed by a reset `1..3` returning exactly 16 questions.

- [ ] **Step 6: Commit**

```powershell
git add backend/app/projects/numbered_series.py backend/app/projects/importer.py backend/app/materials/service.py backend/tests/test_numbered_series.py backend/tests/test_exam_wizard_materials.py
git commit -m "fix: select the intended exam question series"
```

---

### Task 2: Layout-Aware Native PDF to Markdown

**Files:**
- Create: `backend/app/materials/parsers/pdf_layout.py`
- Modify: `backend/app/materials/parsers/native.py`
- Modify: `backend/requirements.txt`
- Modify: `backend/requirements-worker.txt`
- Test: `backend/tests/test_pdf_layout_parser.py`

**Interfaces:**
- Produces: `parse_layout_page(document: fitz.Document, page_index: int) -> ParsedPage`.
- Consumes: existing `ParsedElement`, `ParsedPage`, `ElementKind`, page width/height and quality values.
- Preserves: `iter_pages(...) -> Iterator[ParsedPage]`; worker and persistence code do not change.

- [ ] **Step 1: Add a generated-PDF failing test**

```python
def test_native_pdf_preserves_table_nested_list_and_columns(tmp_path):
    pdf_path = build_layout_fixture(tmp_path)
    page = next(iter_pages(pdf_path, "application/pdf", "fast", tmp_path / "assets"))
    assert "| Column A | Column B |" in page.markdown
    assert "- Parent" in page.markdown
    assert "  - Child" in page.markdown
    assert [element.kind for element in page.elements].count("table") == 1
    assert "layout_markdown" in page.diagnostics
```

The fixture is generated in the test with PyMuPDF and contains only synthetic English labels, a ruled 2×2 table, a nested bullet list, a heading, and two text columns.

- [ ] **Step 2: Run the test and confirm current extraction loses structure**

Run: `docker compose exec worker pytest tests/test_pdf_layout_parser.py -q`

Expected: FAIL because the native parser emits flattened paragraphs and no table element.

- [ ] **Step 3: Add the official local layout dependency**

Add one compatible version range to the shared backend requirements and keep `requirements-worker.txt` including it through `-r requirements.txt`:

```text
PyMuPDF4LLM>=0.2,<1
```

Rebuild the worker image before the passing run: `docker compose build worker`.

- [ ] **Step 4: Adapt layout output to `ParsedPage`**

```python
def parse_layout_page(document: fitz.Document, page_index: int) -> ParsedPage:
    """Convert one text-layer page to Tentex Markdown and bbox elements."""
```

Call PyMuPDF4LLM for exactly one page with OCR disabled. Convert layout blocks to headings, paragraphs, nested lists, tables, and images; keep bbox coordinates and hierarchy levels. Use `Table.to_markdown()` where the layout payload exposes a detected table. Set count-only diagnostics such as `layout_markdown`, `tables:2`, and `structure_elements:14`.

- [ ] **Step 5: Add per-page fallback in the existing native parser**

```python
try:
    return parse_layout_page(document, page_index)
except Exception:
    fallback = _native_pdf_page(document, page_index)
    fallback.diagnostics.append("layout_fallback")
    return fallback
```

Catch at the page boundary, not around the entire document. Do not send native pages to PP-OCR; existing low-text scan detection and PP-OCR behavior remain unchanged.

- [ ] **Step 6: Test structure and fallback**

Run: `docker compose exec worker pytest tests/test_pdf_layout_parser.py tests/test_material_segmentation.py -q`

Expected: PASS; the fallback test monkeypatches the adapter to raise and verifies usable paragraph Markdown plus `layout_fallback`.

- [ ] **Step 7: Commit**

```powershell
git add backend/app/materials/parsers/pdf_layout.py backend/app/materials/parsers/native.py backend/requirements.txt backend/requirements-worker.txt backend/tests/test_pdf_layout_parser.py
git commit -m "feat: preserve native PDF layout as Markdown"
```

---

### Task 3: Safe Ordinal Linking for Answer Files

**Files:**
- Modify: `backend/app/models.py`
- Create: `backend/migrations/versions/20260814_0016_numbered_answer_match.py`
- Modify: `backend/app/bindings/answers_link.py`
- Modify: `backend/app/bindings/schemas.py`
- Test: `backend/tests/test_answers_link.py`

**Interfaces:**
- Consumes: `select_numbered_series`, current active study nodes ordered by program preorder, persisted material blocks/fragments.
- Produces: `ReferenceAnswerMatchMethod.NUMBERED_ORDER = "numbered_order"`.
- Extends: `AnswersLinkResult` with `numbered_sections: int`, `extra_sections: int`, and `ordinal_rejected_reason: str | None`.
- Preserves: exact, fuzzy and user-resolved title matching; `_rebind` and `_fill_answers` idempotence and manual/confirmed-answer protection.

- [ ] **Step 1: Write failing linking tests**

```python
def test_links_numbered_answers_by_current_program_order(session):
    project, nodes = make_numbered_program(session, count=3)
    material = make_answer_material(session, headings=["1. Different", "2. Other", "3. Third"])
    result = link_answers_material(session, project.id, material.id)
    assert result.numbered_sections == 3
    assert result.unmatched_headings == []
    answers = load_answers(session, project.id)
    assert [answer.match_method for answer in answers] == [
        ReferenceAnswerMatchMethod.NUMBERED_ORDER,
    ] * 3
    assert all(answer.is_confirmed is False for answer in answers)


def test_ordinal_linking_fails_closed_on_gap_or_duplicate(session):
    ...
    assert result.numbered_sections == 0
    assert result.ordinal_rejected_reason is not None
```

Also cover nested headings `1.1`, repeated runs, extra answer sections after the program, rerun idempotence, and preservation of a manual confirmed answer.

- [ ] **Step 2: Run the focused test and confirm title-only behavior fails**

Run: `docker compose exec api pytest tests/test_answers_link.py -q`

Expected: FAIL with all differently worded headings reported unmatched.

- [ ] **Step 3: Add the enum migration**

```python
OLD_METHODS = ("manual", "exact_title", "fuzzy_title", "resolved_title")
NEW_METHODS = (*OLD_METHODS, "numbered_order")
```

Rebuild the SQLite enum constraint with `batch_alter_table`, mirroring migration `20260812_0010_fuzzy_title_match.py`. On downgrade, rewrite `numbered_order` to `exact_title`. Set `down_revision` to the actual latest committed migration at execution time; do not depend on an unrelated uncommitted migration.

- [ ] **Step 4: Build top-level answer sections and apply guarded ordinal matching**

Create sections only at a selected `1..N` top-level run. Nested numbered headings, tables, lists, and paragraphs remain fragments of the current section. First apply exact/resolved/fuzzy matches; for the remaining sections, ordinal-match only when the selected series is unique, starts at 1, is consecutive, preserves document order, and overlaps the current program from its first item. Count clean surplus sections after the program as `extra_sections` rather than suggestions.

- [ ] **Step 5: Mark ordinal answers for review and expose aggregate diagnostics**

When `_fill_answers` writes `numbered_order`, set `is_confirmed=False`, persist the source number in `matched_title`, and never overwrite manual or confirmed rows. Return counts and a Russian `ordinal_rejected_reason` without exposing answer text.

- [ ] **Step 6: Run linking and migration tests**

Run: `docker compose exec api alembic upgrade head`

Run: `docker compose exec api pytest tests/test_answers_link.py tests/test_heading_match.py -q`

Expected: PASS; old exact/fuzzy tests remain green and rerunning linking creates no duplicates.

- [ ] **Step 7: Commit**

```powershell
git add backend/app/models.py backend/migrations/versions/20260814_0016_numbered_answer_match.py backend/app/bindings/answers_link.py backend/app/bindings/schemas.py backend/tests/test_answers_link.py
git commit -m "feat: link numbered answer sections safely"
```

---

### Task 4: OCR Processing Section and Answer Copy

**Files:**
- Modify: `frontend/src/api/materials.ts`
- Modify: `frontend/src/screens/Materials.tsx`
- Modify: `frontend/src/styles/domain.css`
- Modify: `SCREENS.md`
- Modify: `docs/ui/stage-1-interface-baseline.md`
- Modify: `docs/architecture/materials-viewer-and-answers-autolink.md`

**Interfaces:**
- Consumes: existing `MaterialRead` page/quality counts, `MaterialCapabilities`, processing callbacks, and the extended answer-link response.
- Produces: one persistent `OCR` inspector section for `ready_to_process` and `ready` states.
- Copy: `Ответы из файла`, `Связать с вопросами`, and `Импортировать ответы текстом`.

- [ ] **Step 1: Extend frontend response types**

```ts
export interface AnswersLinkResult {
  linked_sections: number;
  numbered_sections: number;
  extra_sections: number;
  ordinal_rejected_reason: string | null;
  // existing fields stay unchanged
}
```

Use the actual existing interface name returned by `linkMaterialAnswers`; do not duplicate a second contract.

- [ ] **Step 2: Replace the ready-state reparse button with the OCR section**

```tsx
<section className="materials-processing-section materials-ocr-section">
  <h3>OCR</h3>
  <p>Быстро · локально</p>
  <dl>{/* pages, scans, low-quality pages, tables/structure diagnostics */}</dl>
  <Button onClick={material.status === "ready" ? onReparse : () => onStart("fast")}>
    {material.status === "ready" ? "Запустить заново" : "Запустить"}
  </Button>
</section>
```

Keep the four deferred modes visible and disabled with their existing reasons. Remove only the old standalone `Разобрать заново` button.

- [ ] **Step 3: Change answer copy and notices**

The answer section explains the matching order: number, exact title, close title, manual choice. The linking notice reports linked sections, surplus sections outside the current program, and a rejected ordinal reason; it no longer presents every subheading as an unmatched question.

- [ ] **Step 4: Add token-based styles and document the approved deviation**

Add only layout selectors needed for the compact OCR definition list, using existing spacing/color/border tokens. Append a dated Materials row to the baseline document without editing the unrelated Projects row already in the worktree. Update `SCREENS.md` and the architecture contract with the fail-closed number-link rules and local layout parser.

- [ ] **Step 5: Verify the frontend statically**

Run: `npm run typecheck`

Run: `npm run build`

Run: `npm run lint`

Expected: all commands exit 0.

- [ ] **Step 6: Commit**

```powershell
git add frontend/src/api/materials.ts frontend/src/screens/Materials.tsx frontend/src/styles/domain.css docs/architecture/materials-viewer-and-answers-autolink.md
git add -p SCREENS.md docs/ui/stage-1-interface-baseline.md
git commit -m "feat: add OCR processing controls and answer linking copy"
```

Confirm the staged diff contains only this task's hunks before committing.

---

### Task 5: End-to-End Verification and Browser Evidence

**Files:**
- Modify if needed: only files already owned by Tasks 1–4.

**Interfaces:**
- Consumes: the complete pipeline and existing project/material APIs.
- Produces: verified behavior and one final corrective commit only if verification finds a defect.

- [ ] **Step 1: Run backend quality gates**

Run: `docker compose exec api python -m ruff check app tests`

Run: `docker compose exec api pytest tests/test_numbered_series.py tests/test_exam_wizard_materials.py tests/test_pdf_layout_parser.py tests/test_answers_link.py tests/test_heading_match.py -q`

Run: `docker compose exec api python scripts/check_stage2.py`

Run: `docker compose exec api python scripts/check_stage3.py`

Run: `docker compose exec api python scripts/check_stage4.py`

Expected: all exit 0.

- [ ] **Step 2: Restart the frontend container**

Run: `docker compose restart web`

Expected: the container returns to `running` and serves `http://localhost:5173`.

- [ ] **Step 3: Verify the real browser flow**

Open an exam project, Materials, an answer file, and the `Обработка` tab. Verify keyboard focus, both themes, and a 390 px viewport. Confirm `OCR`, `Быстро · локально`, `Запустить заново`, `Ответы из файла`, `Связать с вопросами`, and `Импортировать ответы текстом` are visible; deferred modes are disabled; the old two button labels are absent.

- [ ] **Step 4: Run a content-free aggregate smoke check on the user's files**

Through the API only, reprocess the question file and answer file if the user-visible operation is safe. Assert counts, never log text: the question import preview contains 16 questions, answer linking links only program ordinals `1..16`, extra sections are counted, and Markdown diagnostics report tables/structure. If reprocessing would replace user corrections, stop and leave this smoke check to the user's planned manual test.

- [ ] **Step 5: Inspect repository and staged scope**

Run: `git status --short`

Run: `git diff --check`

Run: `git log -5 --oneline`

Expected: no whitespace errors; unrelated dirty files remain unstaged and untouched.

- [ ] **Step 6: Commit any verification-only fix**

```powershell
git add <only files changed to fix a verified defect>
git commit -m "fix: harden material markdown linking verification"
```

Skip this commit when verification required no correction.
