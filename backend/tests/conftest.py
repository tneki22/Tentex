from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from app.db import Base
from app.models import (
    BlockClass,
    Material,
    MaterialBlock,
    MaterialFragment,
    MaterialPage,
    MaterialSourceKind,
    MaterialState,
    NodeType,
    PageQuality,
    ProgramNode,
    Project,
    ProjectMaterial,
    ProjectStatus,
    SourceRole,
    TemplateKey,
    WorkspaceVariant,
    utc_now,
)


@pytest.fixture
def session(tmp_path: Path) -> Iterator[Session]:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'test.sqlite'}")

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection: object, _: object) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE VIRTUAL TABLE fragment_search USING fts5("
            "text, lemmas, fragment_id UNINDEXED, material_id UNINDEXED, "
            "tokenize = 'unicode61 remove_diacritics 2')"
        )
        connection.exec_driver_sql(
            "CREATE TABLE fragment_search_map ("
            "fragment_id TEXT PRIMARY KEY, material_id TEXT NOT NULL, rowid INTEGER NOT NULL)"
        )
    with Session(engine, expire_on_commit=False) as db_session:
        yield db_session
    engine.dispose()


def make_material(db_session: Session, seed: str) -> Material:
    material = Material(
        id=uuid4(),
        sha256=seed.rjust(64, "0"),
        original_name="Методичка.txt",
        storage_path=f"text/{seed}.txt",
        media_type="text/plain",
        source_kind=MaterialSourceKind.TEXT,
        size_bytes=100,
        page_count=1,
        status=MaterialState.READY,
        active_parse_revision=1,
        created_at=utc_now(),
        updated_at=utc_now(),
    )
    db_session.add(material)
    db_session.commit()
    return material


@dataclass(frozen=True, slots=True)
class PageFragments:
    page_id: UUID
    block_id: UUID
    fragment_ids: list[UUID]


def add_page_with_fragments(
    db_session: Session,
    material: Material,
    *,
    page_number: int,
    revision: int,
    fragments: list[str],
    block_title: str | None = None,
    block_class: BlockClass = BlockClass.CONTENT,
) -> PageFragments:
    page = MaterialPage(
        id=uuid4(),
        material_id=material.id,
        revision=revision,
        page_number=page_number,
        width=595,
        height=842,
        text="\n".join(fragments),
        markdown="\n".join(fragments),
        quality=PageQuality.NATIVE,
        elements=[],
        diagnostics=[],
        created_at=utc_now(),
    )
    db_session.add(page)
    db_session.flush()
    block = MaterialBlock(
        id=uuid4(),
        material_id=material.id,
        revision=revision,
        sort_order=0,
        title=block_title,
        block_class=block_class,
        page_from=page_number,
        page_to=page_number,
    )
    db_session.add(block)
    db_session.flush()
    fragment_ids: list[UUID] = []
    for order, text_value in enumerate(fragments):
        fragment = MaterialFragment(
            id=uuid4(),
            material_id=material.id,
            page_id=page.id,
            block_id=block.id,
            sort_order=order,
            text=text_value,
            bbox=[0, 0, 1, 1],
            element_kind="paragraph",
            degraded_structure=False,
            quality=PageQuality.NATIVE,
        )
        db_session.add(fragment)
        fragment_ids.append(fragment.id)
    db_session.commit()
    return PageFragments(page_id=page.id, block_id=block.id, fragment_ids=fragment_ids)


def make_exam_project(
    db_session: Session, *, status: ProjectStatus = ProjectStatus.ACTIVE
) -> Project:
    project = Project(
        id=uuid4(),
        template_key=TemplateKey.EXAM,
        workspace_variant=WorkspaceVariant.EXAM,
        status=status,
        name="Экзамен",
        created_at=utc_now(),
        updated_at=utc_now(),
    )
    db_session.add(project)
    db_session.commit()
    return project


def make_topic_node(db_session: Session, project: Project, *, title: str) -> ProgramNode:
    node = ProgramNode(
        id=uuid4(),
        project_id=project.id,
        parent_id=None,
        node_type=NodeType.TOPIC,
        sort_order=0,
        title=title,
        is_in_current_program=True,
        needs_material=False,
        is_archived=False,
        created_at=utc_now(),
        updated_at=utc_now(),
    )
    db_session.add(node)
    db_session.commit()
    return node


def link_material(db_session: Session, project: Project, material: Material) -> ProjectMaterial:
    link = ProjectMaterial(
        project_id=project.id,
        material_id=material.id,
        source_role=SourceRole.ADDITIONAL,
        priority=0,
        affects_program=False,
        purposes=["study_source"],
        created_at=utc_now(),
    )
    db_session.add(link)
    db_session.commit()
    return link
