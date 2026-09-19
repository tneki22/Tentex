"""И2: инварианты публикации и restart без реального провайдера."""

from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.bindings.service import remove_binding
from app.coverage.budget import ResearchBudget, budget_usage
from app.coverage.lifecycle import ExecutionToken, control_run, stop_core
from app.coverage.packets import (
    OUTPUT_RESERVE_TOKENS,
    build_packet_specs,
    output_reserve_tokens,
)
from app.coverage.protocol import SYSTEM_RULES, expand_compact_response
from app.coverage.queries import evidence_read, overview, run_read
from app.coverage.research import prepare_task, process_coverage_job, publish_packet
from app.coverage.schemas import Evidence, RunControl, RunPlan, RunStart
from app.coverage.service import preflight, start_run
from app.coverage.validation import (
    CheckedDecision,
    Unit,
    merge_refinement,
    repair_evidence,
    validate_target,
)
from app.db import job_write_transaction
from app.materials.worker import claim_job
from app.models import (
    BackgroundJob,
    BackgroundJobState,
    Binding,
    BindingMechanism,
    BindingStatus,
    BlockClass,
    CoverageBlockResult,
    CoverageDecision,
    CoverageRun,
    CoverageTask,
    MaterialBlock,
    MaterialFragment,
    MaterialPage,
    PageQuality,
    Project,
    utc_now,
)
from app.projects.errors import ProjectConflictError, ProjectNotFoundError
from tests.conftest import link_material, make_material, make_textbook_project, make_topic_node


def setup_source(session, count=3):
    project = make_textbook_project(session)
    topic = make_topic_node(session, project, title="Потоки")
    material = make_material(session, uuid4().hex)
    link_material(session, project, material)
    page = MaterialPage(
        id=uuid4(),
        material_id=material.id,
        revision=1,
        page_number=1,
        width=100,
        height=100,
        quality=PageQuality.NATIVE,
    )
    session.add(page)
    session.flush()
    for index in range(count):
        block = MaterialBlock(
            id=uuid4(),
            material_id=material.id,
            revision=1,
            sort_order=index,
            block_class=BlockClass.CONTENT,
            page_from=1,
            page_to=1,
        )
        session.add(block)
        session.flush()
        session.add(
            MaterialFragment(
                id=uuid4(),
                material_id=material.id,
                page_id=page.id,
                block_id=block.id,
                sort_order=index,
                text=f"Потоки выполняют задачи {index}",
                bbox=[0, 0, 1, 1],
                element_kind="paragraph",
                quality=PageQuality.NATIVE,
            )
        )
    session.commit()
    return project, topic, material


def launch(session, project, material, **kwargs):
    plan = RunPlan(
        material_ids=[material.id], expected_program_revision=project.program_revision, **kwargs
    )
    command = RunStart(
        **plan.model_dump(),
        request_key=str(uuid4()),
        preflight_fingerprint=preflight(session, project.id, plan)["fingerprint"],
    )
    run_id = start_run(session, project.id, command)
    job = claim_job(session, "test-worker", "ai")
    assert job is not None
    token = ExecutionToken(run_id, job.checkpoint["coverage_generation"], job.lease_owner)
    return run_id, job, token, command


def answer(task_input, topic_id):
    result = []
    for target in task_input.targets:
        units = [u for u in task_input.seen.values() if u.block_id == target]
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
                        "topic_id": str(topic_id),
                        "fragment_id": u.ref,
                        "semantic_kind": "content",
                        "roles": ["explanation"],
                        "evidence": [{"key": f"e{i}", "ref": u.ref}],
                    }
                    for i, u in enumerate(units)
                ],
            }
        )
    return result


def first_task(session, run_id):
    return session.scalar(
        select(CoverageTask).where(CoverageTask.run_id == run_id).order_by(CoverageTask.task_key)
    )


def test_100_blocks_error_missing_pause_restart_and_receipts(session):
    project, topic, material = setup_source(session, 100)
    run_id, job, token, command = launch(session, project, material)
    first = True
    calls = 0

    def executor(task_input):
        nonlocal first, calls
        calls += 1
        response = answer(task_input, topic.id)
        if first:
            first = False
            response[0]["links"][0]["roles"] = ["несуществующая_роль"]
            response.pop()
            control_run(
                session,
                project.id,
                run_id,
                RunControl(action="pause", expected_generation=token.generation),
            )
        return response

    process_coverage_job(session, job, executor)
    paused = run_read(session, project.id, run_id)
    assert paused["state"] == "paused"
    assert paused["primary"]["inspected"] == 0
    assert calls == 1
    assert start_run(session, project.id, command) == run_id
    engine = session.get_bind()
    # Новая SQL-сессия и новый owner имитируют полную потерю памяти worker.
    session.commit()
    with Session(engine, expire_on_commit=False) as restarted:
        control_run(
            restarted,
            project.id,
            run_id,
            RunControl(action="resume", expected_generation=token.generation),
        )
        next_job = claim_job(restarted, "restarted", "ai")
        process_coverage_job(restarted, next_job, executor)
        result = run_read(restarted, project.id, run_id)
        assert result["state"] == "completed"
        assert result["primary"] == {
            "total": 100,
            "inspected": 100,
            "error": 0,
            "pending": 0,
            "processing": 0,
        }
        assert restarted.get(BackgroundJob, job.id).done == 100
        assert sum(result["outcomes"].values()) + result["primary"]["error"] == 100
        assert calls == 7  # Сохранённый первый пакет не вызывает executor повторно.
        assert restarted.scalar(select(func.count()).select_from(Binding)) == 98
        assert sum(overview(restarted, project.id)["distribution"].values()) == 100


