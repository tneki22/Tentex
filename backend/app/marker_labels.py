from pathlib import Path
from uuid import UUID


def marker_label(value: str) -> str:
    """Безопасная для `[вид: label]` подпись без потери читаемого имени."""
    normalized = " ".join(value.replace("[", "［").replace("]", "］").split())
    return normalized or "файл"


def material_image_label(material_id: UUID, material_name: str, asset_path: str) -> str:
    """Имя и полный id источника делают маркер картинки однозначным."""
    return f"{marker_label(material_name)} · {marker_label(Path(asset_path).name)} · {material_id}"
