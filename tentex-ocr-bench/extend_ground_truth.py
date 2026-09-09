"""Добавляет ground truth и manifest для страниц 11–24 Tentex OCR Bench v2."""
from __future__ import annotations
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
GT = ROOT / "ground_truth"

PHOTO_MAP = {
    11: (1, ["perspective", "keystone", "page_shadow"]),
    12: (3, ["perspective", "uneven_light", "glare"]),
    13: (5, ["strong_perspective", "corner_shadow", "glare"]),
    14: (7, ["mild_perspective", "finger_occlusion", "page_shadow"]),
    15: (8, ["perspective", "dark_corner", "vignette"]),
    16: (10, ["perspective", "uneven_light", "broad_glare", "camera_blur"]),
}


def body_without_frontmatter(text: str) -> str:
    parts = text.split("---", 2)
    return parts[2].lstrip() if len(parts) == 3 else text


def write(page: int, text: str):
    (GT / f"page_{page:02d}.md").write_text(text.strip() + "\n", encoding="utf-8")


# P11–P16: текст совпадает с исходной чистой страницей; меняется только modality.
for page, (source_page, defects) in PHOTO_MAP.items():
    source = (GT / f"page_{source_page:02d}.md").read_text(encoding="utf-8")
    front = (
        "---\n"
        f"source: контролируемая фотография исходной страницы {source_page}\n"
        f"page_number: {page}\n"
        "modality: phone_photo\n"
        f"variant_of: page_{source_page:02d}.md\n"
        f"defects: {', '.join(defects)}\n"
        f"dewarp_geometry: ../photo_geometry/page_{page:02d}.json\n"
        "---\n\n"
    )
    write(page, front + body_without_frontmatter(source))

P17 = """---
source: пользовательский пример оглавления, страница 3
page_number: 3
modality: rasterized_toc
structure: nested_contents
---

# СОДЕРЖАНИЕ

- **Лекция 1. Вводная лекция** — 5
  - План курса "Операционные системы" — 5
  - Понятие "Операционная система" — 6
  - История эволюции вычислительных систем — 10
  - Основные функции классических операционных систем — 23
- **Лекция 2. Архитектурные особенности и классификация операционных систем** — 26
  - Прерывания. Файловые системы — 26
  - Архитектурные подходы к организации операционных систем — 35
  - Классификация операционных систем — 42
  - Понятие процесса и его состояния, операции над процессами и связанные с ними понятия — 44
- **Лекция 3. Планирование процессов** — 54
  - Операции над процессами и связанные с ними понятия. Окончание — 54
  - Планирование процессов — 60
  - Алгоритмы планирования. Гарантированное и приоритетное планирование — 71
- **Лекция 4. Кооперация процессов и алгоритмы синхронизации** — 84
  - Алгоритмы планирование. Заключение — 84
  - Кооперация процессов — 89
  - Логическая организация механизма обмена данными — 93
  - Передача информации с помощью линий связи — 96
  - Нити исполнения (threads) — 104
  - Алгоритмы синхронизации: чередование, состязание и взаимное исключение — 111
  - Критическая секция — 115
- **Лекция 5. Алгоритмы и механизмы синхронизации** — 118
  - Программные алгоритмы организации взаимодействия процессов — 120
  - Аппаратная поддержка взаимоисключений — 129
  - Механизмы синхронизации. Семафоры — 132
- **Лекция 6. Механизмы синхронизации** — 136
  - Семафоры — 136
  - Мониторы — 137
  - Сообщения — 141
  - Эквивалентность механизмов — 143
- **Лекция 7. Синхронизационные тупики** — 148
  - Условия возникновения и основные направления борьбы с тупиками — 148
  - Восстановление после тупиков — 155
"""

