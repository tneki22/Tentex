from uuid import uuid4

import pytest
from conftest import make_exam_project, make_topic_node
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.conspects.schemas import ConspectWrite
from app.models import Conspect, ConspectImage, utc_now


def test_conspect_rejects_node_from_another_project(session: Session) -> None:
    project = make_exam_project(session)
    other_project = make_exam_project(session)
    foreign_node = make_topic_node(session, other_project, title="Чужая тема")

    session.add(
        Conspect(
            project_id=project.id,
            program_node_id=foreign_node.id,
            content_markdown="текст",
            revision=1,
            created_at=utc_now(),
            updated_at=utc_now(),
        )
    )
    with pytest.raises(IntegrityError):
        session.commit()


def test_conspect_rejects_nonpositive_revision(session: Session) -> None:
    project = make_exam_project(session)
    node = make_topic_node(session, project, title="Тема")

    session.add(
        Conspect(
            project_id=project.id,
            program_node_id=node.id,
            content_markdown="",
            revision=0,
            created_at=utc_now(),
            updated_at=utc_now(),
        )
    )
    with pytest.raises(IntegrityError):
        session.commit()


def test_conspect_image_rejects_node_from_another_project(session: Session) -> None:
    project = make_exam_project(session)
    other_project = make_exam_project(session)
    foreign_node = make_topic_node(session, other_project, title="Чужая тема")

    session.add(
        ConspectImage(
            id=uuid4(),
            project_id=project.id,
            program_node_id=foreign_node.id,
            file_name="a.png",
            storage_path="conspects/x/a.png",
            media_type="image/png",
            size_bytes=10,
            created_at=utc_now(),
        )
    )
    with pytest.raises(IntegrityError):
        session.commit()


def test_conspect_image_rejects_negative_size(session: Session) -> None:
    project = make_exam_project(session)
    node = make_topic_node(session, project, title="Тема")

    session.add(
        ConspectImage(
            id=uuid4(),
            project_id=project.id,
            program_node_id=node.id,
            file_name="a.png",
            storage_path="conspects/x/a.png",
            media_type="image/png",
            size_bytes=-1,
            created_at=utc_now(),
        )
    )
    with pytest.raises(IntegrityError):
        session.commit()


def test_conspect_write_rejects_oversized_markdown() -> None:
    too_big = "a" * (1_048_576 + 1)
    with pytest.raises(ValueError):
        ConspectWrite(content_markdown=too_big, expected_revision=0, retained_image_ids=[])


def test_conspect_write_dedupes_retained_image_ids_preserving_order() -> None:
    first, second = uuid4(), uuid4()
    write = ConspectWrite(
        content_markdown="текст",
        expected_revision=1,
        retained_image_ids=[first, second, first],
    )
    assert write.retained_image_ids == [first, second]
