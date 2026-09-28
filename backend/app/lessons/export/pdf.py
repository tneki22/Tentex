"""PDF уроков через Typst: видимые векторные формулы и невидимый LaTeX под ними.

Формулы рисуются отдельным документом `formulas.typ` (mitex переводит LaTeX в
математику Typst) — по странице на формулу — и выводятся в SVG. В SVG глифы —
контуры, текста в них нет, поэтому в итоговом PDF формула видна, но в текстовом
слое её место занимает только прозрачный исходник `$…$`. Копирование из PDF даёт
текст урока с формулами, которые Tentex снова нарисует.

Формулу, которую mitex не понял, компилятор роняет вместе со всем документом;
ошибка указывает строку `formulas.typ`, эта формула уходит в исходник, и сборка
повторяется. Так одна странная формула не лишает файла весь урок.
"""

from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from app.config import settings
from app.lessons.export import ir
from app.lessons.export.render_markdown import AssetNames
from app.lessons.export.render_typst import FormulaSet, TypstRenderer, string
from app.projects.errors import ProjectDomainError

log = logging.getLogger("tentex.lessons.export")

TEMPLATE_DIR = Path(__file__).with_name("typst")
PACKAGE_DIR = TEMPLATE_DIR / "packages"
COMPILE_TIMEOUT_SECONDS = 120
# Каждая неудачная формула — ещё одна сборка по 0,2 с; дальше предела формулы
# оставшегося документа показываются исходником без попыток.
MAX_FORMULA_RETRIES = 60
FORMULA_HEADER = """#import "@preview/mitex:0.2.7": mitex, mi
#set page(width: auto, height: auto, margin: 0pt, fill: none)
#set text(font: "New Computer Modern", size: 11pt, top-edge: "bounds", bottom-edge: "bounds")
#let fm(key, src, display) = {
  box(if display { mitex(src) } else { mi(src) })
  [#box(width: 0pt, height: 0pt)#label(key)]
  // Нулевая коробка стоит на базовой линии формулы: её место и есть базовая линия.
  context [#metadata((key: key, at: locate(label(key)).position()))<formula-place>]
  pagebreak(weak: true)
}
"""
_SVG_SIZE = re.compile(r'<svg[^>]*?width="([\d.]+)pt"[^>]*?height="([\d.]+)pt"')
_KATEX_ALIASES = {
    r"\R": r"\mathbb{R}", r"\N": r"\mathbb{N}", r"\Z": r"\mathbb{Z}", r"\Q": r"\mathbb{Q}",
    r"\C": r"\mathbb{C}", r"\reals": r"\mathbb{R}", r"\natnums": r"\mathbb{N}",
    r"\Complex": r"\mathbb{C}", r"\tg": r"\operatorname{tg}", r"\ctg": r"\operatorname{ctg}",
    r"\arctg": r"\operatorname{arctg}", r"\sh": r"\operatorname{sh}",
    r"\ch": r"\operatorname{ch}", r"\degree": r"^{\circ}", r"\mbox": r"\text",
    r"\hbox": r"\text", r"\bm": r"\boldsymbol", r"\dfrac": r"\frac", r"\tfrac": r"\frac",
    r"\displaylimits": "", r"\nolimits": "", r"\limits": "", r"\newline": r"\\",
}
_ALIAS = re.compile(r"(\\[A-Za-z]+)(?![A-Za-z])")


class ExportUnavailableError(ProjectDomainError):
    def __init__(self, detail: str) -> None:
        super().__init__(detail, status=503, code="lesson_export_pdf_unavailable")


def normalize_tex(tex: str) -> str:
    """LaTeX для mitex: макросы KaTeX — стандартными, `\\\\3` — `\\\\ 3`.

    mitex читает `\\\\3` как неизвестную команду `\\3`, а KaTeX и LaTeX — как перенос
    строки и цифру; `\\tag{…}` mitex не знает, номер ставится справа вручную.
    """
    tex = tex.strip().strip("$").strip()
    tex = re.sub(r"\\\\(?=\S)", r"\\\\ ", tex)
    tex = re.sub(r"\\operatorname\*", r"\\operatorname", tex)
    tex = re.sub(r"\\(?:label)\{[^{}]*\}", "", tex)
    tag = re.search(r"\\tag\*?\{([^{}]*)\}", tex)
    if tag:
        tex = tex[: tag.start()] + tex[tag.end() :] + rf"\qquad ({tag.group(1)})"
    return _ALIAS.sub(lambda m: _KATEX_ALIASES.get(m.group(1), m.group(1)), tex)


@dataclass(slots=True)
class _Formula:
    key: str
    src: str
    display: bool
    file: str | None = None
    w: float = 0.0
    h: float = 0.0
    b: float = 0.0

    def as_json(self) -> dict[str, object]:
        source = f"$${self.src}$$" if self.display else f"${self.src}$"
        return {"file": self.file, "w": self.w, "h": self.h, "b": self.b, "src": source,
                "display": self.display}