P18 = """---
source: пользовательский пример оглавления, страница 4
page_number: 4
modality: rasterized_toc
structure: nested_contents_continuation
---

# СОДЕРЖАНИЕ (продолжение)

- **Лекция 7. Синхронизационные тупики** (продолжение)
  - Способы предотвращения тупиков — 157
  - Родственные проблемы — 162
- **Лекция 8. Простейшие схемы управления памятью** — 165
  - Организация памяти — 165
  - Простейшие схемы управления памятью — 170
  - Мультипрограммирование с переменными разделами — 175
- **Лекция 9. Средства поддержки виртуальной памяти** — 179
  - Понятие виртуальной памяти и средства её поддержки — 179
  - Страничная память — 183
  - Сегментная и сегментно-страничная виртуальная память — 186
  - Таблица страниц — 189
  - Ассоциативная память — 192
  - Инвертированная таблица страниц — 193
- **Лекция 10. Управление виртуальной памятью в операционных системах** — 196
  - Исключительные ситуации при работе с памятью — 196
  - Стратегии управления страничной памятью — 198
  - Алгоритмы замещения страниц — 200
  - Thrashing, локальность, рабочий набор — 207
  - Аппаратно-независимая модель памяти процесса — 214
  - Отдельные аспекты функционирования менеджера памяти — 217
- **Лекция 11. Файлы с точки зрения пользователя** — 221
  - Основные функции файловой системы — 221
  - Общие сведения о файлах — 225
  - Операции над файлами — 231
  - Логическая структура файлового архива — 233
  - Операции над каталогами — 238
  - Защита файлов — 240
- **Лекция 12. Реализация файловой системы** — 242
  - Общая структура файловой системы — 242
  - Управление внешней памятью — 245
  - Реализация каталогов — 252
  - Монтирование файловых систем — 256
  - Связывание файлов — 258
  - Кооперация процессов при работе с файлами — 260
  - Надежность файловой системы — 263
  - Производительность файловой системы — 267
  - Реализация некоторых операций над файлами — 269
  - Современные архитектуры файловых систем — 272
"""

P19 = r"""---
source: LaTeX-компиляция Tectonic
page_number: 1
modality: native_pdf
text_layer: true
images: 0
---

# Нативный PDF: формулы математического анализа

*Формулы набраны LaTeX и не растеризованы*

Пусть $f$ непрерывна на отрезке $[a,b]$, а $F'(x)=f(x)$. Тогда формула Ньютона--Лейбница имеет вид

$$\int_a^b f(x)\,dx = F(b)-F(a). \tag{N.1}$$

Для функции двух переменных полный дифференциал и квадратичная форма второго порядка записываются так:

$$du = \frac{\partial u}{\partial x}\,dx + \frac{\partial u}{\partial y}\,dy, \tag{N.2}$$

$$d^2u = u_{xx}\,dx^2 + 2u_{xy}\,dx\,dy + u_{yy}\,dy^2. \tag{N.3}$$

Ряд Фурье функции периода $2\pi$ задаётся формулой

$$f(x) \sim \frac{a_0}{2}+\sum_{n=1}^{\infty}\bigl(a_n\cos nx+b_n\sin nx\bigr), \quad a_n=\frac{1}{\pi}\int_{-\pi}^{\pi}f(x)\cos nx\,dx. \tag{N.4}$$

Для проверки распознавания пределов включим составную дробь:

$$\lim_{x\to0}\frac{\sqrt{1+x}-1}{x}=\frac12, \qquad \lim_{n\to\infty}\left(1+\frac{x}{n}\right)^n=e^x. \tag{N.5}$$
"""

P20 = r"""---
source: LaTeX-компиляция Tectonic
page_number: 2
modality: native_pdf
text_layer: true
images: 0
---

# Нативный PDF: линейная алгебра и системы

Система линейных уравнений $A\mathbf{x}=\mathbf{b}$ имеет единственное решение, если $\det A\ne0$. В развёрнутом виде:

$$\begin{cases}2x-y+3z=7,\\x+4y-z=2,\\3x+2y+2z=9.\end{cases} \tag{N.6}$$

Определитель и обратная матрица:

$$\det A=\sum_{\sigma\in S_n}\operatorname{sgn}(\sigma)\prod_{i=1}^{n}a_{i,\sigma(i)}, \qquad A^{-1}=\frac{1}{\det A}\operatorname{adj}A. \tag{N.7}$$

Спектральное разложение симметрической матрицы:

$$A=Q\Lambda Q^{\mathsf T},\qquad Q^{\mathsf T}Q=I, \qquad \Lambda=\operatorname{diag}(\lambda_1,\ldots,\lambda_n). \tag{N.8}$$

Норма и скалярное произведение:

$$\|\mathbf{x}\|_2=\sqrt{\sum_{i=1}^{n}|x_i|^2}, \qquad \langle\mathbf{x},\mathbf{y}\rangle=\mathbf{x}^{\mathsf T}\mathbf{y}. \tag{N.9}$$
"""

