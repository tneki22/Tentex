"""Извлечение оглавления (Работа 4 плана правок мастера учебника).

`find_printed_outline` работает по текстовому слою печатной страницы
«Оглавление»/«Содержание» — без OCR, без разбора материала. Тесты строят
синтетические PDF через `pymupdf`, чтобы детерминированно проверить точечную
выноску и её отсутствие, уровни по нумерации, оглавление в конце книги,
одиночный выброс в номерах страниц и страницу-обманку (список литературы).

Отдельный блок проверяет приоритет источников (`library.outline_sources`) —
`embedded` побеждает `printed`, который побеждает `recognized`.
"""

from pathlib import Path

import pymupdf as fitz
import pytest
from conftest import add_page_with_fragments, make_material
from sqlalchemy.orm import Session

from app.materials import library, outline
from app.materials.outline import find_printed_outline
from app.materials.schemas import OutlineItem
from app.models import MaterialSourceKind

LINE_HEIGHT = 20.0
LEFT_MARGIN = 50.0


@pytest.mark.parametrize("found", [None, ([{"level": 1, "title": "Contents", "page": 1}], [1])])
def test_printed_outline_cache_isolated_and_invalidated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, found: object
) -> None:
    """Опрос не сканирует PDF повторно, включая отсутствие; новый файл виден."""
    path = tmp_path / "cached.pdf"
    path.write_bytes(b"first")
    calls = []

    def scan(source: Path, page_count: int):
        calls.append((source, page_count))
        return found

    monkeypatch.setattr(outline, "_scan_printed_outline", scan)
    first = find_printed_outline(path, 1)
    if first:
        first[0][0]["title"] = "Changed by caller"
        first[1].append(99)
    assert find_printed_outline(path, 1) == found
    assert len(calls) == 1
    path.write_bytes(b"second version")
    assert find_printed_outline(path, 1) == found
    assert len(calls) == 2
    find_printed_outline(path, 2)
    assert len(calls) == 3


def _make_pdf(path: Path, pages: list[list[tuple[str, float]]]) -> Path:
    """Каждая страница — список (текст, отступ от LEFT_MARGIN в пунктах)."""
    document = fitz.open()
    for lines in pages:
        page = document.new_page()
        y = 60.0
        for text, indent in lines:
            page.insert_text((LEFT_MARGIN + indent, y), text, fontsize=11)
            y += LINE_HEIGHT
    document.save(path)
    document.close()
    return path


def _flat(lines: list[str]) -> list[list[tuple[str, float]]]:
    return [[(line, 0.0) for line in lines]]


def test_finds_printed_outline_with_dot_leaders(tmp_path: Path) -> None:
    lines = [
        "Contents",
        "Introduction .......................... 3",
        "Chapter 1 Basics .......................... 5",
        "History .......................... 6",
        "Overview .......................... 8",
        "Chapter 2 Advanced Topics .......................... 12",
        "Details .......................... 14",
        "Examples .......................... 20",
        "Appendix .......................... 25",
    ]
    path = _make_pdf(tmp_path / "leaders.pdf", _flat(lines))

    # page_count — объём книги, которую страница представляет (используется
    # как верхняя граница правдоподобия номера), а не число страниц PDF-файла.
    result = find_printed_outline(path, page_count=30)

    assert result is not None
    items, source_pages = result
    assert source_pages == [1]
    assert [item["page"] for item in items] == [3, 5, 6, 8, 12, 14, 20, 25]
    assert items[0]["title"] == "Introduction"
    assert items[2]["title"] == "History"


def test_finds_printed_outline_without_dot_leaders(tmp_path: Path) -> None:
    lines = [
        "Contents",
        "Introduction     3",
        "Basics     5",
        "History     6",
        "Overview     8",
        "Advanced Topics     12",
        "Details     14",
        "Examples     20",
        "Appendix     25",
    ]
    path = _make_pdf(tmp_path / "plain.pdf", _flat(lines))

    result = find_printed_outline(path, page_count=30)

    assert result is not None
    items, _ = result
    assert [item["page"] for item in items] == [3, 5, 6, 8, 12, 14, 20, 25]
    assert items[0]["title"] == "Introduction"


