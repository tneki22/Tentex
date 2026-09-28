"""Экспорт уроков и перенос файлом `.tentex-lessons` (lessons.md, «Экспорт и перенос уроков»)."""

import io
import json
import shutil
import zipfile
from pathlib import Path

import fitz
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.lessons import editing, service
from app.lessons.export import importer
from app.lessons.export import service as export_service
from app.lessons.export.markdown_in import parse_markdown
from app.lessons.export.pdf import normalize_tex
from app.lessons.export.render_latex import LatexRenderer, katex_renders
from app.lessons.schemas import LessonBlockWrite, LessonNoteWrite
from app.models import (
    Binding,
    Lesson,
    LessonBlockKind,
    ProjectMaterial,
    SourceRole,
)
from app.projects.errors import ProjectDomainError
from app.projects.program import undo_last_project_action
from tests.test_lessons import Book, add_node, make_lessons_project, quick


@pytest.fixture(autouse=True)
def storage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    (settings.storage_dir / "tmp").mkdir(parents=True, exist_ok=True)
    return tmp_path


def _lesson_with_everything(session: Session):
    """Проект-источник: быстрый урок по теме и пояснение с формулами и опорой."""
    project = make_lessons_project(session)
    book = Book(session, project, "Теория вероятностей")
    book.page(4, "h:1.2 Классическая схема", "p:Вероятность равна $p=\\frac{k}{n}$ исходов",
              "p:второй абзац")
    book.page(5, "p:третий абзац", "h:1.3 Геометрия", "p:чужая тема")
    node = add_node(session, project, "Классическая схема", 0, ranges=[(book, 4, 4)])
    add_node(session, project, "Геометрия", 1, ranges=[(book, 5, 6)])
    lesson = quick(session, project, node).lesson
    result = editing.edit_lesson_blocks(session, project.id, lesson.id, LessonBlockWrite(
        expected_revision=lesson.revision, operation="add_note", variant="important"))
    note = next(block for block in result.lesson.blocks if block.kind == LessonBlockKind.NOTE
                and block.variant == "important")
    result = editing.update_lesson_note(session, project.id, lesson.id, note.id, LessonNoteWrite(
        expected_revision=result.lesson.revision,
        body_md="Площадь круга $S=\\pi r^2$, а дробь:\n\n$$\\frac{a}{b}$$\n\n*звёздочка* 5 * 3",
    ))
    return project, book, node, result.lesson


def _export(session: Session, project_id, lesson_ids, fmt: str, **options) -> Path:
    command = export_service.LessonExportWrite(lesson_ids=lesson_ids, format=fmt, **options)
    result = export_service.export_lessons(session, project_id, command)
    return result.path


def test_package_round_trip_links_pieces_to_the_same_material(session: Session):
    source, book, _node, lesson = _lesson_with_everything(session)
    package = _export(session, source.id, [lesson.id], "tentex").read_bytes()

    target = make_lessons_project(session)
    session.add(ProjectMaterial(project_id=target.id, material_id=book.material.id,
                                source_role=SourceRole.MAIN, priority=0))
    topic = add_node(session, target, "1.2 Классическая схема", 0)
    session.commit()

    parsed = importer.read_package(package)
    preview = importer.preview_package(session, target.id, parsed)
    assert preview.lessons[0].program_node_id == topic.id
    assert [item.status for item in preview.materials] == ["project"]

    result = importer.import_package(session, target.id, parsed, importer.LessonImportOptions(
        lessons=[{"key": "l1", "program_node_id": topic.id}],
        materials={"m1": book.material.id},
    ))
    assert result.linked_pieces == 1 and result.snapshot_pieces == 0

    imported = service.get_lesson(session, target.id, result.lessons[0].id)
    [ref] = [block.refs[0] for block in imported.blocks if block.kind == LessonBlockKind.SOURCE]
    [original] = [block.refs[0] for block in lesson.blocks if block.kind == LessonBlockKind.SOURCE]
    assert ref.is_available
    assert (ref.from_fragment_id, ref.to_fragment_id) == \
        (original.from_fragment_id, original.to_fragment_id)
    assert not ref.boundary_shifted
    note = next(block for block in imported.blocks if block.variant == "important")
    assert "$S=\\pi r^2$" in (note.body_md or "")
    bindings = session.scalars(select(Binding).where(Binding.project_id == target.id)).all()
    assert {binding.program_node_id for binding in bindings} == {topic.id}

    undo_last_project_action(session, target.id, result.latest_undoable_action.sequence)
    assert session.scalar(select(Lesson).where(Lesson.project_id == target.id)) is None
    assert session.scalars(select(Binding).where(Binding.project_id == target.id)).all() == []


