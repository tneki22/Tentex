"""Реестр версий общего материала: запись, чтение и человеческое происхождение.

Активная версия остаётся в `Material.active_parse_revision`. Здесь хранится
только история: чем версия получена, из какой выросла, какой снимок источника
ей соответствует и что она дала. Регистрация всегда идёт после успешной
сегментации — незавершённая ревизия в реестр не попадает и активной не станет.
"""

from typing import Any
from uuid import UUID

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.models import (
    Material,
    MaterialPage,
    MaterialRevision,
    MaterialRevisionOrigin,
    PageQuality,
    ParserMode,
    utc_now,
)
from app.projects.errors import ProjectConflictError, ProjectNotFoundError

ORIGIN_LABEL: dict[MaterialRevisionOrigin, str] = {
    MaterialRevisionOrigin.IMPORTED: "Первичная обработка",
    MaterialRevisionOrigin.PARSE: "Повторное распознавание",
    MaterialRevisionOrigin.MANUAL_EDIT: "Исправление страницы",
    MaterialRevisionOrigin.AI_CLEANUP: "Уборка текста",
    MaterialRevisionOrigin.SOURCE_REFRESH: "Обновление снимка",
    MaterialRevisionOrigin.RESTORE: "Восстановление версии",
}


def record_revision(
    session: Session,
    material_id: UUID,
    revision: int,
    *,
    origin: MaterialRevisionOrigin,
    parser_mode: ParserMode | None = None,
    parent_revision: int | None = None,
    task_id: UUID | None = None,
    source_storage_path: str | None = None,
    source_hash: str | None = None,
    scope: dict[str, Any] | None = None,
    summary: dict[str, Any] | None = None,
) -> MaterialRevision:
    """Зарегистрировать готовую версию.

    Повтор номера — ошибка, а не молчаливая замена: два разных разбора под одним
    номером означали бы, что история врёт про то, из чего выросла активная версия.
    """
    if revision < 1:
        raise ValueError("Номер ревизии начинается с 1")
    existing = get_revision(session, material_id, revision)
    if existing is not None:
        raise ProjectConflictError(
            f"Версия {revision} этого материала уже зарегистрирована",
            code="material_revision_exists",
            context={"revision": revision},
        )
    row = MaterialRevision(
        material_id=material_id,
        revision=revision,
        origin=origin,
        parser_mode=parser_mode,
        parent_revision=parent_revision,
        task_id=task_id,
        source_storage_path=source_storage_path,
        source_hash=source_hash,
        scope=scope or {},
        summary=summary or {},
        created_at=utc_now(),
    )
    session.add(row)
    session.flush()
    return row


def get_revision(session: Session, material_id: UUID, revision: int) -> MaterialRevision | None:
    return session.scalar(
        select(MaterialRevision).where(
            MaterialRevision.material_id == material_id,
            MaterialRevision.revision == revision,
        )
    )


def require_revision(session: Session, material_id: UUID, revision: int) -> MaterialRevision:
    row = get_revision(session, material_id, revision)
    if row is None:
        raise ProjectNotFoundError("Такой версии материала нет", code="material_revision_not_found")
    return row


def list_revisions(session: Session, material_id: UUID) -> list[MaterialRevision]:
    return list(
        session.scalars(
            select(MaterialRevision)
            .where(MaterialRevision.material_id == material_id)
            .order_by(desc(MaterialRevision.revision))
        )
    )


def max_revision(session: Session, material_id: UUID) -> int:
    """Наибольший из зарегистрированных и активного номера.

    Активный номер учитывается отдельно: материалы, разобранные до появления
    реестра, могли не получить запись, а номера обязаны расти монотонно.
    """
    registered = (
        session.scalar(
            select(func.max(MaterialRevision.revision)).where(
                MaterialRevision.material_id == material_id
            )
        )
        or 0
    )
    material = session.get(Material, material_id)
    stored = (
        session.scalar(
            select(func.max(MaterialPage.revision)).where(MaterialPage.material_id == material_id)
        )
        or 0
    )
    return max(registered, stored, material.active_parse_revision if material else 0)


def revision_source_path(
    session: Session, material: Material, revision: int | None
) -> tuple[str, str | None]:
    """Путь к исходнику нужной версии и её хеш.

    Веб-снимок и субтитры версионируются вместе с ревизией, локальный файл — нет,
    поэтому для него всегда возвращается текущий путь материала.
    """
    if revision is None or revision == material.active_parse_revision:
        return material.storage_path, material.sha256
    row = get_revision(session, material.id, revision)
    if row is None or not row.source_storage_path:
        return material.storage_path, material.sha256
    return row.source_storage_path, row.source_hash


def revision_summary(session: Session, material_id: UUID, revision: int) -> dict[str, Any]:
    """Стабильная сводка результата: по ней Версии рисуют строку без догадок."""
    pages = list(
        session.scalars(
            select(MaterialPage).where(
                MaterialPage.material_id == material_id,
                MaterialPage.revision == revision,
            )
        )
    )
    return {
        "page_count": len(pages),
        "native_page_count": sum(page.quality == PageQuality.NATIVE for page in pages),
        "ocr_page_count": sum(
            page.quality == PageQuality.OCR
            or (page.quality == PageQuality.OCR_LOW and page.reviewed_at is not None)
            for page in pages
        ),
        "review_page_count": sum(
            page.quality == PageQuality.OCR_LOW and page.reviewed_at is None for page in pages
        ),
        "diagnostics_count": len({item for page in pages for item in page.diagnostics}),
    }


def inherit_source(
    session: Session, material: Material, parent_revision: int | None
) -> tuple[str | None, str | None]:
    """Снимок источника не менялся — новая версия наследует путь и хеш родителя."""
    if parent_revision:
        parent = get_revision(session, material.id, parent_revision)
        if parent and parent.source_storage_path:
            return parent.source_storage_path, parent.source_hash
    return material.storage_path, material.sha256
