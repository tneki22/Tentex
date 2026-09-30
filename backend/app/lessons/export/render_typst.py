"""Узлы `ir` → разметка Typst для `main.typ`; оформление — в `typst/lesson.typ`.

Текст экранируется целиком: учебник полон `*`, `_`, `#` и `//`, и ни один из них
не должен стать разметкой. Формулы в разметку не попадают — только ключ `fx("…")`,
по которому шаблон берёт готовый SVG (`pdf.py`).
"""

from __future__ import annotations

from app.lessons.export import ir
from app.lessons.export.render_markdown import AssetNames

# Знаки со смыслом в разметке Typst; `(`, `.` и `;` — чтобы текст сразу за
# встроенным вызовом не продолжил выражение.
_SPECIAL = set("\\#$*_`<>@[]=-+/~'\".:();")


def escape(text: str) -> str:
    return "".join("\\" + char if char in _SPECIAL else char for char in text)


def string(value: str) -> str:
    """Строковый литерал Typst."""
    cleaned = "".join(char for char in value if char >= " " or char in "\n\t")
    escaped = cleaned.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    return '"' + escaped.replace("\t", "\\t") + '"'


class FormulaSet:
    """Уникальные формулы документа; ключ стабилен в пределах одного экспорта."""

    def __init__(self) -> None:
        self.keys: dict[tuple[str, bool], str] = {}

    def key(self, tex: str, display: bool) -> str:
        item = (tex, display)
        if item not in self.keys:
            self.keys[item] = f"f{len(self.keys)}"
        return self.keys[item]


class TypstRenderer:
    def __init__(self, formulas: FormulaSet, assets: AssetNames) -> None:
        self.formulas = formulas
        self.assets = assets

    # --- строка ---------------------------------------------------------------------

    def inline(self, nodes: list[ir.Inline]) -> str:
        parts: list[str] = []
        for node in nodes:
            match node:
                case ir.Text(text):
                    parts.append(escape(text.replace("\n", " ")))
                case ir.Strong(children):
                    parts.append(f"#strong[{self.inline(children)}];")
                case ir.Emph(children):
                    parts.append(f"#emph[{self.inline(children)}];")
                case ir.Strike(children):
                    parts.append(f"#strike[{self.inline(children)}];")
                case ir.Code(text):
                    parts.append(f"#raw({string(text)});")
                case ir.Math(tex, display):
                    parts.append(f'#fx("{self.formulas.key(tex, display)}");')
                case ir.Link(href, children):
                    parts.append(f"#link({string(href)})[{self.inline(children)}];")
                case ir.Citation(label):
                    parts.append(f"#cite-mark({string(label)});")
                case ir.LineBreak():
                    parts.append("#linebreak();")
        return "".join(parts)

    # --- блоки ----------------------------------------------------------------------

    def blocks(self, blocks: list[ir.Block]) -> str:
        return "\n\n".join(part for part in (self.block(block) for block in blocks) if part)

    def block(self, block: ir.Block) -> str:
        match block:
            case ir.Heading(level, content):
                return f"#heading(level: {min(6, level)})[{self.inline(content)}]"
            case ir.Paragraph(content, indent, muted):
                text = self.inline(content)
                if not text:
                    return ""
                if muted:
                    text = f"#muted[{text}]"
                if indent > 1:
                    return f"#pad(left: {1.2 * (indent - 1):.1f}em)[{text}]"
                # Не `#par[…]`: явный абзац не может содержать блоков, и выносная
                # формула `$$…$$` посреди текста молча пропала бы.
                return text
            case ir.ListBlock(ordered, items, start):
                body = ", ".join(f"[{self.blocks(item)}]" for item in items)
                if ordered:
                    return f"#enum(start: {start}, {body})"
                return f"#list({body})"
            case ir.Quote(blocks):
                return f"#quote[{self.blocks(blocks)}]"
            case ir.CodeBlock(text, lang):
                language = f", lang: {string(lang)}" if lang else ""
                return f"#raw(block: true{language}, {string(text)})"
            case ir.MathBlock(tex):
                return f'#fx("{self.formulas.key(tex, True)}")'
            case ir.Table():
                return self._table(block)
            case ir.Rule():
                return "#line(length: 100%, stroke: 0.5pt + hairline)"
            case ir.Figure(path, caption, width):
                name = self.assets.name(path)
                arguments = [string(name)]
                if width:
                    arguments.append(f"width: {width:.3f}")
                if caption:
                    arguments.append(f"caption: [{self.inline(caption)}]")
                return f"#picture({', '.join(arguments)})"
            case ir.Callout(kind, title, blocks):
                return f"#callout({string(kind)}, {string(title)})[{self.blocks(blocks)}]"
            case ir.SourceBox(title, blocks, note):
                note_arg = f", note: {string(note)}" if note else ""
                return f"#source-box({string(title)}{note_arg})[{self.blocks(blocks)}]"
            case ir.TaskBox(number, label, blocks):
                return f"#task-box({number}, {string(label)})[{self.blocks(blocks)}]"
        return ""

    def _table(self, table: ir.Table) -> str:
        width = max([len(table.head)] + [len(row) for row in table.rows] + [1])

        def cells(row: list[list[ir.Inline]]) -> list[str]:
            values = [f"[{self.inline(cell)}]" for cell in row]
            return values + ["[]"] * (width - len(values))

        parts = [f"columns: {width}"]
        if any(table.head):
            parts.append(f"table.header({', '.join(cells(table.head))})")
        for row in table.rows:
            parts += cells(row)
        return f"#table({', '.join(parts)})"

    # --- документ -------------------------------------------------------------------

    def lesson(self, lesson: ir.LessonDoc) -> str:
        parts = [f"#heading(level: 1)[{escape(lesson.title)}]"]
        head = []
        if lesson.topics:
            head.append(f"topics: {string('; '.join(lesson.topics))}")
        if lesson.goal:
            head.append(f"goal: {string(lesson.goal)}")
        parts.append(f"#lesson-head({', '.join(head)})")
        body = self.blocks(lesson.blocks)
        if body:
            parts.append(body)
        if lesson.citations:
            parts.append("#heading(level: 2, outlined: false)[Опоры пояснений]")
            parts.append("#list(" + ", ".join(
                f"[#strong[{escape(label)}] — {escape(text)}]"
                for label, text in lesson.citations) + ")")
        if lesson.answers:
            parts.append("#heading(level: 2, outlined: false)[Ответы к заданиям]")
            for answer in lesson.answers:
                parts.append(f"#answer({answer.number})[{self.blocks(answer.blocks) or '—'}]")
        return "\n\n".join(parts)

    def document(self, doc: ir.ExportDoc) -> str:
        header = [
            '#import "lesson.typ": *',
            f"#show: lesson-doc.with(title: {string(doc.title)}, lessons: {len(doc.lessons)})",
        ]
        return "\n".join(header) + "\n\n" + "\n\n".join(
            self.lesson(lesson) for lesson in doc.lessons) + "\n"
