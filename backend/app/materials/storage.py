import contextlib
import hashlib
import mimetypes
from pathlib import Path
from uuid import uuid4

from fastapi import UploadFile

from app.config import settings
from app.projects.errors import ProjectDomainError

MAX_FILE_BYTES = 100 * 1024 * 1024
ALLOWED_SUFFIXES = {
    ".pdf",
    ".docx",
    ".txt",
    ".md",
    ".jpg",
    ".jpeg",
    ".png",
    ".mp3",
    ".wav",
    ".m4a",
    ".ogg",
    ".flac",
}


def _unsupported(detail: str) -> ProjectDomainError:
    return ProjectDomainError(detail, status=422, code="material_unsupported")


async def store_upload(upload: UploadFile) -> tuple[str, str, int, str, str]:
    original_name = Path(upload.filename or "material").name
    suffix = Path(original_name).suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise _unsupported("Поддерживаются PDF, DOCX, TXT, MD, JPG, PNG, MP3, WAV, M4A, OGG и FLAC")

    temporary_dir = settings.storage_dir / "tmp"
    temporary_dir.mkdir(parents=True, exist_ok=True)
    temporary_path = temporary_dir / f"{uuid4().hex}{suffix}"
    digest = hashlib.sha256()
    size = 0
    try:
        with temporary_path.open("wb") as target:
            while chunk := await upload.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_FILE_BYTES:
                    raise ProjectDomainError(
                        "Файл больше 100 МБ", status=413, code="material_too_large"
                    )
                digest.update(chunk)
                target.write(chunk)
        if size == 0:
            raise ProjectDomainError("Файл пуст", status=422, code="material_empty")
        sha256 = digest.hexdigest()
        relative_path = Path("materials") / sha256[:2] / f"{sha256}{suffix}"
        final_path = settings.storage_dir / relative_path
        final_path.parent.mkdir(parents=True, exist_ok=True)
        if final_path.exists():
            temporary_path.unlink()
        else:
            temporary_path.replace(final_path)
        media_type = (
            upload.content_type
            or mimetypes.guess_type(original_name)[0]
            or "application/octet-stream"
        )
        return sha256, relative_path.as_posix(), size, original_name, media_type
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise
    finally:
        await upload.close()


def store_text(name: str, text: str) -> tuple[str, str, int, str, str]:
    data = text.encode("utf-8")
    digest = hashlib.sha256(data).hexdigest()
    suffix = ".md" if name.lower().endswith(".md") else ".txt"
    safe_name = Path(name).name
    relative_path = Path("materials") / digest[:2] / f"{digest}{suffix}"
    final_path = settings.storage_dir / relative_path
    final_path.parent.mkdir(parents=True, exist_ok=True)
    if not final_path.exists():
        final_path.write_bytes(data)
    media_type = "text/markdown" if suffix == ".md" else "text/plain"
    return digest, relative_path.as_posix(), len(data), safe_name, media_type


def store_revision_text(
    material_id: object, revision: int, name: str, text: str
) -> tuple[str, int]:
    """Снимок внешнего источника, принадлежащий одной версии материала.

    Общее хранилище по хешу здесь не подходит: обновление снимка не должно
    перезаписывать файл прежней версии, иначе история перестанет читаться.
    """
    data = text.encode("utf-8")
    suffix = ".md" if name.lower().endswith(".md") else ".txt"
    relative_path = Path("snapshots") / str(material_id) / f"{revision}{suffix}"
    final_path = settings.storage_dir / relative_path
    final_path.parent.mkdir(parents=True, exist_ok=True)
    final_path.write_bytes(data)
    return relative_path.as_posix(), len(data)