def test_abandoned_run_leaves_blocks_pending_not_stale(session):
    """Брошенный запуск не делает нерассмотренный блок устаревшим.

    Иначе подключённый учебник, по которому обзор ни разу не доходил до модели,
    целиком уезжает в «устарели» и вытесняет настоящие проблемы из ленты.
    """
    project, topic, material = setup_source(session, 3)
    launch(session, project, material)
    topic.title = "Другой смысл"
    session.commit()
    distribution = overview(session, project.id)["distribution"]
    assert distribution["pending"] == 3 and distribution["stale"] == 0


def test_limits_are_derived_from_packets_and_name_the_exhausted_one(session):
    """Плоский предел не знает размера книги; исчерпанный предел называется явно."""
    project, _, material = setup_source(session, 20)
    run_id, _, token, _ = launch(session, project, material)
    run = session.get(CoverageRun, run_id)
    packets = session.scalar(
        select(func.count()).select_from(CoverageTask).where(CoverageTask.run_id == run_id)
    )
    assert run.limits["max_calls"] == packets * 3 + 1
    assert run.limits["max_total_tokens"] > packets * OUTPUT_RESERVE_TOKENS
    assert run.limits["max_cost_usd"] is None
    run.limits = {**run.limits, "max_total_tokens": 10}
    session.commit()
    with pytest.raises(ProjectConflictError) as error:
        ResearchBudget(session, token, first_task(session, run_id).id).reserve(11, None)
    assert error.value.context["limit"] == "tokens"


def test_resume_raises_limits_so_continuation_is_not_a_dead_button(session):
    """Продолжение с прежним потолком встаёт на первом же вызове."""
    project, _, material = setup_source(session)
    run_id, job, token, _ = launch(session, project, material)
    # claim_job отдаёт отсоединённый объект: паузу пишем по строке этой сессии.
    with job_write_transaction(session):
        stop_core(
            session.get(CoverageRun, run_id),
            session.get(BackgroundJob, job.id),
            BackgroundJobState.PAUSED,
            "budget_tokens",
        )
    control_run(
        session,
        project.id,
        run_id,
        RunControl(
            action="resume",
            expected_generation=token.generation,
            limits={"max_total_tokens": 2_000_000},
        ),
    )
    run = session.get(CoverageRun, run_id)
    assert run.limits["max_total_tokens"] == 2_000_000
    assert run.stop_reason is None
    assert session.get(BackgroundJob, job.id).state == BackgroundJobState.QUEUED


def test_unknown_topic_is_reported_and_own_uuid_still_resolves(session):
    """Потерянная связь превращала разобранный блок в «link_accounting» без причины."""
    project, topic, material = setup_source(session, 1)
    run_id, _, token, _ = launch(session, project, material)
    task_input = prepare_task(session, token, first_task(session, run_id).id)
    alias = task_input.target_aliases[task_input.targets[0]]
    fragment = task_input.fragment_aliases[task_input.target_refs[task_input.targets[0]][0]]

    def packet(topic_value):
        return [{
            "from_target": alias,
            "to_target": alias,
            "outcome": "linked",
            "parts": [{
                "fragment": fragment,
                "outcome": "content",
                "links": [{
                    "topic": topic_value,
                    "semantic_kind": "content",
                    "roles": ["explanation"],
                    "evidence": [fragment],
                }],
            }],
        }]

    raw = expand_compact_response(task_input, packet("T404"))
    assert raw[0]["error"] == "unknown_topic"
    publish_packet(session, token, task_input, raw)
    assert session.scalar(select(CoverageBlockResult)).reason == "invalid_decision:unknown_topic"
    by_uuid = expand_compact_response(task_input, packet(str(topic.id)))[0]
    assert by_uuid["links"][0]["topic_id"] == str(topic.id)
    # К концу книги модель адресует тему заголовком: однозначное название тоже принимается.
    by_title = expand_compact_response(task_input, packet(f"  {topic.title.upper()} "))[0]
    assert by_title["links"][0]["topic_id"] == str(topic.id)


