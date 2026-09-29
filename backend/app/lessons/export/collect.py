"""Урок из базы — в узлы `ir`: то, что человек видит в режиме чтения, без кнопок.

Кусок материала показывается текстом фрагментов (как «Текст» в уроке), листами
страниц или одной строкой-ссылкой — по выбору экспорта. Пояснения — их Markdown,
задания — условием с вариантами, ответы — отдельным разделом в конце урока.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from uuid import UUID

import fitz
from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.lessons import refs as refs_module
from app.lessons.export import ir
from app.lessons.export.markdown_in import (
    formula_looks_reliable,
    formula_runs,
    fragment_table,
    latex_from_fragment,
    parse_markdown,
    text_with_math,
)
from app.lessons.service import _source_name, _topic_reads, media_kind
from app.materials import library
from app.materials.parsers.base import MODEL_DESCRIPTION_MARK
from app.materials.storage import material_path
from app.models import (
    Lesson,
    LessonBlock,
    LessonBlockKind,
    LessonBlockOrigin,
    LessonNoteVariant,
    LessonRefRole,
    LessonSourceRef,
    Material,
    MaterialFragment,
    ProjectMaterial,
    RecognitionSource,
    StudyTask,
    StudyTaskForm,
)
from app.projects.errors import ProjectDomainError, ProjectNotFoundError

SourceMode = Literal["text", "pages", "reference"]

CALLOUT_TITLES = {
    LessonNoteVariant.IMPORTANT: "Важно",
    LessonNoteVariant.EXAMPLE: "Пример",
    LessonNoteVariant.DEFINITION: "Определение",
    LessonNoteVariant.WARNING: "Предупреждение",
}
TASK_LABELS = {
    StudyTaskForm.SINGLE_CHOICE: "Выберите один ответ",
    StudyTaskForm.MULTIPLE_CHOICE: "Выберите все верные ответы",
    StudyTaskForm.FILL_BLANKS: "Заполните пропуски",
    StudyTaskForm.NUMERIC: "Числовой ответ",
    StudyTaskForm.ORDERING: "Расставьте по порядку",
    StudyTaskForm.MATCHING: "Сопоставьте",
    StudyTaskForm.OPEN_ANSWER: "Развёрнутый ответ",
}
LETTERS = "АБВГДЕЖЗИК"
# Лист страницы для печати: 1,5× просмотрщика мелковат, 2,5× даёт ≈180 dpi.
PRINT_ZOOM = 2.5
JPEG_QUALITY = 85


def pages_label(page_from: int, page_to: int) -> str:
    return f"стр. {page_from}" if page_from == page_to else f"стр. {page_from}–{page_to}"


def inline_markdown(text: str) -> list[ir.Inline]:
    """Строка задания или подписи: Markdown одного абзаца, формулы — формулами."""
    blocks = parse_markdown(text)
    if len(blocks) == 1 and isinstance(blocks[0], ir.Paragraph):
        return blocks[0].content
    return text_with_math(" ".join(text.split()))


@dataclass(frozen=True, slots=True)
class ExportOptions:
    sources: SourceMode = "text"
    answers: bool = True


@dataclass(slots=True)
class _Piece:
    ref: LessonSourceRef
    material: Material | None
    link: ProjectMaterial | None

    @property
    def available(self) -> bool:
        return self.material is not None and self.link is not None


class Collector:
    """Собирает `ir.ExportDoc`; картинки, которые надо нарисовать, пишет в `workdir`."""

    def __init__(
        self, session: Session, project_id: UUID, options: ExportOptions, workdir: Path
    ) -> None:
        self.session = session
        self.project_id = project_id
        self.options = options
        self.workdir = workdir
        self._pictures = 0

    # --- урок -----------------------------------------------------------------------

    def lesson(self, lesson: Lesson) -> ir.LessonDoc:
        blocks = list(self.session.scalars(
            select(LessonBlock).where(LessonBlock.lesson_id == lesson.id)
            .order_by(LessonBlock.sort_order)
        ))
        refs: dict[UUID, list[LessonSourceRef]] = defaultdict(list)
        if blocks:
            for ref in self.session.scalars(select(LessonSourceRef).where(
                LessonSourceRef.block_id.in_([block.id for block in blocks])
            )):
                refs[ref.block_id].append(ref)
        content = [ref for block in blocks for ref in refs[block.id]
                   if ref.role == LessonRefRole.CONTENT]
        shown = refs_module.shown_pages(self.session, content)
        topics = [topic.current_title or topic.title_snapshot
                  for topic in _topic_reads(self.session, lesson.id)]
        tasks = self._tasks([block.activity_id for block in blocks if block.activity_id])

        doc = ir.LessonDoc(title=lesson.title, goal=lesson.goal, topics=topics, blocks=[])
        citations: dict[str, str] = {}
        for block in blocks:
            match block.kind:
                case LessonBlockKind.NOTE:
                    doc.blocks += self._note(block, lesson.title)
                    for ref in refs[block.id]:
                        if ref.role == LessonRefRole.SUPPORT and ref.citation_label:
                            citations.setdefault(ref.citation_label, self._ref_caption(ref))
                case LessonBlockKind.SOURCE:
                    for ref in refs[block.id]:
                        if ref.role == LessonRefRole.CONTENT:
                            doc.blocks += self._source(block, ref, shown.get(ref.id, []))
                case LessonBlockKind.MEDIA:
                    doc.blocks += self._media(block)
                case LessonBlockKind.ACTIVITY:
                    task = tasks.get(block.activity_id) if block.activity_id else None
                    if task is not None:
                        number = len(doc.answers) + 1
                        box, answer = task_blocks(task, number)
                        doc.blocks.append(box)
                        doc.answers.append(answer)
        doc.citations = sorted(citations.items(), key=lambda item: _label_order(item[0]))
        if not self.options.answers:
            doc.answers = []
        return doc

    def _tasks(self, activity_ids: list[UUID]) -> dict[UUID, StudyTask]:
        if not activity_ids:
            return {}
        return {task.activity_id: task for task in self.session.scalars(
            select(StudyTask).where(StudyTask.activity_id.in_(activity_ids),
                                    StudyTask.deleted_at.is_(None))
        )}

    # --- пояснение и медиа ----------------------------------------------------------

    def _note(self, block: LessonBlock, lesson_title: str) -> list[ir.Block]:
        body = note_body(block.body_md)
        if not body:
            return []
        if block.variant == LessonNoteVariant.HEADING:
            return heading_blocks(body, lesson_title)
        blocks = parse_markdown(body)
        title = CALLOUT_TITLES.get(block.variant) if block.variant else None
        if title:
            blocks = [ir.Callout(block.variant.value, title, blocks)]
        if block.origin in {LessonBlockOrigin.MODEL, LessonBlockOrigin.MIXED}:
            # FR-L5: текст модели не выдаётся за текст учебника и на бумаге.
            who = "ИИ, правлено вами" if block.origin == LessonBlockOrigin.MIXED else "ИИ"
            blocks.append(ir.Paragraph([ir.Emph([ir.Text(f"{who} · пояснение модели")])],
                                       muted=True))
        return blocks

    def _media(self, block: LessonBlock) -> list[ir.Block]:
        caption = inline_markdown(block.body_md) if (block.body_md or "").strip() else []
        kind = media_kind(block)
        if kind == "link":
            label = caption or [ir.Text(block.media_path or "")]
            return [ir.Paragraph([ir.Text("Ссылка: "), ir.Link(block.media_path or "", label)])]
        if kind == "image":
            path = material_path(block.media_path or "")
            if path.exists():
                return [ir.Figure(self._printable(path), caption, width=None,
                                  alt=ir.plain_text(caption))]
        return []

    # --- кусок материала ------------------------------------------------------------

    def _ref_caption(self, ref: LessonSourceRef) -> str:
        piece = self._piece(ref)
        name = _source_name(piece.material, piece.link, ref.source_name_snapshot)
        return f"{name}, {pages_label(ref.page_from, ref.page_to)}"

    def _piece(self, ref: LessonSourceRef) -> _Piece:
        material = self.session.get(Material, ref.material_id) if ref.material_id else None
        link = (self.session.get(ProjectMaterial, (self.project_id, material.id))
                if material is not None else None)
        return _Piece(ref, material, link)

    def _source(self, block: LessonBlock, ref: LessonSourceRef, shown: list[int]
                ) -> list[ir.Block]:
        piece = self._piece(ref)
        title = self._ref_caption(ref)
        if block.collapsed or self.options.sources == "reference":
            return [ir.Paragraph([ir.Emph([ir.Text(f"В учебнике: {title}")])], muted=True)]
        if not piece.available:
            if ref.snapshot_md:
                return [ir.SourceBox(title, parse_markdown(ref.snapshot_md),
                                     note="Материала нет в этой установке — снимок текста")]
            return [ir.SourceBox(title, [], note="Источник недоступен: материал убран из проекта")]
        if ref.from_fragment_id is not None:
            title += " · с абзаца"
        return [ir.SourceBox(title, self.piece_blocks(piece, shown))]

    def piece_blocks(self, piece: _Piece, shown: list[int] | None) -> list[ir.Block]:
        """Содержимое куска: вырез области, листы страниц или текст фрагментов.

        `shown` — листы режима «Страницы» (лист общий у двух кусков рисуется один раз);
        None — показать весь диапазон ссылки.
        """
        ref, material = piece.ref, piece.material
        assert material is not None
        if ref.region_bbox is not None:
            picture = self._page_picture(material, ref.page_from, ref.region_bbox)
            return [ir.Figure(picture, width=_region_width(ref.region_bbox))] if picture else []
        parsed = material.active_parse_revision > 0
        if self.options.sources == "pages" or ref.always_pages or not parsed:
            pages = shown if shown is not None and self.options.sources == "pages" \
                else list(range(ref.page_from, ref.page_to + 1))
            figures = [self._page_figure(material, page) for page in pages]
            if any(figures) or not parsed:
                return [figure for figure in figures if figure is not None]
        return self._fragment_blocks(material, ref)

    def _fragment_blocks(self, material: Material, ref: LessonSourceRef) -> list[ir.Block]:
        order = refs_module.load_order(self.session, material, ref.page_from, ref.page_to)
        ids = refs_module.content_fragment_ids(order, refs_module.bounds_of(ref))
        if not ids:
            return []
        rows = {fragment.id: fragment for fragment in self.session.scalars(
            select(MaterialFragment).where(MaterialFragment.id.in_(ids))
        )}
        blocks: list[ir.Block] = []
        for fragment_id in ids:
            fragment = rows.get(fragment_id)
            if fragment is not None:
                blocks += self.fragment_blocks(fragment)
        return blocks

    def fragment_blocks(self, fragment: MaterialFragment) -> list[ir.Block]:
        """Один фрагмент — по правилам `StructuredPage`."""
        text = fragment.text or ""
        match fragment.element_kind:
            case "heading":
                level = fragment.structure_level or 1
                return [ir.Heading(3 if level <= 1 else 4 if level == 2 else 5,
                                   text_with_math(text.strip()))]
            case "list":
                return [ir.Paragraph(text_with_math(text.strip()),
                                     indent=max(1, fragment.structure_level or 1))]
            case "formula":
                return self._formula(fragment)
            case "table":
                table = fragment_table(text)
                return [table] if table else [ir.Paragraph(text_with_math(text))]
            case "image":
                return self._fragment_image(fragment)
        return [ir.Paragraph(text_with_math(text.strip()))] if text.strip() else []

    def _formula(self, fragment: MaterialFragment) -> list[ir.Block]:
        source = (fragment.text or "").strip()
        runs, leftover = formula_runs(source)
        if runs and leftover:
            return [ir.Paragraph(text_with_math(source))]
        pieces = runs or [latex_from_fragment(source)]
        from_ocr = fragment.recognition_source == RecognitionSource.OCR
        if all(formula_looks_reliable(piece, from_ocr=from_ocr) for piece in pieces):
            return [ir.MathBlock(piece) for piece in pieces]
        asset = self._asset(fragment)
        if asset is not None:
            return [ir.Figure(asset)]
        return [ir.CodeBlock(source)] if source else []

    def _fragment_image(self, fragment: MaterialFragment) -> list[ir.Block]:
        visual = fragment.visual or {}
        described = visual.get("processing") == "described"
        text = (fragment.text or "").replace(MODEL_DESCRIPTION_MARK, "").strip()
        placeholder = text.strip("[]").lower() in {"изображение", "image", ""}
        asset = self._asset(fragment)
        caption = text_with_math(text) if described and text else []
        if asset is not None:
            return [ir.Figure(asset, caption)]
        if fragment.recognition_source != RecognitionSource.NATIVE and not placeholder:
            return [ir.Paragraph(text_with_math(text))]
        return []

    def _asset(self, fragment: MaterialFragment) -> Path | None:
        if not fragment.asset_path:
            return None
        try:
            path = material_path(fragment.asset_path)
        except RuntimeError:
            return None
        return self._printable(path) if path.exists() else None

    # --- картинки ---------------------------------------------------------------------

    def _next_name(self, suffix: str) -> Path:
        self._pictures += 1
        return self.workdir / f"picture-{self._pictures}{suffix}"

    def _printable(self, path: Path) -> Path:
        """PNG и JPEG идут как есть; WebP и GIF переводятся: pdflatex их не читает."""
        if path.suffix.lower() in {".png", ".jpg", ".jpeg"}:
            return path
        target = self._next_name(".png")
        with Image.open(path) as image:
            image.convert("RGBA" if image.mode in {"RGBA", "LA", "P"} else "RGB").save(target)
        return target

    def _page_figure(self, material: Material, page: int) -> ir.Figure | None:
        picture = self._page_picture(material, page, None)
        return ir.Figure(picture, [ir.Text(f"Страница {page}")], width=1.0) if picture else None

    def _page_picture(self, material: Material, page: int, bbox: list[float] | None
                      ) -> Path | None:
        """Лист или его область: из PDF — растр для печати, у картинки — её вырез."""
        source = library.raster_source(self.session, material.id)
        if source is None:
            return None
        target = self._next_name(".jpg")
        if source.suffix.lower() == ".pdf":
            with fitz.open(source) as document:
                if not 1 <= page <= len(document):
                    return None
                sheet = document[page - 1]
                clip = None
                if bbox is not None:
                    rect = sheet.rect
                    clip = fitz.Rect(
                        rect.x0 + bbox[0] * rect.width, rect.y0 + bbox[1] * rect.height,
                        rect.x0 + bbox[2] * rect.width, rect.y0 + bbox[3] * rect.height,
                    )
                pixmap = sheet.get_pixmap(matrix=fitz.Matrix(PRINT_ZOOM, PRINT_ZOOM), clip=clip,
                                          alpha=False)
                pixmap.pil_save(target, format="JPEG", quality=JPEG_QUALITY)
            return target
        with Image.open(source) as image:
            picture = image.convert("RGB")
            if bbox is not None:
                width, height = picture.size
                picture = picture.crop((int(bbox[0] * width), int(bbox[1] * height),
                                        int(bbox[2] * width), int(bbox[3] * height)))
            picture.save(target, format="JPEG", quality=JPEG_QUALITY)
        return target


def _region_width(bbox: list[float]) -> float:
    """Вырез занимает на бумаге ту же долю ширины, что на листе, но не меньше трети."""
    return max(0.33, min(1.0, bbox[2] - bbox[0]))


def _label_order(label: str) -> int:
    return int(label[1:]) if label[1:].isdigit() else 0


def note_body(body: str | None) -> str:
    """Как `noteBody` урока: строки `<br />` Crepe — пустые абзацы, а не текст."""
    text = re.sub(r"^[ \t]*<br\s*/?>[ \t]*$", "", body or "", flags=re.IGNORECASE | re.MULTILINE)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def heading_blocks(body: str, lesson_title: str) -> list[ir.Block]:
    """Блок «Заголовок»: уровень из `#`, без решёток — первая строка (`headingOf`)."""
    lines = body.split("\n")
    first = next((i for i, line in enumerate(lines) if line.strip()), None)
    if first is None:
        return []
    rest = "\n".join(lines[first + 1 :]).strip()
    marked = re.match(r"^(#{1,6})\s+(.*)$", lines[first].strip())
    text, level = (marked.group(2), min(4, max(2, len(marked.group(1))))) if marked \
        else (lines[first].strip(), 3)
    blocks: list[ir.Block] = []
    # Заголовок, повторяющий название урока, в уроке скрыт — и в файле тоже.
    if text.strip() != lesson_title.strip():
        blocks.append(ir.Heading(level, inline_markdown(text)))
    if rest:
        blocks += parse_markdown(rest)
    return blocks


# --- задания ----------------------------------------------------------------------------


def task_blocks(task: StudyTask, number: int) -> tuple[ir.TaskBox, ir.Answer]:
    """Условие задания для бумаги и его ответ для раздела «Ответы»."""
    payload, key = task.payload or {}, task.answer_key or {}
    prompt = task.prompt_md or ""
    if task.form == StudyTaskForm.FILL_BLANKS:
        prompt = re.sub(r"\{\{(\d+)\}\}", lambda m: f"\\_\\_\\_\\_\\_\\_ ({m.group(1)})", prompt)
    blocks: list[ir.Block] = parse_markdown(prompt)
    answer: list[ir.Block] = []
    match task.form:
        case StudyTaskForm.SINGLE_CHOICE | StudyTaskForm.MULTIPLE_CHOICE:
            options = [str(item) for item in payload.get("options", [])]
            blocks.append(ir.ListBlock(True, [[ir.Paragraph(inline_markdown(item))]
                                              for item in options]))
            correct = [index for index in key.get("correct", []) if 0 <= index < len(options)]
            answer.append(ir.Paragraph([ir.Text("Верно: ")] + _joined(
                [[ir.Text(f"{index + 1}) ")] + inline_markdown(options[index])
                 for index in correct], "; ")))
        case StudyTaskForm.FILL_BLANKS:
            answer.append(ir.Paragraph(_joined(
                [[ir.Text(f"({index + 1}) ")] + inline_markdown(" / ".join(values))
                 for index, values in enumerate(key.get("answers", []))], "; ")))
        case StudyTaskForm.NUMERIC:
            unit = payload.get("unit")
            blocks.append(ir.Paragraph([ir.Text("Ответ: ________" + (f" {unit}" if unit else ""))]))
            answer.append(ir.Paragraph([ir.Text(_numeric_answer(key, unit))]))
        case StudyTaskForm.ORDERING:
            items = [str(item) for item in payload.get("items", [])]
            blocks.append(ir.ListBlock(True, [[ir.Paragraph(inline_markdown(item))]
                                              for item in items]))
            order = [index for index in key.get("order", []) if 0 <= index < len(items)]
            answer.append(ir.Paragraph([ir.Text(" → ".join(str(index + 1) for index in order))]))
        case StudyTaskForm.MATCHING:
            left = [str(item) for item in payload.get("left", [])]
            right = [str(item) for item in payload.get("right", [])]
            rows = []
            for index in range(max(len(left), len(right))):
                rows.append([
                    [ir.Text(f"{index + 1}. ")] + inline_markdown(left[index])
                    if index < len(left) else [],
                    [ir.Text(f"{LETTERS[index]}. ")] + inline_markdown(right[index])
                    if index < len(right) and index < len(LETTERS) else [],
                ])
            blocks.append(ir.Table([[ir.Text("Понятие")], [ir.Text("Соответствие")]], rows,
                                   [None, None]))
            match_key = key.get("match", [])
            answer.append(ir.Paragraph([ir.Text(", ".join(
                f"{index + 1} — {LETTERS[target]}" for index, target in enumerate(match_key)
                if 0 <= target < len(LETTERS)))]))
        case StudyTaskForm.OPEN_ANSWER:
            if task.reference_md:
                answer.append(ir.Paragraph([ir.Strong([ir.Text("Образец ответа")])]))
                answer += parse_markdown(task.reference_md)
            points = [str(item) for item in key.get("points", [])]
            if points:
                answer.append(ir.Paragraph([ir.Strong([ir.Text("Что должно быть в ответе")])]))
                answer.append(ir.ListBlock(False, [[ir.Paragraph(inline_markdown(point))]
                                                   for point in points]))
    if task.hint_md:
        blocks.append(ir.Paragraph([ir.Emph([ir.Text("Подсказка: ")] +
                                            inline_markdown(task.hint_md))], muted=True))
    if task.explanation_md:
        answer.append(ir.Paragraph([ir.Strong([ir.Text("Разбор")])]))
        answer += parse_markdown(task.explanation_md)
    return ir.TaskBox(number, TASK_LABELS[task.form], blocks), ir.Answer(number, answer)


def _joined(parts: list[list[ir.Inline]], separator: str) -> list[ir.Inline]:
    nodes: list[ir.Inline] = []
    for index, part in enumerate(parts):
        if index:
            nodes.append(ir.Text(separator))
        nodes += part
    return nodes


def _numeric_answer(key: dict, unit: str | None) -> str:
    value = key.get("value")
    tolerance = key.get("tolerance") or 0
    text = _number(value)
    if tolerance:
        text += f" ± {_number(tolerance * 100)} %" if key.get("relative") \
            else f" ± {_number(tolerance)}"
    return text + (f" {unit}" if unit else "")


def _number(value: object) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).replace(".", ",")


# --- вход -------------------------------------------------------------------------------


def load_lessons(session: Session, project_id: UUID, lesson_ids: list[UUID]) -> list[Lesson]:
    """Уроки проекта в присланном порядке; чужой или удалённый урок — 404."""
    found = {lesson.id: lesson for lesson in session.scalars(
        select(Lesson).where(Lesson.project_id == project_id, Lesson.id.in_(lesson_ids))
    )}
    missing = [lesson_id for lesson_id in lesson_ids if lesson_id not in found]
    if missing:
        raise ProjectNotFoundError("Урок не найден", context={"lesson_id": str(missing[0])})
    if not lesson_ids:
        raise ProjectDomainError("Выберите хотя бы один урок", status=422,
                                 code="lesson_export_empty")
    return [found[lesson_id] for lesson_id in lesson_ids]

