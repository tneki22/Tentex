"""Текст DOCX вместе с формулами Word и таблицами.

`python-docx` отдаёт `paragraph.text` только из обычных прогонов, а
`document.paragraphs` — только абзацы тела. Формулы редактора Word (OMML,
`<m:oMath>`) из текста абзаца пропадали целиком — «Пусть  – произвольные
формулы», — а таблицы не попадали в материал вовсе.

Здесь абзац читается по порядку своих узлов: прогоны текстом, формула — в
LaTeX (`$...$` в строке, `$$...$$` отдельной строкой), и тело документа
обходится вместе с таблицами. OMML переводится в LaTeX по его же структуре:
дробь, индексы, корень, скобки, n-арные операторы, черта, матрица, система.
Это точнее любого распознавания — формула в файле уже записана структурой.
"""

from __future__ import annotations

import re
from collections.abc import Iterator

from app.materials.parsers.formula_zones import SYMBOL_ENCODING

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
M = "{http://schemas.openxmlformats.org/officeDocument/2006/math}"

# Знаки, которые KaTeX понимает и так, но команда надёжнее и ищется поиском.
UNICODE_COMMANDS = {
    "∧": r"\wedge ", "∨": r"\vee ", "¬": r"\neg ", "→": r"\to ", "←": r"\leftarrow ",
    "↔": r"\leftrightarrow ", "⇒": r"\Rightarrow ", "⇐": r"\Leftarrow ",
    "⇔": r"\Leftrightarrow ", "≡": r"\equiv ", "≤": r"\le ", "≥": r"\ge ", "≠": r"\ne ",
    "≈": r"\approx ", "∈": r"\in ", "∉": r"\notin ", "∀": r"\forall ", "∃": r"\exists ",
    "∞": r"\infty ", "±": r"\pm ", "×": r"\times ", "⋅": r"\cdot ", "·": r"\cdot ",
    "∙": r"\cdot ", "−": "-", "…": r"\ldots ", "⋯": r"\cdots ", "⊂": r"\subset ",
    "⊃": r"\supset ", "⊆": r"\subseteq ", "⊇": r"\supseteq ", "∪": r"\cup ",
    "∩": r"\cap ", "∅": r"\varnothing ", "∂": r"\partial ", "∇": r"\nabla ",
    "⊕": r"\oplus ", "⊗": r"\otimes ", "∘": r"\circ ", "′": "'", "∼": r"\sim ",
}
LATEX_SPECIALS = {
    "\\": r"\backslash ", "{": r"\{", "}": r"\}", "#": r"\#", "$": r"\$", "%": r"\%",
    "_": r"\_", "^": r"\hat{}", "~": r"\sim ",
}
NARY = {
    "∑": r"\sum", "∏": r"\prod", "∐": r"\coprod", "∫": r"\int", "∬": r"\iint",
    "∭": r"\iiint", "∮": r"\oint", "⋃": r"\bigcup", "⋂": r"\bigcap", "⋁": r"\bigvee",
    "⋀": r"\bigwedge", "⨁": r"\bigoplus", "⨂": r"\bigotimes",
}
ACCENTS = {
    "̂": r"\hat", "̃": r"\tilde", "̇": r"\dot", "̈": r"\ddot",
    "⃗": r"\vec", "̅": r"\bar", "¯": r"\bar", "‾": r"\overline",
    "̆": r"\breve", "̌": r"\check", "́": r"\acute", "̀": r"\grave",
    "⃖": r"\overleftarrow", "⃡": r"\overleftrightarrow",
}
DELIMITERS = {
    "": ".", "{": r"\{", "}": r"\}", "|": "|", "‖": r"\|", "⌈": r"\lceil", "⌉": r"\rceil",
    "⌊": r"\lfloor", "⌋": r"\rfloor", "⟨": r"\langle", "⟩": r"\rangle", "〈": r"\langle",
    "〉": r"\rangle",
}
FUNCTIONS = frozenset({
    "sin", "cos", "tan", "cot", "sec", "csc", "arcsin", "arccos", "arctan", "sinh", "cosh",
    "tanh", "coth", "log", "lg", "ln", "exp", "lim", "sup", "inf", "max", "min", "det",
    "deg", "dim", "gcd", "arg", "ker", "tg", "ctg", "arctg", "arcctg", "sh", "ch", "th",
})
CYRILLIC_RE = re.compile(r"[А-Яа-яЁё]")
MATH_SPAN_RE = re.compile(r"\$\$.+?\$\$|\$[^$]+\$", re.DOTALL)


def _val(node, path: str, default: str | None = None) -> str | None:
    """Атрибут `m:val` свойства (`m:chr`, `m:pos`, `m:type`…)."""
    found = node.find(path)
    if found is None:
        return default
    return found.get(f"{M}val", default)


def _local(node) -> str:
    tag = node.tag if isinstance(node.tag, str) else ""
    return tag.rsplit("}", 1)[-1]


def _run_text(run) -> str:
    """Текст прогона формулы: `m:t` и обычный `w:t` внутри неё."""
    return "".join(node.text or "" for node in run.iter() if _local(node) == "t")


