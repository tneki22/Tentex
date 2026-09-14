"""Импорт оглавлений и массовый вывод учебниковой программы."""

from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from app.models import (
    Material,
    MaterialSourceKind,
    MaterialState,
    NodeType,
    ProgramBasisKind,
    Project,
    ProjectMaterial,
    ProjectStatus,
    SourceRole,
    TemplateKey,
    WorkspaceVariant,
    utc_now,
)
from app.projects import program, program_outline
from app.projects.errors import ProjectDomainError
from app.projects.schemas import (
    ProgramNodeCreate,
    ProgramOutlineItemWrite,
    ProgramOutlinesImportWrite,
    ProgramOutlineSourceWrite,
    ProgramRevisionCommand,
)


def _project(session: Session) -> Project:
    project = Project(
        template_key=TemplateKey.TEXTBOOK,
        workspace_variant=WorkspaceVariant.TEXTBOOK,
        status=ProjectStatus.ACTIVE,
        name="Учебник",
    )
    session.add(project)
    session.commit()
    return project


def _material(session: Session, project: Project, name: str, priority: int) -> Material:
    digest = uuid4().hex * 2
    material = Material(
        sha256=digest,
        original_name=name,
        storage_path=f"text/{uuid4()}.txt",
        media_type="text/plain",
        source_kind=MaterialSourceKind.TEXT,
        size_bytes=100,
        page_count=20,
        status=MaterialState.READY,
    )
    session.add(material)
    session.flush()
    session.add(
        ProjectMaterial(
            project_id=project.id,
            material_id=material.id,
            source_role=SourceRole.MAIN if priority == 0 else SourceRole.ADDITIONAL,
            priority=priority,
            affects_program=True,
            display_name=name,
            purposes=["study_source"],
            created_at=utc_now(),
        )
    )
    session.commit()
    return material


def _item(key: str, level: int, title: str, page: int, *, selected: bool = True):
    return ProgramOutlineItemWrite(
        outline_item_key=key,
        level=level,
        title=title,
        page=page,
        selected=selected,
    )


def test_imports_multiple_outlines_ranges_repeat_and_undo(session: Session) -> None:
    project = _project(session)
    later = _material(session, project, "Дополнительный", 10)
    first = _material(session, project, "Основной", 0)
    command = ProgramOutlinesImportWrite(
        expected_program_revision=0,
        sources=[
            ProgramOutlineSourceWrite(
                material_id=later.id,
                items=[_item("l-1", 1, "Практика", 2), _item("l-2", 2, "Задачи", 8)],
            ),
            ProgramOutlineSourceWrite(
                material_id=first.id,
                items=[
                    _item("f-1", 1, "Основы", 1),
                    _item("f-2", 3, "Пропущенный уровень", 3),
                    _item("f-3", 2, "Сети", 5),
                    _item("f-4", 1, "Не выбрано", 9, selected=False),
                ],
            ),
        ],
    )

    imported = program_outline.import_outlines(session, project.id, command)
    visible = [node for node in imported.program.nodes if node.is_in_current_program]
    assert [node.title for node in visible if node.parent_id is None] == ["Основы", "Практика"]
    gap = next(node for node in visible if node.title == "Пропущенный уровень")
    root = next(node for node in visible if node.title == "Основы")
    assert gap.parent_id == root.id
    assert gap.node_type == NodeType.SUBPOINT
    assert all(node.basis_kind == ProgramBasisKind.OUTLINE for node in visible)
    ranges = {node.title: node.source_page_ranges[0] for node in visible}
    assert (ranges["Основы"].page_from, ranges["Основы"].page_to) == (1, 8)
    assert (ranges["Сети"].page_from, ranges["Сети"].page_to) == (5, 8)
    assert (ranges["Задачи"].page_from, ranges["Задачи"].page_to) == (8, 20)

    repeated = program_outline.import_outlines(
        session,
        project.id,
        command.model_copy(update={"expected_program_revision": imported.program.revision}),
    )
    assert repeated.program.revision == imported.program.revision
    assert len(repeated.program.nodes) == len(imported.program.nodes)

    action = imported.latest_undoable_action
    assert action is not None and action.action_type == "outline_import"
    undone = program.undo_last_project_action(session, project.id, action.sequence)
    assert not any(node.is_in_current_program for node in undone.program.nodes)
    restored = program_outline.import_outlines(
        session,
        project.id,
        command.model_copy(update={"expected_program_revision": undone.program.revision}),
    )
    assert {node.id for node in restored.program.nodes} == {
        node.id for node in imported.program.nodes
    }
    assert all(node.is_in_current_program for node in restored.program.nodes)


