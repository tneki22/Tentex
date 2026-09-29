"""Узлы `ir` → документ LaTeX.

Формулы переносятся дословно: это тот же LaTeX, что рисует KaTeX в уроке, а
макросы, которые KaTeX знает сверх стандартного LaTeX (`\\R`, `\\degree`…),
объявлены в преамбуле. Документ собирается pdflatex, xelatex и lualatex.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

from app.lessons.export import ir
from app.lessons.export.render_markdown import AssetNames

_COMMAND = re.compile(r"\\([A-Za-z]+)")
_ENVIRONMENT = re.compile(r"\\begin\{([A-Za-z]+\*?)\}")


@lru_cache(maxsize=1)
def _katex_names() -> frozenset[str]:
    """Команды KaTeX фронтенда; список обновляет `frontend/scripts/katex-commands.mjs`."""
    path = Path(__file__).with_name("katex_commands.txt")
    return frozenset(line for line in path.read_text(encoding="utf-8").splitlines()
                     if line and not line.startswith("#"))


def katex_renders(tex: str) -> bool:
    """Формулу нарисует KaTeX урока: все команды и окружения ему известны.

    Урок показывает непонятую формулу исходником. В .tex её надо вывести так же:
    одна неизвестная `\\b` из распознавания иначе роняет сборку всего документа.
    """
    names = _katex_names()
    if any(f"env:{name}" not in names for name in _ENVIRONMENT.findall(tex)):
        return False
    return all(name in names for name in _COMMAND.findall(tex))

_SPECIAL = {
    "\\": r"\textbackslash{}",
    "{": r"\{",
    "}": r"\}",
    "$": r"\$",
    "&": r"\&",
    "#": r"\#",
    "%": r"\%",
    "_": r"\_",
    "^": r"\textasciicircum{}",
    "~": r"\textasciitilde{}",
    "<": r"\textless{}",
    ">": r"\textgreater{}",
    "|": r"\textbar{}",
}
# Знаки вне кириллицы и латиницы, которых нет в шрифте T2A pdflatex: в тексте
# учебника они встречаются постоянно («α», «≤», «→»), а без замены сборка падает.
_SYMBOLS = {
    "→": r"\rightarrow", "←": r"\leftarrow", "↔": r"\leftrightarrow", "⇒": r"\Rightarrow",
    "⇐": r"\Leftarrow", "⇔": r"\Leftrightarrow", "≤": r"\le", "≥": r"\ge", "≠": r"\ne",
    "≈": r"\approx", "±": r"\pm", "×": r"\times", "·": r"\cdot", "÷": r"\div", "∞": r"\infty",
    "∈": r"\in", "∉": r"\notin", "⊂": r"\subset", "⊆": r"\subseteq", "∪": r"\cup",
    "∩": r"\cap", "∀": r"\forall", "∃": r"\exists", "¬": r"\neg", "∧": r"\wedge",
    "∨": r"\vee", "∅": r"\varnothing", "∑": r"\sum", "∏": r"\prod", "∫": r"\int",
    "√": r"\surd", "∂": r"\partial", "∇": r"\nabla", "°": r"^\circ", "′": r"'",
    "α": r"\alpha", "β": r"\beta", "γ": r"\gamma", "δ": r"\delta", "ε": r"\varepsilon",
    "ζ": r"\zeta", "η": r"\eta", "θ": r"\theta", "ι": r"\iota", "κ": r"\kappa",
    "λ": r"\lambda", "μ": r"\mu", "ν": r"\nu", "ξ": r"\xi", "π": r"\pi", "ρ": r"\rho",
    "σ": r"\sigma", "ς": r"\varsigma", "τ": r"\tau", "υ": r"\upsilon", "φ": r"\varphi",
    "χ": r"\chi", "ψ": r"\psi", "ω": r"\omega", "Γ": r"\Gamma", "Δ": r"\Delta",
    "Θ": r"\Theta", "Λ": r"\Lambda", "Ξ": r"\Xi", "Π": r"\Pi", "Σ": r"\Sigma",
    "Φ": r"\Phi", "Ψ": r"\Psi", "Ω": r"\Omega",
}

PREAMBLE = r"""% Экспорт уроков Tentex. Собирается pdflatex, xelatex или lualatex.
% Формулы — тот же LaTeX, что рисует KaTeX в уроке.
\documentclass[11pt,a4paper]{article}
\usepackage{iftex}
\ifPDFTeX
  \usepackage[T2A]{fontenc}
  \usepackage[utf8]{inputenc}