def _math_text(text: str) -> str:
    return "".join(UNICODE_COMMANDS.get(char) or LATEX_SPECIALS.get(char) or char for char in text)


def _math_run(run) -> str:
    text = _run_text(run)
    if not text:
        return ""
    style = _val(run, f"{M}rPr/{M}sty")
    normal = run.find(f"{M}rPr/{M}nor") is not None
    script = _val(run, f"{M}rPr/{M}scr")
    if normal or CYRILLIC_RE.search(text):
        escaped = "".join(LATEX_SPECIALS.get(char, char) for char in text)
        return rf"\text{{{escaped}}}"
    body = _math_text(text)
    if text.strip().casefold() in FUNCTIONS:
        return f"\\{text.strip()} "
    if script == "double-struck":
        return rf"\mathbb{{{body}}}"
    if script == "script":
        return rf"\mathcal{{{body}}}"
    if script == "fraktur":
        return rf"\mathfrak{{{body}}}"
    if style == "p" and len(text.strip()) > 1 and text.strip().isalpha():
        return rf"\mathrm{{{body}}}"
    return body


def _part(node, name: str) -> str:
    found = node.find(f"{M}{name}")
    return _children(found) if found is not None else ""


def _children(node) -> str:
    return "".join(_convert(child) for child in node)


def _group(text: str) -> str:
    return f"{{{text}}}"


def _delimiter(char: str) -> str:
    return DELIMITERS.get(char, char)


def _convert(node) -> str:  # noqa: C901, PLR0911, PLR0912 — таблица конструкций OMML
    name = _local(node)
    if name.endswith("Pr") or name == "ctrlPr":
        return ""
    if name == "r":
        return _math_run(node)
    if name == "f":
        numerator, denominator = _part(node, "num"), _part(node, "den")
        kind = _val(node, f"{M}fPr/{M}type", "bar")
        if kind in {"lin", "skw"}:
            return f"{_group(numerator)}/{_group(denominator)}"
        if kind == "noBar":
            return rf"\genfrac{{}}{{}}{{0pt}}{{}}{_group(numerator)}{_group(denominator)}"
        return rf"\frac{_group(numerator)}{_group(denominator)}"
    if name == "sSup":
        return f"{_group(_part(node, 'e'))}^{_group(_part(node, 'sup'))}"
    if name == "sSub":
        return f"{_group(_part(node, 'e'))}_{_group(_part(node, 'sub'))}"
    if name == "sSubSup":
        base = _group(_part(node, "e"))
        return f"{base}_{_group(_part(node, 'sub'))}^{_group(_part(node, 'sup'))}"
    if name == "sPre":
        sub, sup = _group(_part(node, "sub")), _group(_part(node, "sup"))
        return f"{{}}_{sub}^{sup}{_group(_part(node, 'e'))}"
    if name == "rad":
        degree = _part(node, "deg").strip()
        hidden = _val(node, f"{M}radPr/{M}degHide") in {"1", "on", "true"}
        body = _group(_part(node, "e"))
        return rf"\sqrt{body}" if hidden or not degree else rf"\sqrt[{degree}]{body}"
    if name == "d":
        begin = _val(node, f"{M}dPr/{M}begChr", "(")
        end = _val(node, f"{M}dPr/{M}endChr", ")")
        separator = _val(node, f"{M}dPr/{M}sepChr", "|")
        items = [_children(item) for item in node.findall(f"{M}e")]
        inner = f" {_delimiter(separator or '|')} ".join(items)
        return rf"\left{_delimiter(begin or '')}{inner}\right{_delimiter(end or '')}"
    if name == "nary":
        char = _val(node, f"{M}naryPr/{M}chr", "∫") or "∫"
        operator = NARY.get(char, _math_text(char))
        sub = "" if _val(node, f"{M}naryPr/{M}subHide") in {"1", "on"} else _part(node, "sub")
        sup = "" if _val(node, f"{M}naryPr/{M}supHide") in {"1", "on"} else _part(node, "sup")
        limits = (f"_{_group(sub)}" if sub else "") + (f"^{_group(sup)}" if sup else "")
        return f"{operator}{limits} {_part(node, 'e')}"
    if name == "acc":
        char = _val(node, f"{M}accPr/{M}chr", "̂") or "̂"
        return f"{ACCENTS.get(char, r'\hat')}{_group(_part(node, 'e'))}"
    if name == "bar":
        top = _val(node, f"{M}barPr/{M}pos", "bot") == "top"
        return rf"\{'overline' if top else 'underline'}{_group(_part(node, 'e'))}"
    if name == "groupChr":
        char = _val(node, f"{M}groupChrPr/{M}chr", "⏟") or "⏟"
        top = _val(node, f"{M}groupChrPr/{M}pos", "bot") == "top" or char == "⏞"
        return rf"\{'overbrace' if top else 'underbrace'}{_group(_part(node, 'e'))}"
    if name in {"limLow", "limUpp"}:
        base, limit = _part(node, "e").strip(), _part(node, "lim")
        if name == "limLow" and base.strip("\\ ") in FUNCTIONS:
            return f"{base}_{_group(limit)}"
        command = "underset" if name == "limLow" else "overset"
        return rf"\{command}{_group(limit)}{_group(base)}"
    if name == "func":
        return f"{_part(node, 'fName')}{_group(_part(node, 'e'))}"
    if name == "eqArr":
        rows = [_children(item) for item in node.findall(f"{M}e")]
        environment = "aligned" if any("&" in row for row in rows) else "gathered"
        return rf"\begin{{{environment}}}" + r" \\ ".join(rows) + rf"\end{{{environment}}}"
    if name == "m":
        rows = [
            " & ".join(_children(cell) for cell in row.findall(f"{M}e"))
            for row in node.findall(f"{M}mr")
        ]
        return r"\begin{matrix}" + r" \\ ".join(rows) + r"\end{matrix}"
    if name == "borderBox":
        return rf"\boxed{_group(_part(node, 'e'))}"
    if name == "phant":
        return rf"\phantom{_group(_part(node, 'e'))}"
    return _children(node)


