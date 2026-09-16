"""Итерация 2.2 «Уроков»: точные куски, разрез и склейка, темы, перенос границ, снятие привязок."""

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.bindings.service import transfer_bindings_on_revision
from app.lessons import editing, service
from app.lessons.schemas import LessonBlockWrite, LessonConfirmWrite, LessonManualWrite
from app.materials.library import fragments_by_page
from app.models import (
    Binding,
    BindingMechanism,
    BindingStatus,
    LessonBlockKind,
    Project,
    ProjectActionLog,
)
from app.projects.errors import ProjectDomainError
from app.projects.program import undo_last_project_action
from tests.test_lessons import Book, add_node, make_lessons_project


@pytest.fixture
def project(session: Session) -> Project:
    return make_lessons_project(session)


def manual_lesson(session, project, topic):
    return service.create_manual_lesson(
        session, project.id, LessonManualWrite(program_node_id=topic.id)
    ).lesson


def edit(session, project, lesson, **fields):
    # Чтения между правками открывают транзакцию сессии, а сервис начинает свою.
    project_id = project.id
    session.rollback()
    return editing.edit_lesson_blocks(
        session, project_id, lesson.id,
        LessonBlockWrite(expected_revision=lesson.revision, **fields),
    )


def bounds(ref):
    return (ref.page_from, ref.from_fragment_id, ref.page_to, ref.to_fragment_id)


def bindings(session, project):
    result = {
        (item.program_node_id, item.fragment_id): (item.id, item.status, item.mechanism)
        for item in session.scalars(select(Binding).where(Binding.project_id == project.id))
    }
    session.rollback()
    return result


@pytest.fixture
def book(session, project) -> Book:
    book = Book(session, project, "Олифер")
    book.page(10, "h:Ethernet", "p:кадр", "p:преамбула")
    book.page(11, "s:Колонтитул", "p:CSMA", "p:коллизии", "h:Wi-Fi", "p:радио")
    book.page(12, "p:радио дальше")
    return book


def test_split_mid_page_and_merge_back_restore_the_same_piece(session, project, book):
    topic = add_node(session, project, "Сети", 0)
    lesson = manual_lesson(session, project, topic)
    lesson = edit(session, project, lesson, operation="add_page", material_id=book.material.id,
                  page_from=10, page_to=12).lesson
    original = lesson.blocks[0].refs[0]

    lesson = edit(session, project, lesson, operation="split", block_id=lesson.blocks[0].id,
                  fragment_id=book.ids["CSMA"], insert_note=True, variant="explanation").lesson

    kinds = [block.kind for block in lesson.blocks]
    assert kinds == [LessonBlockKind.SOURCE, LessonBlockKind.NOTE, LessonBlockKind.SOURCE]
    head, tail = lesson.blocks[0].refs[0], lesson.blocks[2].refs[0]
    assert bounds(head) == (10, None, 11, book.ids["CSMA"])
    assert bounds(tail) == (11, book.ids["коллизии"], 12, None)
    # Лист 11 начинается в первом куске — второй его не повторяет.
    assert (head.pages_shown, tail.pages_shown) == ([10, 11], [12])

    lesson = edit(session, project, lesson, operation="delete", block_id=lesson.blocks[1].id).lesson
    lesson = edit(session, project, lesson, operation="merge", block_id=lesson.blocks[0].id).lesson
    assert len(lesson.blocks) == 1
    assert bounds(lesson.blocks[0].refs[0]) == bounds(original)


def test_split_after_last_fragment_of_page_becomes_page_boundary(session, project, book):
    topic = add_node(session, project, "Сети", 0)
    lesson = manual_lesson(session, project, topic)
    lesson = edit(session, project, lesson, operation="add_page", material_id=book.material.id,
                  page_from=10, page_to=12).lesson

    lesson = edit(session, project, lesson, operation="split", block_id=lesson.blocks[0].id,
                  fragment_id=book.ids["преамбула"]).lesson

    head, tail = (block.refs[0] for block in lesson.blocks)
    assert bounds(head) == (10, None, 10, None)
    assert bounds(tail) == (11, None, 12, None)
    with pytest.raises(ProjectDomainError) as outside:
        edit(session, project, lesson, operation="split", block_id=lesson.blocks[1].id,
             fragment_id=book.ids["радио дальше"])
    assert outside.value.code == "lesson_split_outside"


def test_page_is_drawn_once_where_its_first_fragment_lies_after_reorder(session, project, book):
    topic = add_node(session, project, "Сети", 0)
    lesson = manual_lesson(session, project, topic)
    lesson = edit(session, project, lesson, operation="add_page", material_id=book.material.id,
                  page_from=10, page_to=11).lesson
    lesson = edit(session, project, lesson, operation="split", block_id=lesson.blocks[0].id,
                  fragment_id=book.ids["коллизии"]).lesson
    lesson = edit(
        session, project, lesson, operation="move_up", block_id=lesson.blocks[1].id
    ).lesson

    tail, head = (block.refs[0] for block in lesson.blocks)
    assert tail.from_fragment_id == book.ids["Wi-Fi"]
    assert (tail.pages_shown, head.pages_shown) == ([], [10, 11])