def test_missing_material_becomes_snapshot_and_relinks_later(session: Session):
    source, book, _node, lesson = _lesson_with_everything(session)
    package = importer.read_package(_export(session, source.id, [lesson.id], "tentex").read_bytes())

    target = make_lessons_project(session)
    topic = add_node(session, target, "Другая формулировка", 0)
    preview = importer.preview_package(session, target.id, package)
    assert preview.lessons[0].program_node_id is None
    assert preview.materials[0].status == "library"

    result = importer.import_package(session, target.id, package, importer.LessonImportOptions(
        lessons=[{"key": "l1", "program_node_id": topic.id}], materials={"m1": None},
    ))
    assert result.snapshot_pieces == 1
    imported = service.get_lesson(session, target.id, result.lessons[0].id)
    [ref] = [block.refs[0] for block in imported.blocks if block.kind == LessonBlockKind.SOURCE]
    assert not ref.is_available and not ref.can_relink
    assert "Вероятность равна $p=\\frac{k}{n}$" in (ref.snapshot_md or "")
    assert "чужая тема" not in (ref.snapshot_md or "")

    session.add(ProjectMaterial(project_id=target.id, material_id=book.material.id,
                                source_role=SourceRole.MAIN, priority=0))
    session.commit()
    imported = service.get_lesson(session, target.id, imported.id)
    [ref] = [block.refs[0] for block in imported.blocks if block.kind == LessonBlockKind.SOURCE]
    assert ref.can_relink

    change = editing.edit_lesson_blocks(session, target.id, imported.id, LessonBlockWrite(
        expected_revision=imported.revision, operation="relink"))
    relinked = change.lesson
    [ref] = [block.refs[0] for block in relinked.blocks if block.kind == LessonBlockKind.SOURCE]
    assert ref.is_available and ref.snapshot_md is None
    [original] = [block.refs[0] for block in lesson.blocks if block.kind == LessonBlockKind.SOURCE]
    assert (ref.page_from, ref.page_to) == (original.page_from, original.page_to)
    assert ref.to_fragment_id == original.to_fragment_id == book.ids["третий абзац"]

    undo_last_project_action(session, target.id, change.latest_undoable_action.sequence)
    restored = service.get_lesson(session, target.id, imported.id)
    [ref] = [block.refs[0] for block in restored.blocks if block.kind == LessonBlockKind.SOURCE]
    assert ref.material_id is None and ref.snapshot_md


def test_relink_without_material_is_refused(session: Session):
    source, _book, _node, lesson = _lesson_with_everything(session)
    package = importer.read_package(_export(session, source.id, [lesson.id], "tentex").read_bytes())
    target = make_lessons_project(session)
    topic = add_node(session, target, "Тема", 0)
    result = importer.import_package(session, target.id, package, importer.LessonImportOptions(
        lessons=[{"key": "l1", "program_node_id": topic.id}]))
    imported = service.get_lesson(session, target.id, result.lessons[0].id)
    with pytest.raises(ProjectDomainError) as error:
        editing.edit_lesson_blocks(session, target.id, imported.id, LessonBlockWrite(
            expected_revision=imported.revision, operation="relink"))
    assert error.value.code == "lesson_relink_nothing"


