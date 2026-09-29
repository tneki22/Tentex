"""Быстрый урок: границы, подпункты, привязки и отмена (записка «Уроки» §4.1, §4.4)."""

from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app import db
from app.config import BACKEND_ROOT, settings
from app.lessons import editing, from_search, service
from app.lessons.from_search import FoundPage, LessonFromSearchWrite
from app.lessons.schemas import (
    LessonBlockWrite,
    LessonManualWrite,
    LessonNoteWrite,
    LessonQuickWrite,
    LessonUpdateWrite,
)
from app.models import (
    Binding,
    BindingMechanism,
    BindingStatus,
    BlockClass,
    Lesson,
    LessonBlockKind,
    LessonStatus,
    Material,
    MaterialBlock,
    MaterialFragment,
    MaterialPage,
    MaterialSourceKind,
    MaterialState,
    NodeType,
    PageQuality,
    ProgramNode,
    ProgramNodeSourcePageRange,
    Project,
    ProjectMaterial,
    SourceRole,
    utc_now,
)
from app.projects.errors import ProjectConflictError, ProjectDomainError
from app.projects.program import undo_last_project_action
from tests.conftest import make_exam_project, make_textbook_project


class Book:
    """Материал из строк вида `h:Заголовок`, `p:абзац`, `s:колонтитул`.

    Заголовок открывает новый содержательный блок, абзац продолжает текущий
    (в том числе на следующей странице), колонтитул — отдельный служебный блок.
    """

    def __init__(
        self,
        session: Session,
        project: Project,
        name: str,
        *,
        role: SourceRole = SourceRole.MAIN,
        priority: int = 0,
        page_count: int = 40,
    ) -> None:
        self.session = session
        self.material = Material(
            id=uuid4(),
            sha256=uuid4().hex + uuid4().hex,
            original_name=name,
            storage_path=f"books/{uuid4().hex}.pdf",
            media_type="application/pdf",
            source_kind=MaterialSourceKind.FILE,
            size_bytes=100,
            page_count=page_count,
            status=MaterialState.READY,
            active_parse_revision=1,
        )
        session.add(self.material)
        session.flush()
        session.add(
            ProjectMaterial(
                project_id=project.id,
                material_id=self.material.id,
                source_role=role,
                priority=priority,
            )
        )
        self.block: MaterialBlock | None = None
        self.block_order = 0
        self.revision = 1
        self.ids: dict[str, UUID] = {}
        session.commit()

    def _new_block(self, page: int, block_class: BlockClass, title: str | None) -> MaterialBlock:
        block = MaterialBlock(
            id=uuid4(),
            material_id=self.material.id,
            revision=self.revision,
            sort_order=self.block_order,
            title=title,
            block_class=block_class,
            page_from=page,
            page_to=page,
        )
        self.block_order += 1
        self.session.add(block)
        self.session.flush()
        return block

    def page(self, number: int, *lines: str, quality: PageQuality = PageQuality.NATIVE) -> None:
        page = MaterialPage(
            id=uuid4(),
            material_id=self.material.id,
            revision=self.revision,
            page_number=number,
            width=595,
            height=842,
            quality=quality,
        )
        self.session.add(page)
        self.session.flush()
        for order, line in enumerate(lines):
            kind, text = line.split(":", 1)
            if kind == "s":
                block = self._new_block(number, BlockClass.SERVICE, None)
            elif kind == "h" or self.block is None:
                self.block = self._new_block(number, BlockClass.CONTENT, text)
                block = self.block
            else:
                block = self.block
                block.page_to = number
            fragment = MaterialFragment(
                id=uuid4(),
                material_id=self.material.id,
                page_id=page.id,
                block_id=block.id,
                sort_order=order,
                text=text,
                bbox=[0, 0, 1, 1],
                element_kind="heading" if kind == "h" else "paragraph",
                structure_level=1 if kind == "h" else None,
                quality=quality,
            )
            self.session.add(fragment)
            self.ids[text] = fragment.id
        self.session.commit()


def make_lessons_project(session: Session) -> Project:
    project = make_textbook_project(session)
    project.enabled_modules = ["lessons"]
    session.commit()
    return project


