from dataclasses import dataclass

from app.materials.parsers.base import ParsedElement, ParsedPage

SERVICE_TITLES = {
    "оглавление": "table_of_contents",
    "содержание": "table_of_contents",
    "предисловие": "preface",
    "литература": "bibliography",
    "список литературы": "bibliography",
    "выходные данные": "imprint",
}


@dataclass(slots=True)
class BlockSpec:
    title: str | None
    elements: list[tuple[int, ParsedElement]]
    service_reason: str | None = None


def build_blocks(pages: list[ParsedPage]) -> list[BlockSpec]:
    blocks: list[BlockSpec] = []
    current: BlockSpec | None = None
    for page in pages:
        for element in page.elements:
            if element.kind == "heading":
                current = BlockSpec(element.text, [(page.page_number, element)])
                normalized = element.text.casefold().strip(" .:;—-")
                current.service_reason = SERVICE_TITLES.get(normalized)
                blocks.append(current)
            else:
                if current is None:
                    current = BlockSpec(None, [])
                    blocks.append(current)
                current.elements.append((page.page_number, element))
    return blocks
