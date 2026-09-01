import io
from uuid import UUID, uuid4

import pytest
from conftest import make_exam_project, make_topic_node
from fastapi import UploadFile
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.conspects import service
from app.conspects.schemas import ConspectWrite
from app.models import (
    Conspect,
    ConspectImage,
    NodeType,
    ProgramNode,
    Project,
    ProjectStatus,
    TemplateKey,
    WorkspaceVariant,
    utc_now,
)
from app.projects.errors import ProjectConflictError, ProjectDomainError, ProjectNotFoundError
from app.projects.service import delete_project


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


def make_textbook_project(
    db_session: Session, *, status: ProjectStatus = ProjectStatus.ACTIVE
) -> Project:
    project = Project(
        id=uuid4(),
        template_key=TemplateKey.TEXTBOOK,
        workspace_variant=WorkspaceVariant.TEXTBOOK,
        status=status,
        name="Учебник",
        created_at=utc_now(),
        updated_at=utc_now(),
    )
    db_session.add(project)
    db_session.commit()
    return project


def make_node(
    db_session: Session,
    project: Project,
    *,
    title: str,
    node_type: NodeType = NodeType.TOPIC,
    parent_id: UUID | None = None,
    sort_order: int = 0,
    is_in_current_program: bool = True,
    is_archived: bool = False,
) -> ProgramNode:
    node = ProgramNode(
        id=uuid4(),
        project_id=project.id,
        parent_id=parent_id,
        node_type=node_type,
        sort_order=sort_order,
        title=title,
        is_in_current_program=is_in_current_program,
        needs_material=False,
        is_archived=is_archived,
        created_at=utc_now(),
        updated_at=utc_now(),
    )
    db_session.add(node)
    db_session.commit()
    return node


def _upload(name: str, data: bytes) -> UploadFile:
    return UploadFile(filename=name, file=io.BytesIO(data))


def _assert_conspect_roundtrip(session: Session, project: Project, node: ProgramNode) -> None:
    empty = service.get_conspect(session, project.id, node.id)
    assert empty.revision == 0
    assert empty.content_markdown == ""
    assert empty.updated_at is None
    assert empty.images == []
    session.commit()  # закрыть автоначатую транзакцию чтения перед следующим begin()

    saved = service.save_conspect(
        session,
        project.id,
        node.id,
        ConspectWrite(content_markdown="# Привет", expected_revision=0, retained_image_ids=[]),
    )
    assert saved.revision == 1
    assert saved.content_markdown == "# Привет"

    fetched = service.get_conspect(session, project.id, node.id)
    assert fetched.content_markdown == "# Привет"
    assert fetched.revision == 1
    assert fetched.updated_at is not None


def test_conspect_roundtrip_in_exam_project(session: Session) -> None:
    project = make_exam_project(session)
    node = make_topic_node(session, project, title="Тема")
    _assert_conspect_roundtrip(session, project, node)


def test_conspect_roundtrip_in_textbook_project(session: Session) -> None:
    project = make_textbook_project(session)
    node = make_topic_node(session, project, title="Тема")
    _assert_conspect_roundtrip(session, project, node)


def test_save_conspect_increments_revision(session: Session) -> None:
    project = make_exam_project(session)
    node = make_topic_node(session, project, title="Тема")
    service.save_conspect(
        session,
        project.id,
        node.id,
        ConspectWrite(content_markdown="v1", expected_revision=0, retained_image_ids=[]),
    )

    second = service.save_conspect(
        session,
        project.id,
        node.id,
        ConspectWrite(content_markdown="v2", expected_revision=1, retained_image_ids=[]),
    )

    assert second.revision == 2
    assert second.content_markdown == "v2"


def test_save_conspect_rejects_stale_revision_and_keeps_server_text(session: Session) -> None:
    project = make_exam_project(session)
    node = make_topic_node(session, project, title="Тема")
    service.save_conspect(
        session,
        project.id,
        node.id,
        ConspectWrite(content_markdown="server text", expected_revision=0, retained_image_ids=[]),
    )

    with pytest.raises(ProjectConflictError) as err:
        service.save_conspect(
            session,
            project.id,
            node.id,
            ConspectWrite(
                content_markdown="stale write", expected_revision=0, retained_image_ids=[]
            ),
        )
    assert err.value.code == "stale_conspect_revision"
    assert err.value.context["current_revision"] == 1

    current = service.get_conspect(session, project.id, node.id)
    assert current.content_markdown == "server text"
    assert current.revision == 1


def test_archived_project_blocks_write_but_allows_read(session: Session) -> None:
    project = make_exam_project(session)
    node = make_topic_node(session, project, title="Тема")
    service.save_conspect(
        session,
        project.id,
        node.id,
        ConspectWrite(content_markdown="текст", expected_revision=0, retained_image_ids=[]),
    )

    project.status = ProjectStatus.ARCHIVED
    session.commit()

    read = service.get_conspect(session, project.id, node.id)
    assert read.content_markdown == "текст"
    session.commit()  # закрыть автоначатую транзакцию чтения перед следующим begin()

    with pytest.raises(ProjectConflictError) as err:
        service.save_conspect(
            session,
            project.id,
            node.id,
            ConspectWrite(content_markdown="new", expected_revision=1, retained_image_ids=[]),
        )
    assert err.value.code == "project_read_only"


