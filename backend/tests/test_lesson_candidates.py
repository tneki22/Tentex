"""Кандидаты модельного урока: оглавление, привязки, поиск, дубли и отбор (этап B)."""

import asyncio
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from app.bindings import search as search_module
from app.lessons import candidates
from app.lessons.ai_schemas import LessonPinnedRange
from app.models import (
    Binding,
    BindingMechanism,
    BindingStatus,
    CoverageDecision,
    MaterialFragment,
    PageQuality,
    Project,
    SourceRole,
    utc_now,
)
from app.projects.errors import ProjectDomainError
from app.retrieval.schemas import RetrievalScope, RetrievalSearchWrite
from app.retrieval.search import resolve_scope
from tests.test_lessons import Book, add_node, make_lessons_project


@pytest.fixture
def project(session: Session) -> Project:
    return make_lessons_project(session)


def collect(session, node, *books):
    return asyncio.run(candidates.collect(session, node, [book.material.id for book in books]))


def test_outline_range_gives_block_candidates_in_reading_order(session, project):
    book = Book(session, project, "Олифер")
    book.page(10, "h:2.3 Ethernet", "p:Ethernet передаёт кадры по общей среде.")
    book.page(11, "h:Формат кадра", "p:Кадр начинается преамбулой.")
    node = add_node(session, project, "Ethernet", 0, ranges=[(book, 10, 11)])

    found = collect(session, node, book)

    assert found.has_outline
    assert [item.title for item in found.candidates] == ["2.3 Ethernet", "Формат кадра"]
    first = found.candidates[0]
    assert first.fragment_ids == [book.ids["2.3 Ethernet"], book.ids[
        "Ethernet передаёт кадры по общей среде."]]
    assert "оглавление темы" in first.signals
    assert first.in_outline and first.role == SourceRole.MAIN


def test_binding_inside_outline_adds_signal_instead_of_duplicate(session, project):
    book = Book(session, project, "Олифер")
    book.page(10, "h:2.3 Ethernet", "p:Коллизия — одновременная передача.")
    node = add_node(session, project, "Ethernet", 0, ranges=[(book, 10, 10)])
    now = utc_now()
    session.add(Binding(
        id=uuid4(), project_id=project.id, program_node_id=node.id,
        fragment_id=book.ids["Коллизия — одновременная передача."],
        material_id=book.material.id, block_id=None,
        status=BindingStatus.MANUAL, mechanism=BindingMechanism.MANUAL,
        created_at=now, updated_at=now,
    ))
    session.commit()

    found = collect(session, node, book)

    assert len(found.candidates) == 1
    assert found.candidates[0].signals == ["оглавление темы", "привязка ручная (вручную)"]


def test_topic_without_outline_is_found_by_search(session, project):
    book = Book(session, project, "Конспект")
    book.page(3, "h:Маршрутизация", "p:Протокол OSPF строит карту сети.")
    book.page(4, "h:Коммутация", "p:Коммутатор учит MAC-адреса.")
    search_module.reindex_material(session, book.material.id)
    session.commit()
    node = add_node(session, project, "OSPF", 0)

    found = collect(session, node, book)

    assert not found.has_outline
    assert found.candidates, "поиск по словам должен найти кусок про OSPF"
    assert found.candidates[0].title == "Маршрутизация"
    assert found.candidates[0].signals[0].startswith("поиск")