def test_fragment_range_is_expanded_and_missing_parts_have_their_own_reason(session):
    """Живой прогон: 14 блоков потеряны на «F2-F6», ещё 38 — на linked без parts."""
    project, topic, material = setup_source(session, 1)
    block = session.scalar(select(MaterialBlock).where(MaterialBlock.material_id == material.id))
    page_id = session.scalar(select(MaterialPage.id).where(MaterialPage.material_id == material.id))
    for index in range(1, 4):
        session.add(
            MaterialFragment(
                id=uuid4(),
                material_id=material.id,
                page_id=page_id,
                block_id=block.id,
                sort_order=index,
                text=f"Потоки выполняют задачи дополнительно {index}",
                bbox=[0, 0, 1, 1],
                element_kind="paragraph",
                quality=PageQuality.NATIVE,
            )
        )
    session.commit()
    run_id, _, token, _ = launch(session, project, material)
    task_input = prepare_task(session, token, first_task(session, run_id).id)
    target = task_input.targets[0]
    alias = task_input.target_aliases[target]
    refs = task_input.target_refs[target]
    aliases = [task_input.fragment_aliases[ref] for ref in refs]
    assert len(aliases) == 4

    def packet(parts):
        return [
            {"from_target": alias, "to_target": alias, "outcome": "linked", "parts": parts}
        ]

    link = {
        "topic": task_input.topic_aliases[str(topic.id)][0],
        "semantic_kind": "content",
        "roles": ["explanation"],
        "evidence": [],
    }
    # Сжатая запись покрывает все четыре фрагмента и раскрывается до отдельных строк.
    compact = f"{aliases[0]}–{aliases[2]},{aliases[3]}"
    raw = expand_compact_response(
        task_input, packet([{"fragment": compact, "outcome": "content", "links": [link]}])
    )
    assert "error" not in raw[0]
    assert [d["fragment_id"] for d in raw[0]["dispositions"]] == refs

    empty = expand_compact_response(task_input, packet([]))
    assert empty[0]["error"] == "parts_missing"

    # Вместо F-alias модель присылает фразу: связь остаётся, опорой служит свой фрагмент.
    prose = {**link, "evidence": ["Оглавление указывает предмет экономики."]}
    raw = expand_compact_response(
        task_input,
        packet([{"fragment": a, "outcome": "content", "links": [prose]} for a in aliases]),
    )
    assert [e["ref"] for e in raw[0]["links"][0]["evidence"]] == [refs[0]]
    checked = validate_target(
        target,
        [raw[0]],
        {ref: task_input.seen[ref] for ref in refs},
        task_input.seen,
        set(refs),
        task_input.topics,
    )
    assert checked.valid and checked.outcome == "linked"


def test_heading_link_is_dropped_without_losing_the_body_of_the_block():
    """Ведущий заголовок раздела уносил разом все верные связи его абзацев."""
    topic, block = str(uuid4()), str(uuid4())
    head_ref, body_ref = str(uuid4()), str(uuid4())
    units = {
        head_ref: Unit(head_ref, "Спрос, закон спроса", block, "page:1", kind="heading"),
        body_ref: Unit(
            body_ref, "Спрос — это зависимость величины покупок от цены.", block, "page:1"
        ),
    }
    raw = [
        {
            "target_id": block,
            "outcome": "linked",
            "dispositions": [
                {"fragment_id": ref, "start": 0, "end": len(u.text), "outcome": "content"}
                for ref, u in units.items()
            ],
            "links": [
                {
                    "topic_id": topic,
                    "fragment_id": ref,
                    "semantic_kind": "content",
                    "roles": ["explanation"],
                    "evidence": [{"key": f"e{ref}", "ref": ref}],
                }
                for ref in units
            ],
        }
    ]
    checked = validate_target(block, raw, units, units, set(units), {topic})
    assert checked.valid
    # Связь абзаца сохранена, связь заголовка снята с объяснением.
    assert [link["fragment_id"] for link in checked.links] == [body_ref]
    assert {"reason": "heading_content", "ref": head_ref} in checked.diagnostics
    # Нерассмотренным остаётся только заголовок, и это видно по исходу блока.
    assert checked.outcome == "unresolved" and checked.reason == "unsupported_evidence"


def test_answer_reserve_and_token_limit_follow_the_size_of_the_packet(session):
    """Плоские 8 000 на ответ обрывали перечисление трёхсот фрагментов пакета."""
    assert output_reserve_tokens(1, 1) == OUTPUT_RESERVE_TOKENS
    # Пакет живого прогона: 16 targets и триста фрагментов не помещались в 8 000.
    big = output_reserve_tokens(16, 300)
    assert big > 2 * OUTPUT_RESERVE_TOKENS
    assert output_reserve_tokens(16, 600) > big
    project, _, material = setup_source(session, 20)
    run_id, _, _, _ = launch(session, project, material)
    tasks = list(session.scalars(select(CoverageTask).where(CoverageTask.run_id == run_id)))
    run = session.get(CoverageRun, run_id)
    for task in tasks:
        assert task.checkpoint["output_tokens"] >= OUTPUT_RESERVE_TOKENS
    # Предел покрывает три попытки, каждая из которых переотправляет прошлый ответ.
    answers = sum(task.checkpoint["output_tokens"] for task in tasks)
    assert run.limits["max_total_tokens"] > answers * 3


