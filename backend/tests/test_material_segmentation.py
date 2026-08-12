from app.materials.parsers.base import ParsedElement, ParsedPage
from app.materials.parsers.paddle_fast import split_numbered_line
from app.materials.segmentation import build_blocks


def page(number: int, *elements: ParsedElement) -> ParsedPage:
    return ParsedPage(number, 1, 1, "", "", "native", elements)


def test_blocks_follow_headings_across_pages() -> None:
    blocks = build_blocks(
        [
            page(
                1,
                ParsedElement("paragraph", "Вводный текст", (0, 0, 1, 0.2)),
                ParsedElement("heading", "1. Индексы", (0, 0.2, 1, 0.4), 1),
                ParsedElement("paragraph", "Ответ про индексы", (0, 0.4, 1, 1)),
            ),
            page(
                2,
                ParsedElement("paragraph", "Продолжение ответа", (0, 0, 1, 0.3)),
                ParsedElement("heading", "2. Транзакции", (0, 0.3, 1, 0.5), 1),
                ParsedElement("paragraph", "Ответ про транзакции", (0, 0.5, 1, 1)),
            ),
        ]
    )

    assert [block.title for block in blocks] == [None, "1. Индексы", "2. Транзакции"]
    assert [page_number for page_number, _ in blocks[1].elements] == [1, 1, 2]


def test_known_service_heading_is_classified_without_discarding_text() -> None:
    blocks = build_blocks(
        [
            page(
                1,
                ParsedElement("heading", "Содержание", (0, 0, 1, 0.2), 1),
                ParsedElement("paragraph", "Глава 1 ........ 3", (0, 0.2, 1, 1)),
            )
        ]
    )

    assert blocks[0].service_reason == "table_of_contents"
    assert [element.text for _, element in blocks[0].elements] == [
        "Содержание",
        "Глава 1 ........ 3",
    ]


def test_ocr_line_with_two_questions_is_split_with_coordinates() -> None:
    parts = split_numbered_line(
        "16) Репликация БД 17) Архитектура СУБД",
        0.94,
        (0.1, 0.2, 0.9, 0.3),
    )

    assert [part[0] for part in parts] == ["16) Репликация БД", "17) Архитектура СУБД"]
    assert parts[0][2][2] == parts[1][2][0]
