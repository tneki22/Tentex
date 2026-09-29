"""Куски чтения: опоры темы читаются и выбираются связным отрезком, а не по фрагменту."""

from uuid import UUID, uuid4

from sqlalchemy import select

from app.coverage.interaction import apply_decision, evidence_detail, topic_evidence
from app.coverage.queries import overview
from app.coverage.research import process_coverage_job
from app.coverage.schemas import DecisionWrite
from app.models import (
    Binding,
    BindingMechanism,
    BindingStatus,
    BlockClass,
    MaterialBlock,
    MaterialFragment,
    MaterialPage,
    PageQuality,
)
from app.projects.program import undo_last_project_action
from tests.conftest import link_material, make_material, make_textbook_project, make_topic_node
from tests.test_coverage import answer, launch, setup_source

# Страница → блоки → фрагменты «вид, текст, привязка». Повторяет стр. 26–28 Афанасьева:
# определение с заголовком, свойства на следующей странице, чужой раздел «Способы»,
# алгоритм СДНФ и пример с несвязанной строкой «Решение.» внутри.
LAYOUT = [
    (26, [
        ("1.11. ДНФ", [("paragraph", "Элементарная конъюнкция…", "other")]),
        ("1.13. Совершенные формы", [
            ("heading", "1.13. Совершенные формы", "mention"),
            ("paragraph", "СДНФ формулы — ДНФ со свойствами совершенства.", "definition"),
            ("paragraph", "26", None),
        ]),
    ]),
    (27, [
        ("Свойства совершенства:", [
            ("heading", "Свойства совершенства:", "mention"),
            ("list", "1. Все элементарные конъюнкции различны.", "definition"),
            ("list", "2. Ни одна не содержит переменную с отрицанием.", "definition"),
        ]),
        ("1.14. Способы построения", [
            ("heading", "1.14. Способы построения", None),
            ("paragraph", "Существуют два способа построения.", "other"),
        ]),
        ("СДНФ", [
            ("heading", "СДНФ", "mention"),
            ("list", "1) строим таблицу истинности", "explanation"),
            ("paragraph", "27", None),
        ]),
    ]),
    (28, [
        ("Пример:", [
            ("heading", "Пример:", "mention"),
            ("paragraph", "Записать СДНФ для формулы.", "example"),
            ("paragraph", "Решение.", None),
            ("formula", "$$F = x \\lor y$$", "example"),
        ]),
    ]),
]


def _book(session):
    """Материал по LAYOUT и привязки двух тем: «СКНФ и СДНФ» и соседней."""
    project = make_textbook_project(session)
    topic = make_topic_node(session, project, title="СКНФ и СДНФ")
    other = make_topic_node(session, project, title="Способы построения")
    material = make_material(session, uuid4().hex)
    material.page_count = 3
    link_material(session, project, material)
    fragments = {}
    block_order = 0
    for page_number, blocks in LAYOUT:
        page = MaterialPage(
            id=uuid4(), material_id=material.id, revision=1, page_number=page_number,
            width=100, height=100, quality=PageQuality.NATIVE,
        )
        session.add(page)
        session.flush()
        fragment_order = 0
        for title, items in blocks:
            block = MaterialBlock(
                id=uuid4(), material_id=material.id, revision=1, sort_order=block_order,
                block_class=BlockClass.CONTENT, page_from=page_number, page_to=page_number,
                title=title,
            )
            block_order += 1
            session.add(block)
            session.flush()
            for kind, text, link in items:
                fragment = MaterialFragment(
                    id=uuid4(), material_id=material.id, page_id=page.id, block_id=block.id,
                    sort_order=fragment_order, text=text, bbox=[0, 0, 1, 1],
                    element_kind=kind, quality=PageQuality.NATIVE,
                )
                fragment_order += 1
                session.add(fragment)
                session.flush()
                fragments[text] = fragment
                if link is None:
                    continue
                session.add(Binding(
                    project_id=project.id,
                    program_node_id=other.id if link == "other" else topic.id,
                    fragment_id=fragment.id,
                    material_id=material.id,
                    block_id=block.id,
                    status=BindingStatus.CONFIRMED,
                    mechanism=BindingMechanism.MANUAL,
                    semantic_kind="mention" if link == "mention" else "content",
                    roles=(
                        ["reference"] if link == "mention"
                        else ["explanation"] if link == "other"
                        else [link, "explanation"] if link != "explanation"
                        else ["explanation"]
                    ),
                ))
    session.commit()
    return project, topic, fragments