def test_packet_builder_groups_neighbors_and_covers_oversized_fragment(session):
    _, _, material = setup_source(session, 3)
    blocks = list(
        session.scalars(
            select(MaterialBlock)
            .where(MaterialBlock.material_id == material.id)
            .order_by(MaterialBlock.sort_order)
        )
    )
    rows = [(block, {"section_path": "Один раздел"}) for block in blocks]
    grouped = build_packet_specs(session, rows, token_budget=100)
    assert len(grouped) == 1
    assert grouped[0].targets == [str(block.id) for block in blocks]

    fragment = session.scalar(
        select(MaterialFragment).where(MaterialFragment.block_id == blocks[0].id)
    )
    fragment.text = " ".join(f"слово{i}" for i in range(80))
    session.commit()
    intervals = build_packet_specs(session, rows[:1], token_budget=10)
    assert len(intervals) > 1
    parts = [
        part
        for packet in intervals
        for part in packet.checkpoint["target_specs"][str(blocks[0].id)]["parts"]
    ]
    assert parts[0]["start"] == 0
    assert parts[-1]["end"] == len(fragment.text)
    assert all(
        left["end"] == right["start"]
        for left, right in zip(parts, parts[1:], strict=False)
    )
    assert any(part["forced"] for part in parts)


def test_compact_range_expands_by_packet_order_and_missing_alias_is_not_outside(session):
    project, _, material = setup_source(session, 3)
    run_id, _, token, _ = launch(session, project, material)
    task_input = prepare_task(session, token, first_task(session, run_id).id)
    aliases = list(task_input.target_aliases.values())
    expanded = expand_compact_response(
        task_input,
        [{
            "from_target": aliases[0],
            "to_target": aliases[-1],
            "outcome": "service",
            "parts": [],
        }],
    )
    assert [item["target_id"] for item in expanded] == task_input.targets
    assert all(item["outcome"] == "service" for item in expanded)
    assert expand_compact_response(
        task_input,
        [{
            "from_target": "B404",
            "to_target": "B404",
            "outcome": "outside_program",
            "parts": [],
        }],
    ) == []


def test_isolation_receipt_idempotency_and_original_text(session):
    project, topic, material = setup_source(session)
    run_id, _, token, _ = launch(session, project, material)
    task_input = prepare_task(session, token, first_task(session, run_id).id)
    raw = answer(task_input, topic.id)
    raw[0]["links"][0]["evidence"][0]["quote"] = "Потоки ... задачи"
    raw[1]["links"][0]["evidence"][0]["quote"] = "небылица без соответствия"
    publish_packet(session, token, task_input, raw)
    revision = session.get(Project, project.id).coverage_revision
    publish_packet(session, token, task_input, raw)
    assert session.get(Project, project.id).coverage_revision == revision
    assert session.scalar(select(func.count()).select_from(Binding)) == 2
    ref = next(iter(task_input.seen.values()))
    evidence = evidence_read(session, project.id, f"{task_input.task_id}:{ref.block_id}:e0")
    assert evidence["quote"] == ref.text
    assert evidence["repair"] == "approximate"
    other = make_textbook_project(session)
    with pytest.raises(ProjectNotFoundError):
        evidence_read(session, other.id, evidence["id"])


def test_quote_ladder_and_read_scope():
    unit = Unit("own", r"Значение $$x \in A$$ определено", "b", "page:m:1")
    neighbor = Unit("neighbor", "11.4. Процессы и потоки в Windows", "c", "page:m:1")
    evidence = Evidence(key="e", ref="own", quote=r"\(x ∈ A\)")
    checked = repair_evidence(evidence, {"own": unit}, set())
    assert checked["repair"] == "normalized" and checked["quote"] == unit.text
    evidence = Evidence(key="e", ref="own", quote=neighbor.text)
    assert repair_evidence(evidence, {"own": unit}, set()) is None
    checked = repair_evidence(evidence, {"own": unit, "neighbor": neighbor}, set())
    assert checked["ref"] == "neighbor" and checked["repair"] == "ref_corrected"
    assert (
        repair_evidence(
            Evidence(key="e", ref="own", quote="выдуманное значение"), {"own": unit}, set()
        )
        is None
    )


def test_primary_survives_failed_refinement(session):
    project, topic, material = setup_source(session, 1)
    run_id, _, token, _ = launch(session, project, material)
    task_input = prepare_task(session, token, first_task(session, run_id).id)
    publish_packet(session, token, task_input, answer(task_input, topic.id))
    primary = session.scalar(select(CoverageBlockResult))
    previous = primary.task_id
    refine = CoverageTask(
        run_id=run_id, kind="refine", task_key="refine:1", targets=task_input.targets
    )
    session.add(refine)
    session.commit()
    refine_input = prepare_task(session, token, refine.id)
    publish_packet(session, token, refine_input, [])
    assert primary.task_id == previous and primary.outcome == "linked"
    assert refine.result[task_input.targets[0]]["reason"] == "primary_preserved"
    checked = CheckedDecision(task_input.targets[0], True, "service")
    assert merge_refinement(checked, None) is checked


