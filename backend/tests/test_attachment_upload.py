import io

import pytest
from fastapi import UploadFile

from app.materials.storage import store_answer_upload
from app.projects.errors import ProjectDomainError

ALLOWED = {".txt", ".md", ".png"}


def _upload(name: str, data: bytes) -> UploadFile:
    return UploadFile(filename=name, file=io.BytesIO(data))


@pytest.mark.asyncio
async def test_streams_small_file() -> None:
    rel, media, size, original = await store_answer_upload(
        "proj-1", _upload("note.txt", b"hello"), allowed_suffixes=ALLOWED, max_bytes=1024
    )
    assert size == 5
    assert original == "note.txt"
    assert rel.startswith("answers/proj-1/")


@pytest.mark.asyncio
async def test_rejects_oversize_before_full_buffer() -> None:
    big = b"x" * 5000
    with pytest.raises(ProjectDomainError) as err:
        await store_answer_upload(
            "proj-1", _upload("big.txt", big), allowed_suffixes=ALLOWED, max_bytes=1024
        )
    assert err.value.status == 413


@pytest.mark.asyncio
async def test_rejects_unknown_suffix() -> None:
    with pytest.raises(ProjectDomainError) as err:
        await store_answer_upload(
            "proj-1", _upload("evil.exe", b"x"), allowed_suffixes=ALLOWED, max_bytes=1024
        )
    assert err.value.status == 422