def _run(root: Path, arguments: list[str]) -> subprocess.CompletedProcess[str]:
    binary = shutil.which(str(settings.typst_binary)) or str(settings.typst_binary)
    command = [binary, *arguments, "--root", str(root), "--ignore-system-fonts",
               "--package-path", str(PACKAGE_DIR),
               "--package-cache-path", str(root / ".typst-cache")]
    try:
        return subprocess.run(command, cwd=root, capture_output=True, text=True,
                              encoding="utf-8", timeout=COMPILE_TIMEOUT_SECONDS)
    except FileNotFoundError as error:
        raise ExportUnavailableError(
            "PDF собирается программой Typst, а её нет в этой установке"
        ) from error
    except subprocess.TimeoutExpired as error:
        raise ProjectDomainError("Сборка PDF заняла больше двух минут", status=504,
                                 code="lesson_export_timeout") from error


def _render_formulas(root: Path, formulas: FormulaSet) -> dict[str, _Formula]:
    """SVG и размеры каждой формулы; не понятые mitex остаются без файла."""
    items = [_Formula(key, tex, display) for (tex, display), key in formulas.keys.items()]
    if not items:
        return {}
    failed: set[str] = set()
    folder = root / "formulas"
    for _ in range(MAX_FORMULA_RETRIES + 1):
        good = [item for item in items if item.key not in failed]
        if not good:
            break
        lines = FORMULA_HEADER.split("\n")
        first_line = len(lines) + 1
        body = [f"#fm({string(item.key)}, {string(normalize_tex(item.src))}, "
                f"{'true' if item.display else 'false'})" for item in good]
        (root / "formulas.typ").write_text("\n".join(lines + body) + "\n", encoding="utf-8")
        shutil.rmtree(folder, ignore_errors=True)
        folder.mkdir()
        result = _run(root, ["compile", "formulas.typ", "formulas/{p}.svg"])
        if result.returncode == 0:
            _measure(root, good)
            return {item.key: item for item in items}
        places = [int(line) for line in re.findall(r"formulas\.typ:(\d+):", result.stderr)]
        culprits = [number - first_line for number in places if number >= first_line]
        if not culprits:
            log.warning("Формулы урока не собрались: %s", result.stderr[:500])
            break
        failed.add(good[culprits[-1]].key)
    return {item.key: item for item in items}


def _places(root: Path) -> list[dict[str, object]] | None:
    """Места формул из `formulas.typ`: `query` есть в typst 0.14 и 0.15, `eval` — с 0.15."""
    result = _run(root, ["query", "formulas.typ", "<formula-place>", "--field", "value"])
    if result.returncode != 0:
        result = _run(root, ["eval", "query(<formula-place>).map(it => it.value)",
                             "--in", "formulas.typ", "--format", "json"])
    if result.returncode != 0:
        log.warning("Размеры формул не прочитались: %s", result.stderr[:500])
        return None
    return json.loads(result.stdout)


def _measure(root: Path, good: list[_Formula]) -> None:
    """Страница, размер и базовая линия каждой формулы — по метке нулевой коробки."""
    places = _places(root)
    by_key = {item.key: item for item in good}
    for place in places or []:
        item = by_key.get(str(place.get("key")))
        position = place.get("at")
        if item is None or not isinstance(position, dict):
            continue
        svg = root / "formulas" / f"{position['page']}.svg"
        size = _SVG_SIZE.search(svg.read_text(encoding="utf-8")[:600]) if svg.exists() else None
        if size is None:
            continue
        item.file = f"formulas/{position['page']}.svg"
        item.w, item.h = float(size.group(1)), float(size.group(2))
        item.b = float(str(position["y"]).removesuffix("pt"))


def build_pdf(doc: ir.ExportDoc, workdir: Path) -> Path:
    """Собирает PDF документа в `workdir` и возвращает путь к нему."""
    root = workdir / "typst"
    root.mkdir(parents=True, exist_ok=True)
    shutil.copy2(TEMPLATE_DIR / "lesson.typ", root / "lesson.typ")
    formulas = FormulaSet()
    assets = AssetNames()
    source = TypstRenderer(formulas, assets).document(doc)
    for path, name in assets.names.items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
    rendered = _render_formulas(root, formulas)
    (root / "formulas.json").write_text(
        json.dumps({key: item.as_json() for key, item in rendered.items()}, ensure_ascii=False),
        encoding="utf-8",
    )
    (root / "main.typ").write_text(source, encoding="utf-8")
    output = workdir / "lessons.pdf"
    result = _run(root, ["compile", "main.typ", str(output)])
    if "was ignored" in result.stderr:
        log.warning("Typst пропустил часть урока: %s", result.stderr[:1000])
    if result.returncode != 0 or not output.exists():
        log.error("PDF уроков не собрался: %s", result.stderr[:2000])
        raise ProjectDomainError("PDF не собрался: Typst отказал в сборке документа",
                                 status=500, code="lesson_export_pdf_failed")
    return output
