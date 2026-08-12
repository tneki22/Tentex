import hashlib
from decimal import Decimal

import pytest
from conftest import add_page_with_fragments, link_material, make_exam_project, make_material
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.gateway import ModelGateway
from app.ai.provider import FakeTransport, ProviderCompletion, ProviderUsage
from app.materials import ai_cleanup
from app.models import AiRun, Material, MaterialPage
from app.projects.errors import ProjectDomainError


def _completion() -> ProviderCompletion:
    return ProviderCompletion(
        content=(
            '{"markdown":"# Заголовок\\n\\n- Первый пункт\\n- Второй пункт",'
            '"changes":["Восстановлен список"],"warnings":[]}'
        ),
        actual_model_id="test/structured-model",
        usage=ProviderUsage(
            input_tokens=120,
            output_tokens=40,
            cost_usd=Decimal("0.002"),
        ),
    )


@pytest.mark.asyncio
async def test_cleanup_preflight_run_cache_and_apply(session: Session, ai_config: str) -> None:
    del ai_config
    project = make_exam_project(session)
    material = make_material(session, "81")
    page = add_page_with_fragments(
        session,
        material,
        page_number=1,
        revision=1,
        fragments=["Заголовок", "Первый пункт Второй пункт"],
    )
    link_material(session, project, material)
    source = "Заголовок\nПервый пункт Второй пункт"
    source_hash = hashlib.sha256(source.encode()).hexdigest()
    fake = FakeTransport(completions=[_completion()])
    gateway = ModelGateway(session, fake)
    preview = await ai_cleanup.preflight(
        session,
        gateway,
        project.id,
        material.id,
        1,
        ai_cleanup.CleanupPreflightWrite(),
    )
    assert preview.revision == 1
    assert preview.source_hash == source_hash
    command = ai_cleanup.CleanupRunWrite(
        expected_revision=1,
        expected_source_hash=source_hash,
    )
    first = await ai_cleanup.run(session, gateway, project.id, material.id, 1, command)
    second = await ai_cleanup.run(session, gateway, project.id, material.id, 1, command)
    assert first.suggestion.markdown.startswith("# Заголовок")
    assert second.cached is True
    assert fake.complete_calls == 1
    sent = fake.complete_requests[0]["messages"]
    assert "Дополнительной инструкции нет" in sent[1]["content"]
    correction = ai_cleanup.apply(
        session,
        project.id,
        material.id,
        1,
        ai_cleanup.CleanupApplyWrite(
            run_id=first.run_id,
            expected_revision=1,
            expected_source_hash=source_hash,
            markdown=first.suggestion.markdown,
        ),
    )
    assert correction.page.markdown.startswith("# Заголовок")
    material = session.get(Material, material.id)
    assert material is not None and material.active_parse_revision == 2
    old_page = session.get(MaterialPage, page.page_id)
    assert old_page is not None and old_page.revision == 1


@pytest.mark.asyncio
async def test_cleanup_instruction_changes_hash_and_stale_apply_is_blocked(
    session: Session, ai_config: str
) -> None:
    del ai_config
    project = make_exam_project(session)
    material = make_material(session, "82")
    add_page_with_fragments(
        session, material, page_number=1, revision=1, fragments=["Исходный текст"]
    )
    link_material(session, project, material)
    fake = FakeTransport(completions=[_completion()])
    gateway = ModelGateway(session, fake)
    blank = await ai_cleanup.preflight(
        session,
        gateway,
        project.id,
        material.id,
        1,
        ai_cleanup.CleanupPreflightWrite(),
    )
    explicit = await ai_cleanup.preflight(
        session,
        gateway,
        project.id,
        material.id,
        1,
        ai_cleanup.CleanupPreflightWrite(instruction="Сократи повторы"),
    )
    assert blank.preflight.request_hash != explicit.preflight.request_hash
    run = await ai_cleanup.run(
        session,
        gateway,
        project.id,
        material.id,
        1,
        ai_cleanup.CleanupRunWrite(
            instruction="Сократи повторы",
            expected_revision=1,
            expected_source_hash=blank.source_hash,
        ),
    )
    material.active_parse_revision = 2
    session.commit()
    with pytest.raises(ProjectDomainError) as caught:
        ai_cleanup.apply(
            session,
            project.id,
            material.id,
            1,
            ai_cleanup.CleanupApplyWrite(
                run_id=run.run_id,
                expected_revision=1,
                expected_source_hash=blank.source_hash,
                markdown=run.suggestion.markdown,
            ),
        )
    assert caught.value.code in {"stale_material_revision", "not_found"}
    assert session.scalar(select(AiRun).where(AiRun.id == run.run_id)) is not None