def test_lease_fencing_and_snapshot_change(session):
    project, topic, material = setup_source(session, 1)
    run_id, job, token, _ = launch(session, project, material)
    task_input = prepare_task(session, token, first_task(session, run_id).id)
    stored_job = session.get(BackgroundJob, job.id)
    stored_job.lease_expires_at = utc_now() - timedelta(seconds=1)
    session.commit()
    replacement = claim_job(session, "replacement", "ai")
    assert replacement.checkpoint["coverage_generation"] == 2
    with pytest.raises(ProjectConflictError, match="Worker"):
        publish_packet(session, token, task_input, answer(task_input, topic.id))
    next_token = ExecutionToken(run_id, 2, "replacement")
    material.active_parse_revision = 2
    session.commit()
    publish_packet(session, next_token, task_input, answer(task_input, topic.id))
    assert session.get(BackgroundJob, job.id).state == BackgroundJobState.CANCELLED
    assert session.get(CoverageRun, run_id).stop_reason == "snapshot_changed"
    assert session.scalar(select(func.count()).select_from(Binding)) == 0


def test_manual_removal_wins_and_survives_binding_delete(session):
    project, topic, material = setup_source(session, 1)
    run_id, _, token, _ = launch(session, project, material)
    task_input = prepare_task(session, token, first_task(session, run_id).id)
    fragment_id = UUID(next(iter(task_input.seen)))
    binding = Binding(
        project_id=project.id,
        program_node_id=topic.id,
        fragment_id=fragment_id,
        material_id=material.id,
        status=BindingStatus.MANUAL,
        mechanism=BindingMechanism.MANUAL,
    )
    session.add(binding)
    session.commit()
    remove_binding(session, project.id, binding.id)
    publish_packet(session, token, task_input, answer(task_input, topic.id))
    assert binding.status == BindingStatus.REMOVED
    assert session.scalar(select(CoverageBlockResult)).publication_state == "conflict"
    assert session.scalar(select(CoverageDecision)).payload["rejected"]
    session.delete(binding)
    session.commit()
    assert session.scalar(select(CoverageDecision)).payload["rejected"]


def test_current_queries_ignore_pending_runs_and_display_order(session):
    project, topic, material = setup_source(session, 1)
    run_id, job, _, _ = launch(session, project, material)
    process_coverage_job(session, job, lambda task: answer(task, topic.id))
    assert overview(session, project.id)["topics"]["with_content"] == 1
    topic.sort_order = 9
    session.commit()
    assert not run_read(session, project.id, run_id)["stale"]
    launch(session, project, material)
    assert overview(session, project.id)["distribution"]["linked"] == 1
    topic.title = "Другой смысл"
    session.commit()
    assert overview(session, project.id)["distribution"]["stale"] == 1
    assert overview(session, project.id)["topics"]["with_content"] == 0


def test_budget_is_shared_persistent_and_counts_uncertain_attempts(session):
    project, _, material = setup_source(session)
    run_id, _, token, _ = launch(session, project, material, limits={"max_calls": 2})
    task = first_task(session, run_id)
    budget = ResearchBudget(session, token, task.id)
    first = budget.reserve(100, None)
    budget.settle(first, None)
    budget.reserve(200, None)
    with pytest.raises(ProjectConflictError) as error:
        ResearchBudget(session, token, task.id).reserve(1, None)
    assert error.value.code == "coverage_budget_exhausted"
    assert budget_usage(session, run_id) == {
        "calls": 2,
        "tokens": 300,
        "cost_usd": 0,
        "uncertain_calls": 2,
    }


def test_existing_manual_removed_and_other_machine_mechanism_are_preserved(session):
    project, topic, material = setup_source(session)
    fragments = list(
        session.scalars(select(MaterialFragment).order_by(MaterialFragment.sort_order))
    )
    statuses = [BindingStatus.MANUAL, BindingStatus.REMOVED, BindingStatus.MACHINE]
    for fragment, status in zip(fragments, statuses, strict=True):
        session.add(
            Binding(
                project_id=project.id,
                program_node_id=topic.id,
                fragment_id=fragment.id,
                material_id=material.id,
                block_id=fragment.block_id,
                status=status,
                mechanism=BindingMechanism.SEARCH,
            )
        )
    session.commit()
    _, job, _, _ = launch(session, project, material)
    process_coverage_job(session, job, lambda task: answer(task, topic.id))
    bindings = list(session.scalars(select(Binding).order_by(Binding.fragment_id)))
    assert len(bindings) == 3
    assert {b.mechanism for b in bindings} == {BindingMechanism.SEARCH}
    manual = next(b for b in bindings if b.status == BindingStatus.MANUAL)
    assert manual.semantic_kind is None
    assert next(b for b in bindings if b.status == BindingStatus.MACHINE).semantic_kind == "content"
    assert overview(session, project.id)["distribution"]["unresolved"] == 2


