"""Разбор текста урока в узлы `ir`: Markdown пояснений и текст фрагментов материала.

Пояснения пишет Crepe (CommonMark + GFM + `$…$`) или модель; разбор — markdown-it.
Правила формул и опор повторяют рендер приложения (`MarkdownView`, `StructuredPage`):
`$…$`, `$$…$$`, `\\(…\\)`, `\\[…\\]` и `[S3]`, иначе PDF показал бы не то, что урок.
"""

from __future__ import annotations

import re
from functools import lru_cache

from markdown_it import MarkdownIt
from markdown_it.token import Token
from mdit_py_plugins.dollarmath import dollarmath_plugin

from app.lessons.export import ir

# Ограничители `\(…\)` и `\[…\]` приводятся к долларам до разбора: у markdown-it
# одного плагина на оба вида нет, а `MarkdownView` принимает и те и другие.
_BRACKET_DISPLAY = re.compile(r"\\\[([\s\S]+?)\\\]")
_BRACKET_INLINE = re.compile(r"\\\(([\s\S]+?)\\\)")
_CITATION = re.compile(r"\[(S\d+(?:[ \t]*[,;][ \t]*S\d+)*)\]")
_CITATION_SPLIT = re.compile(r"[ \t]*[,;][ \t]*")
_BREAK = re.compile(r"^<br\s*/?>$", re.IGNORECASE)
_FENCE = re.compile(r"^(```|~~~)")
# Как `INLINE_MATH` в `StructuredPage`: фрагмент материала — не Markdown, а текст
# с формулами, звёздочка в нём остаётся звёздочкой.
_FRAGMENT_MATH = re.compile(r"\$\$([\s\S]+?)\$\$|\$([^$\n]+?)\$|\\\(([\s\S]+?)\\\)")
_DISPLAY_RUN = re.compile(r"\$\$([\s\S]+?)\$\$|\\\[([\s\S]+?)\\\]")
_TABLE_DIVIDER = re.compile(r"^:?-{2,}:?$")


@lru_cache(maxsize=1)
def _parser() -> MarkdownIt:
    parser = MarkdownIt("commonmark", {"html": True, "linkify": False})
    parser.enable(["table", "strikethrough"])
    dollarmath_plugin(parser, allow_space=True, allow_digits=True, double_inline=True)
    return parser


def _normalize_brackets(text: str) -> str:
    """`\\[…\\]` и `\\(…\\)` вне кода — в доллары; внутри ограждённого кода текст не трогаем."""
    result: list[str] = []
    buffer: list[str] = []
    fenced = False
    for line in text.split("\n"):
        if _FENCE.match(line.strip()):
            if not fenced:
                result.append(_convert_brackets("\n".join(buffer)))
                buffer = []
            fenced = not fenced
            result.append(line)
            continue
        (result if fenced else buffer).append(line)
    result.append(_convert_brackets("\n".join(buffer)))
    return "\n".join(result)


def _convert_brackets(text: str) -> str:
    text = _BRACKET_DISPLAY.sub(lambda match: f"\n$$\n{match.group(1).strip()}\n$$\n", text)
    return _BRACKET_INLINE.sub(lambda match: f"${match.group(1).strip()}$", text)


# --- Markdown пояснения -----------------------------------------------------------------


def parse_markdown(text: str) -> list[ir.Block]:
    """Блоки пояснения; пустой абзац Crepe `<br />` пропускается, как в чтении урока."""
    tokens = _parser().parse(_normalize_brackets(text or ""))
    blocks, _ = _blocks(tokens, 0, None)
    return blocks


def _blocks(tokens: list[Token], index: int, stop: str | None) -> tuple[list[ir.Block], int]:
    blocks: list[ir.Block] = []
    while index < len(tokens):
        token = tokens[index]
        if stop is not None and token.type == stop:
            return blocks, index + 1
        match token.type:
            case "heading_open":
                level = int(token.tag[1:])
                blocks.append(ir.Heading(level, _inline(tokens[index + 1])))
                index += 3
            case "paragraph_open":
                content = _inline(tokens[index + 1])
                if content:
                    blocks.append(ir.Paragraph(content))
                index += 3
            case "bullet_list_open" | "ordered_list_open":
                ordered = token.type == "ordered_list_open"
                start = int(token.attrGet("start") or 1) if ordered else 1
                closing = token.type.replace("_open", "_close")
                items: list[list[ir.Block]] = []
                index += 1
                while tokens[index].type != closing:
                    item, index = _blocks(tokens, index + 1, "list_item_close")
                    items.append(item)
                blocks.append(ir.ListBlock(ordered, items, start))
                index += 1
            case "blockquote_open":
                inner, index = _blocks(tokens, index + 1, "blockquote_close")
                blocks.append(ir.Quote(inner))
            case "fence" | "code_block":
                blocks.append(ir.CodeBlock(token.content.rstrip("\n"), token.info.strip()))
                index += 1
            case "math_block" | "math_block_label":
                tex = token.content.strip()
                if tex:
                    blocks.append(ir.MathBlock(tex))
                index += 1
            case "hr":
                blocks.append(ir.Rule())
                index += 1
            case "table_open":
                table, index = _table(tokens, index + 1)
                blocks.append(table)
            case "html_block":
                text = token.content.strip()
                if text and not _BREAK.match(text):
                    blocks.append(ir.Paragraph([ir.Text(text)]))
                index += 1
            case _:
                index += 1
    return blocks, index