P21 = r"""---
source: LaTeX-компиляция Tectonic
page_number: 3
modality: native_pdf
text_layer: true
images: 0
---

# Нативный PDF: вероятность и статистика

Для дискретной случайной величины $X$ математическое ожидание и дисперсия равны

$$\mathbb{E}X = \sum_k x_k p_k, \tag{N.10}$$

$$\operatorname{Var}(X) = \mathbb{E}\bigl[(X-\mathbb{E}X)^2\bigr] =\mathbb{E}X^2-(\mathbb{E}X)^2. \tag{N.11}$$

Плотность нормального распределения:

$$p(x)=\frac{1}{\sigma\sqrt{2\pi}}\exp\!\left[-\frac{(x-\mu)^2}{2\sigma^2}\right]. \tag{N.12}$$

Формула Байеса для полной группы гипотез $H_1,\ldots,H_m$:

$$\mathbb{P}(H_i\mid A)=\frac{\mathbb{P}(H_i)\,\mathbb{P}(A\mid H_i)}{\sum_{j=1}^{m}\mathbb{P}(H_j)\,\mathbb{P}(A\mid H_j)}. \tag{N.13}$$

В качестве теста комбинаторной записи используем биномиальное тождество

$$\sum_{k=0}^{n}\binom{n}{k}p^k(1-p)^{n-k}=1. \tag{N.14}$$
"""

P22 = r"""---
source: учебник по общей химии
page_number: 178
modality: scanned_pdf
---

# § 9. Равновесие в растворах электролитов

Слабая уксусная кислота диссоциирует обратимо. Равновесие записывают уравнением $CH_3COOH \rightleftharpoons H^+ + CH_3COO^-$.

$$K_a = \frac{[H^+][CH_3COO^-]}{[CH_3COOH]} = 1{,}8 \cdot 10^{-5}. \tag{9.1}$$

Для водного раствора справедливо ионное произведение воды $K_w = [H^+][OH^-] = 10^{-14}$ при температуре 25 °C. Поэтому водородный показатель определяют как

$$\mathrm{pH} = -\lg[H^+], \qquad \mathrm{pOH} = -\lg[OH^-], \qquad \mathrm{pH}+\mathrm{pOH}=14. \tag{9.2}$$

## Буферные растворы

Для смеси слабой кислоты HA и её соли применяется уравнение Хендерсона — Хассельбаха:

$$\mathrm{pH}=\mathrm{p}K_a+\lg\frac{[A^-]}{[HA]}. \tag{9.3}$$

*Таблица 9.1 — Примеры буферных систем*

| Система | Реакция | Тип |
|---|---|---|
| Гидрокарбонат | H₂CO₃ ⇄ H⁺ + HCO₃⁻ | кислотная |
| Аммоний | NH₄⁺ ⇄ H⁺ + NH₃ | кислотная |
| Фосфат | H₂PO₄⁻ ⇄ H⁺ + HPO₄²⁻ | амфолит |

**Пример.** В растворе концентрации уксусной кислоты и ацетата натрия равны соответственно 0,10 и 0,20 моль/л. Тогда $\mathrm{pH}=4{,}74+\lg 2 \approx 5{,}04$.
"""

