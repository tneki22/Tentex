"""Единые правила пользовательских названий материалов."""

from app.models import Material, ProjectMaterial


def material_display_name(material: Material) -> str:
    """Вернуть глобальное пользовательское имя материала."""
    return material.display_name


def project_material_display_name(material: Material, link: ProjectMaterial) -> str:
    """Вернуть проектный псевдоним или глобальное имя материала."""
    return link.display_name or material.display_name