def add_node(
    session: Session,
    project: Project,
    title: str,
    order: int,
    *,
    parent: ProgramNode | None = None,
    ranges: list[tuple[Book, int, int]] = (),
) -> ProgramNode:
    node = ProgramNode(
        id=uuid4(),
        project_id=project.id,
        parent_id=parent.id if parent else None,
        node_type=NodeType.SUBPOINT if parent else NodeType.TOPIC,
        sort_order=order,
        title=title,
    )
    session.add(node)
    session.flush()
    for book, page_from, page_to in ranges:
        session.add(
            ProgramNodeSourcePageRange(
                project_id=project.id,
                program_node_id=node.id,
                material_id=book.material.id,
                source_name_snapshot=book.material.original_name,
                outline_item_key=f"{title}-{page_from}",
                page_from=page_from,
                page_to=page_to,
            )
        )
    session.commit()
    return node


def quick(session: Session, project: Project, node: ProgramNode, materials=None):
    return service.create_quick_lesson(
        session, project.id, LessonQuickWrite(program_node_id=node.id, material_ids=materials)
    )


def source_refs(result):
    return [block.refs[0] for block in result.lesson.blocks if block.kind == LessonBlockKind.SOURCE]


@pytest.fixture
def project(session: Session) -> Project:
    return make_lessons_project(session)


def test_next_item_from_middle_of_page_extends_topic_to_text_before_heading(session, project):
    book = Book(session, project, "Олифер")
    book.page(10, "p:хвост 2.2", "h:2.3 Ethernet", "p:Ethernet использует кадры")
    book.page(11, "s:Колонтитул 11", "p:хвост Ethernet", "h:2.4 Wi-Fi", "p:Wi-Fi текст")
    ethernet = add_node(session, project, "Ethernet", 0, ranges=[(book, 10, 10)])
    add_node(session, project, "Wi-Fi", 1, ranges=[(book, 11, 12)])

    [ref] = source_refs(quick(session, project, ethernet))

    assert (ref.page_from, ref.page_to) == (10, 11)
    assert ref.from_fragment_id == book.ids["2.3 Ethernet"]
    assert ref.to_fragment_id == book.ids["хвост Ethernet"]


def test_next_item_from_top_of_page_keeps_outline_end(session, project):
    book = Book(session, project, "Олифер")
    book.page(10, "h:2.3 Ethernet", "p:текст")
    book.page(11, "s:Колонтитул", "h:2.4 Wi-Fi", "p:Wi-Fi текст")
    ethernet = add_node(session, project, "Ethernet", 0, ranges=[(book, 10, 10)])
    add_node(session, project, "Wi-Fi", 1, ranges=[(book, 11, 12)])

    [ref] = source_refs(quick(session, project, ethernet))

    assert (ref.page_from, ref.page_to, ref.to_fragment_id) == (10, 10, None)


def test_unparsed_boundary_page_is_added_whole(session, project):
    book = Book(session, project, "Олифер")
    book.page(10, "h:2.3 Ethernet", "p:текст")
    ethernet = add_node(session, project, "Ethernet", 0, ranges=[(book, 10, 10)])
    add_node(session, project, "Wi-Fi", 1, ranges=[(book, 11, 12)])

    [ref] = source_refs(quick(session, project, ethernet))

    assert (ref.page_from, ref.page_to, ref.to_fragment_id) == (10, 11, None)


def test_last_topic_of_material_is_not_extended(session, project):
    book = Book(session, project, "Олифер")
    book.page(10, "h:2.3 Ethernet", "p:текст")
    book.page(11, "p:ещё текст")
    ethernet = add_node(session, project, "Ethernet", 0, ranges=[(book, 10, 10)])

    [ref] = source_refs(quick(session, project, ethernet))

    assert (ref.page_from, ref.page_to) == (10, 10)


