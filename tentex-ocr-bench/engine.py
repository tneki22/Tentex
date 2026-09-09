"""Мини-типографский движок для генерации PDF-бенчмарка Tentex.

Рисует страницы A4: заголовки, абзацы с inline-формулами (matplotlib mathtext ->
PNG), блочные формулы с нумерацией, списки, таблицы (в т.ч. с формулами в ячейках),
код моноширинным шрифтом, рисунки с подписями, колонки, маргиналии, колонтитулы.
"""
from __future__ import annotations

import io
import math
from dataclasses import dataclass, field
from typing import Any

import fitz  # PyMuPDF
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from PIL import Image, ImageFilter

# ---------------------------------------------------------------- шрифты
FONTS = {
    "serif":      "/usr/share/fonts/dejavu-serif-fonts/DejaVuSerif.ttf",
    "serif_bold": "/usr/share/fonts/dejavu-serif-fonts/DejaVuSerif-Bold.ttf",
    "serif_it":   "/usr/share/fonts/dejavu-serif-fonts/DejaVuSerif-Italic.ttf",
    "serif_bdi":  "/usr/share/fonts/dejavu-serif-fonts/DejaVuSerif-BoldItalic.ttf",
    "sans_bold":  "/usr/share/fonts/dejavu-sans-fonts/DejaVuSans-Bold.ttf",
    "mono":       "/usr/share/fonts/liberation-mono/LiberationMono-Regular.ttf",
    "mono_bold":  "/usr/share/fonts/liberation-mono/LiberationMono-Bold.ttf",
}

_font_cache: dict[str, fitz.Font] = {}


def F(name: str) -> fitz.Font:
    if name not in _font_cache:
        _font_cache[name] = fitz.Font(fontfile=FONTS[name])
    return _font_cache[name]


# ---------------------------------------------------------------- рендер формул
_tex_cache: dict[tuple[str, float], Image.Image] = {}


def render_tex(tex: str, fontsize: float = 13.0) -> Image.Image:
    """Рендер LaTeX-строки в PNG (белый фон, чёрный текст) через mathtext."""
    key = (tex, fontsize)
    if key in _tex_cache:
        return _tex_cache[key]
    plt.rc("mathtext", fontset="dejavuserif")
    fig = plt.figure()
    fig.text(0.5, 0.5, tex, fontsize=fontsize, ha="center", va="center", color="black")
    buf = io.BytesIO()
    fig.savefig(buf, dpi=200, bbox_inches="tight", pad_inches=0.015, facecolor="white")
    plt.close(fig)
    buf.seek(0)
    img = Image.open(buf).convert("L")
    _tex_cache[key] = img
    return img


def render_tex_piece(lines: list[str], fontsize: float = 13.0) -> Image.Image:
    """Несколько строк формул одна под другой (для систем/выравниваний)."""
    key = ("PIECE:" + "\n".join(lines), fontsize)
    if key in _tex_cache:
        return _tex_cache[key]
    plt.rc("mathtext", fontset="dejavuserif")
    fig, ax = plt.subplots(figsize=(6, 0.4 * len(lines) + 0.4))
    ax.axis("off")
    n = len(lines)
    for i, ln in enumerate(lines):
        y = 1 - (i + 0.5) / n
        ax.text(0.03, y, ln, fontsize=fontsize, va="center", ha="left", color="black")
    buf = io.BytesIO()
    fig.savefig(buf, dpi=200, bbox_inches="tight", pad_inches=0.03, facecolor="white")
    plt.close(fig)
    buf.seek(0)
    img = Image.open(buf).convert("L")
    _tex_cache[key] = img
    return img