def test_broken_packages_are_rejected_with_codes():
    with pytest.raises(ProjectDomainError) as error:
        importer.read_package(b"not a zip")
    assert error.value.code == "lesson_package_corrupt"

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("manifest.json", json.dumps({"format": "tentex-lessons", "version": 99}))
        archive.writestr("lessons.json", "[]")
    with pytest.raises(ProjectDomainError) as error:
        importer.read_package(buffer.getvalue())
    assert error.value.code == "lesson_package_incompatible"

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("../evil.json", "{}")
    with pytest.raises(ProjectDomainError) as error:
        importer.read_package(buffer.getvalue())
    assert error.value.code == "lesson_package_corrupt"


def test_markdown_and_latex_keep_formulas_as_written(session: Session):
    project, _book, _node, lesson = _lesson_with_everything(session)

    markdown = _export(session, project.id, [lesson.id], "markdown").read_text(encoding="utf-8")
    assert "$S=\\pi r^2$" in markdown and "> $$\n> \\frac{a}{b}\n> $$" in markdown
    assert "$p=\\frac{k}{n}$" in markdown
    assert "5 \\* 3" in markdown
    assert "**Важно.**" in markdown

    latex = _export(session, project.id, [lesson.id], "latex").read_text(encoding="utf-8")
    assert "$S=\\pi r^2$" in latex and "\\[\n\\frac{a}{b}\n\\]" in latex
    assert "\\begin{lessoncallout}{Важно}" in latex
    assert "\\providecommand{\\R}{\\mathbb{R}}" in latex

    reference = _export(session, project.id, [lesson.id], "markdown", sources="reference")
    assert "В учебнике: Теория вероятностей, стр. 4" in reference.read_text(encoding="utf-8")


def test_note_markdown_follows_the_app_renderer():
    blocks = parse_markdown("Опора [S3] и \\(x^2\\)<br />\n\n<br />\n\n\\[y\\]")
    kinds = [type(block).__name__ for block in blocks]
    assert kinds == ["Paragraph", "MathBlock"]
    names = [type(node).__name__ for node in blocks[0].content]
    assert "Citation" in names and "Math" in names


def test_latex_prints_formulas_katex_cannot_draw_as_source():
    assert katex_renders("\\frac{a}{b} + \\mathsf{P}(A) \\begin{cases} x \\\\ y \\end{cases}")
    assert not katex_renders("\\foobar{x}")
    assert not katex_renders("\\begin{weird} x \\end{weird}")
    doc = parse_markdown("Ошибка OCR $\\b x$ и верная $x^2$.")
    text = LatexRenderer().blocks(doc)
    assert "\\texttt{\\$\\textbackslash{}b x\\$}" in text and "$x^2$" in text


def test_tex_is_normalized_for_mitex():
    assert normalize_tex("\\begin{pmatrix}1&2\\\\3&4\\end{pmatrix}") == \
        "\\begin{pmatrix}1&2\\\\ 3&4\\end{pmatrix}"
    assert normalize_tex("\\mbox{если } x \\in \\R") == "\\text{если } x \\in \\mathbb{R}"
    assert normalize_tex("E=mc^2 \\tag{3}").endswith("\\qquad (3)")


@pytest.mark.skipif(shutil.which(str(settings.typst_binary)) is None, reason="нет typst")
def test_pdf_shows_formulas_and_keeps_latex_in_text_layer(session: Session):
    project, _book, _node, lesson = _lesson_with_everything(session)
    pdf = _export(session, project.id, [lesson.id], "pdf")
    formulas = json.loads((pdf.parent / "typst" / "formulas.json").read_text(encoding="utf-8"))
    assert formulas and all(item["file"] for item in formulas.values())
    with fitz.open(pdf) as document:
        text = "".join(page.get_text() for page in document)
        drawings = sum(len(page.get_drawings()) for page in document)
    assert "$S=\\pi r^2$" in text
    assert "$$\\frac{a}{b}$$" in text
    assert "$p=\\frac{k}{n}$" in text
    assert "Площадь круга" in text
    assert drawings > 0