def test_next_item_on_start_page_cuts_the_same_page(session, project):
    book = Book(session, project, "Олифер")
    book.page(10, "p:хвост прошлой темы", "h:2.3 Ethernet", "p:кратко", "h:2.4 Wi-Fi", "p:w")
    ethernet = add_node(session, project, "Ethernet", 0, ranges=[(book, 10, 10)])
    add_node(session, project, "Wi-Fi", 1, ranges=[(book, 10, 12)])

    [ref] = source_refs(quick(session, project, ethernet))

    assert (ref.page_from, ref.page_to) == (10, 10)
    assert ref.from_fragment_id == book.ids["2.3 Ethernet"]
    assert ref.to_fragment_id == book.ids["кратко"]


def test_start_without_matching_heading_takes_page_from_top(session, project):
    book = Book(session, project, "Олифер")
    book.page(10, "p:хвост", "h:Совсем другой заголовок", "p:текст")
    topic = add_node(session, project, "Переименованная тема", 0, ranges=[(book, 10, 10)])

    [ref] = source_refs(quick(session, project, topic))

    assert ref.from_fragment_id is None


def test_subpoints_cut_by_headings_and_add_heading_notes(session, project):
    book = Book(session, project, "Олифер")
    book.page(10, "h:2.3 Ethernet", "p:введение")
    book.page(11, "p:введение дальше", "h:2.3.1 Формат кадра", "p:кадр")
    book.page(12, "h:2.3.2 CSMA/CD", "p:коллизии", "h:2.3.3 Дуплекс", "p:дуплекс")
    ethernet = add_node(session, project, "Ethernet", 0, ranges=[(book, 10, 12)])
    add_node(session, project, "Формат кадра", 0, parent=ethernet, ranges=[(book, 11, 11)])
    add_node(session, project, "CSMA/CD", 1, parent=ethernet, ranges=[(book, 12, 12)])
    add_node(session, project, "Дуплекс", 2, parent=ethernet, ranges=[(book, 12, 12)])

    result = quick(session, project, ethernet)

    kinds = [(block.kind, block.body_md) for block in result.lesson.blocks]
    assert kinds == [
        (LessonBlockKind.NOTE, "## Ethernet"),
        (LessonBlockKind.SOURCE, None),
        (LessonBlockKind.NOTE, "### Формат кадра"),
        (LessonBlockKind.SOURCE, None),
        (LessonBlockKind.NOTE, "### CSMA/CD"),
        (LessonBlockKind.SOURCE, None),
        (LessonBlockKind.NOTE, "### Дуплекс"),
        (LessonBlockKind.SOURCE, None),
    ]
    intro, frame, csma, duplex = source_refs(result)
    assert (intro.page_from, intro.page_to, intro.to_fragment_id) == (
        10,
        11,
        book.ids["введение дальше"],
    )
    assert (frame.from_fragment_id, frame.page_to, frame.to_fragment_id) == (
        book.ids["2.3.1 Формат кадра"],
        11,
        None,
    )
    assert (csma.page_from, csma.to_fragment_id) == (12, book.ids["коллизии"])
    assert (duplex.from_fragment_id, duplex.page_to) == (book.ids["2.3.3 Дуплекс"], 12)
    assert result.lesson.status == LessonStatus.DRAFT
    assert result.lesson.undo_sequence is not None


def test_subpoint_range_outside_topic_is_ignored(session, project):
    book = Book(session, project, "Олифер")
    book.page(10, "h:2.3 Ethernet", "p:введение")
    ethernet = add_node(session, project, "Ethernet", 0, ranges=[(book, 10, 10)])
    add_node(session, project, "MAC-адреса", 0, parent=ethernet, ranges=[(book, 3, 3)])

    result = quick(session, project, ethernet)

    assert [block.kind for block in result.lesson.blocks] == [
        LessonBlockKind.NOTE,
        LessonBlockKind.SOURCE,
    ]