def _table(tokens: list[Token], index: int) -> tuple[ir.Table, int]:
    head: list[list[ir.Inline]] = []
    rows: list[list[list[ir.Inline]]] = []
    align: list[str | None] = []
    current: list[list[ir.Inline]] | None = None
    in_head = False
    while tokens[index].type != "table_close":
        token = tokens[index]
        if token.type == "thead_open":
            in_head = True
        elif token.type == "thead_close":
            in_head = False
        elif token.type == "tr_open":
            current = []
        elif token.type == "tr_close" and current is not None:
            if in_head:
                head = current
            else:
                rows.append(current)
            current = None
        elif token.type in {"th_open", "td_open"} and current is not None:
            style = token.attrGet("style") or ""
            if in_head:
                align.append(style.split(":")[-1] if style.startswith("text-align") else None)
            current.append(_inline(tokens[index + 1]))
        index += 1
    return ir.Table(head, rows, align), index + 1


def _inline(token: Token) -> list[ir.Inline]:
    nodes, _ = _inline_children(token.children or [], 0, None)
    return _trim(nodes)


def _inline_children(
    children: list[Token], index: int, stop: str | None
) -> tuple[list[ir.Inline], int]:
    nodes: list[ir.Inline] = []
    while index < len(children):
        token = children[index]
        if stop is not None and token.type == stop:
            return nodes, index + 1
        match token.type:
            case "text":
                nodes += _with_citations(token.content)
                index += 1
            case "softbreak":
                nodes.append(ir.Text(" "))
                index += 1
            case "hardbreak":
                nodes.append(ir.LineBreak())
                index += 1
            case "code_inline":
                nodes.append(ir.Code(token.content))
                index += 1
            case "math_inline" | "math_inline_double":
                if token.content.strip():
                    nodes.append(ir.Math(token.content.strip(),
                                         display=token.type == "math_inline_double"))
                index += 1
            case "strong_open":
                inner, index = _inline_children(children, index + 1, "strong_close")
                nodes.append(ir.Strong(inner))
            case "em_open":
                inner, index = _inline_children(children, index + 1, "em_close")
                nodes.append(ir.Emph(inner))
            case "s_open":
                inner, index = _inline_children(children, index + 1, "s_close")
                nodes.append(ir.Strike(inner))
            case "link_open":
                href = token.attrGet("href") or ""
                inner, index = _inline_children(children, index + 1, "link_close")
                nodes.append(ir.Link(str(href), inner))
            case "image":
                # Картинки пояснений живут блоком «Медиа»; в тексте остаётся подпись.
                alt = token.content or "изображение"
                nodes.append(ir.Emph([ir.Text(f"[{alt}]")]))
                index += 1
            case "html_inline":
                if _BREAK.match(token.content.strip()):
                    nodes.append(ir.LineBreak())
                index += 1
            case _:
                index += 1
    return nodes, index


def _with_citations(text: str) -> list[ir.Inline]:
    nodes: list[ir.Inline] = []
    cursor = 0
    for match in _CITATION.finditer(text):
        if match.start() > cursor:
            nodes.append(ir.Text(text[cursor : match.start()]))
        nodes += [ir.Citation(label) for label in _CITATION_SPLIT.split(match.group(1))]
        cursor = match.end()
    if cursor < len(text):
        nodes.append(ir.Text(text[cursor:]))
    return nodes


def _trim(nodes: list[ir.Inline]) -> list[ir.Inline]:
    while nodes and isinstance(nodes[-1], ir.LineBreak):
        nodes.pop()
    return nodes


# --- текст фрагментов материала ----------------------------------------------------------


