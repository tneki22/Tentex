"""7.1: правка программы не обесценивает исследование — устаревает только затронутое."""

from uuid import uuid4

from sqlalchemy import select

from app.coverage.interaction import apply_decision, topic_evidence, topics_page
from app.coverage.queries import fresh_binding_ids, overview, run_read
from app.coverage.research import process_coverage_job
from app.coverage.schemas import DecisionWrite, RunPlan, RunStart
from app.coverage.service import preflight, start_run
from app.coverage.snapshots import runs_currency
from app.materials.worker import claim_job
from app.models import (
    Binding,
    BlockClass,
    CoverageRun,
    GoalPassport,
    GoalPurpose,
    Material,
    MaterialBlock,
    MaterialFragment,
    MaterialPage,
    PageQuality,
)
from tests.conftest import link_material, make_material, make_topic_node
from tests.test_coverage import launch, setup_source


def answer_topics(task_input, topics_by_block):
    """Ответ по блокам: каждый фрагмент — content по всем темам своего блока."""
    result = []
    for index, target in enumerate(task_input.targets):
        units = [u for u in task_input.seen.values() if u.block_id == target]
        topics = topics_by_block[index]
        result.append(
            {
                "target_id": target,
                "outcome": "linked",
                "dispositions": [
                    {"fragment_id": u.ref, "start": 0, "end": len(u.text), "outcome": "content"}
                    for u in units
                ],
                "links": [
                    {
                        "topic_id": str(topic.id),
                        "fragment_id": u.ref,
                        "semantic_kind": "content",
                        "roles": ["explanation"],
                        "evidence": [{"key": f"e{i}_{n}", "ref": u.ref}],
                    }
                    for i, u in enumerate(units)
                    for n, topic in enumerate(topics)
                ],
            }
        )
    return result


def researched(session):
    """Две темы и завершённый запуск: блоки 0–1 про первую, 2 про вторую, 3 про обе."""
    project, first, material = setup_source(session, 4)
    second = make_topic_node(session, project, title="Кванторы")
    plan = [[first], [first], [second], [first, second]]
    _, job, _, _ = launch(session, project, material)
    process_coverage_job(session, job, lambda task: answer_topics(task, plan))
    return project, first, second, material


def pieces(session, project, topic):
    """Куски темы: актуальные (по группам чтения) и ушедшие в «Из уроков и оглавления»."""
    groups = topic_evidence(session, project.id, topic.id)
    names = ("starter", "explanations", "practice", "depth")
    return [item for name in names for item in groups[name]], groups["legacy"]


def readable(session, project):
    items = topics_page(session, project.id, "readable", 0, 10)["items"]
    return {item["node_id"] for item in items}


def test_new_topic_next_to_the_research_makes_nothing_stale(session):
    project, first, second, _ = researched(session)
    before = overview(session, project.id)
    assert before["distribution"]["linked"] == 4 and before["distribution"]["stale"] == 0

    make_topic_node(session, project, title="Хеширование")

    after = overview(session, project.id)
    assert after["distribution"] == before["distribution"]
    assert after["topics"]["with_content"] == 2
    assert readable(session, project) == {str(first.id), str(second.id)}
    for topic in (first, second):
        fresh, legacy = pieces(session, project, topic)
        assert fresh and not legacy


def test_renaming_a_topic_stales_only_its_links_and_the_blocks_that_rested_on_them(session):
    project, first, second, _ = researched(session)

    first.title = "Логические функции"
    session.commit()

    # Куски переименованной темы ушли в «Из уроков и оглавления»; чужие остались на месте.
    fresh_first, legacy_first = pieces(session, project, first)
    assert not fresh_first and legacy_first
    fresh_second, legacy_second = pieces(session, project, second)
    assert fresh_second and not legacy_second
    summary = overview(session, project.id)
    # Блоки 0 и 1 держались на одной теме и устарели; блок 3 ещё стоит на второй теме.
    source = summary["sources"][0]["distribution"]
    assert (source["stale"], source["linked"]) == (2, 2)
    assert summary["topics"]["with_content"] == 1
    assert readable(session, project) == {str(second.id)}