def test_from_sources_orders_main_then_additional_and_skips_reference_by_default(
    session, project
):
    extra = Book(session, project, "Методичка", role=SourceRole.ADDITIONAL)
    main = Book(session, project, "Олифер", role=SourceRole.MAIN)
    ref = Book(session, project, "Конспект", role=SourceRole.REFERENCE)
    for book in (extra, main, ref):
        book.page(5, "h:Ethernet", f"p:{book.material.original_name}")
    topic = add_node(
        session, project, "Ethernet", 0, ranges=[(extra, 5, 5), (main, 5, 5), (ref, 5, 5)]
    )

    sources = service.topic_sources(session, project.id, topic.id)
    assert [(item.source_name, item.default_selected) for item in sources.ranges] == [
        ("Олифер", True),
        ("Методичка", True),
        ("Конспект", False),
    ]
    selected = [item.material_id for item in sources.ranges if item.default_selected]
    project_id, topic_id = project.id, topic.id
    session.rollback()
    result = service.create_quick_lesson(
        session,
        project_id,
        LessonQuickWrite(program_node_id=topic_id, material_ids=list(reversed(selected))),
    )

    assert [item.material_id for item in source_refs(result)] == [
        main.material.id,
        extra.material.id,
    ]


def test_quick_lesson_bindings_respect_existing_status_and_skip_service(session, project):
    book = Book(session, project, "Олифер")
    book.page(10, "s:Колонтитул", "h:Ethernet", "p:первый", "p:второй")
    topic = add_node(session, project, "Ethernet", 0, ranges=[(book, 10, 10)])
    now = utc_now()
    for text, status in (("первый", BindingStatus.REMOVED), ("второй", BindingStatus.MANUAL)):
        session.add(
            Binding(
                project_id=project.id,
                program_node_id=topic.id,
                fragment_id=book.ids[text],
                material_id=book.material.id,
                status=status,
                mechanism=BindingMechanism.MANUAL,
                created_at=now,
                updated_at=now,
            )
        )
    session.commit()

    quick(session, project, topic)
    quick(session, project, topic)

    bindings = {
        binding.fragment_id: binding
        for binding in session.scalars(select(Binding).where(Binding.program_node_id == topic.id))
    }
    assert len(bindings) == 3
    assert book.ids["Колонтитул"] not in bindings
    assert bindings[book.ids["первый"]].status == BindingStatus.REMOVED
    assert bindings[book.ids["второй"]].status == BindingStatus.MANUAL
    heading = bindings[book.ids["Ethernet"]]
    assert (heading.status, heading.mechanism) == (BindingStatus.MACHINE, BindingMechanism.OUTLINE)


def test_undo_lesson_create_removes_lesson_and_only_its_bindings(session, project):
    book = Book(session, project, "Олифер")
    book.page(10, "h:Ethernet", "p:первый")
    topic = add_node(session, project, "Ethernet", 0, ranges=[(book, 10, 10)])
    session.add(
        Binding(
            project_id=project.id,
            program_node_id=topic.id,
            fragment_id=book.ids["первый"],
            material_id=book.material.id,
            status=BindingStatus.MANUAL,
            mechanism=BindingMechanism.MANUAL,
        )
    )
    session.commit()
    result = quick(session, project, topic)

    undo_last_project_action(session, project.id, result.lesson.undo_sequence)

    assert session.get(Lesson, result.lesson.id) is None
    remaining = list(session.scalars(select(Binding.fragment_id)))
    assert remaining == [book.ids["первый"]]


def test_update_lesson_checks_revision(session, project):
    book = Book(session, project, "Олифер")
    book.page(10, "h:Ethernet", "p:первый")
    topic = add_node(session, project, "Ethernet", 0, ranges=[(book, 10, 10)])
    lesson = quick(session, project, topic).lesson
    assert service.lessons_overview(session, project.id).lessons[0].creation_type == "quick"
    session.get(Lesson, lesson.id).build_meta = None
    session.flush()
    assert service.lessons_overview(session, project.id).lessons[0].creation_type == "quick"

    updated = service.update_lesson(
        session,
        project.id,
        lesson.id,
        LessonUpdateWrite(title="Ethernet кратко", status=LessonStatus.READY, expected_revision=1),
    ).lesson
    assert (updated.title, updated.status, updated.revision) == (
        "Ethernet кратко",
        LessonStatus.READY,
        2,
    )
    with pytest.raises(ProjectConflictError):
        service.update_lesson(
            session, project.id, lesson.id, LessonUpdateWrite(title="x", expected_revision=1)
        )


