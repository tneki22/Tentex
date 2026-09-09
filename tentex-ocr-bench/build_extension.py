"""Расширение Tentex OCR Bench v2: 24 страницы.

Добавляет к исходным 10 страницам:
- 6 контролируемых фотографий страниц телефона (перспектива/тень/свет/блик/окклюзия);
- 2 страницы оглавления из пользовательского примера;
- 3 страницы, скомпилированные настоящим LaTeX с нативным текстовым слоем формул;
- 3 дополнительных учебных сценария (химия, вложенное решение, библиография/DOI).
"""
from __future__ import annotations

import io
import json
import os
import subprocess
from pathlib import Path

import fitz
import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter

from engine import PageBuilder, A4_W, A4_H, img_to_png_bytes, rasterize_scan

ROOT = Path(__file__).resolve().parent
PHOTO_DIR = ROOT / "photo_pages"
GEOM_DIR = ROOT / "photo_geometry"
PHOTO_DIR.mkdir(exist_ok=True)
GEOM_DIR.mkdir(exist_ok=True)


def render_page(doc: fitz.Document, index: int, dpi: int = 220) -> Image.Image:
    page = doc[index]
    pix = page.get_pixmap(matrix=fitz.Matrix(dpi / 72, dpi / 72), colorspace=fitz.csRGB, alpha=False)
    return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)


def _perspective_coeffs(src, dst):
    """Коэффициенты PIL: отображение выходного dst-квадрилатераля в src."""
    matrix = []
    target = []
    for (x, y), (u, v) in zip(dst, src):
        matrix.append([x, y, 1, 0, 0, 0, -u * x, -u * y])
        matrix.append([0, 0, 0, x, y, 1, -v * x, -v * y])
        target.extend([u, v])
    return np.linalg.solve(np.asarray(matrix, float), np.asarray(target, float))


def _desk_background(size, seed: int) -> Image.Image:
    rng = np.random.default_rng(seed)
    w, h = size
    y = np.linspace(0, 1, h)[:, None]
    x = np.linspace(0, 1, w)[None, :]
    grain = rng.normal(0, 3.2, (h, w))
    bands = 5.5 * np.sin((x * 18 + y * 1.4) * np.pi)
    light = 8 * (1 - y) - 4 * x
    base = np.zeros((h, w, 3), dtype=np.float32)
    base[:, :, 0] = 119 + grain + bands + light
    base[:, :, 1] = 80 + grain * 0.65 + bands * 0.45 + light * 0.55
    base[:, :, 2] = 52 + grain * 0.45 + bands * 0.25 + light * 0.35
    return Image.fromarray(np.clip(base, 0, 255).astype(np.uint8), "RGB")


def _apply_page_lighting(page: Image.Image, cfg: dict) -> Image.Image:
    arr = np.asarray(page).astype(np.float32)
    h, w = arr.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w]
    # Градиент освещения: значения задаются по горизонтали и вертикали.
    gx = cfg.get("light_x", 0.0) * (xx / max(w - 1, 1) - 0.5)
    gy = cfg.get("light_y", 0.0) * (yy / max(h - 1, 1) - 0.5)
    shade = 1.0 + gx + gy
    if cfg.get("corner_shadow"):
        cx, cy, strength, radius = cfg["corner_shadow"]
        dist = ((xx / w - cx) ** 2 + (yy / h - cy) ** 2) / max(radius ** 2, 1e-6)
        shade *= 1.0 - strength * np.exp(-dist)
    arr *= shade[:, :, None]
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), "RGB")


