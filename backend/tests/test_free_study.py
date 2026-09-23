"""Свободное изучение поверх учебниковой среды — docs/architecture/free-study-wizard.md."""

from uuid import uuid4

from sqlalchemy.orm import Session

from app.exam import chat as exam_chat
from app.models import (
    ChatMode,
    ChatSession,
    ExaminerPersona,
    ExaminerStrictness,
    ProgramNodeSourcePageRange,
    Project,
    ProjectMaterial,
    ProjectStatus,
    TemplateKey,
    WorkspaceVariant,
    utc_now,
)
from app.projects import program, program_chat
from tests.conftest import link_material, make_material, make_topic_node


def make_free_project(session: Session, *, status: ProjectStatus = ProjectStatus.ACTIVE) -> Project:
    project = Project(
        id=uuid4(),
        template_key=TemplateKey.FREE,
        workspace_variant=WorkspaceVariant.TEXTBOOK,
        status=status,
        name="Нейросети",
        created_at=utc_now(),
        updated_at=utc_now(),
    )
    session.add(project)
    session.commit()
    return project


def test_program_hides_page_ranges_of_detached_material(session: Session) -> None:
    project = make_free_project(session)
    topic = make_topic_node(session, project, title="Свёртка")
    kept = make_material(session, "a1")
    detached = make_material(session, "b2")
    link_material(session, project, kept)
    link_material(session, project, detached)
    for material, page in ((kept, 3), (detached, 9)):
        session.add(ProgramNodeSourcePageRange(
            project_id=project.id,
            program_node_id=topic.id,
            material_id=material.id,
            source_name_snapshot=material.original_name,
            outline_item_key=f"{material.id}:1",
            page_from=page,
            page_to=page + 1,
        ))
    session.commit()
    session.delete(session.get(ProjectMaterial, (project.id, detached.id)))
    session.commit()

    state = program.read_program(session, project.id)
    ranges = next(node for node in state.nodes if node.id == topic.id).source_page_ranges
    assert [item.material_id for item in ranges] == [kept.id]


def test_project_chat_list_skips_program_sessions(session: Session) -> None:
    project = make_free_project(session)
    program_chat.create_session(session, project.id)
    session.add(ChatSession(
        project_id=project.id,
        program_node_id=None,
        title="Свободное изучение",
        persona=ExaminerPersona.NEUTRAL_EXAMINER,
        strictness=ExaminerStrictness.NORMAL,
        mode=ChatMode.STUDY,
    ))
    session.commit()

    sessions = exam_chat.list_sessions(session, project.id, None)
    assert [chat.mode for chat in sessions] == [ChatMode.STUDY]