def test_manual_lesson_page_binding_and_undo(session, project):
    book = Book(session, project, "Методичка")
    book.page(4, "h:Тема", "p:содержательное", "s:колонтитул")
    topic = add_node(session, project, "Тема", 0)
    session.add(Binding(
        project_id=project.id, program_node_id=topic.id,
        fragment_id=book.ids["содержательное"], material_id=book.material.id,
        status=BindingStatus.REMOVED, mechanism=BindingMechanism.MANUAL,
    ))
    session.commit()
    lesson = service.create_manual_lesson(
        session, project.id, LessonManualWrite(program_node_id=topic.id)
    ).lesson
    assert lesson.blocks == []
    assert service.lessons_overview(session, project.id).lessons[0].creation_type == "manual"
    added = editing.edit_lesson_blocks(session, project.id, lesson.id, LessonBlockWrite(
        expected_revision=1, operation="add_page", material_id=book.material.id, page_from=4,
    )).lesson
    assert added.blocks[0].refs[0].page_from == 4
    bindings = list(session.scalars(select(Binding).where(Binding.project_id == project.id)))
    assert {(item.fragment_id, item.status) for item in bindings} == {
        (book.ids["содержательное"], BindingStatus.REMOVED),
        (book.ids["Тема"], BindingStatus.MANUAL),
    }
    project_id = project.id
    lesson_id = lesson.id
    sequence = added.undo_sequence
    session.rollback()
    undo_last_project_action(session, project_id, sequence)
    assert service.get_lesson(session, project_id, lesson_id).blocks == []
    assert {item.fragment_id for item in session.scalars(select(Binding))} == {
        book.ids["содержательное"]
    }


def test_move_undo_keeps_note_text_saved_after_move(session, project):
    topic = add_node(session, project, "Тема", 0)
    lesson = service.create_manual_lesson(
        session, project.id, LessonManualWrite(program_node_id=topic.id)
    ).lesson
    first = editing.edit_lesson_blocks(session, project.id, lesson.id, LessonBlockWrite(
        expected_revision=1, operation="add_note",
    )).lesson
    second = editing.edit_lesson_blocks(session, project.id, lesson.id, LessonBlockWrite(
        expected_revision=first.revision, operation="add_note",
    )).lesson
    moved = editing.edit_lesson_blocks(session, project.id, lesson.id, LessonBlockWrite(
        expected_revision=second.revision, operation="move_up", block_id=second.blocks[1].id,
    )).lesson
    editing.update_lesson_note(session, project.id, lesson.id, second.blocks[0].id,
        LessonNoteWrite(expected_revision=moved.revision, body_md="Пояснение после перемещения"))
    undo_last_project_action(session, project.id, moved.undo_sequence)
    restored = service.get_lesson(session, project.id, lesson.id)
    assert [block.id for block in restored.blocks] == [item.id for item in second.blocks]
    assert restored.blocks[0].body_md == "Пояснение после перемещения"


def test_delete_undo_restores_source_ref(session, project):
    book = Book(session, project, "Учебник")
    book.page(8, "h:Тема", "p:текст")
    topic = add_node(session, project, "Тема", 0)
    lesson = service.create_manual_lesson(
        session, project.id, LessonManualWrite(program_node_id=topic.id)
    ).lesson
    added = editing.edit_lesson_blocks(session, project.id, lesson.id, LessonBlockWrite(
        expected_revision=1, operation="add_page", material_id=book.material.id, page_from=8,
    )).lesson
    deleted = editing.edit_lesson_blocks(session, project.id, lesson.id, LessonBlockWrite(
        expected_revision=added.revision, operation="delete", block_id=added.blocks[0].id,
    )).lesson
    assert deleted.blocks == []
    undo_last_project_action(session, project.id, deleted.undo_sequence)
    restored = service.get_lesson(session, project.id, lesson.id)
    assert restored.blocks[0].id == added.blocks[0].id
    assert restored.blocks[0].refs[0].material_id == book.material.id