def test_printed_outline_joins_detached_pages_and_wrapped_titles(tmp_path: Path) -> None:
    """Макет реального учебника: номер лекции отдельным блоком справа."""
    path = tmp_path / "detached-pages.pdf"
    document = fitz.open()
    page = document.new_page()
    page.insert_text((50, 40), "Course header", fontsize=9)
    page.insert_text((50, 60), "Contents", fontsize=12)
    rows = [
        ("Lecture 1. Introduction", 5, 0),
        ("Course plan", 5, 70),
        ("Operating system", 6, 70),
        ("History", 10, 70),
        ("Classic functions", 23, 70),
        ("Lecture 2. Architecture", 26, 0),
        ("Interrupts", 26, 70),
    ]
    y = 90
    for title, target_page, indent in rows:
        if title == "History":
            page.insert_text((50 + indent, y), "History of computing", fontsize=11)
            y += 14
            title = "systems ........................"
        page.insert_text((50 + indent, y), title, fontsize=11)
        page.insert_text((520, y), str(target_page), fontsize=11)
        y += 20
    page.insert_text((120, y), "Scheduling ........................ 30", fontsize=11)
    document.save(path)
    document.close()

    result = find_printed_outline(path, page_count=40)

    assert result is not None
    items, source_pages = result
    assert source_pages == [1]
    assert [(item["level"], item["title"], item["page"]) for item in items] == [
        (1, "Lecture 1. Introduction", 5),
        (2, "Course plan", 5),
        (2, "Operating system", 6),
        (2, "History of computing systems", 10),
        (2, "Classic functions", 23),
        (1, "Lecture 2. Architecture", 26),
        (2, "Interrupts", 26),
        (2, "Scheduling", 30),
    ]


def test_recognized_outline_uses_sections_as_roots_and_removes_noise() -> None:
    items = [
        OutlineItem(level=1, title="OPERATING SYSTEMS", page=1),
        OutlineItem(level=2, title="Author Name", page=1),
        OutlineItem(level=1, title="Lecture 1. Introduction", page=5),
        OutlineItem(level=1, title="Operating system", page=6),
        OutlineItem(level=1, title="Producer: while(1) {", page=12),
        OutlineItem(level=1, title="Lecture 2. Architecture", page=26),
        OutlineItem(level=2, title="Interrupts", page=26),
    ]

    normalized = library._normalize_recognized_outline(items)

    assert [(item.level, item.title) for item in normalized] == [
        (1, "Lecture 1. Introduction"),
        (2, "Operating system"),
        (1, "Lecture 2. Architecture"),
        (2, "Interrupts"),
    ]


def test_recognized_outline_preserves_part_topic_and_subpoint_levels() -> None:
    items = [
        OutlineItem(level=1, title="ЭКОНОМИКА", page=1),
        OutlineItem(level=1, title="ЧАСТЬ ПЕРВАЯ. ВВЕДЕНИЕ", page=8),
        OutlineItem(level=1, title="ТЕМА 1. ПРЕДМЕТ И МЕТОД", page=8),
        OutlineItem(level=1, title="Что изучает экономическая теория?", page=8),
        OutlineItem(level=1, title="Вопросы для повторения", page=28),
        OutlineItem(level=1, title="ТЕМА 2. РЫНОЧНАЯ ЭКОНОМИКА", page=29),
        OutlineItem(level=1, title="Различные экономические системы", page=29),
    ]

    normalized = library._normalize_recognized_outline(items)

    assert [(item.level, item.title) for item in normalized] == [
        (1, "ЧАСТЬ ПЕРВАЯ. ВВЕДЕНИЕ"),
        (2, "ТЕМА 1. ПРЕДМЕТ И МЕТОД"),
        (3, "Что изучает экономическая теория?"),
        (3, "Вопросы для повторения"),
        (2, "ТЕМА 2. РЫНОЧНАЯ ЭКОНОМИКА"),
        (3, "Различные экономические системы"),
    ]