def test_split_undo_restores_original_boundaries(session, project, book):
    topic = add_node(session, project, "Сети", 0)
    lesson = manual_lesson(session, project, topic)
    added = edit(session, project, lesson, operation="add_page", material_id=book.material.id,
                 page_from=10, page_to=12).lesson
    split = edit(session, project, added, operation="split", block_id=added.blocks[0].id,
                 fragment_id=book.ids["CSMA"]).lesson

    undo_last_project_action(session, project.id, split.undo_sequence)

    restored = service.get_lesson(session, project.id, lesson.id)
    assert [block.id for block in restored.blocks] == [added.blocks[0].id]
    assert bounds(restored.blocks[0].refs[0]) == bounds(added.blocks[0].refs[0])


def test_selected_fragments_and_structure_block_bind_only_the_selection(session, project, book):
    topic = add_node(session, project, "Сети", 0)
    lesson = manual_lesson(session, project, topic)

    lesson = edit(session, project, lesson, operation="add_fragments",
                  material_id=book.material.id, from_fragment_id=book.ids["коллизии"],
                  to_fragment_id=book.ids["CSMA"]).lesson
    ref = lesson.blocks[0].refs[0]
    assert bounds(ref) == (11, book.ids["CSMA"], 11, book.ids["коллизии"])
    assert set(bindings(session, project)) == {
        (topic.id, book.ids["CSMA"]), (topic.id, book.ids["коллизии"])
    }

    lesson = edit(session, project, lesson, operation="add_block", material_id=book.material.id,
                  fragment_id=book.ids["радио дальше"]).lesson
    block_ref = lesson.blocks[1].refs[0]
    assert bounds(block_ref) == (11, book.ids["Wi-Fi"], 12, None)
    created = bindings(session, project)
    assert {fragment for _, fragment in created} == {
        book.ids[text] for text in ("CSMA", "коллизии", "Wi-Fi", "радио", "радио дальше")
    }
    assert all(
        item[1:] == (BindingStatus.MANUAL, BindingMechanism.LESSON) for item in created.values()
    )


def test_new_revision_transfers_boundaries_and_degrades_lost_one_to_page(session, project, book):
    topic = add_node(session, project, "Сети", 0)
    lesson = manual_lesson(session, project, topic)
    lesson = edit(session, project, lesson, operation="add_fragments",
                  material_id=book.material.id, from_fragment_id=book.ids["CSMA"],
                  to_fragment_id=book.ids["коллизии"]).lesson
    old_csma = book.ids["CSMA"]

    book.revision, book.block = 2, None
    book.page(10, "h:Ethernet", "p:кадр", "p:преамбула")
    book.page(11, "s:Колонтитул", "p:CSMA", "p:коллизии ИСПРАВЛЕНО", "h:Wi-Fi", "p:радио", "p:ещё")
    book.page(12, "p:радио дальше")
    old = fragments_by_page(session, book.material.id, 1)
    book.material.active_parse_revision = 2
    new = fragments_by_page(session, book.material.id, 2)
    transfer_bindings_on_revision(session, book.material.id, old, new)
    session.commit()

    ref = service.get_lesson(session, project.id, lesson.id).blocks[0].refs[0]
    assert ref.from_fragment_id == book.ids["CSMA"] != old_csma
    assert (ref.page_to, ref.to_fragment_id, ref.boundary_shifted) == (11, None, True)
    assert ref.material_revision == 2


def test_topic_rename_needs_review_and_confirm_clears_snapshots(session, project, book):
    topic = add_node(session, project, "Сети", 0)
    lesson = manual_lesson(session, project, topic)
    topic.title = "Компьютерные сети"
    session.commit()

    lesson = service.get_lesson(session, project.id, lesson.id)
    assert lesson.needs_review
    assert service.lessons_overview(session, project.id).lessons[0].needs_review

    project_id = project.id
    session.rollback()
    confirmed = editing.confirm_lesson(
        session, project_id, lesson.id, LessonConfirmWrite(expected_revision=lesson.revision)
    ).lesson
    assert not confirmed.needs_review
    assert confirmed.topics[0].title_snapshot == "Компьютерные сети"