def _texts(passage, fragments):
    by_id = {str(fragment.id): text for text, fragment in fragments.items()}
    return [by_id[fragment_id] for fragment_id in passage["fragment_ids"]]


def test_adjacent_fragments_become_readable_passages(session):
    project, topic, fragments = _book(session)
    grouped = topic_evidence(session, project.id, topic.id)

    starter, = grouped["starter"]
    assert starter["title"] == "1.13. Совершенные формы"
    assert starter["from_fragment_id"] == str(fragments["1.13. Совершенные формы"].id)
    assert starter["to_fragment_id"] == str(
        fragments["2. Ни одна не содержит переменную с отрицанием."].id
    )
    assert (starter["page_from"], starter["page_to"]) == (26, 27)
    assert starter["fragment_count"] == 3
    assert grouped["best_evidence_id"] == starter["id"]

    algorithm, = grouped["explanations"]
    assert algorithm["title"] == "СДНФ"
    assert _texts(algorithm, fragments) == ["1) строим таблицу истинности"]

    example, = grouped["practice"]
    assert example["title"] == "Пример:"
    assert example["fragment_count"] == 2
    assert example["to_fragment_id"] == str(fragments["$$F = x \\lor y$$"].id)
    assert "26" not in starter["quote"] and "СДНФ формулы" in starter["quote"]
    # Заголовки-упоминания вошли в куски и отдельными карточками не повторяются.
    assert grouped["mentions"] == []


def test_passage_detail_and_decisions_cover_every_binding(session):
    project, topic, fragments = _book(session)
    grouped = topic_evidence(session, project.id, topic.id)
    starter = grouped["starter"][0]
    second = starter["member_ids"][1]

    detail = evidence_detail(session, project.id, second)
    assert detail["id"] == starter["id"]
    assert detail["fragment_count"] == 3
    assert "1. Все элементарные конъюнкции различны." in detail["text"]
    assert "\n26\n" not in f"\n{detail['text']}\n"

    receipt = apply_decision(session, project.id, DecisionWrite(
        request_key=str(uuid4()),
        expected_coverage_revision=grouped["coverage_revision"],
        action="remove",
        binding_ids=starter["binding_ids"],
    ))
    assert receipt["message"] == "Кусок снят с темы."
    statuses = {
        row.status
        for row in session.scalars(
            select(Binding).where(Binding.id.in_([UUID(item) for item in starter["binding_ids"]]))
        )
    }
    assert statuses == {BindingStatus.REMOVED}
    assert topic_evidence(session, project.id, topic.id)["starter"][0]["id"] != starter["id"]

    undo_last_project_action(session, project.id, receipt["action_sequence"])
    assert topic_evidence(session, project.id, topic.id)["starter"][0]["id"] == starter["id"]


def test_passage_http_contract_keeps_ranges_and_members(session):
    from fastapi.testclient import TestClient

    from app.db import get_session
    from app.main import create_app

    project, topic, _ = _book(session)
    app = create_app()
    app.dependency_overrides[get_session] = lambda: session
    client = TestClient(app)
    base = f"/api/projects/{project.id}/coverage"

    grouped = client.get(f"{base}/topics/{topic.id}/evidence")
    assert grouped.status_code == 200
    starter = grouped.json()["starter"][0]
    assert len(starter["binding_ids"]) == 3 and "text" not in starter
    detail = client.get(f"{base}/evidence/{starter['member_ids'][-1]}")
    assert detail.status_code == 200
    assert detail.json()["from_fragment_id"] == starter["from_fragment_id"]
    assert detail.json()["linked_topics"] == []


def test_overview_names_when_each_source_was_researched(session):
    project, topic, material = setup_source(session, 2)
    before = overview(session, project.id)["sources"][0]
    assert before["researched_at"] is None and before["run_state"] is None

    _, job, _, _ = launch(session, project, material)
    process_coverage_job(session, job, lambda task: answer(task, topic.id))
    after = overview(session, project.id)["sources"][0]
    assert after["researched_at"] is not None
    assert after["run_state"] == "completed"
    assert after["distribution"]["pending"] == 0
