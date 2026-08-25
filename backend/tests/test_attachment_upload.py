import importlib
import io
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from conftest import (
    add_page_with_fragments,
    link_material,
    make_exam_project,
    make_material,
    make_topic_node,
)
from fastapi import UploadFile
from sqlalchemy import select

from app.bindings import service
from app.bindings.schemas import BindingCreateWrite
from app.marker_labels import material_image_label
from app.materials.storage import store_answer_upload
from app.models import MaterialFragment, ReferenceAnswerAttachment
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


@pytest.mark.asyncio
async def test_attachment_marker_label_replaces_bracket_delimiters(
    session, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = make_exam_project(session)
    node = make_topic_node(session, project, title="Безопасный маркер")

    async def store_delimited_name(*_args, **_kwargs):
        return "answers/test/file.png", "image/png", 3, "scheme].png"

    monkeypatch.setattr(answers, "store_answer_upload", store_delimited_name)

    attachment = await answers.add_attachment(
        session, project.id, node.id, _upload("scheme].png", b"x")
    )

    assert attachment.file_name == "scheme］.png"


@pytest.mark.asyncio
async def test_attachment_label_avoids_a_bound_image_label(
    session, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = make_exam_project(session)
    node = make_topic_node(session, project, title="Коллизия")
    material = make_material(session, "a4")
    link_material(session, project, material)
    page = add_page_with_fragments(
        session, material, page_number=1, revision=1, fragments=["[Изображение]"]
    )
    image = session.get(MaterialFragment, page.fragment_ids[0])
    assert image is not None
    image.element_kind = "image"
    image.asset_path = "assets/material/flow.png"
    session.commit()
    service.create_bindings(
        session,
        project.id,
        BindingCreateWrite(program_node_id=node.id, fragment_ids=page.fragment_ids),
    )
    image_label = material_image_label(material.id, material.original_name, image.asset_path)

    async def store_colliding_name(*_args, **_kwargs):
        return "answers/test/file.png", "image/png", 3, image_label

    monkeypatch.setattr(answers, "store_answer_upload", store_colliding_name)

    attachment = await answers.add_attachment(
        session, project.id, node.id, _upload("flow.png", b"x")
    )

    assert attachment.file_name != image_label
    assert "(2)" in attachment.file_name


def test_attachment_label_migration_normalizes_and_uniquifies_existing_rows(
    session, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = make_exam_project(session)
    node = make_topic_node(session, project, title="Старые вложения")
    other_node = make_topic_node(session, project, title="Другая тема")
    created = datetime(2026, 8, 25, tzinfo=UTC)
    session.add_all(
        [
            ReferenceAnswerAttachment(
                id=uuid4(),
                project_id=project.id,
                program_node_id=node.id,
                file_name="scheme].png",
                storage_path="answers/test/one",
                media_type="image/png",
                size_bytes=1,
                created_at=created,
            ),
            ReferenceAnswerAttachment(
                id=uuid4(),
                project_id=project.id,
                program_node_id=node.id,
                file_name="scheme］.png",
                storage_path="answers/test/two",
                media_type="image/png",
                size_bytes=1,
                created_at=created + timedelta(seconds=1),
            ),
            ReferenceAnswerAttachment(
                id=uuid4(),
                project_id=project.id,
                program_node_id=node.id,
                file_name=" draft [v1] .md ",
                storage_path="answers/test/three",
                media_type="text/markdown",
                size_bytes=1,
                created_at=created + timedelta(seconds=2),
            ),
            ReferenceAnswerAttachment(
                id=uuid4(),
                project_id=project.id,
                program_node_id=other_node.id,
                file_name="scheme].png",
                storage_path="answers/test/four",
                media_type="image/png",
                size_bytes=1,
                created_at=created,
            ),
        ]
    )
    session.flush()
    migration = importlib.import_module(
        "migrations.versions.20260825_0020_reference_attachment_marker_labels"
    )
    monkeypatch.setattr(migration.op, "get_bind", session.connection)

    migration.upgrade()
    session.expire_all()
    names = list(
        session.scalars(
            select(ReferenceAnswerAttachment.file_name)
            .where(
                ReferenceAnswerAttachment.project_id == project.id,
                ReferenceAnswerAttachment.program_node_id == node.id,
            )
            .order_by(ReferenceAnswerAttachment.created_at)
        )
    )
    other_name = session.scalar(
        select(ReferenceAnswerAttachment.file_name).where(
            ReferenceAnswerAttachment.project_id == project.id,
            ReferenceAnswerAttachment.program_node_id == other_node.id,
        )
    )

    assert names == ["scheme］.png", "scheme］ (2).png", "draft ［v1］ .md"]
    assert other_name == "scheme］.png"
