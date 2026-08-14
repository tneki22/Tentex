"""Сквозная серверная проверка шлюза и двух первых ИИ-потребителей."""

import asyncio
import json
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

from app.ai import catalog  # noqa: E402
from app.ai.gateway import ModelGateway  # noqa: E402
from app.ai.provider import (  # noqa: E402
    FakeTransport,
    ProviderCompletion,
    ProviderModel,
    ProviderUsage,
)
from app.ai.schemas import (  # noqa: E402
    AiCatalogModelWrite,
    AiDefaultWrite,
    AiGlobalSettingsWrite,
    AiModelSelection,
    AiProviderWrite,
)
from app.ai.settings import (  # noqa: E402
    create_provider,
    read_settings,
    set_default,
    update_global_settings,
)
from app.config import settings  # noqa: E402
from app.db import Base  # noqa: E402
from app.materials import ai_cleanup  # noqa: E402
from app.models import (  # noqa: E402
    ExamKind,
    Material,
    MaterialPage,
    MaterialSourceKind,
    MaterialState,
    NodeType,
    PageQuality,
    ProgramNode,
    Project,
    ProjectMaterial,
    ProjectStatus,
    SourceRole,
    TemplateKey,
    WorkspaceVariant,
)
from app.projects import program, program_ai  # noqa: E402
from app.projects.errors import ProjectDomainError  # noqa: E402

MODEL_ID = "fake/structured"


def _completion(payload: dict, cost: str) -> ProviderCompletion:
    return ProviderCompletion(
        content=json.dumps(payload, ensure_ascii=False),
        actual_model_id=MODEL_ID,
        usage=ProviderUsage(
            input_tokens=100,
            output_tokens=50,
            cost_usd=Decimal(cost),
        ),
    )


def _seed_project(session: Session) -> tuple[Project, Material, list[ProgramNode]]:
    project = Project(
        template_key=TemplateKey.EXAM,
        workspace_variant=WorkspaceVariant.EXAM,
        status=ProjectStatus.ACTIVE,
        name="Проверка шлюза",
    )
    material = Material(
        sha256="a" * 64,
        original_name="Конспект.txt",
        storage_path="text/check.txt",
        media_type="text/plain",
        source_kind=MaterialSourceKind.TEXT,
        size_bytes=100,
        page_count=1,
        status=MaterialState.READY,
        active_parse_revision=1,
    )
    session.add_all([project, material])
    session.flush()
    session.add(
        ProjectMaterial(
            project_id=project.id,
            material_id=material.id,
            source_role=SourceRole.ADDITIONAL,
            priority=0,
            affects_program=False,
            purposes=["study_source"],
        )
    )
    session.add(
        MaterialPage(
            material_id=material.id,
            revision=1,
            page_number=1,
            width=595,
            height=842,
            text="Заголовок\nПервый пункт Второй пункт",
            markdown="Заголовок\nПервый пункт Второй пункт",
            quality=PageQuality.NATIVE,
            elements=[],
            diagnostics=[],
        )
    )
    nodes = []
    for index in range(6):
        node = ProgramNode(
            project_id=project.id,
            parent_id=None,
            node_type=NodeType.TOPIC,
            exam_kind=ExamKind.QUESTION,
            sort_order=index,
            title=f"Вопрос номер {index + 1}",
            is_in_current_program=True,
            is_archived=False,
        )
        session.add(node)
        nodes.append(node)
    session.commit()
    return project, material, nodes