def test_flags_mark_exercises_low_ocr_and_undescribed_figures(session, project):
    book = Book(session, project, "Олифер")
    book.page(10, "h:2.3 Ethernet", "p:Текст темы")
    book.page(11, "h:Вопросы для самопроверки", "p:Что такое коллизия?",
              quality=PageQuality.OCR_LOW)
    block_id = session.get(MaterialFragment, book.ids["Текст темы"]).block_id
    page_id = session.get(MaterialFragment, book.ids["Текст темы"]).page_id
    session.add(MaterialFragment(
        id=uuid4(), material_id=book.material.id, page_id=page_id, block_id=block_id,
        sort_order=5, text="[Изображение]", bbox=[0, 0, 1, 1], element_kind="image",
        quality=PageQuality.NATIVE, visual={"role": "content", "processing": "unprocessed"},
    ))
    session.commit()
    node = add_node(session, project, "Ethernet", 0, ranges=[(book, 10, 11)])

    found = collect(session, node, book)

    theory, exercises = found.candidates
    assert theory.figures == ["рисунок без описания, стр. 10"]
    assert "[Рисунок без описания, стр. 10" in theory.text
    assert "упражнения" in exercises.flags
    assert any(flag.startswith("OCR низкого качества") for flag in exercises.flags)
    assert exercises.score < theory.score
    header = candidates.header(exercises, "S2")
    assert header.startswith("[S2] Олифер · основной · стр. 11 · «Вопросы для самопроверки»")


def test_large_block_is_split_into_parts(session, project, monkeypatch):
    monkeypatch.setattr(candidates, "PART_TOKENS", 9)
    book = Book(session, project, "Олифер")
    book.page(10, "h:2.3 Ethernet", "p:один два три четыре", "p:пять шесть семь восемь")
    node = add_node(session, project, "Ethernet", 0, ranges=[(book, 10, 10)])

    found = collect(session, node, book)

    assert len(found.candidates) == 2
    assert found.candidates[1].fragment_ids == [book.ids["пять шесть семь восемь"]]


def test_same_text_in_second_material_becomes_also_in(session, project):
    first = Book(session, project, "Олифер")
    first.page(10, "h:2.3 Ethernet", "p:Кадр Ethernet начинается преамбулой.")
    second = Book(session, project, "Методичка", role=SourceRole.ADDITIONAL)
    second.page(5, "h:2.3 Ethernet", "p:Кадр Ethernet начинается преамбулой.")
    node = add_node(session, project, "Ethernet", 0,
                    ranges=[(first, 10, 10), (second, 5, 5)])

    found = collect(session, node, first, second)

    assert len(found.candidates) == 1
    assert found.candidates[0].material_name == "Олифер"
    assert found.candidates[0].also_in == ["Методичка"]


def test_only_content_and_human_bindings_are_topic_support(session, project):
    """Упоминание в оглавлении и привязка самого урока не материал темы (шаг 3.4)."""
    book = Book(session, project, "Афанасьев")
    titles = ["Определение", "Содержание", "Пример", "Заметка", "Скрытое"]
    book.page(3, *(f"h:{title}" for title in titles))
    node = add_node(session, project, "Гарантия", 0)
    now = utc_now()
    made = {}
    for title, status, mechanism, kind in [
        ("Определение", BindingStatus.MACHINE, BindingMechanism.PASS_TWO, "content"),
        ("Содержание", BindingStatus.MACHINE, BindingMechanism.PASS_TWO, "mention"),
        ("Пример", BindingStatus.MACHINE, BindingMechanism.LESSON, None),
        ("Заметка", BindingStatus.MANUAL, BindingMechanism.MANUAL, None),
        ("Скрытое", BindingStatus.MACHINE, BindingMechanism.PASS_TWO, "content"),
    ]:
        made[title] = Binding(
            id=uuid4(), project_id=project.id, program_node_id=node.id,
            fragment_id=book.ids[title], material_id=book.material.id,
            block_id=session.get(MaterialFragment, book.ids[title]).block_id,
            status=status, mechanism=mechanism, semantic_kind=kind,
            created_at=now, updated_at=now,
        )
        session.add(made[title])
    session.add(CoverageDecision(
        project_id=project.id, kind="hide_evidence", target_key=str(made["Скрытое"].id),
        payload={"hidden": True},
    ))
    session.commit()
    kept = ["Определение", "Заметка"]

    found = collect(session, node, book)

    assert {fragment for item in found.candidates for fragment in item.fragment_ids} == {
        book.ids[title] for title in kept
    }
    scope = resolve_scope(session, RetrievalSearchWrite(
        query="Что такое гарантия?", scope=RetrievalScope.LINKED_TOPIC,
        project_id=project.id, node_id=node.id,
    ))
    assert scope.block_ids == sorted((made[title].block_id for title in kept), key=str)


