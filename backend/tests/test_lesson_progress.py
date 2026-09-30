"""Этап 3 «Уроков»: массовая подготовка, область страницы и прохождение урока."""

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.lessons import bulk, editing, progress, service
from app.lessons.schemas import (
    LessonBlockWrite,
    LessonBulkItem,
    LessonBulkWrite,
    LessonCompletionWrite,
    LessonManualWrite,
    LessonProgressWrite,
)
from app.models import Binding, Lesson, LessonBlockKind, LessonSourceRef, MaterialFragment, Project
from app.preparation.models import StudyActivity
from app.projects import service as project_service
from app.projects.errors import ProjectConflictError, ProjectDomainError
from app.projects.program import undo_last_project_action
from tests.test_lessons import Book, add_node, make_lessons_project


@pytest.fixture
def project(session: Session) -> Project:
    return make_lessons_project(session)


def bulk_create(session, project, *items):
    session.rollback()
    return bulk.create_bulk_lessons(
        session,
        project.id,
        LessonBulkWrite(items=[LessonBulkItem(program_node_id=node.id, action=action)
                               for node, action in items]),
    )


def test_bulk_creates_quick_and_empty_lessons_in_one_action(session, project):
    book = Book(session, project, "Олифер")
    book.page(10, "h:2.3 Ethernet", "p:кадр")
    book.page(11, "h:2.4 Wi-Fi", "p:канал")
    ethernet = add_node(session, project, "Ethernet", 0, ranges=[(book, 10, 10)])
    wifi = add_node(session, project, "Wi-Fi", 1, ranges=[(book, 11, 11)])
    vlan = add_node(session, project, "VLAN", 2)

    result = bulk_create(session, project, (ethernet, "quick"), (wifi, "quick"), (vlan, "manual"))

    assert [item.title for item in result.lessons] == ["Ethernet", "Wi-Fi", "VLAN"]
    assert result.latest_undoable_action.action_type == "lesson_bulk_create"
    vlan_lesson = service.get_lesson(session, project.id, result.lessons[2].id)
    assert vlan_lesson.blocks == []
    ethernet_lesson = service.get_lesson(session, project.id, result.lessons[0].id)
    assert any(block.kind == LessonBlockKind.SOURCE for block in ethernet_lesson.blocks)


def test_bulk_undo_removes_every_lesson_and_its_bindings(session, project):
    book = Book(session, project, "Олифер")
    book.page(10, "h:2.3 Ethernet", "p:кадр")
    book.page(11, "h:2.4 Wi-Fi", "p:канал")
    ethernet = add_node(session, project, "Ethernet", 0, ranges=[(book, 10, 10)])
    wifi = add_node(session, project, "Wi-Fi", 1, ranges=[(book, 11, 11)])

    project_id = project.id
    result = bulk_create(session, project, (ethernet, "quick"), (wifi, "quick"))
    assert session.scalar(select(Binding).where(Binding.project_id == project_id)) is not None

    # Откат закрывает читающую транзакцию: сервис отмены начинает свою.
    session.rollback()
    undo_last_project_action(session, project_id, result.latest_undoable_action.sequence)

    assert session.scalars(select(Lesson).where(Lesson.project_id == project_id)).all() == []
    assert session.scalars(select(Binding).where(Binding.project_id == project_id)).all() == []


def test_bulk_quick_without_ranges_creates_nothing(session, project):
    book = Book(session, project, "Олифер")
    book.page(10, "h:2.3 Ethernet", "p:кадр")
    ethernet = add_node(session, project, "Ethernet", 0, ranges=[(book, 10, 10)])
    vlan = add_node(session, project, "VLAN", 1)

    with pytest.raises(ProjectConflictError):
        bulk_create(session, project, (ethernet, "quick"), (vlan, "quick"))

    session.rollback()
    assert session.scalars(select(Lesson).where(Lesson.project_id == project.id)).all() == []


def test_bulk_refuses_the_same_topic_twice(session, project):
    topic = add_node(session, project, "Ethernet", 0)

    with pytest.raises(ProjectDomainError):
        bulk_create(session, project, (topic, "manual"), (topic, "manual"))


# --- область страницы ------------------------------------------------------------------


def place(session, book, text, bbox):
    """Фрагменты `Book` лежат на всей странице — тесту области нужны настоящие координаты."""
    fragment = session.get(MaterialFragment, book.ids[text])
    fragment.bbox = bbox
    session.commit()


def test_region_binds_only_fragments_inside_it_and_shows_as_a_crop(session, project):
    book = Book(session, project, "Олифер")
    book.page(10, "h:2.3 Ethernet", "p:схема кадра", "p:совсем другой абзац")
    place(session, book, "2.3 Ethernet", [0.1, 0.02, 0.9, 0.08])
    place(session, book, "схема кадра", [0.1, 0.2, 0.9, 0.4])
    place(session, book, "совсем другой абзац", [0.1, 0.7, 0.9, 0.9])
    topic = add_node(session, project, "Ethernet", 0, ranges=[(book, 10, 10)])
    lesson = service.create_manual_lesson(
        session, project.id, LessonManualWrite(program_node_id=topic.id)
    ).lesson

    session.rollback()
    result = editing.edit_lesson_blocks(
        session, project.id, lesson.id,
        LessonBlockWrite(expected_revision=lesson.revision, operation="add_region",
                         material_id=book.material.id, page_from=10,
                         region_bbox=[0.05, 0.15, 0.95, 0.5]),
    )

    [block] = [item for item in result.lesson.blocks if item.kind == LessonBlockKind.SOURCE]
    ref = block.refs[0]
    assert ref.region_bbox == [0.05, 0.15, 0.95, 0.5]
    assert (ref.page_from, ref.page_to, ref.always_pages) == (10, 10, True)
    # Кусок-вырез не забирает лист себе: страницами его рисует собственный вырез.
    assert ref.pages_shown == []
    bound = session.scalars(
        select(Binding.fragment_id).where(Binding.project_id == project.id)
    ).all()
    assert bound == [book.ids["схема кадра"]]