def store_material_asset(owner: str, name: str, data: bytes) -> str:
    """Картинка из материала с именем по содержимому.

    Индекс блока может измениться между версиями OCR. Хеш не даёт новому блоку
    переиспользовать чужую старую вырезку и при этом сохраняет дедупликацию.
    """
    source_name = Path(name)
    digest = hashlib.sha256(data).hexdigest()[:16]
    hashed_name = f"{source_name.stem}-{digest}{source_name.suffix}"
    relative_path = Path("assets") / owner / hashed_name
    final_path = settings.storage_dir / relative_path
    final_path.parent.mkdir(parents=True, exist_ok=True)
    if not final_path.exists():
        final_path.write_bytes(data)
    return relative_path.as_posix()


async def store_namespaced_upload(
    namespace: str,
    owner_id: str,
    upload: UploadFile,
    *,
    allowed_suffixes: set[str],
    max_bytes: int,
    unsupported_message: str,
    error_code_prefix: str,
) -> tuple[str, int, str]:
    """Потоковая запись вложения в `<namespace>/<owner_id>/<uuid><suffix>`.

    Общий вынос из прежнего `store_answer_upload`: другому домену (конспектам)
    нужен тот же потоковый предел на файл, но не общий вывод media type — это
    решает вызывающий, у которого разные требования к доверию `content_type`.
    В отличие от `await file.read()`, гигантский файл не попадает в память
    целиком — превышение ловится посреди потока и временный файл удаляется.
    """
    original_name = Path(upload.filename or "файл").name
    suffix = Path(original_name).suffix.lower()
    if suffix not in allowed_suffixes:
        raise ProjectDomainError(
            unsupported_message, status=422, code=f"{error_code_prefix}_unsupported"
        )
    temporary_dir = settings.storage_dir / "tmp"
    temporary_dir.mkdir(parents=True, exist_ok=True)
    temporary_path = temporary_dir / f"{uuid4().hex}{suffix}"
    size = 0
    try:
        with temporary_path.open("wb") as target:
            while chunk := await upload.read(1024 * 1024):
                size += len(chunk)
                if size > max_bytes:
                    raise ProjectDomainError(
                        f"Файл больше {max_bytes // (1024 * 1024)} МБ",
                        status=413,
                        code=f"{error_code_prefix}_too_large",
                    )
                target.write(chunk)
        if size == 0:
            raise ProjectDomainError("Файл пуст", status=422, code=f"{error_code_prefix}_empty")
        relative_path = Path(namespace) / owner_id / f"{uuid4().hex}{suffix}"
        final_path = settings.storage_dir / relative_path
        final_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path.replace(final_path)
        return relative_path.as_posix(), size, original_name
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise
    finally:
        await upload.close()


async def store_answer_upload(
    project_id: str,
    upload: UploadFile,
    *,
    allowed_suffixes: set[str],
    max_bytes: int,
) -> tuple[str, str, int, str]:
    """Совместимая обёртка над `store_namespaced_upload` для вложений к эталонам."""
    content_type = upload.content_type
    relative_path, size, original_name = await store_namespaced_upload(
        "answers",
        project_id,
        upload,
        allowed_suffixes=allowed_suffixes,
        max_bytes=max_bytes,
        unsupported_message="К ответу прикрепляются изображения, PDF, DOCX, TXT и MD",
        error_code_prefix="attachment",
    )
    media_type = (
        content_type or mimetypes.guess_type(original_name)[0] or "application/octet-stream"
    )
    return relative_path, media_type, size, original_name


def material_path(storage_path: str) -> Path:
    candidate = (settings.storage_dir / storage_path).resolve()
    root = settings.storage_dir.resolve()
    if root not in candidate.parents:
        raise RuntimeError("Material path escaped storage root")
    return candidate


def remove_storage_dir_if_empty(relative_dir: str) -> None:
    """Убирает каталог хранилища, если он существует и уже пуст.

    Молчит, если каталога нет или в нём остались файлы: вызывающая очистка
    (например, удаление проекта) не должна падать из-за гонки или недомёта.
    """
    with contextlib.suppress(OSError):
        material_path(relative_dir).rmdir()