def img_to_png_bytes(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# ---------------------------------------------------------------- модель страницы
A4_W, A4_H = 595.27, 841.89  # pt


@dataclass
class Margin:
    top: float = 56
    bottom: float = 52
    left: float = 46
    right: float = 46


@dataclass
class Cursor:
    x0: float
    x1: float
    y: float
    y_max: float


class PageBuilder:
    def __init__(self, doc: fitz.Document):
        self.doc = doc
        self.page = doc.new_page(width=A4_W, height=A4_H)
        for name, path in FONTS.items():
            self.page.insert_font(fontname=name, fontfile=path)
        self.tw = fitz.TextWriter(self.page.rect, color=(0, 0, 0))
        self.m = Margin()
        self.body_size = 10.0
        self.line_h = 13.6
        self.cursor = Cursor(self.m.left, A4_W - self.m.right, self.m.top, A4_H - self.m.bottom)
        self._fig_counter = 0

    # ---------- низкоуровневое
    def _write(self, x: float, y_baseline: float, text: str, font: str, size: float,
               color=(0, 0, 0)):
        if not text:
            return
        w = fitz.TextWriter(self.page.rect, color=color)
        w.append(fitz.Point(x, y_baseline), text, font=F(font), fontsize=size)
        w.write_text(self.page)

    def text_w(self, text: str, font: str, size: float) -> float:
        return F(font).text_length(text, fontsize=size)

    def space(self, h: float):
        self.cursor.y += h

    def check_room(self, needed: float):
        """Если блок не влезает на страницу — сообщить (страницы не ломаем намеренно)."""
        if self.cursor.y + needed > self.cursor.y_max:
            raise OverflowError(f"block needs {needed:.0f}pt at y={self.cursor.y:.0f}")

    # ---------- заголовки
    def heading(self, text: str, level: int = 1, center: bool = False):
        sizes = {1: 15.5, 2: 12.5, 3: 11.0}
        size = sizes.get(level, 11.0)
        self.space(9 if level == 1 else 7)
        self.check_room(size + 8)
        y_base = self.cursor.y + size
        w = self.text_w(text, "sans_bold", size)
        x = self.cursor.x0
        if center:
            x = self.cursor.x0 + (self.cursor.x1 - self.cursor.x0 - w) / 2
        elif level == 2:
            pass
        self._write(x, y_base, text, "sans_bold", size)
        self.cursor.y = y_base + 6
        self.space(2)

    # ---------- токены текста: ('t', s) обычный, ('b', s) жирный, ('i', s) курсив,
    #                              ('m', tex) inline-формула, ('c', s) inline-код
    def _measure_token(self, tok: tuple[str, str], size: float) -> float:
        kind, val = tok
        if kind == "m":
            img = render_tex("$" + val + "$" if not val.startswith("$") else val, fontsize=size * 0.98)
            return img.width / 200.0 * 72.0
        if kind == "b":
            return self.text_w(val, "serif_bold", size)
        if kind == "i":
            return self.text_w(val, "serif_it", size)
        if kind == "c":
            return self.text_w(val, "mono", size * 0.9)
        return self.text_w(val, "serif", size)

    def _token_img(self, tok: tuple[str, str], size: float) -> Image.Image:
        _, val = tok
        return render_tex("$" + val + "$" if not val.startswith("$") else val, fontsize=size * 0.98)

    def _flow(self, tokens: list[tuple[str, str]], width: float, size: float):
        """Разбить токены на строки. Возвращает список строк: [(token, w, img|None)]."""
        space_w = self.text_w(" ", "serif", size)
        lines: list[list] = []
        cur: list = []
        cur_w = 0.0
        for tok in tokens:
            kind, val = tok
            if kind == "t" or kind == "i":
                # разбиваем по словам
                words = val.split(" ")
                for i, wd in enumerate(words):
                    if wd == "" and i > 0:
                        continue
                    piece = ("t" if kind == "t" else "i", wd)
                    w = self._measure_token(piece, size)
                    add = w + (space_w if cur else 0)
                    if cur and cur_w + add > width:
                        lines.append(cur); cur = []; cur_w = 0
                    if cur:
                        cur.append(("t", " ")); cur_w += space_w
                    cur.append(piece); cur_w += w
            else:
                w = self._measure_token(tok, size)
                add = w + (space_w if cur else 0)
                if cur and cur_w + add > width:
                    lines.append(cur); cur = []; cur_w = 0
                if cur:
                    cur.append(("t", " ")); cur_w += space_w
                cur.append(tok); cur_w += w
        if cur:
            lines.append(cur)
        return lines

    def _draw_line(self, line: list, x0: float, y_top: float, size: float) -> float:
        """Рисует строку от y_top. Возвращает высоту строки."""
        text_size = size
        cap = size * 0.72
        h = text_size * 1.22
        img_items = [(tok, self._token_img(tok, size)) for tok in line if tok[0] == "m"]
        for tok, img in img_items:
            ih = img.height / 200.0 * 72.0
            h = max(h, ih + 2)
        baseline = y_top + max(text_size * 0.92, h * 0.58)
        x = x0
        for tok in line:
            kind, val = tok
            if kind == "m":
                img = self._token_img(tok, size)
                ih = img.height / 200.0 * 72.0
                iw = img.width / 200.0 * 72.0
                top = baseline - cap / 2 - ih / 2
                self.page.insert_image(
                    fitz.Rect(x, top, x + iw, top + ih),
                    stream=img_to_png_bytes(img))
                x += iw
            elif kind == "b":
                self._write(x, baseline, val, "serif_bold", size)
                x += self.text_w(val, "serif_bold", size)
            elif kind == "i":
                self._write(x, baseline, val, "serif_it", size)
                x += self.text_w(val, "serif_it", size)
            elif kind == "c":
                self._write(x, baseline, val, "mono", size * 0.9)
                x += self.text_w(val, "mono", size * 0.9)
            else:
                self._write(x, baseline, val, "serif", size)
                x += self.text_w(val, "serif", size)
        return h

    def paragraph(self, tokens, size: float | None = None, justify: bool = True,
                  indent: float = 14):
        """Абзац. tokens: список токенов или строка."""
        if isinstance(tokens, str):
            tokens = [("t", tokens)]
        size = size or self.body_size
        width = self.cursor.x1 - self.cursor.x0 - indent
        lines = self._flow(tokens, width, size)
        for i, line in enumerate(lines):
            self.check_room(self.line_h)
            self._draw_line(line, self.cursor.x0 + indent, self.cursor.y, size)
            self.cursor.y += max(self.line_h, self._line_h_measured(line, size))
        self.space(2.5)

    def _line_h_measured(self, line, size):
        h = size * 1.22
        for tok in line:
            if tok[0] == "m":
                img = self._token_img(tok, size)
                ih = img.height / 200.0 * 72.0
                h = max(h, ih + 2)
        return h

    # ---------- блочная формула
    def display_formula(self, tex: str, label: str | None = None, fontsize: float = 13.0):
        img = render_tex(tex, fontsize=fontsize)
        ih = img.height / 200.0 * 72.0
        iw = img.width / 200.0 * 72.0
        self.space(5)
        self.check_room(ih + 8)
        x = self.cursor.x0 + (self.cursor.x1 - self.cursor.x0 - iw) / 2
        self.page.insert_image(fitz.Rect(x, self.cursor.y, x + iw, self.cursor.y + ih),
                               stream=img_to_png_bytes(img))
        if label:
            lw = self.text_w(label, "serif", self.body_size)
            self._write(self.cursor.x1 - lw, self.cursor.y + ih / 2 + 3.5,
                        label, "serif", self.body_size)
        self.cursor.y += ih + 7

    def display_formula_piece(self, lines: list[str], label: str | None = None,
                              fontsize: float = 13.0, left: bool = False):
        img = render_tex_piece(lines, fontsize=fontsize)
        ih = img.height / 200.0 * 72.0
        iw = img.width / 200.0 * 72.0
        self.space(4)
        self.check_room(ih + 6)
        x = self.cursor.x0 + (self.cursor.x1 - self.cursor.x0 - iw) / 2 if not left \
            else self.cursor.x0 + 24
        self.page.insert_image(fitz.Rect(x, self.cursor.y, x + iw, self.cursor.y + ih),
                               stream=img_to_png_bytes(img))
        if label:
            lw = self.text_w(label, "serif", self.body_size)
            self._write(self.cursor.x1 - lw, self.cursor.y + ih / 2 + 3.5,
                        label, "serif", self.body_size)
        self.cursor.y += ih + 6

    # ---------- списки
    def bullet_list(self, items: list[list], size: float | None = None, ordered: bool = False):
        size = size or self.body_size
        for i, it in enumerate(items):
            tokens = list(it)
            marker = f"{i + 1}." if ordered else "–"
            mw = self.text_w(marker, "serif", size)
            indent0 = self.cursor.x0 + 16
            width = self.cursor.x1 - indent0 - mw - 6
            lines = self._flow(tokens, width, size)
            for j, line in enumerate(lines):
                self.check_room(self.line_h)
                if j == 0:
                    self._write(indent0 - mw - 5, self.cursor.y + size * 0.92,
                                marker, "serif", size)
                self._draw_line(line, indent0, self.cursor.y, size)
                self.cursor.y += max(self.line_h, self._line_h_measured(line, size))
        self.space(3)

    # ---------- таблицы
    def table(self, headers: list, rows: list[list], col_widths: list[float],
              caption: str | None = None, font_size: float = 8.6,
              cell_pad: float = 3.5, header_fill: float = 0.92):
        """Ячейка: строка или ('tex', latex) или ('b', s)."""
        total = sum(col_widths)
        x0 = self.cursor.x0 + (self.cursor.x1 - self.cursor.x0 - total) / 2

        def cell_lines(cell):
            if isinstance(cell, tuple) and cell[0] == "tex":
                img = render_tex(cell[1], fontsize=font_size + 1.5)
                return [("img", img)]
            text = cell if isinstance(cell, str) else cell[1]
            bold = isinstance(cell, tuple) and cell[0] == "b"
            toks = [("b" if bold else "t", text)]
            w = col_widths[0]  # заглушка, переопределяется ниже
            return None, toks, bold

        # считаем высоты строк
        row_h = []
        rendered_rows = []
        for r in [headers] + rows:
            cells = []
            hmax = font_size * 1.3 + 2 * cell_pad
            for ci, cell in enumerate(r):
                w = col_widths[ci] - 2 * cell_pad
                if isinstance(cell, tuple) and cell[0] == "tex":
                    img = render_tex(cell[1], fontsize=font_size + 1.0)
                    iw = img.width / 200.0 * 72.0
                    ih = img.height / 200.0 * 72.0
                    scale = min(1.0, w / iw)
                    cells.append(("img", img, iw * scale, ih * scale))
                    hmax = max(hmax, ih * scale + 2 * cell_pad)
                else:
                    text = cell if isinstance(cell, str) else cell[1]
                    bold = isinstance(cell, tuple) and cell[0] == "b"
                    toks = [("b" if bold else "t", text)]
                    lines = self._flow(toks, w, font_size)
                    hmax = max(hmax, len(lines) * font_size * 1.25 + 2 * cell_pad)
                    cells.append(("lines", lines))
            row_h.append(hmax)
            rendered_rows.append(cells)

        table_h = sum(row_h) + (20 if caption else 0)
        self.space(4)
        self.check_room(table_h)
        if caption:
            cw = self.text_w(caption, "serif_it", font_size)
            self._write(x0, self.cursor.y + font_size, caption, "serif_it", font_size)
            self.cursor.y += font_size + 6

        y = self.cursor.y
        for ri, (cells, rh) in enumerate(zip(rendered_rows, row_h)):
            x = x0
            for ci, cell in enumerate(cells):
                w = col_widths[ci]
                rect = fitz.Rect(x, y, x + w, y + rh)
                if ri == 0:
                    self.page.draw_rect(rect, color=(0, 0, 0), width=0.6,
                                        fill=(header_fill, header_fill, header_fill))
                else:
                    self.page.draw_rect(rect, color=(0, 0, 0), width=0.5)
                if cell[0] == "img":
                    _, img, iw, ih = cell
                    ix = x + (w - iw) / 2
                    iy = y + (rh - ih) / 2
                    self.page.insert_image(fitz.Rect(ix, iy, ix + iw, iy + ih),
                                           stream=img_to_png_bytes(img))
                else:
                    _, lines = cell
                    ty = y + cell_pad
                    for line in lines:
                        self._draw_line(line, x + cell_pad, ty, font_size)
                        ty += font_size * 1.25
                x += w
            y += rh
        self.cursor.y = y + 6

    # ---------- код
    def code_block(self, lines: list[str], font_size: float = 8.2):
        h = len(lines) * font_size * 1.35 + 10
        self.space(4)
        self.check_room(h)
        rect = fitz.Rect(self.cursor.x0 + 8, self.cursor.y,
                         self.cursor.x1 - 8, self.cursor.y + h)
        self.page.draw_rect(rect, color=(0.55, 0.55, 0.55), width=0.7,
                            fill=(0.965, 0.965, 0.965))
        y = self.cursor.y + 5 + font_size
        for ln in lines:
            self._write(rect.x0 + 8, y, ln, "mono", font_size)
            y += font_size * 1.35
        self.cursor.y += h + 5

    # ---------- рисунки
    def figure(self, img: Image.Image, width_pt: float, caption: str,
               cap_size: float = 8.8):
        w = width_pt
        h = img.height / img.width * w
        self.space(4)
        self.check_room(h + cap_size + 10)
        x = self.cursor.x0 + (self.cursor.x1 - self.cursor.x0 - w) / 2
        self.page.insert_image(fitz.Rect(x, self.cursor.y, x + w, self.cursor.y + h),
                               stream=img_to_png_bytes(img))
        self.cursor.y += h + 3
        cap_lines = self._flow([("t", caption)], self.cursor.x1 - self.cursor.x0 - 40, cap_size)
        for line in cap_lines:
            self._draw_line(line, self.cursor.x0 + 20, self.cursor.y, cap_size)
            self.cursor.y += cap_size * 1.25
        self.space(5)

    # ---------- маргиналия
    def margin_note(self, text: str, y: float, side: str = "right", width: float = 0):
        size = 7.6
        if side == "right":
            x0 = A4_W - 44
            x1 = A4_W - 7
        else:
            x0 = 8
            x1 = self.m.left - 6
        self.cursor_saved = None
        saved = (self.cursor.x0, self.cursor.x1, self.cursor.y, self.cursor.y_max)
        self.cursor = Cursor(x0, x1, y, A4_H)
        lines = self._flow([("i", text)], x1 - x0, size)
        for line in lines:
            self._draw_line(line, x0, self.cursor.y, size)
            self.cursor.y += size * 1.3
        self.cursor = Cursor(*saved)
        return

    # ---------- колонтитулы
    def header_footer(self, header: str | None, page_no: int):
        size = 8.0
        if header:
            w = self.text_w(header, "serif_it", size)
            self._write((A4_W - w) / 2, 30, header, "serif_it", size)
            self.page.draw_line(fitz.Point(self.m.left, 38), fitz.Point(A4_W - self.m.right, 38),
                                color=(0, 0, 0), width=0.4)
        pn = str(page_no)
        w = self.text_w(pn, "serif", size)
        self._write((A4_W - w) / 2, A4_H - 24, pn, "serif", size)

    def finish(self):
        pass


# ---------------------------------------------------------------- деградация скана
def rasterize_scan(doc: fitz.Document, out_doc: fitz.Document, dpi: int = 300,
                   jpeg_q: int = 88, noise_sigma: float = 3.5, rotate_deg: float = 0.0,
                   paper_rgb: tuple | None = None, seed: int = 7, blur_px: float = 0.0,
                   paper_blend: float = 0.94):
    """Растеризует doc и собирает страницы-сканы в out_doc."""
    import numpy as np
    rng = np.random.default_rng(seed)
    zoom = dpi / 72.0
    for i, page in enumerate(doc):
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), colorspace=fitz.csRGB)
        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        if blur_px > 0:
            img = img.filter(ImageFilter.GaussianBlur(blur_px))
        arr = np.asarray(img).astype(np.float32)
        noise = rng.normal(0, noise_sigma, arr.shape[:2] if len(arr.shape) == 2 else arr.shape[:2])
        for c in range(3):
            arr[:, :, c] += noise
        arr = np.clip(arr, 0, 255).astype(np.uint8)
        img = Image.fromarray(arr)
        if paper_rgb is not None:
            # старение бумаги: фон становится желтоватым
            bg = Image.new("RGB", img.size, paper_rgb)
            img = Image.blend(bg, img, paper_blend)
        if rotate_deg:
            img = img.rotate(rotate_deg, fillcolor=(255, 255, 255) if paper_rgb is None else paper_rgb,
                             expand=False)
        buf = io.BytesIO()
        img.convert("RGB").save(buf, format="JPEG", quality=jpeg_q)
        buf.seek(0)
        p = out_doc.new_page(width=page.rect.width, height=page.rect.height)
        p.insert_image(p.rect, stream=buf.read())
