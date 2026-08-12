import hashlib
import mimetypes
from pathlib import Path
from uuid import uuid4

from fastapi import UploadFile

from app.config import settings
from app.projects.errors import ProjectDomainError

MAX_FILE_BYTES = 100 * 1024 * 1024
ALLOWED_SUFFIXES = {
    ".pdf", ".docx", ".txt", ".md", ".jpg", ".jpeg", ".png",
    ".mp3", ".wav", ".m4a", ".ogg", ".flac",
}


def _unsupported(detail: str) -> ProjectDomainError:
    return ProjectDomainError(detail, status=422, code="material_unsupported")


async def store_upload(upload: UploadFile) -> tuple[str, str, int, str, str]:
    original_name = Path(upload.filename or "material").name
    suffix = Path(original_name).suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise _unsupported(
            "Поддерживаются PDF, DOCX, TXT, MD, JPG, PNG, MP3, WAV, M4A, OGG и FLAC"
        )

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


def store_material_asset(owner: str, name: str, data: bytes) -> str:
    """Картинка, вынутая из материала. Имя детерминированное, поэтому повторный
    разбор той же страницы переиспользует файл и не плодит копий."""
    relative_path = Path("assets") / owner / name
    final_path = settings.storage_dir / relative_path
    final_path.parent.mkdir(parents=True, exist_ok=True)
    if not final_path.exists():
        final_path.write_bytes(data)
    return relative_path.as_posix()


def store_answer_attachment(project_id: str, file_name: str, data: bytes) -> tuple[str, str]:
    """Файл, принесённый к эталонному ответу: путь в хранилище и media type."""
    suffix = Path(file_name).suffix.lower()
    relative_path = Path("answers") / project_id / f"{uuid4().hex}{suffix}"
    final_path = settings.storage_dir / relative_path
    final_path.parent.mkdir(parents=True, exist_ok=True)
    final_path.write_bytes(data)
    media_type = mimetypes.guess_type(file_name)[0] or "application/octet-stream"
    return relative_path.as_posix(), media_type


def material_path(storage_path: str) -> Path:
    candidate = (settings.storage_dir / storage_path).resolve()
    root = settings.storage_dir.resolve()
    if root not in candidate.parents:
        raise RuntimeError("Material path escaped storage root")
    return candidate