\else
  % Шрифты по именам файлов пакета cm-unicode: так их находят и TeX Live, и MiKTeX,
  % и Tectonic, даже без системной базы шрифтов.
  \usepackage{fontspec}
  \setmainfont{cmunrm}[Extension=.otf, BoldFont=cmunbx, ItalicFont=cmunti,
    BoldItalicFont=cmunbi]
  \setsansfont{cmunss}[Extension=.otf, BoldFont=cmunsx, ItalicFont=cmunsi,
    BoldItalicFont=cmunso]
  \setmonofont{cmuntt}[Extension=.otf, BoldFont=cmuntb, ItalicFont=cmunit,
    BoldItalicFont=cmuntx]
\fi
\usepackage[russian]{babel}
\usepackage[margin=2cm]{geometry}
\usepackage{mathtools,amssymb,bm,cancel}
\usepackage{xcolor}
\usepackage{graphicx}
\usepackage[export]{adjustbox}
\usepackage{tabularx}
\usepackage[normalem]{ulem}
\usepackage[hidelinks]{hyperref}
\setlength{\parindent}{0pt}
\setlength{\parskip}{0.6em}

% Макросы, которые KaTeX понимает без пакетов.
\providecommand{\R}{\mathbb{R}}
\providecommand{\N}{\mathbb{N}}
\providecommand{\Z}{\mathbb{Z}}
\providecommand{\Q}{\mathbb{Q}}
\providecommand{\C}{\mathbb{C}}
\providecommand{\reals}{\mathbb{R}}
\providecommand{\natnums}{\mathbb{N}}
\providecommand{\Complex}{\mathbb{C}}
\providecommand{\degree}{^\circ}
\providecommand{\argmax}{\operatorname*{arg\,max}}
\providecommand{\argmin}{\operatorname*{arg\,min}}
% \tg, \ctg, \arctg, \sh, \ch объявляет babel с русским языком — как и KaTeX.

