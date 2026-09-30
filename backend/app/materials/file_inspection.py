"""Первичный осмотр загруженного файла вне event loop и памяти API.

В процесс передаётся только путь; байты большого PDF не сериализуются.
В API возвращаются счётчики и оглавление, а ошибки сохраняют прежние коды.
"""

import asyncio
import shutil
from pathlib import Path
from tempfile import TemporaryDirectory

from app.config import settings
from app.process_pool import IdleProcessPool
from app.projects.errors import ProjectDomainError

inspection_pool = IdleProcessPool(idle_seconds=settings.pdf_estimate_idle_seconds)


def _inspect_local(path: Path) -> dict:
    """Случайное чтение bind mount Windows заменяется одной локальной копией."""
    from app.materials.parsers.native import extract_outline, inspect

    try:
        with TemporaryDirectory(prefix="tentex-inspect-") as temporary:
            local = Path(temporary) / f"source{path.suffix}"
            shutil.copyfile(path, local)
            counts = inspect(local)
            outline = extract_outline(local)
        return {"counts": counts, "outline": outline}
    except PermissionError as error:
        return {"detail": str(error), "code": "material_encrypted"}
    except (ValueError, OSError) as error:
        return {"detail": str(error), "code": "material_corrupt"}


async def inspect_upload(path: Path) -> dict:
    """Ожидать Future без блокировки event loop и без открытой транзакции БД."""
    result = await asyncio.wrap_future(inspection_pool.submit(_inspect_local, path))
    if "code" in result:
        raise ProjectDomainError(result["detail"], status=422, code=result["code"])
    return result
