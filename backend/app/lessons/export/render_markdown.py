"""Узлы `ir` → Markdown в том же диалекте, что пишут пояснения урока.

Формулы остаются `$…$` и `$$…$$`, поэтому текст вставляется обратно в пояснение
Tentex и рисуется тем же KaTeX. Картинки — относительные пути `images/…`.
"""

from __future__ import annotations

import re
from pathlib import Path

from app.lessons.export import ir

_ESCAPE = re.compile(r"([\\`*_\[\]<>$|])")
_LINE_START = re.compile(r"^(\s*)([#>+\-=]|\d+[.)])")


class AssetNames:
    """Имена картинок внутри архива: одна картинка — одно имя, сколько бы раз ни встретилась."""

    def __init__(self, folder: str = "images") -> None:
        self.folder = folder
        self.names: dict[Path, str] = {}

    def name(self, path: Path) -> str:
        if path not in self.names:
            suffix = path.suffix.lower() or ".png"
            self.names[path] = f"{self.folder}/image-{len(self.names) + 1}{suffix}"
        return self.names[path]


def _text(value: str) -> str:
    return _ESCAPE.sub(r"\\\1", value)


class MarkdownRenderer:
    def __init__(self, assets: AssetNames | None = None, *, images: bool = True) -> None:
        self.assets = assets or AssetNames()
        # Снимок куска для файла переноса картинок не несёт — только подпись.
        self.images = images

    # --- строка ---------------------------------------------------------------------

    def inline(self, nodes: list[ir.Inline]) -> str:
        parts: list[str] = []
        for node in nodes:
            match node:
                case ir.Text(text):
                    parts.append(_text(text))
                case ir.Strong(children):
                    parts.append(f"**{self.inline(children).strip()}**")
                case ir.Emph(children):
                    parts.append(f"*{self.inline(children).strip()}*")
                case ir.Strike(children):
                    parts.append(f"~~{self.inline(children)}~~")
                case ir.Code(text):
                    fence = "``" if "`" in text else "`"
                    parts.append(f"{fence}{text}{fence}")
                case ir.Math(tex, display):
                    parts.append(f"$${tex}$$" if display else f"${tex}$")
                case ir.Link(href, children):
                    parts.append(f"[{self.inline(children)}]({href})")
                case ir.Citation(label):
                    parts.append(f"[{label}]")
                case ir.LineBreak():
                    parts.append("<br />")
        return "".join(parts)

    def _line(self, nodes: list[ir.Inline]) -> str:
        """Строка абзаца: знак в начале не должен превратиться в список или заголовок."""
        return _LINE_START.sub(lambda m: m.group(1) + "\\" + m.group(2), self.inline(nodes))

    # --- блоки ----------------------------------------------------------------------

    def blocks(self, blocks: list[ir.Block]) -> str:
        return "\n\n".join(part for part in (self.block(block) for block in blocks) if part)

    def block(self, block: ir.Block) -> str:
        match block:
            case ir.Heading(level, content):
                return f"{'#' * min(6, level)} {self.inline(content)}"
            case ir.Paragraph(content, indent, _muted):
                return ("  " * max(0, indent - 1)) + self._line(content)
            case ir.ListBlock(ordered, items, start):
                return self._list(ordered, items, start)
            case ir.Quote(blocks):
                return _quoted(self.blocks(blocks))
            case ir.CodeBlock(text, lang):
                fence = "````" if "```" in text else "```"
                return f"{fence}{lang}\n{text}\n{fence}"
            case ir.MathBlock(tex):
                return f"$$\n{tex}\n$$"
            case ir.Table():
                return self._table(block)
            case ir.Rule():
                return "---"
            case ir.Figure(path, caption, _width, alt):
                caption_text = self.inline(caption)
                if not self.images:
                    return f"*[Рисунок{': ' + caption_text if caption_text else ''}]*"
                image = f"![{_text(alt or ir.plain_text(caption))}]({self.assets.name(path)})"
                return f"{image}\n\n*{caption_text}*" if caption_text else image
            case ir.Callout(_kind, title, blocks):
                body = self.blocks(blocks)
                return _quoted(f"**{title}.** {body}" if body else f"**{title}.**")
            case ir.SourceBox(title, blocks, note):
                head = f"*Из материала: {_text(title)}*"
                if note:
                    head += f"  \n*{_text(note)}*"
                body = self.blocks(blocks)
                return _quoted(f"{head}\n\n{body}" if body else head)
            case ir.TaskBox(number, label, blocks):
                body = self.blocks(blocks)
                return f"**Задание {number}.** *{label}*\n\n{body}".rstrip()
        return ""

    def _list(self, ordered: bool, items: list[list[ir.Block]], start: int) -> str:
        lines: list[str] = []
        for index, item in enumerate(items):
            marker = f"{start + index}. " if ordered else "- "
            body = self.blocks(item) or ""
            indented = body.replace("\n", "\n" + " " * len(marker))
            lines.append(marker + indented)
        return "\n".join(lines)

    def _table(self, table: ir.Table) -> str:
        width = max([len(table.head)] + [len(row) for row in table.rows])

        def row(cells: list[list[ir.Inline]]) -> str:
            values = [self.inline(cell).replace("\n", " ") for cell in cells]
            values += [""] * (width - len(values))
            return "| " + " | ".join(values) + " |"

        divider = []
        for index in range(width):
            align = table.align[index] if index < len(table.align) else None
            divider.append({"center": ":---:", "right": "---:", "left": ":---"}.get(
                align or "", "---"))
        return "\n".join([row(table.head), "| " + " | ".join(divider) + " |",
                          *(row(cells) for cells in table.rows)])

    # --- документ -------------------------------------------------------------------

    def lesson(self, lesson: ir.LessonDoc) -> str:
        parts = [f"# {_text(lesson.title)}"]
        if lesson.goal:
            parts.append(f"*Цель:* {_text(lesson.goal)}")
        if lesson.topics:
            parts.append(f"*Темы:* {_text('; '.join(lesson.topics))}")
        body = self.blocks(lesson.blocks)
        if body:
            parts.append(body)
        if lesson.citations:
            parts.append("## Опоры пояснений")
            parts.append("\n".join(f"- **{label}** — {_text(text)}"
                                   for label, text in lesson.citations))
        if lesson.answers:
            parts.append("## Ответы к заданиям")
            for answer in lesson.answers:
                parts.append(f"**{answer.number}.** " + (self.blocks(answer.blocks) or "—"))
        return "\n\n".join(parts)

    def document(self, doc: ir.ExportDoc) -> str:
        return "\n\n---\n\n".join(self.lesson(lesson) for lesson in doc.lessons) + "\n"


def _quoted(text: str) -> str:
    return "\n".join("> " + line if line else ">" for line in text.split("\n"))