def test_archived_topic_stales_like_a_renamed_one_and_restoring_it_heals(session):
    project, first, _, _ = researched(session)

    first.is_archived = True
    session.commit()
    assert overview(session, project.id)["sources"][0]["distribution"]["stale"] == 2

    first.is_archived = False
    session.commit()
    assert overview(session, project.id)["sources"][0]["distribution"]["stale"] == 0
    assert pieces(session, project, first)[0]


def test_goal_change_does_not_stale_the_research_but_still_stops_the_run(session):
    project, _, _, _ = researched(session)
    before = overview(session, project.id)["distribution"]

    session.add(GoalPassport(project_id=project.id, goal="Сдать зачёт", purpose=GoalPurpose.EXAM))
    session.commit()

    assert overview(session, project.id)["distribution"] == before
    # Возобновить прежний запуск по другой цели нельзя, но прочитанное остаётся верным.
    run_id = session.scalar(select(CoverageRun.id))
    assert run_read(session, project.id, run_id)["stale"]


def test_confirmed_link_is_a_human_decision_and_survives_the_rename(session):
    project, first, _, _ = researched(session)
    grouped = topic_evidence(session, project.id, first.id)
    piece = (grouped["starter"] or grouped["explanations"])[0]
    apply_decision(
        session,
        project.id,
        DecisionWrite(
            request_key="confirm-one",
            expected_coverage_revision=grouped["coverage_revision"],
            action="confirm",
            binding_ids=piece["binding_ids"],
        ),
    )

    first.title = "Логические функции"
    session.commit()

    fresh, _ = pieces(session, project, first)
    kept = {binding for item in fresh for binding in item["binding_ids"]}
    assert kept == set(piece["binding_ids"])


def fresh_materials(session, project):
    """Материалы, чьи связи сейчас читаются как актуальные."""
    live = fresh_binding_ids(session, project.id)
    return {item.material_id for item in session.scalars(select(Binding)) if item.id in live}


def add_source(session, project, blocks):
    """Второй материал проекта: страница и `blocks` блоков по одному фрагменту."""
    material = make_material(session, uuid4().hex)
    link_material(session, project, material)
    page = MaterialPage(
        id=uuid4(), material_id=material.id, revision=1, page_number=1, width=100, height=100,
        quality=PageQuality.NATIVE,
    )
    session.add(page)
    session.flush()
    for index in range(blocks):
        block = MaterialBlock(
            id=uuid4(), material_id=material.id, revision=1, sort_order=index,
            block_class=BlockClass.CONTENT, page_from=1, page_to=1,
        )
        session.add(block)
        session.flush()
        session.add(MaterialFragment(
            id=uuid4(), material_id=material.id, page_id=page.id, block_id=block.id,
            sort_order=index, text=f"Кванторы связывают переменные {index}",
            bbox=[0, 0, 1, 1], element_kind="paragraph", quality=PageQuality.NATIVE,
        ))
    session.commit()
    return material


def test_source_revision_change_stales_only_that_source(session):
    project, first, _, material = researched(session)
    other = add_source(session, project, 2)
    plan = RunPlan(
        material_ids=[material.id, other.id], expected_program_revision=project.program_revision
    )
    command = RunStart(
        **plan.model_dump(), request_key=str(uuid4()),
        preflight_fingerprint=preflight(session, project.id, plan)["fingerprint"],
    )
    # Прошлый запуск завершён: новый встаёт в очередь сразу.
    run_id = start_run(session, project.id, command)
    job = claim_job(session, "test-worker", "ai")
    process_coverage_job(session, job, lambda task: answer_topics(task, [[first]] * 8))
    run = session.get(CoverageRun, run_id)
    assert runs_currency(session, [run])[run.id].stale_sources == frozenset()
    assert fresh_materials(session, project) == {material.id, other.id}

    session.get(Material, other.id).active_parse_revision = 2
    session.commit()

    currency = runs_currency(session, [run])[run.id]
    assert currency.stale_sources == frozenset({str(other.id)})
    # Устарел разбор одного источника: второй и программа остались на месте.
    assert currency.fresh(material.id, first.id) and not currency.fresh(other.id, first.id)
    assert currency.stale_topics == frozenset()
    assert fresh_materials(session, project) == {material.id}
