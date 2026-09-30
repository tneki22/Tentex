from uuid import uuid4

import pytest
from conftest import make_textbook_project
from sqlalchemy.orm import Session

from app.models import NodeType, ProgramNode, utc_now
from app.projects.errors import ProjectInvariantError
from app.projects.schemas import WorkspaceStateWrite
from app.projects.service import save_workspace_state


def make_section(session: Session, project_id, *, visible: bool = True, archived: bool = False):
    node = ProgramNode(
        id=uuid4(), project_id=project_id, parent_id=None, node_type=NodeType.SECTION,
        sort_order=0, title="Раздел", is_in_current_program=visible, needs_material=False,
        is_archived=archived, created_at=utc_now(), updated_at=utc_now(),
    )
    session.add(node)
    session.commit()
    return node


def command(node_id) -> WorkspaceStateWrite:
    return WorkspaceStateWrite.model_validate({
        "schema_version": 1,
        "layout": {
            "selected_node_id": str(node_id),
            "groups": [{"id": "main", "tabs": ["source"], "active_tab": "source"}],
            "group_weights": [1],
        },
    })


def test_workspace_accepts_active_section(session: Session) -> None:
    project = make_textbook_project(session)
    section = make_section(session, project.id)
    saved = save_workspace_state(session, project.id, command(section.id))
    assert saved.layout.selected_node_id == section.id


@pytest.mark.parametrize("invalid", ["foreign", "hidden", "archived"])
def test_workspace_rejects_unavailable_section(session: Session, invalid: str) -> None:
    project = make_textbook_project(session)
    owner = make_textbook_project(session) if invalid == "foreign" else project
    section = make_section(
        session, owner.id, visible=invalid != "hidden", archived=invalid == "archived"
    )
    with pytest.raises(ProjectInvariantError):
        save_workspace_state(session, project.id, command(section.id))
