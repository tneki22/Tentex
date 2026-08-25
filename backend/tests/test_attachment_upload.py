import io

import pytest
from conftest import make_exam_project, make_topic_node
from fastapi import UploadFile

from app.materials.storage import store_answer_upload
from app.projects import answers
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


@pytest.mark.asyncio
async def test_attachment_names_are_unique_within_an_answer(
    session, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = make_exam_project(session)
    node = make_topic_node(session, project, title="Вложение")

    async def store_same_name(*_args, **_kwargs):
        return "answers/test/file.png", "image/png", 3, "scheme.png"

    monkeypatch.setattr(answers, "store_answer_upload", store_same_name)

    first = await answers.add_attachment(
        session, project.id, node.id, _upload("scheme.png", b"one")
    )
    second = await answers.add_attachment(
        session, project.id, node.id, _upload("scheme.png", b"two")
    )
    third = await answers.add_attachment(
        session, project.id, node.id, _upload("scheme.png", b"three")
    )

    assert [first.file_name, second.file_name, third.file_name] == [
        "scheme.png",
        "scheme (2).png",
        "scheme (3).png",
    ]