def pin(book, first, last):
    """Кусок, выбранный человеком: от одного фрагмента книги до другого."""
    return LessonPinnedRange(
        material_id=book.material.id, from_fragment_id=book.ids[first],
        to_fragment_id=book.ids[last],
    )


def two_books(session, project):
    main = Book(session, project, "Афанасьев")
    main.page(26, "h:1.13. Совершенные формы", "p:СДНФ строится по таблице истинности.")
    second = Book(session, project, "Игошин", role=SourceRole.ADDITIONAL)
    second.page(45, "h:3.2 Нормальные формы", "p:КНФ — конъюнкция дизъюнкций.")
    second.page(46, "h:Пример", "p:Построим КНФ для импликации.")
    node = add_node(session, project, "СКНФ и СДНФ", 0, ranges=[(main, 26, 26)])
    pins = [
        pin(second, "3.2 Нормальные формы", "КНФ — конъюнкция дизъюнкций."),
        pin(second, "Пример", "Построим КНФ для импликации."),
    ]
    return main, second, node, pins


def test_pinned_pieces_are_first_protected_and_in_book_order(session, project):
    """Выбор человека не вытесняется оглавлением и поиском (шаг 4.1)."""
    main, second, node, pins = two_books(session, project)

    found = asyncio.run(candidates.collect(
        session, node, [main.material.id], pins, pinned_only=False,
    ))

    assert found.pinned == 2 and found.searched and found.has_outline
    titles = [(item.material_name, item.title) for item in found.candidates]
    # Порядок книги: основной материал, затем выбранные куски второго по страницам.
    assert titles == [
        ("Афанасьев", "1.13. Совершенные формы"),
        ("Игошин", "3.2 Нормальные формы"),
        ("Игошин", "Пример"),
    ]
    chosen = found.candidates[1:]
    assert all(item.pinned and item.in_outline for item in chosen)
    assert all(item.signals[0] == candidates.PINNED_SIGNAL for item in chosen)
    assert not found.candidates[0].pinned


def test_pinned_only_builds_from_the_choice_and_skips_outline_and_search(session, project):
    main, second, node, pins = two_books(session, project)

    found = asyncio.run(candidates.collect(session, node, [main.material.id], pins))

    assert not found.has_outline and not found.searched and found.search_notes == []
    assert [item.title for item in found.candidates] == ["3.2 Нормальные формы", "Пример"]
    # Материал выбранных кусков участвует, даже если его не отметили в диалоге.
    assert {item.material_name for item in found.candidates} == {"Игошин"}


def test_pinned_range_must_be_ordered_inside_a_project_material(session, project):
    main, second, node, pins = two_books(session, project)
    outsider = Book(session, make_lessons_project(session), "Чужая")
    outsider.page(1, "h:Чужой раздел", "p:Чужой абзац.")

    def refused(pinned):
        with pytest.raises(ProjectDomainError) as error:
            asyncio.run(candidates.collect(session, node, [main.material.id], pinned))
        assert error.value.status == 422
        return error.value.code

    backwards = pin(second, "Построим КНФ для импликации.", "3.2 Нормальные формы")
    assert refused([backwards]) == "lesson_pinned_range"
    # Начало из одного материала, а материал указан другой: фрагмента там нет.
    mixed = LessonPinnedRange(
        material_id=main.material.id, from_fragment_id=second.ids["Пример"],
        to_fragment_id=second.ids["Построим КНФ для импликации."],
    )
    assert refused([mixed]) == "lesson_pinned_range"
    assert refused([pin(outsider, "Чужой раздел", "Чужой абзац.")]) == "lesson_source_unavailable"