def test_topic_without_ranges_and_exam_project_are_refused(session, project):
    topic = add_node(session, project, "Своя тема", 0)
    with pytest.raises(ProjectConflictError) as no_ranges:
        quick(session, project, topic)
    assert no_ranges.value.code == "lesson_no_ranges"
    session.rollback()

    exam = make_exam_project(session)
    with pytest.raises(ProjectConflictError) as exam_error:
        service.lessons_overview(session, exam.id)
    assert exam_error.value.code == "lessons_unavailable"


def test_alembic_check_is_clean_on_fresh_database(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    engine = create_engine(f"sqlite+pysqlite:///{settings.database_path}")
    monkeypatch.setattr(db, "engine", engine)
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "migrations"))
    command.upgrade(config, "head")
    command.check(config)
    engine.dispose()


def test_lesson_from_search_creates_draft_with_pages_in_order_and_one_undo(session, project):
    book = Book(session, project, "Статья")
    book.page(3, "h:Свёртка", "p:ядро скользит по изображению")
    book.page(7, "h:Пулинг", "p:уменьшает карту признаков")
    topic = add_node(session, project, "Операция свёртки", 0)

    result = from_search.create_lesson_from_search(session, project.id, LessonFromSearchWrite(
        program_node_id=topic.id,
        pages=[
            FoundPage(material_id=book.material.id, page=7),
            FoundPage(material_id=book.material.id, page=3),
            FoundPage(material_id=book.material.id, page=7),
        ],
    ))

    lesson = result.lesson
    assert lesson.status == LessonStatus.DRAFT
    assert [block.refs[0].page_from for block in lesson.blocks] == [7, 3]
    bindings = list(session.scalars(select(Binding).where(Binding.program_node_id == topic.id)))
    assert bindings and {item.status for item in bindings} == {BindingStatus.MANUAL}

    assert result.latest_undoable_action is not None
    project_id, lesson_id = project.id, lesson.id
    sequence = result.latest_undoable_action.sequence
    session.rollback()
    undo_last_project_action(session, project_id, sequence)
    assert session.get(Lesson, lesson_id) is None
    assert list(session.scalars(select(Binding).where(Binding.project_id == project_id))) == []


def test_lesson_from_search_appends_to_existing_lesson(session, project):
    book = Book(session, project, "Статья")
    book.page(2, "h:Введение", "p:о чём урок")
    topic = add_node(session, project, "Тема", 0)
    lesson = service.create_manual_lesson(
        session, project.id, LessonManualWrite(program_node_id=topic.id)
    ).lesson
    note = editing.edit_lesson_blocks(session, project.id, lesson.id, LessonBlockWrite(
        expected_revision=1, operation="add_note",
    )).lesson

    appended = from_search.create_lesson_from_search(session, project.id, LessonFromSearchWrite(
        program_node_id=topic.id, lesson_id=lesson.id, expected_revision=note.revision,
        pages=[FoundPage(material_id=book.material.id, page=2)],
    )).lesson

    kinds = [block.kind for block in appended.blocks]
    assert kinds == [LessonBlockKind.NOTE, LessonBlockKind.SOURCE]
    assert appended.revision == note.revision + 1
    with pytest.raises(ProjectConflictError):
        from_search.create_lesson_from_search(session, project.id, LessonFromSearchWrite(
            program_node_id=topic.id, lesson_id=lesson.id, expected_revision=note.revision,
            pages=[FoundPage(material_id=book.material.id, page=2)],
        ))


def test_lesson_from_search_rejects_material_outside_project(session, project):
    topic = add_node(session, project, "Тема", 0)
    other = make_lessons_project(session)
    stranger = Book(session, other, "Чужая книга")
    stranger.page(1, "h:Глава", "p:текст")

    with pytest.raises(ProjectDomainError):
        from_search.create_lesson_from_search(session, project.id, LessonFromSearchWrite(
            program_node_id=topic.id, pages=[FoundPage(material_id=stranger.material.id, page=1)],
        ))
    assert list(session.scalars(select(Lesson).where(Lesson.project_id == project.id))) == []
