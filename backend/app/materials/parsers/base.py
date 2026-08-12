from dataclasses import dataclass
from typing import Literal

ElementKind = Literal["heading", "paragraph", "list", "table", "formula", "image"]


@dataclass(frozen=True, slots=True)
class ParsedElement:
    kind: ElementKind
    text: str
    bbox: tuple[float, float, float, float]
    level: int | None = None
    confidence: float | None = None
    time_from: float | None = None
    time_to: float | None = None
    # Путь в хранилище: заполняется только у kind == "image".
    asset_path: str | None = None


@dataclass(frozen=True, slots=True)
class ParsedPage:
    page_number: int
    width: float
    height: float
    markdown: str
    plain_text: str
    quality: Literal["native", "ocr", "ocr_low"]
    elements: tuple[ParsedElement, ...]
    diagnostics: tuple[str, ...] = ()
    confidence: float | None = None