def make_phone_photo(page: Image.Image, cfg: dict, out_path: Path, geom_path: Path):
    canvas_size = (1800, 2400)
    cw, ch = canvas_size
    page = _apply_page_lighting(page, cfg)
    page = ImageEnhance.Contrast(page).enhance(cfg.get("contrast", 0.98))

    src = [(0, 0), (page.width, 0), (page.width, page.height), (0, page.height)]
    dst = cfg["quad"]
    coeffs = _perspective_coeffs(src, dst)

    mask_src = Image.new("L", page.size, 255)
    mask = mask_src.transform(canvas_size, Image.Transform.PERSPECTIVE, coeffs,
                              resample=Image.Resampling.BICUBIC, fillcolor=0)
    warped = page.transform(canvas_size, Image.Transform.PERSPECTIVE, coeffs,
                            resample=Image.Resampling.BICUBIC, fillcolor=(255, 255, 255))

    canvas = _desk_background(canvas_size, cfg["seed"])
    shadow = mask.filter(ImageFilter.GaussianBlur(cfg.get("shadow_blur", 28)))
    shadow_layer = Image.new("RGB", canvas_size, (20, 15, 12))
    shadow_alpha = shadow.point(lambda p: int(p * cfg.get("shadow_alpha", 0.34)))
    # небольшой сдвиг тени от страницы
    shifted = Image.new("L", canvas_size, 0)
    shifted.paste(shadow_alpha, (cfg.get("shadow_dx", 18), cfg.get("shadow_dy", 24)))
    canvas.paste(shadow_layer, (0, 0), shifted)
    canvas.paste(warped, (0, 0), mask)

    arr = np.asarray(canvas).astype(np.float32)
    yy, xx = np.mgrid[0:ch, 0:cw]
    # Блик эллиптической формы; маска ограничивается страницей.
    if cfg.get("glare"):
        gx, gy, rx, ry, strength = cfg["glare"]
        glare = np.exp(-(((xx - gx) / rx) ** 2 + ((yy - gy) / ry) ** 2) * 2.0)
        m = np.asarray(mask).astype(np.float32) / 255.0
        glare *= m
        arr = arr + (255 - arr) * (glare * strength)[:, :, None]
    # Общая виньетка камеры.
    cx, cy = cw / 2, ch / 2
    rr = ((xx - cx) / cw) ** 2 + ((yy - cy) / ch) ** 2
    arr *= (1.0 - cfg.get("vignette", 0.16) * rr)[:, :, None]
    canvas = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), "RGB")

    # Частичная окклюзия у края (палец/телефон), если задана.
    if cfg.get("occlusion"):
        draw = ImageDraw.Draw(canvas, "RGBA")
        kind = cfg["occlusion"]
        if kind == "finger":
            draw.ellipse((1450, 2010, 1880, 2490), fill=(160, 96, 66, 220))
        elif kind == "dark_corner":
            draw.polygon([(0, 0), (420, 0), (0, 310)], fill=(10, 12, 14, 235))

    canvas = canvas.filter(ImageFilter.GaussianBlur(cfg.get("camera_blur", 0.35)))
    canvas.save(out_path, "JPEG", quality=cfg.get("jpeg_q", 82), subsampling=1)

    corners_norm = [[round(x / cw, 6), round(y / ch, 6)] for x, y in dst]
    geom = {
        "image": out_path.name,
        "width": cw,
        "height": ch,
        "page_corners_px": dst,
        "page_corners_normalized": corners_norm,
        "order": ["top_left", "top_right", "bottom_right", "bottom_left"],
        "variant_of_original_page": cfg["source_page"],
        "defects": cfg["defects"],
    }
    geom_path.write_text(json.dumps(geom, ensure_ascii=False, indent=2), encoding="utf-8")
    return canvas


