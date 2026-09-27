from uuid import uuid4

import pytest
from conftest import (
    add_page_with_fragments,
    link_material,
    make_material,
    make_textbook_project,
    make_topic_node,
)
from sqlalchemy.orm import Session

from app.materials import service
from app.materials.schemas import MaterialOrderWrite
from app.models import Binding, BindingMechanism, BindingStatus, utc_now
from app.projects.errors import ProjectConflictError


def _bind(session: Session, project_id, node_id, material_id, fragment_id, status) -> None:
    session.add(
        Binding(
            id=uuid4(),
            project_id=project_id,
            program_node_id=node_id,
            fragment_id=fragment_id,
            material_id=material_id,
            status=status,
            mechanism=BindingMechanism.MANUAL,
            created_at=utc_now(),
            updated_at=utc_now(),
        )
    )


def test_used_by_topics_counts_each_topic_once(session: Session) -> None:
    project = make_textbook_project(session)
    material = make_material(session, "e1")
    link_material(session, project, material)
    page = add_page_with_fragments(
        session, material, page_number=1, revision=1, fragments=["Один", "Два"]
    )
    grown = make_topic_node(session, project, title="Из оглавления")
    grown.origin_material_id = material.id
    bound = make_topic_node(session, project, title="Привязанная")
    removed = make_topic_node(session, project, title="Снятая привязка")
    # Тема и выросла из источника, и привязана к нему — считается один раз.
    _bind(session, project.id, grown.id, material.id, page.fragment_ids[0], BindingStatus.MANUAL)
    _bind(session, project.id, bound.id, material.id, page.fragment_ids[1], BindingStatus.MACHINE)
    _bind(
        session, project.id, removed.id, material.id, page.fragment_ids[0], BindingStatus.REMOVED
    )
    session.commit()

    [listed] = service.list_materials(session, project.id)

    assert listed.used_by_topics == 2


def test_reorder_turns_row_order_into_priority(session: Session) -> None:
    project = make_textbook_project(session)
    first, second, third = (make_material(session, seed) for seed in ("c1", "c2", "c3"))
    for material in (first, second, third):
        link_material(session, project, material)

    listed = service.reorder_materials(
        session, project.id, MaterialOrderWrite(material_ids=[third.id, first.id, second.id])
    )

    assert [(item.id, item.priority) for item in listed] == [
        (third.id, 0),
        (first.id, 1),
        (second.id, 2),
    ]
    with pytest.raises(ProjectConflictError) as caught:
        service.reorder_materials(
            session, project.id, MaterialOrderWrite(material_ids=[first.id, second.id])
        )
    assert caught.value.code == "material_order_stale"