def test_conspect_rejects_section_node(session: Session) -> None:
    project = make_exam_project(session)
    section = make_node(session, project, title="Раздел", node_type=NodeType.SECTION)

    with pytest.raises(ProjectDomainError) as err:
        service.get_conspect(session, project.id, section.id)
    assert err.value.code == "conspect_requires_study_node"


def test_conspect_service_rejects_node_from_another_project(session: Session) -> None:
    project = make_exam_project(session)
    other_project = make_exam_project(session)
    foreign_node = make_topic_node(session, other_project, title="Чужая тема")

    with pytest.raises(ProjectNotFoundError):
        service.get_conspect(session, project.id, foreign_node.id)


def test_conspect_rejects_archived_node(session: Session) -> None:
    project = make_exam_project(session)
    node = make_node(session, project, title="Архивная", is_archived=True)

    with pytest.raises(ProjectNotFoundError):
        service.get_conspect(session, project.id, node.id)


def test_conspect_summary_dfs_order_and_filters(session: Session) -> None:
    project = make_exam_project(session)
    section_a = make_node(
        session, project, title="Раздел А", node_type=NodeType.SECTION, sort_order=0
    )
    topic_a1 = make_node(session, project, title="A.1", parent_id=section_a.id, sort_order=0)
    topic_a2 = make_node(session, project, title="A.2", parent_id=section_a.id, sort_order=1)
    make_node(session, project, title="Пустая", parent_id=section_a.id, sort_order=2)
    section_b = make_node(
        session, project, title="Раздел Б", node_type=NodeType.SECTION, sort_order=1
    )
    topic_b1 = make_node(session, project, title="Б.1", parent_id=section_b.id, sort_order=0)
    archived_topic = make_node(
        session, project, title="Будет архивной", parent_id=section_b.id, sort_order=1
    )
    out_of_program_topic = make_node(
        session,
        project,
        title="Вне программы",
        parent_id=section_b.id,
        sort_order=2,
        is_in_current_program=False,
    )

    for node, text in [
        (topic_a1, "A1 текст"),
        (topic_a2, "A2 текст"),
        (topic_b1, "Б1 текст"),
        (archived_topic, "архивный текст"),
        (out_of_program_topic, "вне программы текст"),
    ]:
        service.save_conspect(
            session,
            project.id,
            node.id,
            ConspectWrite(content_markdown=text, expected_revision=0, retained_image_ids=[]),
        )

    archived_topic.is_archived = True
    session.commit()

    summary = service.list_conspect_summary(session, project.id)

    assert [entry.node_id for entry in summary.entries] == [topic_a1.id, topic_a2.id, topic_b1.id]
    assert [entry.position for entry in summary.entries] == [1, 2, 3]
    assert [entry.title for entry in summary.entries] == ["A.1", "A.2", "Б.1"]


def test_conspect_summary_rejects_textbook_project(session: Session) -> None:
    project = make_textbook_project(session)
    node = make_topic_node(session, project, title="Тема")
    service.save_conspect(
        session,
        project.id,
        node.id,
        ConspectWrite(content_markdown="текст", expected_revision=0, retained_image_ids=[]),
    )

    with pytest.raises(ProjectConflictError) as err:
        service.list_conspect_summary(session, project.id)
    assert err.value.code == "conspect_summary_requires_exam_project"

    personal = service.get_conspect(session, project.id, node.id)
    assert personal.content_markdown == "текст"