def test_recognized_candidate_accepts_named_paragraphs_and_rejects_layout_noise() -> None:
    assert library._recognized_candidate("ЧАСТЬ ПЕРВАЯ. ВВЕДЕНИЕ", "paragraph")
    assert library._recognized_candidate("ТЕМА 1. ПРЕДМЕТ ЭКОНОМИКИ", "paragraph")
    assert library._recognized_candidate("1. ВАЖНЕЙШИЕ ПОНЯТИЯ", "paragraph")
    assert library._recognized_candidate("Вопросы для повторения", "paragraph")
    assert library._recognized_candidate("Понятие операционной системы", "heading")
    assert not library._recognized_candidate("Рис. 1.4. Ограниченность ресурсов", "heading")
    assert not library._recognized_candidate("Qd = f(P, I, Z)", "heading")
    assert not library._recognized_candidate("Обычный абзац текста.", "heading")
    assert not library._recognized_candidate("Часть определений приведена ниже", "heading")


def test_named_parts_and_topics_restore_hierarchy_without_indents(tmp_path: Path) -> None:
    lines = [
        "Contents",
        "Preface .......................... 6",
        "Part First. Introduction .......................... 8",
        "Topic 1. Fundamentals .......................... 8",
        "1. Subject and method .......................... 8",
        "2. Core concepts .......................... 16",
        "Review questions .......................... 28",
        "Topic 2. Market economy .......................... 29",
        "1. Economic systems .......................... 29",
    ]
    path = _make_pdf(tmp_path / "named-hierarchy.pdf", _flat(lines))

    result = find_printed_outline(path, page_count=40)

    assert result is not None
    items, _ = result
    assert [(item["level"], item["title"]) for item in items] == [
        (1, "Preface"),
        (1, "Part First. Introduction"),
        (2, "Topic 1. Fundamentals"),
        (3, "Subject and method"),
        (3, "Core concepts"),
        (3, "Review questions"),
        (2, "Topic 2. Market economy"),
        (3, "Economic systems"),
    ]


def test_numbering_maps_to_levels(tmp_path: Path) -> None:
    lines = [
        "Contents",
        "1 Introduction .......... 3",
        "1.1 Background .......... 4",
        "1.1.1 Details .......... 5",
        "2 Methods .......... 8",
        "2.1 Approach .......... 9",
        "3 Results .......... 15",
        "4 Conclusion .......... 20",
        "4.1 Future Work .......... 22",
    ]
    path = _make_pdf(tmp_path / "numbered.pdf", _flat(lines))

    result = find_printed_outline(path, page_count=25)

    assert result is not None
    items, _ = result
    assert [item["level"] for item in items] == [1, 2, 3, 1, 2, 1, 1, 2]
    assert [item["title"] for item in items] == [
        "Introduction",
        "Background",
        "Details",
        "Methods",
        "Approach",
        "Results",
        "Conclusion",
        "Future Work",
    ]


def test_outline_at_end_of_book_is_found(tmp_path: Path) -> None:
    toc_lines = [
        "Contents",
        "Introduction .......... 3",
        "Basics .......... 5",
        "History .......... 6",
        "Overview .......... 8",
        "Advanced Topics .......... 12",
        "Details .......... 14",
        "Examples .......... 20",
        "Appendix .......... 25",
    ]
    pages = [[(f"Filler page {number}", 0.0)] for number in range(1, 45)]
    pages.insert(44, [(line, 0.0) for line in toc_lines])  # страница 45 (индекс 44) — оглавление
    path = _make_pdf(tmp_path / "trailing.pdf", pages)

    result = find_printed_outline(path, page_count=len(pages))

    assert result is not None
    items, source_pages = result
    assert source_pages == [45]
    assert len(items) == 8