def text_with_math(text: str) -> list[ir.Inline]:
    """Строка фрагмента: текст как есть, формулы — формулами (`renderInlineMath`)."""
    nodes: list[ir.Inline] = []
    cursor = 0
    for match in _FRAGMENT_MATH.finditer(text):
        if match.start() > cursor:
            nodes.append(ir.Text(text[cursor : match.start()]))
        tex = (match.group(1) or match.group(2) or match.group(3) or "").strip()
        display = match.group(1) is not None
        nodes.append(ir.Math(tex, display=display) if tex else ir.Text(match.group(0)))
        cursor = match.end()
    if cursor < len(text):
        nodes.append(ir.Text(text[cursor:]))
    return nodes


def formula_runs(text: str) -> tuple[list[str], str]:
    """Выносные формулы фрагмента-формулы и остаток текста вне них (`displayMathRuns`)."""
    runs: list[str] = []
    leftover: list[str] = []
    cursor = 0
    for match in _DISPLAY_RUN.finditer(text):
        leftover.append(text[cursor : match.start()])
        body = (match.group(1) or match.group(2) or "").strip()
        if body:
            runs.append(body)
        cursor = match.end()
    leftover.append(text[cursor:])
    return runs, "".join(leftover).strip()


def latex_from_fragment(text: str) -> str:
    """Формула без внешних ограничителей (`latexFromFragment`)."""
    value = text.strip()
    for opening, closing in (("$$", "$$"), ("\\[", "\\]"), ("\\(", "\\)"), ("$", "$")):
        if (
            len(value) >= len(opening) + len(closing)
            and value.startswith(opening)
            and value.endswith(closing)
        ):
            return value[len(opening) : len(value) - len(closing)].strip()
    return value


def formula_looks_reliable(latex: str, *, from_ocr: bool) -> bool:
    """Та же проверка, что `formulaLooksReliable`: мусор OCR формулой не рисуется."""
    compact = re.sub(r"\s+", "", latex)
    if not compact or len(compact) > 4000:
        return False
    if re.search(r"[\u3400-\u9fff\ufffd]", compact) or "$" in compact:
        return False
    if not re.search(r"[\\^_{}]", compact):
        return False
    if not from_ocr:
        return True
    tokens = re.findall(r"\\[A-Za-z]+|[A-Za-z]+|\d+|[^A-Za-z\d]", compact)
    if len(tokens) < 120:
        return True
    return len(set(tokens)) / len(tokens) >= 0.08


def split_table_row(row: str) -> list[str]:
    """Ячейки строки таблицы фрагмента; `|` внутри формулы ячейку не режет."""
    source = row.strip()
    source = source.removeprefix("|")
    if source.endswith("|") and not source.endswith("\\|"):
        source = source[:-1]
    spans = [(m.start(), m.end()) for m in re.finditer(r"\$[^$]*\$", source)]
    cells: list[str] = []
    cell: list[str] = []
    index = 0
    while index < len(source):
        char = source[index]
        if char == "\\" and source[index + 1 : index + 2] == "|":
            cell.append("|")
            index += 2
            continue
        if char == "|" and not any(start < index < end for start, end in spans):
            cells.append("".join(cell).strip())
            cell = []
        else:
            cell.append(char)
        index += 1
    cells.append("".join(cell).strip())
    return cells


def fragment_table(text: str) -> ir.Table | None:
    """Таблица фрагмента (`MarkdownTable`): строки с `|`, вторая — разделитель."""
    rows = [split_table_row(line) for line in text.split("\n") if "|" in line]
    if len(rows) < 2 or not (
        len(rows[1]) > 1 and all(_TABLE_DIVIDER.match(cell) for cell in rows[1])
    ):
        return None

    def cell(value: str) -> list[ir.Inline]:
        # В ячейках учебника бывают `**жирный**` и `<br>` — это разметка, а не текст.
        parts = re.split(r"<br\s*/?>", value, flags=re.IGNORECASE)
        nodes: list[ir.Inline] = []
        for number, part in enumerate(parts):
            if number:
                nodes.append(ir.LineBreak())
            nodes += _bold_runs(part)
        return nodes

    return ir.Table(
        head=[cell(value) for value in rows[0]],
        rows=[[cell(value) for value in row] for row in rows[2:]],
        align=[None] * len(rows[0]),
    )


def _bold_runs(text: str) -> list[ir.Inline]:
    nodes: list[ir.Inline] = []
    for number, part in enumerate(re.split(r"\*\*", text)):
        if not part:
            continue
        inner = text_with_math(part)
        nodes += [ir.Strong(inner)] if number % 2 else inner
    return nodes