def test_region_piece_cannot_be_split(session, project):
    book = Book(session, project, "Олифер")
    book.page(10, "h:2.3 Ethernet", "p:схема")
    topic = add_node(session, project, "Ethernet", 0, ranges=[(book, 10, 10)])
    lesson = service.create_manual_lesson(
        session, project.id, LessonManualWrite(program_node_id=topic.id)
    ).lesson
    session.rollback()
    result = editing.edit_lesson_blocks(
        session, project.id, lesson.id,
        LessonBlockWrite(expected_revision=lesson.revision, operation="add_region",
                         material_id=book.material.id, page_from=10,
                         region_bbox=[0.0, 0.0, 1.0, 0.5]),
    )
    block = result.lesson.blocks[0]

    session.rollback()
    with pytest.raises(ProjectDomainError):
        editing.edit_lesson_blocks(
            session, project.id, lesson.id,
            LessonBlockWrite(expected_revision=result.lesson.revision, operation="split",
                             block_id=block.id, split_after_page=10),
        )


# --- прохождение -----------------------------------------------------------------------


def test_position_is_remembered_and_foreign_block_is_refused(session, project):
    book = Book(session, project, "Олифер")
    book.page(10, "h:2.3 Ethernet", "p:кадр")
    topic = add_node(session, project, "Ethernet", 0, ranges=[(book, 10, 10)])
    other = add_node(session, project, "Wi-Fi", 1, ranges=[(book, 10, 10)])
    lesson = service.create_quick_lesson(
        session, project.id, service.LessonQuickWrite(program_node_id=topic.id)
    ).lesson
    session.rollback()
    foreign = service.create_quick_lesson(
        session, project.id, service.LessonQuickWrite(program_node_id=other.id)
    ).lesson

    session.rollback()
    saved = progress.save_position(
        session, project.id, lesson.id, LessonProgressWrite(last_block_id=lesson.blocks[1].id)
    )
    assert saved.lesson.last_block_id == lesson.blocks[1].id
    # Позиция чтения не считается правкой урока: ревизия остаётся прежней.
    assert saved.lesson.revision == lesson.revision

    session.rollback()
    with pytest.raises(ProjectDomainError):
        progress.save_position(
            session, project.id, lesson.id,
            LessonProgressWrite(last_block_id=foreign.blocks[0].id),
        )


def test_completion_writes_one_history_record_and_undoes_it(session, project):
    book = Book(session, project, "Олифер")
    book.page(10, "h:2.3 Ethernet", "p:кадр")
    topic = add_node(session, project, "Ethernet", 0, ranges=[(book, 10, 10)])
    project_id, topic_id = project.id, topic.id
    lesson = service.create_quick_lesson(
        session, project_id, service.LessonQuickWrite(program_node_id=topic.id)
    ).lesson

    session.rollback()
    done = progress.set_completed(session, project_id, lesson.id, LessonCompletionWrite())
    session.rollback()
    # Второе нажатие не плодит вторую строку «Истории».
    progress.set_completed(session, project_id, lesson.id, LessonCompletionWrite())

    assert done.lesson.completed_at is not None
    rows = session.scalars(
        select(StudyActivity).where(StudyActivity.project_id == project_id)
    ).all()
    assert [(row.kind, row.node_id, row.seconds) for row in rows] == [("lesson", topic_id, 0)]

    session.rollback()
    undone = progress.set_completed(
        session, project_id, lesson.id, LessonCompletionWrite(completed=False)
    )
    assert undone.lesson.completed_at is None
    assert session.scalars(
        select(StudyActivity).where(StudyActivity.project_id == project_id)
    ).all() == []


def test_recent_study_lists_only_completed_lessons(session, project):
    topic = add_node(session, project, "Ethernet", 0)
    lesson = service.create_manual_lesson(
        session, project.id, LessonManualWrite(program_node_id=topic.id)
    ).lesson
    session.rollback()
    progress.set_completed(session, project.id, lesson.id, LessonCompletionWrite())

    recent = project_service.list_recent_study(session)

    assert [(item.kind, item.item_id, item.title) for item in recent] == [
        ("lesson", lesson.id, "Ethernet")
    ]


def test_undo_removes_the_added_region(session, project):
    book = Book(session, project, "Олифер")
    book.page(10, "h:2.3 Ethernet", "p:схема")
    topic = add_node(session, project, "Ethernet", 0, ranges=[(book, 10, 10)])
    lesson = service.create_manual_lesson(
        session, project.id, LessonManualWrite(program_node_id=topic.id)
    ).lesson
    session.rollback()
    added = editing.edit_lesson_blocks(
        session, project.id, lesson.id,
        LessonBlockWrite(expected_revision=lesson.revision, operation="add_region",
                         material_id=book.material.id, page_from=10,
                         region_bbox=[0.0, 0.0, 1.0, 0.5]),
    )

    session.rollback()
    undo_last_project_action(session, project.id, added.lesson.undo_sequence)

    session.rollback()
    assert service.get_lesson(session, project.id, lesson.id).blocks == []
    assert session.scalars(select(LessonSourceRef)).all() == []