P23 = r"""---
source: сборник задач по математике
page_number: 246
modality: scanned_pdf
structure: nested_task_and_solution
---

# Задача 12.7. Исследование функции

Дана функция $f(x)=x^3-3x^2-9x+5$.

## Требуется

1. Найти область определения и нули функции.
2. Исследовать функцию: а) на монотонность; б) на экстремумы; в) на выпуклость и точки перегиба.
3. Построить эскиз графика и отметить характерные точки.

## Решение

Производные первого и второго порядка равны

$$f'(x)=3x^2-6x-9=3(x+1)(x-3),$$

$$f''(x)=6x-6=6(x-1). \tag{12.8}$$

Критические точки: $x_1=-1$ и $x_2=3$. Точка перегиба: $x=1$.

*Таблица 12.2 — Таблица монотонности*

| Интервал | знак f′ | Поведение f | Вывод |
|---|---|---|---|
| (−∞; −1) | + | возрастает | — |
| (−1; 3) | − | убывает | max при x=−1 |
| (3; +∞) | + | возрастает | min при x=3 |

**Ответ.** Локальный максимум $f(-1)=10$; локальный минимум $f(3)=-22$; точка перегиба $(1;-6)$.
"""

P24 = """---
source: список литературы и электронных ресурсов
page_number: 312
modality: scanned_pdf
structure: bibliography_and_abbreviations
---

# Литература и электронные ресурсы

Ниже приведён пример списка источников, содержащего кириллицу, латиницу, DOI, URL и диапазоны страниц. Такой материал проверяет сохранение пунктуации и порядка чтения.

1. Иванов А. В., Петрова Н. С. Цифровая обработка учебных материалов. — М.: Техносфера, 2024. — 368 с. — ISBN 978-5-94836-712-9.
2. Smith J., Lee K. Layout-aware document parsing for education. Document Intelligence, 2025, vol. 8, no. 2, pp. 41–59. DOI: 10.1234/di.2025.00802.
3. Ouyang L. et al. OmniDocBench: Benchmarking Diverse PDF Document Parsing. Proceedings of CVPR, 2025, pp. 1386–1397.
4. Zhong X., ShafieiBavani E., Jimeno Yepes A. Image-based table recognition: data, model, and evaluation. ECCV, 2020. DOI: 10.1007/978-3-030-58589-1_33.
5. W3C. Mathematical Markup Language (MathML) Version 3.0. URL: https://www.w3.org/TR/MathML3/ (дата обращения: 15.08.2026).

## Список сокращений

*Таблица 14 — Сокращения, используемые в тексте*

| Сокращение | Расшифровка |
|---|---|
| OCR | optical character recognition |
| VLM | vision-language model |
| RAG | retrieval-augmented generation |
| PDF | Portable Document Format |
| CDM | formula character/structure distance metric |

**Примечание.** Идентификатор DOI следует сохранять как одну непрерывную строку; перенос URL допускается только после символа косой черты.
"""

for n, text in [(17, P17), (18, P18), (19, P19), (20, P20), (21, P21), (22, P22), (23, P23), (24, P24)]:
    write(n, text)

manifest_path = GT / "manifest.json"
m = json.loads(manifest_path.read_text(encoding="utf-8"))
m["benchmark"] = "Tentex OCR Bench v2"
m["version"] = "2.0"
m["description"] = "24 страницы для оценки OCR/VLM: сканы, телефонные фото с dewarp-разметкой, оглавление, нативный PDF с LaTeX-формулами и дополнительные учебные сценарии."
m["primary_pdf"] = "tentex_ocr_bench_v2_24p.pdf"
m["page_count"] = 24
m["scenario_summary"] = {
    "scanned_pages": 13,
    "phone_photos": 6,
    "table_of_contents": 2,
    "native_latex_pdf": 3,
    "reference_handwritten_photos_unscored": 3,
}
# Исправляем старое имя и дополняем параметры.
m["degradation"]["pages_1_to_8_and_10"] = "dpi=300, jpeg_q=88, noise_sigma=3.0, rotate=0.0"
m["degradation"]["pages_11_to_16"] = "контролируемые phone-photo variants; точные углы в photo_geometry/page_XX.json"
m["degradation"]["pages_17_to_18"] = "user-provided TOC rendered at 240 DPI, mild JPEG/noise/rotation"
m["degradation"]["pages_19_to_21"] = "none; true Tectonic LaTeX PDF, native text layer, zero images"
m["degradation"]["pages_22_to_24"] = "dpi=300, jpeg_q=88, noise_sigma=2.8"