def build_supplement() -> fitz.Document:
    doc = fitz.open()

    # P22 — химические формулы и реакции.
    b = PageBuilder(doc)
    b.header_footer("Общая химия. Раздел 5", 178)
    b.heading("§ 9. Равновесие в растворах электролитов", level=1)
    b.paragraph([("t", "Слабая уксусная кислота диссоциирует обратимо. Равновесие записывают уравнением "),
                 ("m", r"CH_3COOH \rightleftharpoons H^+ + CH_3COO^-"), ("t", ".")])
    b.display_formula(r"$K_a = \frac{[H^+][CH_3COO^-]}{[CH_3COOH]} = 1{,}8 \cdot 10^{-5}.$", label="(9.1)")
    b.paragraph([("t", "Для водного раствора справедливо ионное произведение воды "),
                 ("m", r"K_w = [H^+][OH^-] = 10^{-14}"),
                 ("t", " при температуре 25 °C. Поэтому водородный показатель определяют как")])
    b.display_formula(r"$\mathrm{pH} = -\lg[H^+], \qquad \mathrm{pOH} = -\lg[OH^-], \qquad \mathrm{pH}+\mathrm{pOH}=14.$", label="(9.2)")
    b.heading("Буферные растворы", level=2)
    b.paragraph([("t", "Для смеси слабой кислоты HA и её соли применяется уравнение Хендерсона — Хассельбаха:")])
    b.display_formula(r"$\mathrm{pH}=\mathrm{p}K_a+\lg\frac{[A^-]}{[HA]}.$", label="(9.3)")
    b.table(headers=[("b", "Система"), ("b", "Реакция"), ("b", "Тип")],
            rows=[
                ["Гидрокарбонат", "H₂CO₃ ⇄ H⁺ + HCO₃⁻", "кислотная"],
                ["Аммоний", "NH₄⁺ ⇄ H⁺ + NH₃", "кислотная"],
                ["Фосфат", "H₂PO₄⁻ ⇄ H⁺ + HPO₄²⁻", "амфолит"],
            ], col_widths=[110, 200, 88], caption="Таблица 9.1 — Примеры буферных систем")
    b.paragraph([("b", "Пример. "), ("t", "В растворе концентрации уксусной кислоты и ацетата натрия равны соответственно 0,10 и 0,20 моль/л. Тогда "),
                 ("m", r"\mathrm{pH}=4{,}74+\lg 2 \approx 5{,}04"), ("t", ".")])
    b.finish()

    # P23 — вложенное условие и решение.
    b = PageBuilder(doc)
    b.header_footer("Сборник задач по математике", 246)
    b.heading("Задача 12.7. Исследование функции", level=1)
    b.paragraph([("t", "Дана функция "), ("m", r"f(x)=x^3-3x^2-9x+5"), ("t", ".")])
    b.heading("Требуется", level=2)
    b.bullet_list([
        [("t", "Найти область определения и нули функции.")],
        [("t", "Исследовать функцию:"),
         ("t", " а) на монотонность; б) на экстремумы; в) на выпуклость и точки перегиба.")],
        [("t", "Построить эскиз графика и отметить характерные точки.")],
    ], ordered=True)
    b.heading("Решение", level=2)
    b.paragraph([("t", "Производные первого и второго порядка равны")])
    b.display_formula_piece([r"$f'(x)=3x^2-6x-9=3(x+1)(x-3),$",
                             r"$f''(x)=6x-6=6(x-1).$"], label="(12.8)")
    b.paragraph([("t", "Критические точки: "), ("m", r"x_1=-1"), ("t", " и "),
                 ("m", r"x_2=3"), ("t", ". Точка перегиба: "), ("m", r"x=1"), ("t", ".")])
    b.table(headers=[("b", "Интервал"), ("b", "знак f′"), ("b", "Поведение f"), ("b", "Вывод")],
            rows=[
                ["(−∞; −1)", "+", "возрастает", "—"],
                ["(−1; 3)", "−", "убывает", "max при x=−1"],
                ["(3; +∞)", "+", "возрастает", "min при x=3"],
            ], col_widths=[94, 72, 118, 114], caption="Таблица 12.2 — Таблица монотонности")
    b.paragraph([("b", "Ответ. "), ("t", "Локальный максимум "), ("m", r"f(-1)=10"),
                 ("t", "; локальный минимум "), ("m", r"f(3)=-22"),
                 ("t", "; точка перегиба "), ("m", r"(1;-6)"), ("t", ".")])
    b.finish()

    # P24 — библиография, DOI, URL и смешанная кириллица/латиница.
    b = PageBuilder(doc)
    b.header_footer("Методы анализа образовательных документов", 312)
    b.heading("Литература и электронные ресурсы", level=1)
    b.paragraph([("t", "Ниже приведён пример списка источников, содержащего кириллицу, латиницу, DOI, URL и диапазоны страниц. Такой материал проверяет сохранение пунктуации и порядка чтения.")])
    b.bullet_list([
        [("t", "Иванов А. В., Петрова Н. С. Цифровая обработка учебных материалов. — М.: Техносфера, 2024. — 368 с. — ISBN 978-5-94836-712-9.")],
        [("t", "Smith J., Lee K. Layout-aware document parsing for education. Document Intelligence, 2025, vol. 8, no. 2, pp. 41–59. DOI: 10.1234/di.2025.00802.")],
        [("t", "Ouyang L. et al. OmniDocBench: Benchmarking Diverse PDF Document Parsing. Proceedings of CVPR, 2025, pp. 1386–1397.")],
        [("t", "Zhong X., ShafieiBavani E., Jimeno Yepes A. Image-based table recognition: data, model, and evaluation. ECCV, 2020. DOI: 10.1007/978-3-030-58589-1_33.")],
        [("t", "W3C. Mathematical Markup Language (MathML) Version 3.0. URL: https://www.w3.org/TR/MathML3/ (дата обращения: 15.08.2026).")],
    ], ordered=True)
    b.heading("Список сокращений", level=2)
    b.table(headers=[("b", "Сокращение"), ("b", "Расшифровка")],
            rows=[
                ["OCR", "optical character recognition"],
                ["VLM", "vision-language model"],
                ["RAG", "retrieval-augmented generation"],
                ["PDF", "Portable Document Format"],
                ["CDM", "formula character/structure distance metric"],
            ], col_widths=[95, 303], caption="Таблица 14 — Сокращения, используемые в тексте")
    b.paragraph([("b", "Примечание. "), ("t", "Идентификатор DOI следует сохранять как одну непрерывную строку; перенос URL допускается только после символа косой черты.")])
    b.finish()
    return doc