def test_remove_all_is_one_undo_and_manual_nodes_are_custom(session: Session) -> None:
    project = _project(session)
    first = program.create_program_node(
        session,
        project.id,
        ProgramNodeCreate(
            expected_program_revision=0,
            node_type=NodeType.SECTION,
            title="Раздел",
        ),
    )
    created = first.changed_node
    assert created is not None and created.basis_kind == ProgramBasisKind.CUSTOM
    program.create_program_node(
        session,
        project.id,
        ProgramNodeCreate(
            expected_program_revision=1,
            parent_id=created.id,
            node_type=NodeType.TOPIC,
            title="Тема",
        ),
    )
    removed = program.remove_all_program_nodes(
        session, project.id, ProgramRevisionCommand(expected_program_revision=2)
    )
    assert not any(node.is_in_current_program for node in removed.program.nodes)
    action = removed.latest_undoable_action
    assert action is not None and action.action_type == "program_remove_all"
    undone = program.undo_last_project_action(session, project.id, action.sequence)
    assert all(node.is_in_current_program for node in undone.program.nodes)


def test_import_allows_fifth_outline_level(session: Session) -> None:
    project = _project(session)
    material = _material(session, project, "Глубокое оглавление", 0)
    imported = program_outline.import_outlines(
        session,
        project.id,
        ProgramOutlinesImportWrite(
            expected_program_revision=0,
            sources=[
                ProgramOutlineSourceWrite(
                    material_id=material.id,
                    items=[
                        _item("1", 1, "Раздел", 1),
                        _item("1.1", 2, "Тема", 2),
                        _item("1.1.1", 3, "Подпункт", 3),
                        _item("1.1.1.1", 4, "Деталь", 4),
                        _item("1.1.1.1.1", 5, "Уточнение", 5),
                    ],
                )
            ],
        ),
    )

    nodes = {node.title: node for node in imported.program.nodes}
    assert nodes["Уточнение"].parent_id == nodes["Деталь"].id
    extended = program.create_program_node(
        session,
        project.id,
        ProgramNodeCreate(
            expected_program_revision=imported.program.revision,
            parent_id=nodes["Уточнение"].id,
            node_type=NodeType.SUBPOINT,
            title="Ещё глубже",
        ),
    )
    assert extended.changed_node is not None
    assert extended.changed_node.parent_id == nodes["Уточнение"].id


def test_import_rejects_foreign_material_and_stale_revision(session: Session) -> None:
    project = _project(session)
    foreign_project = _project(session)
    foreign = _material(session, foreign_project, "Чужой", 0)
    command = ProgramOutlinesImportWrite(
        expected_program_revision=0,
        sources=[
            ProgramOutlineSourceWrite(
                material_id=foreign.id,
                items=[_item("foreign", 1, "Чужая тема", 1)],
            )
        ],
    )
    with pytest.raises(ProjectDomainError, match="не принадлежит проекту"):
        program_outline.import_outlines(session, project.id, command)

    own = _material(session, project, "Свой", 0)
    program.create_program_node(
        session,
        project.id,
        ProgramNodeCreate(
            expected_program_revision=0,
            node_type=NodeType.SECTION,
            title="Раздел",
        ),
    )
    stale = command.model_copy(
        update={
            "sources": [
                ProgramOutlineSourceWrite(
                    material_id=own.id,
                    items=[_item("own", 1, "Своя тема", 1)],
                )
            ]
        }
    )
    with pytest.raises(ProjectDomainError) as caught:
        program_outline.import_outlines(session, project.id, stale)
    assert caught.value.code == "stale_program_revision"