def test_new_run_obeys_durable_rejection_after_binding_was_deleted(session):
    from app.coverage.decisions import remember_binding_choice

    project, topic, material = setup_source(session, 1)
    fragment = session.scalar(select(MaterialFragment))
    binding = Binding(
        project_id=project.id,
        program_node_id=topic.id,
        fragment_id=fragment.id,
        material_id=material.id,
        block_id=fragment.block_id,
        status=BindingStatus.REMOVED,
        mechanism=BindingMechanism.MANUAL,
    )
    session.add(binding)
    session.flush()
    remember_binding_choice(session, binding)
    session.delete(binding)
    session.commit()
    _, job, _, _ = launch(session, project, material)
    process_coverage_job(session, job, lambda task: answer(task, topic.id))
    assert session.scalar(select(func.count()).select_from(Binding)) == 0
    assert overview(session, project.id)["distribution"]["unresolved"] == 1


def test_partial_fragment_failure_keeps_valid_link_and_unknown_remainder(session):
    project, topic, material = setup_source(session, 1)
    original = session.scalar(select(MaterialFragment))
    extra = MaterialFragment(
        material_id=material.id,
        page_id=original.page_id,
        block_id=original.block_id,
        sort_order=1,
        text="Другой фрагмент",
        bbox=[0, 0, 1, 1],
        element_kind="paragraph",
        quality=PageQuality.NATIVE,
    )
    session.add(extra)
    session.commit()
    run_id, _, token, _ = launch(session, project, material)
    task_input = prepare_task(session, token, first_task(session, run_id).id)
    raw = answer(task_input, topic.id)
    raw[0]["links"][1]["evidence"][0]["quote"] = "совершенно выдуманная цитата"
    publish_packet(session, token, task_input, raw)
    row = session.scalar(select(CoverageBlockResult))
    assert row.work_state == "inspected" and row.outcome == "unresolved"
    assert row.result["dispositions"][1]["outcome"] == "unresolved"
    assert session.scalar(select(func.count()).select_from(Binding)) == 1


def test_default_handler_is_offline_and_cancel_from_registry_handles_pause(session, monkeypatch):
    from app.background.registry import cancel_job

    project, _, material = setup_source(session, 1)
    run_id, job, _, _ = launch(session, project, material)
    process_coverage_job(session, job)
    assert run_read(session, project.id, run_id)["stop_reason"] == "executor_unavailable"
    assert cancel_job(session, job.id).state == BackgroundJobState.CANCELLED


def test_current_count_does_not_promote_mentions_or_exercise_to_reading_basis(session):
    project, topic, material = setup_source(session, 2)
    _, job, _, _ = launch(session, project, material)

    def executor(task):
        raw = answer(task, topic.id)
        raw[0]["links"][0].update(semantic_kind="mention", roles=["reference"])
        raw[0]["dispositions"][0]["outcome"] = "mention"
        raw[1]["links"][0]["roles"] = ["exercise"]
        return raw

    process_coverage_job(session, job, executor)
    summary = overview(session, project.id)
    assert summary["topics"] == {"total": 1, "with_content": 1, "reading_basis": 0, "legacy": 0}
    assert summary["material_ratio"]["numerator"] == 2


def test_api_offline_preflight_scope_and_request_key_conflict(session):
    from fastapi.testclient import TestClient

    from app.db import get_session
    from app.main import create_app

    project, _, material = setup_source(session, 1)
    app = create_app()
    app.dependency_overrides[get_session] = lambda: session
    client = TestClient(app)
    base = f"/api/projects/{project.id}/coverage"
    plan = {"material_ids": [str(material.id)], "expected_program_revision": 0}
    checked = client.post(f"{base}/preflight", json=plan)
    assert checked.status_code == 200 and not checked.json()["execution_available"]
    command = {
        **plan,
        "request_key": "same-key",
        "preflight_fingerprint": checked.json()["fingerprint"],
    }
    started = client.post(f"{base}/runs", json=command)
    assert started.status_code == 202
    assert client.post(f"{base}/runs", json=command).json()["id"] == started.json()["id"]
    command["limits"] = {"max_calls": 1}
    assert client.post(f"{base}/runs", json=command).status_code == 409
    other = make_textbook_project(session)
    assert (
        client.get(f"/api/projects/{other.id}/coverage/runs/{started.json()['id']}").status_code
        == 404
    )
    assert client.get(f"{base}/overview").json()["total"] == 1


