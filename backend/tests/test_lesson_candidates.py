"""Кандидаты модельного урока: оглавление, привязки, поиск, дубли и отбор (этап B)."""

import asyncio
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from app.bindings import search as search_module
from app.lessons import candidates
from app.models import (
    Binding,
    BindingMechanism,
    BindingStatus,
    MaterialFragment,
    PageQuality,
    Project,
    SourceRole,
    utc_now,
)
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