\newenvironment{lessoncallout}[1]%
  {\begin{quote}\textbf{#1.}\ }%
  {\end{quote}}
\newenvironment{lessonsource}[1]%
  {\begin{quote}{\small\color{gray}\textit{Из материала: #1}}\par}%
  {\end{quote}}
\newcommand{\lessonmuted}[1]{{\small\color{gray}#1}}
\newcommand{\lessonimage}[1]{\includegraphics[max width=\linewidth,max height=0.8\textheight]{#1}}
"""


def escape(text: str) -> str:
    out: list[str] = []
    for char in text:
        if char in _SPECIAL:
            out.append(_SPECIAL[char])
        elif char in _SYMBOLS:
            out.append(f"\\ensuremath{{{_SYMBOLS[char]}}}")
        elif char == "\u00a0":
            out.append("~")
        else:
            out.append(char)
    return "".join(out)


class LatexRenderer:
    def __init__(self, assets: AssetNames | None = None) -> None:
        self.assets = assets or AssetNames()

    def inline(self, nodes: list[ir.Inline]) -> str:
        parts: list[str] = []
        for node in nodes:
            match node:
                case ir.Text(text):
                    parts.append(escape(text))
                case ir.Strong(children):
                    parts.append(f"\\textbf{{{self.inline(children)}}}")
                case ir.Emph(children):
                    parts.append(f"\\emph{{{self.inline(children)}}}")
                case ir.Strike(children):
                    parts.append(f"\\sout{{{self.inline(children)}}}")
                case ir.Code(text):
                    parts.append(f"\\texttt{{{escape(text)}}}")
                case ir.Math(tex, display) if not katex_renders(tex):
                    source = f"$${tex}$$" if display else f"${tex}$"
                    parts.append(f"\\texttt{{{escape(source)}}}")
                case ir.Math(tex, display):
                    parts.append(f"\\[{tex}\\]" if display else f"${tex}$")
                case ir.Link(href, children):
                    target = href.replace("\\", "/").replace("%", "\\%").replace("#", "\\#")
                    parts.append(f"\\href{{{target}}}{{{self.inline(children)}}}")
                case ir.Citation(label):
                    parts.append(f"[{label}]")
                case ir.LineBreak():
                    parts.append("\\newline{}")
        return "".join(parts)

    def blocks(self, blocks: list[ir.Block]) -> str:
        return "\n\n".join(part for part in (self.block(block) for block in blocks) if part)

    def block(self, block: ir.Block) -> str:
        match block:
            case ir.Heading(level, content):
                command = {2: "subsection*", 3: "subsubsection*"}.get(level, "paragraph*")
                return f"\\{command}{{{self.inline(content)}}}"
            case ir.Paragraph(content, indent, muted):
                text = self.inline(content)
                if muted:
                    text = f"\\lessonmuted{{{text}}}"
                if indent:
                    return f"\\hspace*{{{1.2 * (indent - 1):.1f}em}}{text}" if indent > 1 else text
                return text
            case ir.ListBlock(ordered, items, start):
                environment = "enumerate" if ordered else "itemize"
                lines = [f"\\begin{{{environment}}}"]
                if ordered and start != 1:
                    lines.append(f"\\setcounter{{enumi}}{{{start - 1}}}")
                lines += [f"\\item {self.blocks(item)}" for item in items]
                lines.append(f"\\end{{{environment}}}")
                return "\n".join(lines)
            case ir.Quote(blocks):
                return f"\\begin{{quote}}\n{self.blocks(blocks)}\n\\end{{quote}}"
            case ir.CodeBlock(text):
                # verbatim не умеет `\end{verbatim}` внутри себя — разрываем такую строку.
                safe = text.replace("\\end{verbatim}", "\\end {verbatim}")
                return f"\\begin{{verbatim}}\n{safe}\n\\end{{verbatim}}"
            case ir.MathBlock(tex) if not katex_renders(tex):
                return self.block(ir.CodeBlock(f"$${tex}$$"))
            case ir.MathBlock(tex):
                return f"\\[\n{tex}\n\\]"
            case ir.Table():
                return self._table(block)
            case ir.Rule():
                return "\\noindent\\rule{\\linewidth}{0.4pt}"
            case ir.Figure(path, caption, width):
                name = self.assets.name(path)
                image = (f"\\includegraphics[width={width:.2f}\\linewidth,"
                         f"max height=0.85\\textheight,keepaspectratio]{{{name}}}"
                         if width else f"\\lessonimage{{{name}}}")
                caption_text = self.inline(caption)
                tail = f"\\\\\n\\lessonmuted{{{caption_text}}}" if caption_text else ""
                return f"\\begin{{center}}\n{image}{tail}\n\\end{{center}}"
            case ir.Callout(_kind, title, blocks):
                return (f"\\begin{{lessoncallout}}{{{escape(title)}}}\n{self.blocks(blocks)}\n"
                        "\\end{lessoncallout}")
            case ir.SourceBox(title, blocks, note):
                body = self.blocks(blocks)
                if note:
                    body = f"\\lessonmuted{{{escape(note)}}}\n\n{body}"
                return f"\\begin{{lessonsource}}{{{escape(title)}}}\n{body}\n\\end{{lessonsource}}"
            case ir.TaskBox(number, label, blocks):
                return (f"\\noindent\\textbf{{Задание {number}.}} \\emph{{{escape(label)}}}\n\n"
                        f"{self.blocks(blocks)}")
        return ""

    def _table(self, table: ir.Table) -> str:
        width = max([len(table.head)] + [len(row) for row in table.rows] + [1])

        def row(cells: list[list[ir.Inline]], bold: bool = False) -> str:
            values = [self.inline(cell) for cell in cells] + [""] * (width - len(cells))
            if bold:
                values = [f"\\textbf{{{value}}}" if value else value for value in values]
            return " & ".join(values) + r" \\ \hline"

        lines = [f"\\begin{{tabularx}}{{\\linewidth}}{{|{'X|' * width}}}", "\\hline"]
        if any(table.head):
            lines.append(row(table.head, bold=True))
        lines += [row(cells) for cells in table.rows]
        lines.append("\\end{tabularx}")
        return "\n".join(lines)

    def lesson(self, lesson: ir.LessonDoc) -> str:
        title = escape(lesson.title)
        parts = [f"\\section*{{{title}}}\n\\addcontentsline{{toc}}{{section}}{{{title}}}"]
        if lesson.goal:
            parts.append(f"\\textit{{Цель:}} {escape(lesson.goal)}")
        if lesson.topics:
            parts.append(f"\\lessonmuted{{Темы: {escape('; '.join(lesson.topics))}}}")
        body = self.blocks(lesson.blocks)
        if body:
            parts.append(body)
        if lesson.citations:
            parts.append("\\subsection*{Опоры пояснений}")
            parts.append("\\begin{itemize}\n" + "\n".join(
                f"\\item \\textbf{{{label}}} --- {escape(text)}"
                for label, text in lesson.citations) + "\n\\end{itemize}")
        if lesson.answers:
            parts.append("\\subsection*{Ответы к заданиям}")
            for answer in lesson.answers:
                body = self.blocks(answer.blocks) or "---"
                parts.append(f"\\textbf{{{answer.number}.}} {body}")
        return "\n\n".join(parts)

    def document(self, doc: ir.ExportDoc) -> str:
        body: list[str] = [PREAMBLE, "\\begin{document}"]
        if len(doc.lessons) > 1:
            body.append(f"\\begin{{center}}\\Large\\textbf{{{escape(doc.title)}}}\\end{{center}}")
            body.append("\\tableofcontents\n\\clearpage")
        body.append("\n\n\\clearpage\n\n".join(self.lesson(lesson) for lesson in doc.lessons))
        body.append("\\end{document}\n")
        return "\n\n".join(body)