@pytest.mark.asyncio
async def test_add_conspect_image_roundtrip(
    session: Session, tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    project = make_exam_project(session)
    node = make_topic_node(session, project, title="Тема")

    image = await service.add_conspect_image(
        session, project.id, node.id, _upload("scheme.png", b"pngdata")
    )

    assert image.file_name == "scheme.png"
    assert image.media_type == "image/png"
    assert image.size_bytes == len(b"pngdata")

    path = service.conspect_image_path(session, project.id, image.id)
    assert path.exists()
    assert path.read_bytes() == b"pngdata"
    session.commit()  # закрыть автоначатую транзакцию чтения перед следующим begin()

    service.delete_conspect_image(session, project.id, image.id)

    assert not path.exists()
    assert session.get(ConspectImage, image.id) is None


@pytest.mark.asyncio
async def test_add_conspect_image_rejects_unsupported_suffix(
    session: Session, tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    project = make_exam_project(session)
    node = make_topic_node(session, project, title="Тема")

    with pytest.raises(ProjectDomainError) as err:
        await service.add_conspect_image(
            session, project.id, node.id, _upload("evil.svg", b"<svg/>")
        )
    assert err.value.status == 422
    assert err.value.code == "conspect_image_unsupported"


@pytest.mark.asyncio
async def test_add_conspect_image_rejects_empty_file(
    session: Session, tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    project = make_exam_project(session)
    node = make_topic_node(session, project, title="Тема")

    with pytest.raises(ProjectDomainError) as err:
        await service.add_conspect_image(session, project.id, node.id, _upload("empty.png", b""))
    assert err.value.status == 422
    assert err.value.code == "conspect_image_empty"


@pytest.mark.asyncio
async def test_add_conspect_image_rejects_oversize(
    session: Session, tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    project = make_exam_project(session)
    node = make_topic_node(session, project, title="Тема")
    big = b"x" * (20 * 1024 * 1024 + 1)

    with pytest.raises(ProjectDomainError) as err:
        await service.add_conspect_image(session, project.id, node.id, _upload("big.png", big))
    assert err.value.status == 413
    assert err.value.code == "conspect_image_too_large"


@pytest.mark.asyncio
async def test_save_conspect_removes_images_not_retained(
    session: Session, tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    project = make_exam_project(session)
    node = make_topic_node(session, project, title="Тема")
    kept = await service.add_conspect_image(
        session, project.id, node.id, _upload("kept.png", b"kept")
    )
    removed = await service.add_conspect_image(
        session, project.id, node.id, _upload("removed.png", b"removed")
    )
    removed_path = service.conspect_image_path(session, project.id, removed.id)
    assert removed_path.exists()
    session.commit()  # закрыть автоначатую транзакцию чтения перед следующим begin()

    result = service.save_conspect(
        session,
        project.id,
        node.id,
        ConspectWrite(
            content_markdown=f"![]({kept.id})",
            expected_revision=0,
            retained_image_ids=[kept.id],
        ),
    )

    assert {image.id for image in result.images} == {kept.id}
    assert session.get(ConspectImage, removed.id) is None
    assert session.get(ConspectImage, kept.id) is not None
    assert not removed_path.exists()


@pytest.mark.asyncio
async def test_save_conspect_rejects_foreign_retained_image_id(
    session: Session, tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    project = make_exam_project(session)
    node = make_topic_node(session, project, title="Тема")
    other_node = make_topic_node(session, project, title="Другая тема")
    foreign_image = await service.add_conspect_image(
        session, project.id, other_node.id, _upload("x.png", b"x")
    )

    with pytest.raises(ProjectDomainError) as err:
        service.save_conspect(
            session,
            project.id,
            node.id,
            ConspectWrite(
                content_markdown="текст",
                expected_revision=0,
                retained_image_ids=[foreign_image.id],
            ),
        )
    assert err.value.code == "conspect_image_not_found"


@pytest.mark.asyncio
async def test_delete_conspect_image_blocked_while_referenced(
    session: Session, tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    project = make_exam_project(session)
    node = make_topic_node(session, project, title="Тема")
    image = await service.add_conspect_image(session, project.id, node.id, _upload("a.png", b"a"))
    service.save_conspect(
        session,
        project.id,
        node.id,
        ConspectWrite(
            content_markdown=f"![]({image.id})",
            expected_revision=0,
            retained_image_ids=[image.id],
        ),
    )

    with pytest.raises(ProjectConflictError) as err:
        service.delete_conspect_image(session, project.id, image.id)
    assert err.value.code == "conspect_image_in_use"


@pytest.mark.asyncio
async def test_conspect_image_not_accessible_from_another_project(
    session: Session, tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    project = make_exam_project(session)
    other_project = make_exam_project(session)
    node = make_topic_node(session, project, title="Тема")
    image = await service.add_conspect_image(session, project.id, node.id, _upload("a.png", b"a"))

    with pytest.raises(ProjectNotFoundError):
        service.conspect_image_path(session, other_project.id, image.id)
    # commit(), не rollback(): при expire_on_commit=False это просто закрывает
    # автоначатую транзакцию чтения, не «протухая» other_project/image для
    # следующего вызова (rollback() экспирит все объекты сессии).
    session.commit()
    with pytest.raises(ProjectNotFoundError):
        service.delete_conspect_image(session, other_project.id, image.id)


@pytest.mark.asyncio
async def test_delete_project_cleans_up_conspect_image_files(
    session: Session, tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    project = make_exam_project(session)
    node = make_topic_node(session, project, title="Тема")
    image = await service.add_conspect_image(session, project.id, node.id, _upload("a.png", b"a"))
    service.save_conspect(
        session,
        project.id,
        node.id,
        ConspectWrite(
            content_markdown=f"![]({image.id})",
            expected_revision=0,
            retained_image_ids=[image.id],
        ),
    )
    path = service.conspect_image_path(session, project.id, image.id)
    assert path.exists()
    project_dir = path.parent
    session.commit()  # закрыть автоначатую транзакцию чтения перед следующим begin()

    delete_project(session, project.id)

    assert not path.exists()
    assert not project_dir.exists()
    assert session.get(ConspectImage, image.id) is None
    assert session.get(Conspect, (project.id, node.id)) is None