def test_issues_page_lists_only_blocks_that_need_attention(session):
    """Экран берёт короткую ленту проблем, а не выкачивает все блоки проекта."""
    from fastapi.testclient import TestClient

    from app.db import get_session
    from app.main import create_app

    project, topic, material = setup_source(session, 3)
    run_id, job, token, _ = launch(session, project, material)

    def executor(task_input):
        raw = answer(task_input, topic.id)
        raw[0]["links"][0]["roles"] = ["invalid_role"]
        return raw

    process_coverage_job(session, job, executor)
    app = create_app()
    app.dependency_overrides[get_session] = lambda: session
    client = TestClient(app)
    base = f"/api/projects/{project.id}/coverage"
    issues = client.get(f"{base}/issues").json()
    assert issues["total"] == 1 and issues["next_offset"] is None
    assert [item["bucket"] for item in issues["items"]] == ["unresolved"]
    assert client.get(f"{base}/issues?limit=1").json()["total"] == 1
    blocks = client.get(f"{base}/sources/{material.id}/blocks").json()
    assert blocks["total"] == 3
    assert run_read(session, project.id, run_id)["primary"]["inspected"] == 3


def test_preflight_returns_resolved_roles_when_models_are_configured(session, ai_config):
    """Настроенная модель — единственный путь к платному запуску, и он не должен ломать ответ."""
    from fastapi.testclient import TestClient
    from sqlalchemy import select as sa_select

    from app.db import get_session
    from app.main import create_app
    from app.models import AiProviderConnection

    project, _, material = setup_source(session, 1)
    provider_id = session.scalar(sa_select(AiProviderConnection.id))
    app = create_app()
    app.dependency_overrides[get_session] = lambda: session
    client = TestClient(app)
    plan = {
        "material_ids": [str(material.id)],
        "expected_program_revision": 0,
        "roles": {
            key: {"provider_id": str(provider_id), "model_id": ai_config}
            for key in ("overview", "research")
        },
    }
    checked = client.post(f"/api/projects/{project.id}/coverage/preflight", json=plan)
    assert checked.status_code == 200, checked.text
    body = checked.json()
    assert body["execution_available"] and body["execution_issue"] is None
    assert body["model_roles"]["overview"]["model_id"] == ai_config
    assert body["model_roles"]["overview"]["context_length"] == 100_000


def test_block_outcome_is_derived_from_parts_not_taken_on_trust():
    """Живой прогон: 23 блока потеряны на «linked, а часть служебная» — это mixed."""
    topic, block = str(uuid4()), str(uuid4())
    body_ref, service_ref = str(uuid4()), str(uuid4())
    units = {
        body_ref: Unit(body_ref, "Спрос — зависимость покупок от цены.", block, "page:1"),
        service_ref: Unit(service_ref, "Контрольные вопросы к главе", block, "page:1"),
    }
    raw = [
        {
            "target_id": block,
            # Модель называет агрегат «linked», хотя сама же отдала служебную часть.
            "outcome": "linked",
            "dispositions": [
                {
                    "fragment_id": ref,
                    "start": 0,
                    "end": len(units[ref].text),
                    "outcome": outcome,
                }
                for ref, outcome in ((body_ref, "content"), (service_ref, "service"))
            ],
            "links": [
                {
                    "topic_id": topic,
                    "fragment_id": body_ref,
                    "semantic_kind": "content",
                    "roles": ["explanation"],
                    "evidence": [{"key": "e0", "ref": body_ref}],
                }
            ],
        }
    ]
    checked = validate_target(block, raw, units, units, set(units), {topic})
    assert checked.valid and checked.outcome == "mixed_resolved"
    assert [link["fragment_id"] for link in checked.links] == [body_ref]
    # Часть без связи, названная содержательной, становится unresolved, а не роняет блок.
    raw[0]["dispositions"][1]["outcome"] = "content"
    demoted = validate_target(block, raw, units, units, set(units), {topic})
    assert demoted.valid and demoted.outcome == "unresolved"
    assert demoted.reason == "unsupported_evidence"
    assert [link["fragment_id"] for link in demoted.links] == [body_ref]


def test_unseen_image_drops_its_fragment_not_the_whole_block():
    """Один непросмотренный рисунок отменял разбор всего раздела: 27 блоков из 126."""
    topic, block = str(uuid4()), str(uuid4())
    body_ref, image_ref = str(uuid4()), str(uuid4())
    units = {
        body_ref: Unit(body_ref, "Кривая спроса убывает по цене.", block, "page:1"),
        image_ref: Unit(image_ref, "Рис. 3.1. Кривая спроса", block, "page:1", kind="image"),
    }
    raw = [
        {
            "target_id": block,
            "outcome": "linked",
            "dispositions": [
                {"fragment_id": ref, "start": 0, "end": len(unit.text), "outcome": "content"}
                for ref, unit in units.items()
            ],
            "links": [
                {
                    "topic_id": topic,
                    "fragment_id": ref,
                    "semantic_kind": "content",
                    "roles": ["explanation"],
                    "evidence": [{"key": f"e{index}", "ref": ref}],
                }
                for index, ref in enumerate(units)
            ],
        }
    ]
    checked = validate_target(block, raw, units, units, set(), {topic})
    # Блок честно остаётся unresolved: часть его не просмотрена.
    assert checked.valid and checked.outcome == "unresolved"
    assert checked.reason == "visual_unavailable"
    # Но текст рядом с картинкой разобран, и его связь публикуется.
    assert [link["fragment_id"] for link in checked.links] == [body_ref]
    assert {"reason": "visual_unavailable", "ref": image_ref} in checked.diagnostics
    # Просмотренная страница ничего не снимает.
    seen = validate_target(block, raw, units, units, {"page:1"}, {topic})
    assert seen.outcome == "linked" and len(seen.links) == 2


