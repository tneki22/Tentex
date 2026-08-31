from conftest import (
    add_page_with_fragments,
    link_material,
    make_exam_project,
    make_material,
    make_topic_node,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.bindings import service
from app.bindings.schemas import BindingCreateWrite
from app.models import Binding, BindingStatus, MaterialFragment


def _fragments(session: Session, page) -> list[MaterialFragment]:
    return list(
        session.scalars(
            select(MaterialFragment)
            .where(MaterialFragment.id.in_(page.fragment_ids))
            .order_by(MaterialFragment.sort_order)
        )
    )


def test_edit_without_changing_fragment_count_keeps_all_bindings(session: Session) -> None:
    project = make_exam_project(session)
    node = make_topic_node(session, project, title="Тема")
    material = make_material(session, "aa")
    link_material(session, project, material)
    old_page = add_page_with_fragments(
        session,
        material,
        page_number=1,
        revision=1,
        fragments=["Первый абзац.", "Второй абзац.", "Третий абзац."],
    )
    service.create_bindings(
        session,
        project.id,
        BindingCreateWrite(program_node_id=node.id, fragment_ids=old_page.fragment_ids),
    )

    new_page = add_page_with_fragments(
        session,
        material,
        page_number=1,
        revision=2,
        fragments=["Первый абзац.", "Второй абзац ИЗМЕНЁН.", "Третий абзац."],
    )

    result = service.transfer_bindings_on_revision(
        session,
        material.id,
        {1: _fragments(session, old_page)},
        {1: _fragments(session, new_page)},
    )
    session.commit()

    assert result.transferred == 3
    assert result.orphaned == []
    active = service.list_bindings(session, project.id, node_id=node.id)
    assert len(active) == 3
    texts = {binding.text for binding in active}
    assert texts == {"Первый абзац.", "Второй абзац ИЗМЕНЁН.", "Третий абзац."}


def test_removing_a_paragraph_leaves_exactly_one_orphaned(session: Session) -> None:
    project = make_exam_project(session)
    node = make_topic_node(session, project, title="Тема")
    material = make_material(session, "bb")
    link_material(session, project, material)
    old_page = add_page_with_fragments(
        session,
        material,
        page_number=1,
        revision=1,
        fragments=["Первый абзац.", "Второй абзац.", "Третий абзац."],
    )
    service.create_bindings(
        session,
        project.id,
        BindingCreateWrite(program_node_id=node.id, fragment_ids=old_page.fragment_ids),
    )

    new_page = add_page_with_fragments(
        session,
        material,
        page_number=1,
        revision=2,
        fragments=["Первый абзац.", "Третий абзац."],
    )

    result = service.transfer_bindings_on_revision(
        session,
        material.id,
        {1: _fragments(session, old_page)},
        {1: _fragments(session, new_page)},
    )
    session.commit()

    assert result.transferred == 2
    assert len(result.orphaned) == 1
    orphaned_binding = session.get(Binding, result.orphaned[0])
    assert orphaned_binding.status == BindingStatus.ORPHANED
    session.commit()
    active = service.list_bindings(session, project.id, node_id=node.id)
    assert len(active) == 2
    orphaned_list = service.list_bindings(
        session, project.id, node_id=node.id, status=BindingStatus.ORPHANED
    )
    assert len(orphaned_list) == 1
    assert orphaned_list[0].text == "Второй абзац."


def test_delete_preview_reports_binding_count_and_affected_nodes(session: Session) -> None:
    project = make_exam_project(session)
    node = make_topic_node(session, project, title="Единственный источник")
    material = make_material(session, "cc")
    other_material = make_material(session, "dd")
    link_material(session, project, material)
    link_material(session, project, other_material)
    page = add_page_with_fragments(
        session, material, page_number=1, revision=1, fragments=["Текст."]
    )
    other_page = add_page_with_fragments(
        session, other_material, page_number=1, revision=1, fragments=["Другой текст."]
    )
    service.create_bindings(
        session,
        project.id,
        BindingCreateWrite(program_node_id=node.id, fragment_ids=page.fragment_ids),
    )

    assert service.binding_count_for_materials(session, [material.id]) == 1
    affected = service.affected_projects_preview(session, [material.id])
    assert len(affected) == 1
    assert affected[0].project_id == project.id
    assert affected[0].nodes_losing_material == ["Единственный источник"]
    session.commit()

    service.create_bindings(
        session,
        project.id,
        BindingCreateWrite(program_node_id=node.id, fragment_ids=other_page.fragment_ids),
    )

    affected_after_second_source = service.affected_projects_preview(session, [material.id])
    assert affected_after_second_source == []

    # А пачкой — тема всё-таки осиротеет. Поштучный предпросмотр этого не видит:
    # каждый из двух материалов по отдельности выглядит заменимым другим.
    both = [material.id, other_material.id]
    affected_for_both = service.affected_projects_preview(session, both)
    assert len(affected_for_both) == 1
    assert affected_for_both[0].nodes_losing_material == ["Единственный источник"]
    assert service.binding_count_for_materials(session, both) == 2