def test_out_of_order_page_is_dropped_not_whole_page(tmp_path: Path) -> None:
    lines = [
        "Contents",
        "A .......... 3",
        "B .......... 5",
        "C .......... 7",
        "D .......... 4",  # выброс: меньше предыдущего — отбрасывается один
        "E .......... 9",
        "F .......... 11",
        "G .......... 13",
        "H .......... 15",
        "I .......... 17",
    ]
    path = _make_pdf(tmp_path / "outlier.pdf", _flat(lines))

    result = find_printed_outline(path, page_count=20)

    assert result is not None
    items, _ = result
    assert [item["title"] for item in items] == ["A", "B", "C", "E", "F", "G", "H", "I"]
    assert [item["page"] for item in items] == [3, 5, 7, 9, 11, 13, 15, 17]


def test_page_footer_with_year_is_not_mistaken_for_entry(tmp_path: Path) -> None:
    # Найдено на реальном учебнике: повторяющийся колонтитул с годом издания
    # ("Курс, Университет, 2023") оканчивается числом и проходит первичный
    # regex, но 2023 намного больше объёма книги — верхняя граница по
    # page_count должна его отсечь, а не показать пользователю лишний пункт.
    lines = [
        "Contents",
        "Introduction .......................... 3",
        "Course Name, University, 2023",
        "Chapter 1 Basics .......................... 5",
        "History .......................... 6",
        "Overview .......................... 8",
        "Chapter 2 Advanced Topics .......................... 12",
        "Details .......................... 14",
        "Examples .......................... 20",
        "Appendix .......................... 25",
    ]
    path = _make_pdf(tmp_path / "footer-year.pdf", _flat(lines))

    result = find_printed_outline(path, page_count=30)

    assert result is not None
    items, _ = result
    assert [item["page"] for item in items] == [3, 5, 6, 8, 12, 14, 20, 25]
    assert all(item["page"] != 2023 for item in items)


def test_bibliography_page_is_not_mistaken_for_outline(tmp_path: Path) -> None:
    # Список литературы: годы идут вразнобой (по алфавиту автора), а не по
    # возрастанию, и точечной выноски нет — ровно то, чем такая страница
    # отличается от настоящего оглавления.
    lines = [
        "References",
        "Smith J. Great Book 2015",
        "Doe A. Another Work 1998",
        "Lee K. Something Else 2020",
        "Brown M. Old Text 1975",
        "Grey P. New Paper 2003",
        "White S. Classic 1990",
        "Black T. Modern 2018",
        "Green R. Ancient 1965",
    ]
    path = _make_pdf(tmp_path / "bibliography.pdf", _flat(lines))

    result = find_printed_outline(path, page_count=1)

    assert result is None


