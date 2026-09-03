import pytest
from conftest import (
    add_page_with_fragments,
    link_material,
    make_exam_project,
    make_material,
    make_topic_node,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.bindings import search as search_module
from app.bindings import service
from app.bindings.schemas import BindingCreateWrite
from app.materials.schemas import MaterialPurpose
from app.models import (
    Binding,
    BindingMechanism,
    BindingStatus,
    MaterialFragment,
    ProgramNode,
    ProjectMaterial,
    ProjectStatus,
)
from app.projects.errors import ProjectConflictError, ProjectNotFoundError
from app.projects.program import undo_last_project_action


def _bind(session: Session, project, node, fragment_ids):
    return service.create_bindings(
        session,
        project.id,
        BindingCreateWrite(program_node_id=node.id, fragment_ids=list(fragment_ids)),
    )


def test_repeated_create_does_not_duplicate(session: Session) -> None:
    project = make_exam_project(session)
    node = make_topic_node(session, project, title="Транзакции")
    material = make_material(session, "aa")
    link_material(session, project, material)
    page = add_page_with_fragments(
        session, material, page_number=1, revision=1, fragments=["Текст фрагмента."]
    )

    first = _bind(session, project, node, page.fragment_ids)
    second = _bind(session, project, node, page.fragment_ids)

    assert len(first.bindings) == 1
    assert len(second.bindings) == 1
    assert first.bindings[0].id == second.bindings[0].id
    count = session.scalar(select(Binding).where(Binding.project_id == project.id))
    assert count is not None
    all_rows = list(session.scalars(select(Binding).where(Binding.project_id == project.id)))
    assert len(all_rows) == 1


def test_active_image_binding_includes_kind_and_asset_label(session: Session) -> None:
    project = make_exam_project(session)
    node = make_topic_node(session, project, title="Схема")
    material = make_material(session, "a1")
    link_material(session, project, material)
    page = add_page_with_fragments(
        session, material, page_number=1, revision=1, fragments=["[Изображение]"]
    )
    image = session.get(MaterialFragment, page.fragment_ids[0])
    assert image is not None
    image.element_kind = "image"
    image.asset_path = "assets/material/flow.png"
    session.commit()

    _bind(session, project, node, page.fragment_ids)
    active = service.list_bindings(session, project.id, node_id=node.id)

    assert active[0].element_kind == "image"
    assert active[0].asset_label is not None
    assert active[0].asset_label.endswith(f" · {material.id}")


def test_active_table_binding_includes_kind_and_asset_label(session: Session) -> None:
    project = make_exam_project(session)
    node = make_topic_node(session, project, title="Таблица")
    material = make_material(session, "a4")
    link_material(session, project, material)
    page = add_page_with_fragments(
        session, material, page_number=1, revision=1, fragments=["Таблица"]
    )
    table = session.get(MaterialFragment, page.fragment_ids[0])
    assert table is not None
    table.element_kind = "table"
    table.asset_path = "assets/material/table.png"
    session.commit()

    _bind(session, project, node, page.fragment_ids)
    active = service.list_bindings(session, project.id, node_id=node.id)

    assert active[0].element_kind == "table"
    assert active[0].asset_label is not None
    assert active[0].asset_label.endswith(f" · {material.id}")


def test_image_binding_labels_do_not_collide_between_materials(session: Session) -> None:
    project = make_exam_project(session)
    node = make_topic_node(session, project, title="Две схемы")
    labels = []
    for seed in ("a2", "a3"):
        material = make_material(session, seed)
        link_material(session, project, material)
        page = add_page_with_fragments(
            session, material, page_number=1, revision=1, fragments=["[Изображение]"]
        )
        image = session.get(MaterialFragment, page.fragment_ids[0])
        assert image is not None
        image.element_kind = "image"
        image.asset_path = "assets/material/flow.png"
        session.commit()
        _bind(session, project, node, page.fragment_ids)
        binding = service.list_bindings(session, project.id, material_id=material.id)[0]
        labels.append(binding.asset_label)

    assert labels[0] != labels[1]


def test_remove_is_reversible_via_restore(session: Session) -> None:
    project = make_exam_project(session)
    node = make_topic_node(session, project, title="Индексы")
    material = make_material(session, "bb")
    link_material(session, project, material)
    page = add_page_with_fragments(
        session, material, page_number=1, revision=1, fragments=["Индекс ускоряет поиск."]
    )
    created = _bind(session, project, node, page.fragment_ids)
    binding_id = created.bindings[0].id

    removed = service.remove_binding(session, project.id, binding_id)
    assert removed.bindings[0].status == BindingStatus.REMOVED
    active = service.list_bindings(session, project.id, node_id=node.id)
    assert active == []
    session.commit()

    restored = service.restore_binding(session, project.id, binding_id)
    assert restored.bindings[0].status == BindingStatus.MANUAL
    active_again = service.list_bindings(session, project.id, node_id=node.id)
    assert len(active_again) == 1


def test_undo_removes_a_whole_block_batch(session: Session) -> None:
    project = make_exam_project(session)
    node = make_topic_node(session, project, title="Нормальные формы")
    material = make_material(session, "cc")
    link_material(session, project, material)
    page = add_page_with_fragments(
        session,
        material,
        page_number=1,
        revision=1,
        fragments=["Первая нормальная форма.", "Вторая нормальная форма.", "Третья форма."],
    )

    result = service.create_bindings(
        session,
        project.id,
        BindingCreateWrite(program_node_id=node.id, block_id=page.block_id),
    )
    assert len(result.bindings) == 3
    assert result.latest_undoable_action is not None
    sequence = result.latest_undoable_action.sequence

    undo_last_project_action(session, project.id, sequence)

    active = service.list_bindings(session, project.id, node_id=node.id)
    assert active == []
    all_rows = list(session.scalars(select(Binding).where(Binding.project_id == project.id)))
    assert len(all_rows) == 3
    assert all(row.status == BindingStatus.REMOVED for row in all_rows)


def test_binding_to_node_from_another_project_is_conflict(session: Session) -> None:
    project = make_exam_project(session)
    other_project = make_exam_project(session)
    other_node = make_topic_node(session, other_project, title="Чужой узел")
    material = make_material(session, "dd")
    link_material(session, project, material)
    page = add_page_with_fragments(
        session, material, page_number=1, revision=1, fragments=["Текст."]
    )

    with pytest.raises(ProjectNotFoundError):
        service.create_bindings(
            session,
            project.id,
            BindingCreateWrite(program_node_id=other_node.id, fragment_ids=page.fragment_ids),
        )


def test_archived_project_rejects_binding_changes(session: Session) -> None:
    project = make_exam_project(session)
    node = make_topic_node(session, project, title="Узел")
    material = make_material(session, "ee")
    link_material(session, project, material)
    page = add_page_with_fragments(
        session, material, page_number=1, revision=1, fragments=["Текст."]
    )
    project.status = ProjectStatus.ARCHIVED
    session.commit()

    with pytest.raises(ProjectConflictError):
        service.create_bindings(
            session,
            project.id,
            BindingCreateWrite(program_node_id=node.id, fragment_ids=page.fragment_ids),
        )


def test_binding_cascades_when_program_node_is_deleted(session: Session) -> None:
    project = make_exam_project(session)
    node = make_topic_node(session, project, title="Удаляемый узел")
    material = make_material(session, "ff")
    link_material(session, project, material)
    page = add_page_with_fragments(
        session, material, page_number=1, revision=1, fragments=["Текст."]
    )
    _bind(session, project, node, page.fragment_ids)

    with session.begin():
        session.execute(
            ProgramNode.__table__.delete().where(ProgramNode.id == node.id)
        )
    remaining = list(session.scalars(select(Binding).where(Binding.project_id == project.id)))
    assert remaining == []


def test_binding_cascades_when_material_is_deleted(session: Session) -> None:
    project = make_exam_project(session)
    node = make_topic_node(session, project, title="Узел")
    material = make_material(session, "77")
    link_material(session, project, material)
    page = add_page_with_fragments(
        session, material, page_number=1, revision=1, fragments=["Текст."]
    )
    _bind(session, project, node, page.fragment_ids)

    with session.begin():
        session.execute(
            ProjectMaterial.__table__.delete().where(ProjectMaterial.material_id == material.id)
        )
        stored_material = session.get(type(material), material.id)
        session.delete(stored_material)
    remaining = list(session.scalars(select(Binding).where(Binding.project_id == project.id)))
    assert remaining == []


def test_general_search_excludes_reference_answers_material(session: Session) -> None:
    project = make_exam_project(session)
    material = make_material(session, "78")
    link = link_material(session, project, material)
    link.purposes = [MaterialPurpose.REFERENCE_ANSWERS.value]
    page = add_page_with_fragments(
        session,
        material,
        page_number=1,
        revision=1,
        fragments=["Реляционная модель хранит данные в таблицах."],
    )
    search_module.reindex_material(session, material.id)
    session.commit()

    assert service.search_project_materials(session, project.id, "реляционная модель") == []
    explicit = service.search_project_materials(
        session, project.id, "реляционная модель", material_id=material.id
    )
    assert explicit[0].fragment_ids == page.fragment_ids


def test_answers_file_binding_does_not_mark_study_result_as_bound(session: Session) -> None:
    project = make_exam_project(session)
    node = make_topic_node(session, project, title="Реляционная модель")
    material = make_material(session, "79")
    link_material(session, project, material)
    page = add_page_with_fragments(
        session,
        material,
        page_number=1,
        revision=1,
        fragments=["Реляционная модель хранит данные в таблицах."],
    )
    search_module.reindex_material(session, material.id)
    session.commit()
    service.create_bindings(
        session,
        project.id,
        BindingCreateWrite(
            program_node_id=node.id,
            fragment_ids=page.fragment_ids,
            mechanism=BindingMechanism.ANSWERS_FILE,
        ),
    )

    results = service.search_project_materials(
        session, project.id, "реляционная модель", node_id=node.id
    )
    assert results[0].already_bound is False