PHOTO_CONFIGS = [
    {"source_page": 1, "seed": 101, "quad": [(250, 155), (1600, 270), (1535, 2250), (135, 2110)],
     "defects": ["perspective", "keystone", "page_shadow"], "light_x": -0.10, "light_y": 0.08, "jpeg_q": 84},
    {"source_page": 3, "seed": 102, "quad": [(110, 305), (1565, 125), (1690, 2180), (260, 2280)],
     "defects": ["perspective", "uneven_light", "glare"], "light_x": 0.30, "light_y": -0.16,
     "glare": (1250, 610, 520, 250, 0.42), "jpeg_q": 80},
    {"source_page": 5, "seed": 103, "quad": [(325, 120), (1640, 385), (1460, 2290), (95, 1970)],
     "defects": ["strong_perspective", "corner_shadow", "glare"], "light_x": -0.22,
     "corner_shadow": (0.15, 0.88, 0.55, 0.42), "glare": (920, 1160, 430, 620, 0.35), "jpeg_q": 78},
    {"source_page": 7, "seed": 104, "quad": [(175, 145), (1610, 90), (1715, 2200), (120, 2290)],
     "defects": ["mild_perspective", "finger_occlusion", "page_shadow"], "light_y": 0.15,
     "occlusion": "finger", "jpeg_q": 82},
    {"source_page": 8, "seed": 105, "quad": [(85, 265), (1515, 125), (1695, 2060), (310, 2320)],
     "defects": ["perspective", "dark_corner", "vignette"], "light_x": 0.18, "light_y": 0.10,
     "occlusion": "dark_corner", "vignette": 0.30, "jpeg_q": 76},
    {"source_page": 10, "seed": 106, "quad": [(255, 95), (1585, 235), (1540, 2300), (165, 2155)],
     "defects": ["perspective", "uneven_light", "broad_glare", "camera_blur"], "light_x": -0.28,
     "light_y": 0.18, "glare": (730, 880, 720, 360, 0.28), "camera_blur": 0.70, "jpeg_q": 74},
]


def main():
    base = fitz.open(ROOT / "tentex_ocr_bench_scan.pdf")
    clean = fitz.open(ROOT / "clean_master.pdf")
    toc = fitz.open(ROOT / "sources" / "contents_user_example.pdf")

    # Настоящая LaTeX-компиляция — не заменять растровым рендером.
    tectonic = Path(os.environ.get("TECTONIC", "/agent/workspace/bin/tectonic"))
    tex = ROOT / "native_latex" / "native_formulas.tex"
    subprocess.run([str(tectonic), tex.name], cwd=tex.parent, check=True)
    native = fitz.open(tex.with_suffix(".pdf"))

    supplement = build_supplement()
    supplement.save(ROOT / "supplement_clean.pdf")

    out = fitz.open()
    out.insert_pdf(base)

    # P11–P16: phone-photo variants from clean pages.
    for final_page, cfg in enumerate(PHOTO_CONFIGS, start=11):
        page_img = render_page(clean, cfg["source_page"] - 1, dpi=220)
        jpg_path = PHOTO_DIR / f"page_{final_page:02d}.jpg"
        geom_path = GEOM_DIR / f"page_{final_page:02d}.json"
        photo = make_phone_photo(page_img, cfg, jpg_path, geom_path)
        p = out.new_page(width=A4_W, height=A4_H)
        p.insert_image(p.rect, stream=jpg_path.read_bytes())

    # P17–P18: пользовательский пример оглавления, приведённый к скан-виду.
    for i in range(len(toc)):
        tmp = fitz.open()
        tmp.insert_pdf(toc, from_page=i, to_page=i)
        rasterize_scan(tmp, out, dpi=240, jpeg_q=84, noise_sigma=2.0,
                       rotate_deg=0.18 if i == 0 else -0.12, seed=217 + i)
        tmp.close()

    # P19–P21: настоящий нативный текстовый слой формул.
    out.insert_pdf(native)

    # P22–P24: дополнительные контролируемые учебные страницы, как сканы.
    for i in range(len(supplement)):
        tmp = fitz.open()
        tmp.insert_pdf(supplement, from_page=i, to_page=i)
        rasterize_scan(tmp, out, dpi=300, jpeg_q=88, noise_sigma=2.8,
                       rotate_deg=0.0, seed=322 + i)
        tmp.close()

    out_path = ROOT / "tentex_ocr_bench_v2_24p.pdf"
    out.save(out_path)
    out.close()
    supplement.close()
    native.close()
    toc.close()
    clean.close()
    base.close()
    print(f"saved {out_path}")


if __name__ == "__main__":
    main()