async def _run(session: Session) -> None:
    snapshot = read_settings(session)
    assert len(snapshot.providers) == 0
    session.commit()
    snapshot = create_provider(
        session,
        AiProviderWrite(
            label="Fake provider",
            catalog_profile="openai_compatible",
            base_url="https://fake.test/v1",
            api_key="not-a-real-key",
        ),
    )
    provider_id = snapshot.providers[0].id
    session.commit()
    update_global_settings(
        session,
        AiGlobalSettingsWrite(
            external_models_enabled=True,
            daily_limit_usd=Decimal("1"),
            operation_limit_usd=Decimal("0.5"),
            confirm_input_tokens=100_000,
            usd_rub_rate=Decimal("90"),
            usd_rub_rate_date=date.today(),
        ),
    )
    project, material, nodes = _seed_project(session)
    groups = {
        "groups": [
            {
                "title": "Основы дисциплины",
                "rationale": "Базовая часть",
                "node_ids": [str(node.id) for node in nodes[:3]],
            },
            {
                "title": "Практические вопросы",
                "rationale": "Прикладная часть",
                "node_ids": [str(node.id) for node in nodes[3:]],
            },
        ]
    }
    fake = FakeTransport(
        models=[
            ProviderModel(
                model_id=MODEL_ID,
                display_name="Fake structured",
                context_length=100_000,
                supported_parameters=["response_format"],
                input_modalities=["text"],
                output_modalities=["text"],
                prompt_price_usd=Decimal("0.000001"),
                completion_price_usd=Decimal("0.000002"),
            )
        ],
        completions=[
            _completion(
                {
                    "markdown": "# Заголовок\n\n- Первый пункт\n- Второй пункт",
                    "changes": ["Восстановлен список"],
                    "warnings": [],
                },
                "0.002",
            ),
            _completion(groups, "0.003"),
        ],
    )
    catalog_result = await catalog.search_catalog(session, provider_id, fake)
    assert catalog_result[0].model_id == MODEL_ID
    assert not catalog_result[0].is_added
    catalog.add_catalog_model(
        session,
        provider_id,
        AiCatalogModelWrite.model_validate(
            catalog_result[0].model_dump(exclude={"is_added"})
        ),
    )
    session.commit()
    set_default(
        session,
        "text",
        AiDefaultWrite(
            selection=AiModelSelection(provider_id=provider_id, model_id=MODEL_ID)
        ),
    )
    gateway = ModelGateway(session, fake)
    cleanup_preview = await ai_cleanup.preflight(
        session,
        gateway,
        project.id,
        material.id,
        1,
        ai_cleanup.CleanupPreflightWrite(),
    )
    cleanup_command = ai_cleanup.CleanupRunWrite(
        expected_revision=cleanup_preview.revision,
        expected_source_hash=cleanup_preview.source_hash,
    )
    cleanup_run = await ai_cleanup.run(
        session, gateway, project.id, material.id, 1, cleanup_command
    )
    cleanup_cached = await ai_cleanup.run(
        session, gateway, project.id, material.id, 1, cleanup_command
    )
    assert cleanup_cached.cached and fake.complete_calls == 1
    ai_cleanup.apply(
        session,
        project.id,
        material.id,
        1,
        ai_cleanup.CleanupApplyWrite(
            run_id=cleanup_run.run_id,
            expected_revision=cleanup_preview.revision,
            expected_source_hash=cleanup_preview.source_hash,
            markdown=cleanup_run.suggestion.markdown,
        ),
    )
    grouping_preview = await program_ai.preflight(session, gateway, project.id)
    grouping_run = await program_ai.run(
        session,
        gateway,
        project.id,
        program_ai.ProgramGroupingRunWrite(
            expected_program_revision=grouping_preview.program_revision,
            expected_source_hash=grouping_preview.source_hash,
        ),
    )
    grouping_result = program_ai.apply(
        session,
        project.id,
        program_ai.ProgramGroupingApplyWrite(
            run_id=grouping_run.run_id,
            expected_program_revision=grouping_preview.program_revision,
            expected_source_hash=grouping_preview.source_hash,
            groups=grouping_run.suggestion.groups,
        ),
    )
    action = grouping_result.latest_undoable_action
    assert action is not None
    undone = program.undo_last_project_action(session, project.id, action.sequence)
    assert all(node.parent_id is None for node in undone.program.nodes)
    snapshot = read_settings(session)
    session.commit()
    update_global_settings(
        session,
        AiGlobalSettingsWrite(
            external_models_enabled=True,
            daily_limit_usd=snapshot.daily_limit_usd,
            operation_limit_usd=Decimal("0.000001"),
            confirm_cost_usd=snapshot.confirm_cost_usd,
            confirm_input_tokens=snapshot.confirm_input_tokens,
            usd_rub_rate=snapshot.usd_rub_rate,
            usd_rub_rate_date=snapshot.usd_rub_rate_date,
        ),
    )
    try:
        await program_ai.preflight(session, gateway, project.id)
    except ProjectDomainError as error:
        assert error.code == "ai_operation_limit"
    else:
        raise AssertionError("operation limit did not stop the gateway")
    session.rollback()
    update_global_settings(
        session,
        AiGlobalSettingsWrite(
            external_models_enabled=False,
            daily_limit_usd=snapshot.daily_limit_usd,
            operation_limit_usd=snapshot.operation_limit_usd,
            confirm_cost_usd=snapshot.confirm_cost_usd,
            confirm_input_tokens=snapshot.confirm_input_tokens,
            usd_rub_rate=snapshot.usd_rub_rate,
            usd_rub_rate_date=snapshot.usd_rub_rate_date,
        ),
    )
    try:
        await ai_cleanup.preflight(
            session,
            gateway,
            project.id,
            material.id,
            1,
            ai_cleanup.CleanupPreflightWrite(),
        )
    except ProjectDomainError as error:
        assert error.code == "ai_disabled"
    else:
        raise AssertionError("global off did not stop the gateway")


def main() -> None:
    with TemporaryDirectory(prefix="tentex-ai-gateway-") as temporary:
        settings.data_dir = Path(temporary)
        engine = create_engine(f"sqlite+pysqlite:///{Path(temporary) / 'check.sqlite'}")

        @event.listens_for(engine, "connect")
        def _foreign_keys(dbapi_connection: object, _: object) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        Base.metadata.create_all(engine)
        with engine.begin() as connection:
            connection.exec_driver_sql(
                "CREATE VIRTUAL TABLE fragment_search USING fts5("
                "text, lemmas, fragment_id UNINDEXED, material_id UNINDEXED)"
            )
            connection.exec_driver_sql(
                "CREATE TABLE fragment_search_map ("
                "fragment_id TEXT PRIMARY KEY, material_id TEXT NOT NULL, rowid INTEGER NOT NULL)"
            )
        with Session(engine, expire_on_commit=False) as session:
            asyncio.run(_run(session))
            assert session.execute(text("PRAGMA foreign_key_check")).all() == []
        engine.dispose()
    print("check_ai_gateway: OK")


if __name__ == "__main__":
    main()