m["pages"].extend([
    {"page": 11, "file": "page_11.md", "source": "phone photo variant of page 1", "modality": "phone_photo", "variant_of": 1, "elements": ["perspective", "keystone", "shadow", "dewarp_corners"], "difficulty": "hard", "text_layer": False},
    {"page": 12, "file": "page_12.md", "source": "phone photo variant of page 3", "modality": "phone_photo", "variant_of": 3, "elements": ["perspective", "uneven_light", "glare", "figure"], "difficulty": "hard", "text_layer": False},
    {"page": 13, "file": "page_13.md", "source": "phone photo variant of page 5", "modality": "phone_photo", "variant_of": 5, "elements": ["strong_perspective", "corner_shadow", "glare", "chart", "table"], "difficulty": "very_hard", "text_layer": False},
    {"page": 14, "file": "page_14.md", "source": "phone photo variant of page 7", "modality": "phone_photo", "variant_of": 7, "elements": ["mild_perspective", "finger_occlusion", "code_block"], "difficulty": "hard", "text_layer": False},
    {"page": 15, "file": "page_15.md", "source": "phone photo variant of page 8", "modality": "phone_photo", "variant_of": 8, "elements": ["perspective", "dark_corner", "vignette", "dense_math", "table"], "difficulty": "very_hard", "text_layer": False},
    {"page": 16, "file": "page_16.md", "source": "phone photo variant of page 10", "modality": "phone_photo", "variant_of": 10, "elements": ["perspective", "uneven_light", "broad_glare", "camera_blur", "table"], "difficulty": "very_hard", "text_layer": False},
    {"page": 17, "file": "page_17.md", "source": "user-provided OS contents page 3", "modality": "rasterized_toc", "elements": ["nested_contents", "dot_leaders", "page_numbers", "wrapped_entries"], "difficulty": "hard", "text_layer": False},
    {"page": 18, "file": "page_18.md", "source": "user-provided OS contents page 4", "modality": "rasterized_toc", "elements": ["nested_contents_continuation", "dot_leaders", "page_numbers", "mixed_latin"], "difficulty": "hard", "text_layer": False},
    {"page": 19, "file": "page_19.md", "source": "Tectonic LaTeX: calculus", "modality": "native_pdf", "elements": ["native_text_layer", "display_math", "fractions", "integrals", "limits", "partial_derivatives"], "difficulty": "medium", "text_layer": True, "images": 0},
    {"page": 20, "file": "page_20.md", "source": "Tectonic LaTeX: linear algebra", "modality": "native_pdf", "elements": ["native_text_layer", "equation_system", "matrices", "determinant", "norm"], "difficulty": "hard", "text_layer": True, "images": 0},
    {"page": 21, "file": "page_21.md", "source": "Tectonic LaTeX: probability", "modality": "native_pdf", "elements": ["native_text_layer", "expectation", "variance", "normal_density", "Bayes", "binomial"], "difficulty": "hard", "text_layer": True, "images": 0},
    {"page": 22, "file": "page_22.md", "source": "synthetic chemistry textbook", "modality": "scanned_pdf", "elements": ["chemical_formula", "charges", "reversible_reaction", "table"], "difficulty": "hard", "text_layer": False},
    {"page": 23, "file": "page_23.md", "source": "synthetic problem book", "modality": "scanned_pdf", "elements": ["nested_task", "stepwise_solution", "sign_table", "display_math"], "difficulty": "medium", "text_layer": False},
    {"page": 24, "file": "page_24.md", "source": "synthetic bibliography", "modality": "scanned_pdf", "elements": ["bibliography", "DOI", "URL", "ISBN", "mixed_cyrillic_latin", "abbreviation_table"], "difficulty": "medium", "text_layer": False},
])
manifest_path.write_text(json.dumps(m, ensure_ascii=False, indent=2), encoding="utf-8")
print("wrote pages 11–24 and manifest v2")