def test_multi_topic_lesson_binds_by_range_and_topic_change_offers_unbind(session, project, book):
    ethernet = add_node(session, project, "Ethernet", 0, ranges=[(book, 10, 11)])
    wifi = add_node(session, project, "Wi-Fi", 1, ranges=[(book, 11, 12)])
    lesson = manual_lesson(session, project, ethernet)
    lesson = edit(session, project, lesson, operation="add_topic",
                  program_node_id=wifi.id).lesson
    assert [topic.program_node_id for topic in lesson.topics] == [ethernet.id, wifi.id]

    lesson = edit(session, project, lesson, operation="add_page", material_id=book.material.id,
                  page_from=12).lesson
    block = lesson.blocks[0]
    assert block.bound_program_node_id == wifi.id
    assert set(bindings(session, project)) == {(wifi.id, book.ids["радио дальше"])}

    changed = edit(session, project, lesson, operation="set_topic", block_id=block.id,
                   program_node_id=ethernet.id)
    assert changed.lesson.blocks[0].bound_program_node_id == ethernet.id
    offer = changed.unbind_offer
    assert (offer.program_node_id, len(offer.binding_ids)) == (wifi.id, 1)
    with pytest.raises(ProjectDomainError) as in_use:
        edit(session, project, changed.lesson, operation="remove_topic",
             program_node_id=ethernet.id)
    assert in_use.value.code == "lesson_topic_in_use"

    project_id = project.id
    session.rollback()
    unbound = editing.unbind_lesson_bindings(
        session, project_id, lesson.id,
        editing.LessonUnbindWrite(binding_ids=offer.binding_ids),
    )
    key = (wifi.id, book.ids["радио дальше"])
    assert bindings(session, project)[key][1] == BindingStatus.REMOVED
    undo_last_project_action(session, project_id, unbound.lesson.undo_sequence)
    assert bindings(session, project)[key][1] == BindingStatus.MANUAL


def test_delete_offers_only_lesson_bindings_not_held_by_other_pieces(session, project, book):
    topic = add_node(session, project, "Сети", 0)
    session.add(Binding(
        project_id=project.id, program_node_id=topic.id, fragment_id=book.ids["преамбула"],
        material_id=book.material.id, status=BindingStatus.MANUAL,
        mechanism=BindingMechanism.MANUAL,
    ))
    session.commit()
    lesson = manual_lesson(session, project, topic)
    lesson = edit(session, project, lesson, operation="add_page", material_id=book.material.id,
                  page_from=10).lesson
    lesson = edit(session, project, lesson, operation="add_fragments",
                  material_id=book.material.id, from_fragment_id=book.ids["кадр"],
                  to_fragment_id=book.ids["кадр"]).lesson

    deleted = edit(session, project, lesson, operation="delete", block_id=lesson.blocks[0].id)

    offered = set(deleted.unbind_offer.binding_ids)
    by_fragment = {key[1]: item[0] for key, item in bindings(session, project).items()}
    assert offered == {by_fragment[book.ids["Ethernet"]]}


def test_link_media_requires_http_and_always_pages_toggles(session, project, book):
    topic = add_node(session, project, "Сети", 0)
    lesson = manual_lesson(session, project, topic)
    with pytest.raises(ProjectDomainError) as bad:
        edit(session, project, lesson, operation="add_link", media_url="file:///etc/passwd")
    assert bad.value.code == "lesson_media_url"
    session.rollback()
    lesson = edit(session, project, lesson, operation="add_link",
                  media_url="https://example.org/ethernet", caption="Схема").lesson
    lesson = edit(session, project, lesson, operation="add_page", material_id=book.material.id,
                  page_from=10).lesson
    lesson = edit(session, project, lesson, operation="set_always_pages",
                  block_id=lesson.blocks[1].id, always_pages=True).lesson

    media, source = lesson.blocks
    assert (media.media_kind, media.media_url, media.body_md) == (
        "link", "https://example.org/ethernet", "Схема"
    )
    assert source.refs[0].always_pages


def test_before_block_id_inserts_above_the_very_first_block(session, project, book):
    topic = add_node(session, project, "Сети", 0)
    lesson = manual_lesson(session, project, topic)
    lesson = edit(session, project, lesson, operation="add_page", material_id=book.material.id,
                  page_from=10).lesson
    first = lesson.blocks[0]

    lesson = edit(session, project, lesson, operation="add_note", variant="heading",
                  before_block_id=first.id).lesson

    assert [block.kind for block in lesson.blocks] == [LessonBlockKind.NOTE, LessonBlockKind.SOURCE]
    assert lesson.blocks[1].id == first.id


def test_delete_lesson_removes_it_and_disarms_its_undo(session, project, book):
    topic = add_node(session, project, "Сети", 0)
    lesson = manual_lesson(session, project, topic)
    lesson = edit(session, project, lesson, operation="add_page", material_id=book.material.id,
                  page_from=10).lesson
    session.rollback()

    service.delete_lesson(session, project.id, lesson.id)

    assert service.lessons_overview(session, project.id).lessons == []
    session.rollback()
    # Отменять нечего: записи журнала об этом уроке погашены вместе с ним.
    live = session.scalars(
        select(ProjectActionLog).where(
            ProjectActionLog.project_id == project.id, ProjectActionLog.undone_at.is_(None)
        )
    )
    assert all(item.inverse_data.get("lesson_id") != str(lesson.id) for item in live)