def test_prefers_full_toc_over_brief_contents_page(tmp_path: Path) -> None:
    # Найдено на реальном учебнике (Олифер, «Компьютерные сети», кириллица —
    # воспроизведено здесь латиницей: `insert_text` без встроенного шрифта не
    # печатает кириллицу, см. остальные тесты файла): короткое «Краткое
    # содержание» (только части книги, 2 страницы) стоит в файле раньше
    # подробного «Оглавление» (все главы, 14 страниц) — по плотности выносок
    # обе страницы проходят фильтр одинаково, но заголовок различает их
    # однозначно. Раньше сканер останавливался на первой подходящей странице
    # и возвращал укороченный вариант.
    brief = [
        "Brief Contents",
        "Part I .......... 24",
        "Part II .......... 120",
        "Part III .......... 300",
        "Part IV .......... 450",
        "Part V .......... 600",
        "Part VI .......... 750",
        "Part VII .......... 900",
    ]
    full_page_1 = [
        "Contents",
        "Preface .......... 21",
        "Chapter 1. Introduction .......... 26",
        "Chapter 2. Basics .......... 41",
        "Chapter 3. Networks .......... 53",
        "Chapter 4. Protocols .......... 60",
        "Chapter 5. Addressing .......... 70",
        "Chapter 6. Routing .......... 80",
        "Chapter 7. Switching .......... 90",
    ]
    full_page_2 = [
        "Contents",
        "Chapter 8. Security .......... 100",
        "Chapter 9. DWDM .......... 110",
        "Chapter 10. VLAN .......... 120",
        "Chapter 11. DHCP .......... 130",
        "Chapter 12. Routing 2 .......... 140",
        "Chapter 13. LSP .......... 150",
        "Chapter 14. Bluetooth .......... 160",
        "Chapter 15. SMTP .......... 170",
    ]
    pages = [
        [("Title page", 0.0)],
        [("Copyright", 0.0)],
        [(line, 0.0) for line in brief],
        [(line, 0.0) for line in full_page_1],
        [(line, 0.0) for line in full_page_2],
    ]
    path = _make_pdf(tmp_path / "brief-vs-full.pdf", pages)

    result = find_printed_outline(path, page_count=200)

    assert result is not None
    items, source_pages = result
    assert source_pages == [4, 5]
    assert len(items) == 16
    assert items[0]["title"] == "Preface"
    titles = [item["title"] for item in items]
    assert "Part I" not in titles


def test_missing_file_returns_none_instead_of_raising(tmp_path: Path) -> None:
    assert find_printed_outline(tmp_path / "does-not-exist.pdf", page_count=10) is None


def test_non_pdf_returns_none(tmp_path: Path) -> None:
    text_path = tmp_path / "notes.txt"
    text_path.write_text("Contents\nIntroduction 3\n")
    assert find_printed_outline(text_path, page_count=1) is None


# ── Приоритет источников ─────────────────────────────────────────────────


def _pdf_material(session: Session, seed: str, tmp_path: Path, page_count: int = 1) -> object:
    """Материал с реальным PDF-файлом на диске, без embedded/recognized."""
    material = make_material(session, seed)
    material.media_type = "application/pdf"
    material.source_kind = MaterialSourceKind.FILE
    material.storage_path = f"materials/{seed}.pdf"
    material.page_count = page_count
    session.commit()
    return material