def test_topic_alias_in_to_target_keeps_the_single_decision(session):
    """Живой прогон: alias темы в to_target уносил все восемь targets пакета."""
    project, topic, material = setup_source(session, 3)
    run_id, _, token, _ = launch(session, project, material)
    task_input = prepare_task(session, token, first_task(session, run_id).id)
    alias = task_input.target_aliases[task_input.targets[0]]
    topic_alias = task_input.topic_aliases[str(topic.id)][0]
    expanded = expand_compact_response(
        task_input,
        [{"from_target": alias, "to_target": topic_alias, "outcome": "service", "parts": []}],
    )
    assert [item["target_id"] for item in expanded] == [task_input.targets[0]]
    assert expanded[0]["outcome"] == "service"
    # Точечное решение сильнее накрывшего его диапазона, дубль больше не теряет оба.
    last = task_input.target_aliases[task_input.targets[-1]]
    both = expand_compact_response(
        task_input,
        [
            {"from_target": alias, "to_target": last, "outcome": "outside_program", "parts": []},
            {"from_target": last, "to_target": last, "outcome": "service", "parts": []},
        ],
    )
    assert [item["target_id"] for item in both] == task_input.targets
    assert both[-1]["outcome"] == "service"
    assert all(item["outcome"] == "outside_program" for item in both[:-1])


def test_nested_fragment_range_is_an_exception_not_a_duplicate(session):
    """«F200-F209 content, следом F201-F203 service» — вырезанное исключение, не дубль."""
    project, topic, material = setup_source(session, 1)
    block = session.scalar(select(MaterialBlock).where(MaterialBlock.material_id == material.id))
    page_id = session.scalar(select(MaterialPage.id).where(MaterialPage.material_id == material.id))
    for index in range(1, 4):
        session.add(
            MaterialFragment(
                id=uuid4(),
                material_id=material.id,
                page_id=page_id,
                block_id=block.id,
                sort_order=index,
                text=f"Кривая спроса убывает {index}",
                bbox=[0, 0, 1, 1],
                element_kind="paragraph",
                quality=PageQuality.NATIVE,
            )
        )
    session.commit()
    run_id, _, token, _ = launch(session, project, material)
    task_input = prepare_task(session, token, first_task(session, run_id).id)
    target = task_input.targets[0]
    alias = task_input.target_aliases[target]
    refs = task_input.target_refs[target]
    aliases = [task_input.fragment_aliases[ref] for ref in refs]
    link = {
        "topic": task_input.topic_aliases[str(topic.id)][0],
        "semantic_kind": "content",
        "roles": ["explanation"],
        "evidence": [],
    }
    raw = expand_compact_response(
        task_input,
        [
            {
                "from_target": alias,
                "to_target": alias,
                "outcome": "mixed_resolved",
                "parts": [
                    {
                        "fragment": f"{aliases[0]}-{aliases[3]}",
                        "outcome": "content",
                        "links": [link],
                    },
                    {"fragment": f"{aliases[1]}-{aliases[2]}", "outcome": "service", "links": []},
                ],
            }
        ],
    )
    assert "error" not in raw[0]
    assert [part["fragment_id"] for part in raw[0]["dispositions"]] == refs
    # Исключение выигрывает у объемлющего диапазона, крайние фрагменты остаются content.
    assert [part["outcome"] for part in raw[0]["dispositions"]] == [
        "content",
        "service",
        "service",
        "content",
    ]
    assert {item["fragment_id"] for item in raw[0]["links"]} == {refs[0], refs[3]}
    checked = validate_target(
        target,
        raw,
        {ref: task_input.seen[ref] for ref in refs},
        task_input.seen,
        set(refs),
        task_input.topics,
    )
    assert checked.valid and checked.outcome == "mixed_resolved"


def test_rules_separate_a_plan_from_a_list_that_explains():
    """План отдавался как content (20 ложных связей), а на список факторов правило
    без второй половины срабатывало наоборот: 332 связи на списках стали mention."""
    assert "План и оглавление" in SYSTEM_RULES
    assert "Список факторов, признаков, видов или условий раскрывает тему" in SYSTEM_RULES
