"""Растр страницы: кэш на диске, метка растра и заголовки кэширования браузера.

Отзывчивость просмотрщика держится на трёх вещах, и каждая ломается молча.
Открытый документ переиспользуется между запросами (иначе тысячестраничный
учебник заново разбирается на каждое перелистывание), нарисованная страница
лежит на диске в WebP, а адрес с актуальной меткой растра разрешено кэшировать
браузеру надолго — именно поэтому листание назад идёт без обращения к серверу.
"""

from pathlib import Path
from uuid import uuid4

import pymupdf as fitz
import pytest
from conftest import make_material
from sqlalchemy.orm import Session

from app.config import settings
from app.materials import library
from app.materials.storage import material_path
from app.models import MaterialSourceKind, TypstMaterial


@pytest.fixture(autouse=True)
def storage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Исходники и растр пишутся во временный каталог, а не в рабочий `data/`."""
    monkeypatch.setattr(settings, "data_dir", tmp_path)


def _pdf_material(session: Session, seed: str, pages: int = 3):
    """Материал с настоящим PDF в хранилище: растр берётся из файла, не из базы."""
    document = fitz.open()
    for number in range(pages):
        page = document.new_page()
        page.insert_text((72.0, 96.0), f"Страница {number + 1}", fontsize=14)
    material = make_material(session, seed)
    material.original_name = "Учебник.pdf"
    material.storage_path = f"pdf/{seed}.pdf"
    material.media_type = "application/pdf"
    material.source_kind = MaterialSourceKind.FILE
    material.page_count = pages
    target = material_path(material.storage_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    document.save(target)
    document.close()
    session.commit()
    return material


def test_renders_page_to_webp_and_reuses_the_file(session: Session) -> None:
    material = _pdf_material(session, "a1")

    first = library.library_page_image_path(session, material.id, 2)
    assert first.suffix == ".webp"
    assert first.exists()
    stamp = first.stat().st_mtime_ns

    second = library.library_page_image_path(session, material.id, 2)
    assert second == first
    # Второй запрос не перерисовывает страницу, а отдаёт уже нарисованную.
    assert second.stat().st_mtime_ns == stamp
    # Недописанных файлов после отрисовки не остаётся.
    assert list(first.parent.glob("*.part")) == []


def test_keeps_previously_rendered_png(session: Session) -> None:
    """Кэш, накопленный до перехода на WebP, остаётся годным и не перерисовывается."""
    material = _pdf_material(session, "a2")
    legacy = settings.storage_dir / "pages" / str(material.id) / "1.png"
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_bytes(b"old-raster")

    assert library.library_page_image_path(session, material.id, 1) == legacy
    assert legacy.read_bytes() == b"old-raster"


def test_missing_page_is_not_found(session: Session) -> None:
    material = _pdf_material(session, "a3", pages=2)

    try:
        library.library_page_image_path(session, material.id, 9)
    except Exception as error:  # noqa: BLE001 — важен код домена, а не класс
        assert getattr(error, "code", None) == "material_page_not_found"
    else:
        raise AssertionError("несуществующая страница отдала картинку")


def test_raster_token_follows_the_file(session: Session) -> None:
    material = _pdf_material(session, "a4")
    token = library.raster_token(session, material.id)

    # Разбор, правки текста и версии растр не трогают — метка обязана держаться.
    material.active_parse_revision = 7
    session.commit()
    assert library.raster_token(session, material.id) == token

    # Другой файл — другая метка, иначе браузер показывал бы страницы прошлого.
    material.storage_path = "pdf/another.pdf"
    session.commit()
    assert library.raster_token(session, material.id) != token


def test_token_in_address_unlocks_long_browser_cache() -> None:
    assert library.page_image_cache_headers("abc", "abc") == {
        "Cache-Control": "private, max-age=31536000, immutable"
    }
    # Адрес без метки или с устаревшей нельзя кэшировать надолго: за ним может
    # оказаться другой документ.
    assert library.page_image_cache_headers(None, "abc")["Cache-Control"] == "private, max-age=60"
    assert library.page_image_cache_headers("old", "abc")["Cache-Control"] == "private, max-age=60"


def test_material_without_pages_has_no_raster(session: Session) -> None:
    material = make_material(session, "a5")

    assert library.raster_token(session, material.id) == "none"
    assert library.raster_source(session, material.id) is None


def test_unbuilt_typst_project_still_reads_its_card(session: Session) -> None:
    """Карточка Typst без сборки обязана читаться: её опрашивают, пока сборка идёт."""
    material = make_material(session, "a8")
    material.source_kind = MaterialSourceKind.TYPST
    session.add(TypstMaterial(
        material_id=material.id,
        input_kind="file",
        entrypoint="main.typ",
        current_pdf_path=None,
    ))
    session.commit()

    assert library.raster_source(session, material.id) is None
    assert library.raster_token(session, material.id) == "none"
    assert library.read_library_material(session, material.id).raster_token == "none"


def test_drop_page_images_clears_the_directory(session: Session) -> None:
    material = _pdf_material(session, "a6")
    rendered = library.library_page_image_path(session, material.id, 1)
    assert rendered.exists()

    library.drop_page_images(material.id)
    assert not rendered.exists()
    # Повторный сброс на пустом месте не должен падать: пересборка Typst
    # вызывает его и тогда, когда страницы ещё никто не открывал.
    library.drop_page_images(uuid4())


def test_open_document_cache_survives_requests_and_notices_replacement(
    session: Session, tmp_path: Path
) -> None:
    material = _pdf_material(session, "a7")
    source = material_path(material.storage_path)

    first = library._open_document(source)
    assert library._open_document(source) is first

    # Подменённый по тому же пути файл ловится сигнатурой, а не остаётся в кэше.
    replacement = fitz.open()
    replacement.new_page()
    replacement.new_page()
    replacement.save(tmp_path / "other.pdf")
    replacement.close()
    source.write_bytes((tmp_path / "other.pdf").read_bytes())

    assert library._open_document(source) is not first