def omml_latex(node) -> str:
    """LaTeX формулы `m:oMath` без обрамления `$`."""
    latex = _children(node)
    # В системе уравнений Word ставит `&` точкой выравнивания; вне её это знак.
    if r"\begin{aligned}" not in latex:
        latex = latex.replace("&", r"\&")
    return re.sub(r"\s+", " ", latex).strip()


def _symbol(node) -> str:
    """`w:sym` — знак шрифта Symbol или Wingdings по коду."""
    code = node.get(f"{W}char", "")
    try:
        value = int(code, 16)
    except ValueError:
        return ""
    if "symbol" in node.get(f"{W}font", "").casefold():
        return SYMBOL_ENCODING.get(value & 0xFF, "")
    return ""


def _run(node) -> str:
    parts: list[str] = []
    for child in node:
        name = _local(child)
        if name == "t":
            parts.append(child.text or "")
        elif name == "tab":
            parts.append("\t")
        elif name in {"br", "cr"}:
            parts.append("\n")
        elif name == "noBreakHyphen":
            parts.append("-")
        elif name == "sym":
            parts.append(_symbol(child))
    return "".join(parts)


def paragraph_text(paragraph_node) -> str:
    """Текст абзаца `w:p` с формулами Word в LaTeX, в порядке узлов."""
    return "".join(_inline(paragraph_node)).strip()


def _inline(node) -> Iterator[str]:
    for child in node:
        name = _local(child)
        tag = child.tag if isinstance(child.tag, str) else ""
        if tag.startswith(M) and name == "oMathPara":
            formulas = [omml_latex(item) for item in child.iter(f"{M}oMath")]
            yield " ".join(f"$${latex}$$" for latex in formulas if latex)
        elif tag.startswith(M) and name == "oMath":
            latex = omml_latex(child)
            if latex:
                yield f"${latex}$"
        elif name == "r":
            yield _run(child)
        elif name in {"del", "pPr", "rPr", "moveFrom"}:
            continue
        else:
            # Гиперссылка, правка, поле, смарт-тег: текст внутри них тот же абзац.
            yield from _inline(child)


def display_only(text: str) -> bool:
    """Абзац — одна выносная формула (или несколько подряд) без текста вокруг."""
    return bool(text) and not MATH_SPAN_RE.sub("", text).strip() and text.startswith("$$")


def _cell_text(cell_node) -> str:
    texts = [paragraph_text(node) for node in cell_node.iter(f"{W}p")]
    return " ".join(text for text in texts if text)


def _escaped_cell(text: str) -> str:
    """Черта в ячейке экранируется — кроме черты внутри формулы."""
    parts: list[str] = []
    cursor = 0
    for match in MATH_SPAN_RE.finditer(text):
        parts.append(text[cursor : match.start()].replace("|", r"\|"))
        parts.append(match.group(0).replace("$$", "$"))
        cursor = match.end()
    parts.append(text[cursor:].replace("|", r"\|"))
    return " ".join("".join(parts).split())


def table_markdown(table_node) -> str:
    """Таблица `w:tbl` в Markdown: объединённые ячейки — один раз, остальное пусто."""
    rows: list[list[str]] = []
    for row in table_node.findall(f"{W}tr"):
        cells: list[str] = []
        for cell in row.findall(f"{W}tc"):
            span = cell.find(f"{W}tcPr/{W}gridSpan")
            width = int(span.get(f"{W}val", "1")) if span is not None else 1
            merged = cell.find(f"{W}tcPr/{W}vMerge")
            continued = merged is not None and merged.get(f"{W}val", "continue") != "restart"
            text = "" if continued else _escaped_cell(_cell_text(cell))
            cells.extend([text, *([""] * (max(1, width) - 1))])
        if cells:
            rows.append(cells)
    if not rows or not any(any(cell for cell in row) for row in rows):
        return ""
    columns = max(len(row) for row in rows)
    rows = [row + [""] * (columns - len(row)) for row in rows]
    lines = [
        "| " + " | ".join(rows[0]) + " |",
        "|" + "|".join(["---"] * columns) + "|",
        *("| " + " | ".join(row) + " |" for row in rows[1:]),
    ]
    return "\n".join(lines)
