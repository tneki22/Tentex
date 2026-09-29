"""Нейтральное представление урока для экспорта.

Урок один раз переводится в эти узлы (`collect`), а PDF, LaTeX и Markdown
рисуются из них. Так правила «что попадает в файл» живут в одном месте, а
каждый формат отвечает только за свою разметку.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

# --- строчные узлы ----------------------------------------------------------------------


@dataclass(slots=True)
class Text:
    text: str


@dataclass(slots=True)
class Strong:
    children: list[Inline]


@dataclass(slots=True)
class Emph:
    children: list[Inline]


@dataclass(slots=True)
class Strike:
    children: list[Inline]


@dataclass(slots=True)
class Code:
    text: str


@dataclass(slots=True)
class Math:
    """Формула внутри абзаца; `tex` — LaTeX без ограничителей, как его понимает KaTeX.

    `display` — `$$…$$` посреди абзаца: приложение рисует её выносной, и файл тоже.
    """

    tex: str
    display: bool = False


@dataclass(slots=True)
class Link:
    href: str
    children: list[Inline]


@dataclass(slots=True)
class Citation:
    """Опора пояснения модели `[S3]`; расшифровка — в списке опор урока."""

    label: str


@dataclass(slots=True)
class LineBreak:
    pass


Inline = Text | Strong | Emph | Strike | Code | Math | Link | Citation | LineBreak

# --- блоки ------------------------------------------------------------------------------


@dataclass(slots=True)
class Heading:
    level: int
    content: list[Inline]


@dataclass(slots=True)
class Paragraph:
    content: list[Inline]
    # Отступ пункта списка из учебника: фрагмент «1) …» несёт свой маркер в тексте.
    indent: int = 0
    # Служебная строка мелким серым: «В учебнике: …», метка модели, подсказка.
    muted: bool = False


@dataclass(slots=True)
class ListBlock:
    ordered: bool
    items: list[list[Block]]
    start: int = 1


@dataclass(slots=True)
class Quote:
    blocks: list[Block]


@dataclass(slots=True)
class CodeBlock:
    text: str
    lang: str = ""


@dataclass(slots=True)
class MathBlock:
    tex: str


@dataclass(slots=True)
class Table:
    head: list[list[Inline]]
    rows: list[list[list[Inline]]]
    align: list[str | None]


@dataclass(slots=True)
class Rule:
    pass


@dataclass(slots=True)
class Figure:
    """Картинка из хранилища: вырез материала, лист страницы или изображение урока."""

    path: Path
    caption: list[Inline] = field(default_factory=list)
    # Доля ширины текста. Лист страницы — во всю ширину, вырез — по своему размеру.
    width: float | None = None
    alt: str = ""


@dataclass(slots=True)
class Callout:
    """Пояснение с оформлением: «Важно», «Пример», «Определение», «Внимание»."""

    kind: str
    title: str
    blocks: list[Block]


@dataclass(slots=True)
class SourceBox:
    """Кусок материала: подпись с источником и страницами, затем сам текст или листы."""

    title: str
    blocks: list[Block]
    note: str | None = None


@dataclass(slots=True)
class TaskBox:
    number: int
    label: str
    blocks: list[Block]


Block = (
    Heading | Paragraph | ListBlock | Quote | CodeBlock | MathBlock | Table | Rule | Figure
    | Callout | SourceBox | TaskBox
)


@dataclass(slots=True)
class Answer:
    number: int
    blocks: list[Block]


@dataclass(slots=True)
class LessonDoc:
    title: str
    goal: str | None
    topics: list[str]
    blocks: list[Block]
    # Расшифровка опор `[S3]`: метка → «источник, страницы».
    citations: list[tuple[str, str]] = field(default_factory=list)
    answers: list[Answer] = field(default_factory=list)


@dataclass(slots=True)
class ExportDoc:
    title: str
    project_name: str
    lessons: list[LessonDoc]


def plain_text(nodes: list[Inline]) -> str:
    """Текст строки без разметки: подписи, имена файлов, alt-текст."""
    parts: list[str] = []
    for node in nodes:
        match node:
            case Text(text) | Code(text):
                parts.append(text)
            case Math(tex, display):
                parts.append(f"$${tex}$$" if display else f"${tex}$")
            case Strong(children) | Emph(children) | Strike(children) | Link(_, children):
                parts.append(plain_text(children))
            case Citation(label):
                parts.append(f"[{label}]")
            case LineBreak():
                parts.append(" ")
    return "".join(parts)