def test_outline_source_priority_embedded_wins(
    session: Session, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from app.config import settings

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    material = _pdf_material(session, "1a2b", tmp_path)
    material.outline = [{"level": 1, "title": "Из закладок", "page": 1}]
    session.commit()
    from app.materials.storage import material_path

    file_path = material_path(material.storage_path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    _make_pdf(file_path, _flat([
        "Contents", "A .......... 1", "B .......... 2", "C .......... 3", "D .......... 4",
        "E .......... 5", "F .......... 6", "G .......... 7", "H .......... 8",
    ]))

    found = library.outline_sources(session, material)

    assert set(found) >= {"embedded", "printed"}

    def unexpected_scan(*args):
        pytest.fail("Карточка с закладками не должна сканировать запасные источники")

    monkeypatch.setattr(library, "_printed_outline", unexpected_scan)
    monkeypatch.setattr(library, "_recognized_outline", unexpected_scan)
    items, source = library._outline(session, material)
    assert source == "embedded"
    assert [item.title for item in items] == ["Из закладок"]


def test_outline_source_priority_printed_over_recognized(
    session: Session, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from app.config import settings

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    material = _pdf_material(session, "3c4d", tmp_path)
    from app.materials.storage import material_path

    file_path = material_path(material.storage_path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    _make_pdf(file_path, _flat([
        "Contents", "A .......... 1", "B .......... 2", "C .......... 3", "D .......... 4",
        "E .......... 5", "F .......... 6", "G .......... 7", "H .......... 8",
    ]))
    # Распознанные заголовки тоже есть, но печатное оглавление приоритетнее.
    add_page_with_fragments(session, material, page_number=1, revision=1, fragments=["Заголовок"])
    material.active_parse_revision = 1
    session.commit()
    page_fragments = library.fragments_by_page(session, material.id, 1)[1]
    page_fragments[0].element_kind = "heading"
    session.commit()

    items, source = library._outline(session, material)

    assert source == "printed"
    assert len(items) == 8


def test_outline_source_priority_recognized_when_no_pdf_source(session: Session) -> None:
    material = make_material(session, "5e6f")
    material.active_parse_revision = 0
    add_page_with_fragments(session, material, page_number=1, revision=1, fragments=["Заголовок"])
    material.active_parse_revision = 1
    session.commit()
    page_fragments = library.fragments_by_page(session, material.id, 1)[1]
    page_fragments[0].element_kind = "heading"
    page_fragments[0].structure_level = 1
    session.commit()

    items, source = library._outline(session, material)

    assert source == "recognized"
    assert [item.title for item in items] == ["Заголовок"]


# ── Страница для просмотрщика (`resolve_outline`) ────────────────────────
#
# Независима от того, откуда взяты сами пункты: печатная страница «Оглавление»
# — самый надёжный ориентир для проверки глазами, даже когда пункты в итоге
# взяты из закладок PDF (у самих закладок привязки к странице нет).


def test_resolve_outline_review_page_prefers_printed_even_when_embedded_wins(
    session: Session, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from app.config import settings

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    material = _pdf_material(session, "6a7b", tmp_path)
    material.outline = [{"level": 1, "title": "Из закладок", "page": 1}]
    session.commit()
    from app.materials.storage import material_path

    file_path = material_path(material.storage_path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    _make_pdf(file_path, _flat([
        "Contents", "A .......... 6", "B .......... 7", "C .......... 8", "D .......... 9",
        "E .......... 10", "F .......... 11", "G .......... 12", "H .......... 13",
    ]))

    detail = library.resolve_outline(session, material, "auto")

    assert detail.source == "embedded"
    assert detail.review_pages == [1]
    assert detail.review_needs_check is False


def test_resolve_outline_review_page_defaults_quietly_for_embedded_only(session: Session) -> None:
    # Материал текстовый (не PDF) — печатную страницу искать негде, но
    # закладки нашлись сами по себе: страница 1 по умолчанию — не повод
    # для предупреждения, это ожидаемое поведение для такого источника.
    material = make_material(session, "7c8d")
    material.outline = [{"level": 1, "title": "Из закладок", "page": 1}]
    session.commit()

    detail = library.resolve_outline(session, material, "auto")

    assert detail.source == "embedded"
    assert detail.review_pages == []
    assert detail.review_needs_check is False


def test_resolve_outline_review_page_warns_without_printed_anchor(session: Session) -> None:
    material = make_material(session, "9e0f")
    material.active_parse_revision = 0
    add_page_with_fragments(session, material, page_number=1, revision=1, fragments=["Заголовок"])
    material.active_parse_revision = 1
    session.commit()
    page_fragments = library.fragments_by_page(session, material.id, 1)[1]
    page_fragments[0].element_kind = "heading"
    page_fragments[0].structure_level = 1
    session.commit()

    detail = library.resolve_outline(session, material, "auto")

    assert detail.source == "recognized"
    assert detail.review_pages == []
    assert detail.review_needs_check is True


def test_resolve_outline_review_page_warns_when_nothing_found(session: Session) -> None:
    material = make_material(session, "1f2e")
    material.active_parse_revision = 0
    session.commit()

    detail = library.resolve_outline(session, material, "auto")

    assert detail.source == "none"
    assert detail.review_pages == []
    assert detail.review_needs_check is True
