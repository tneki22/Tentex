from pathlib import Path
from uuid import UUID, uuid4

import pytest
from conftest import add_page_with_fragments, link_material, make_exam_project, make_material
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.ai.provider import FakeTransport, ProviderEmbeddings, ProviderError, ProviderUsage
from app.background.registry import cancel_job
from app.config import settings
from app.exam import chat as chat_service
from app.models import (
    BackgroundJob,
    BackgroundJobKind,
    BackgroundJobState,
    EmbeddingBackendKind,
    EmbeddingProfile,
    Material,
    MaterialBlock,
    MaterialSourceKind,
    MaterialState,
    PageQuality,
    Project,
    ProjectMaterial,
    ProjectStatus,
    RetrievalChunk,
    RetrievalChunkKind,
    RetrievalIndex,
    RetrievalIndexState,
    RetrievalPreset,
    RetrievalSettings,
    SourceRole,
    TemplateKey,
    TypstSourceChunk,
    WorkspaceVariant,
    utc_now,
)
from app.projects.errors import ProjectConflictError, ProjectDomainError
from app.retrieval import indexing as indexing_service
from app.retrieval import local_models
from app.retrieval.chunking import (
    ChunkAtom,
    Section,
    _chunk_title,
    _Outline,
    chunk_atoms,
    material_chunks,
)
from app.retrieval.context import ContextAssembler
from app.retrieval.embeddings import OpenAIEmbeddingBackend, _validate_vectors
from app.retrieval.exhaustive import start_run
from app.retrieval.indexing import (
    activate_index,
    embedding_batch_size,
    finish_index_build,
    pause_index_build,
    process_index_job,
    queue_incremental_reindex,
    queue_index_materials,
    resume_index_build,
    start_index_build,
)
from app.retrieval.schemas import (
    ExhaustiveRunWrite,
    RetrievalIndexBuildWrite,
    RetrievalIndexMaterialsWrite,
    RetrievalScope,
    RetrievalSearchRead,
    RetrievalSearchWrite,
    SearchStrategy,
)
from app.retrieval.search import (
    HybridRetriever,
    ScopeFilter,
    _lexical_candidates,
    _lexical_coverage,
)
from app.retrieval.settings import read_settings
from app.retrieval.vector import VectorHit, reciprocal_rank_fusion


def _profile(session: Session, *, external: bool = False) -> EmbeddingProfile:
    profile = EmbeddingProfile(
        id=uuid4(),
        label=f"profile-{uuid4()}",
        backend_kind=(
            EmbeddingBackendKind.OPENAI_COMPATIBLE if external else EmbeddingBackendKind.LOCAL_HF
        ),
        model_id="test/embeddings",
        batch_size=8,
        installed=True,
    )
    session.add(profile)
    session.commit()
    return profile


def _index(session: Session, profile: EmbeddingProfile) -> RetrievalIndex:
    row = RetrievalIndex(
        id=uuid4(),
        profile_id=profile.id,
        state=RetrievalIndexState.READY,
        preset=RetrievalPreset.BALANCED,
        chunk_target_tokens=384,
        chunk_max_tokens=480,
        chunk_overlap_tokens=64,
    )
    session.add(row)
    session.commit()
    return row


def test_settings_count_material_once_only_for_current_index_revision(session: Session) -> None:
    current = make_material(session, "501")
    outdated = make_material(session, "502")
    make_material(session, "503")
    profile = _profile(session)
    index = _index(session, profile)
    index.state = RetrievalIndexState.ACTIVE
    session.add(RetrievalSettings(id=1, active_index_id=index.id))
    for order, (material, revision) in enumerate(
        [(current, 1), (current, 1), (outdated, 1)]
    ):
        session.add(RetrievalChunk(
            index_id=index.id, material_id=material.id, revision=revision,
            kind=RetrievalChunkKind.TEXT, sort_order=order,
            text="текст", token_count=1, content_hash=str(order).rjust(64, "0"),
        ))
    outdated.active_parse_revision = 2
    session.commit()

    result = read_settings(session)
    assert result.ready_materials == 1
    assert result.total_ready_materials == 3
    assert result.degraded


def test_chunking_splits_a_giant_atom_without_exceeding_maximum() -> None:
    chunks = chunk_atoms(
        [ChunkAtom(" ".join(f"слово{number}" for number in range(2_000)))],
        target_tokens=384,
        max_tokens=480,
        overlap_tokens=64,
    )

    assert len(chunks) > 1
    assert all(sum(len(atom.text.split()) for atom in chunk) <= 480 for chunk in chunks)


def test_material_chunks_skip_visual_stub_and_keep_ocr_warning(session: Session) -> None:
    material = make_material(session, "91")
    rows = add_page_with_fragments(
        session,
        material,
        page_number=1,
        revision=1,
        fragments=["[Изображение]", "Слабое распознавание всё равно участвует в поиске."],
    )
    from app.models import MaterialFragment

    fragment = session.get(MaterialFragment, rows.fragment_ids[1])
    assert fragment is not None
    fragment.quality = PageQuality.OCR_LOW
    session.commit()

    chunks = material_chunks(session, material, target_tokens=20, max_tokens=40, overlap_tokens=5)

    assert len(chunks) == 1
    assert "[Изображение]" not in chunks[0].text
    assert chunks[0].quality == PageQuality.OCR_LOW


def test_typst_chunk_preserves_file_and_line_locator(session: Session) -> None:
    material = Material(
        id=uuid4(),
        sha256="7" * 64,
        original_name="main.typ",
        storage_path="typst/main.zip",
        media_type="application/zip",
        source_kind=MaterialSourceKind.TYPST,
        size_bytes=100,
        status=MaterialState.READY,
        active_parse_revision=1,
    )
    session.add(material)
    session.add(
        TypstSourceChunk(
            material_id=material.id,
            revision=1,
            sort_order=0,
            path="chapters/db.typ",
            line_from=12,
            line_to=18,
            source_text="#heading[Транзакции]\n$A arrow B$",
            source_hash="8" * 64,
        )
    )
    session.commit()

    chunk = material_chunks(
        session, material, target_tokens=384, max_tokens=480, overlap_tokens=64
    )[0]

    assert chunk.locator == {
        "typst_path": "chapters/db.typ",
        "line_from": 12,
        "line_to": 18,
    }
    assert "$A arrow B$" in chunk.text


def test_rrf_combines_signals_and_honors_weights() -> None:
    first, second = uuid4(), uuid4()

    ranking = reciprocal_rank_fusion(
        [first, second],
        [second],
        k=60,
        lexical_weight=0.5,
        semantic_weight=2,
    )

    assert ranking[0][0] == second
    assert ranking[0][2] == ["lexical", "semantic"]


def test_embedding_dimension_mismatch_has_stable_error() -> None:
    with pytest.raises(ProjectDomainError) as excinfo:
        _validate_vectors([[0.1, 0.2]], 1, 3)

    assert excinfo.value.code == "retrieval_dimension_mismatch"


def test_qwen_cpu_indexing_uses_a_bounded_embedding_batch(session: Session) -> None:
    profile = _profile(session)
    profile.model_id = "Qwen/Qwen3-Embedding-0.6B"
    profile.batch_size = 32
    session.commit()

    assert embedding_batch_size(profile) == 4


def test_other_embedding_profiles_keep_their_configured_batch(session: Session) -> None:
    profile = _profile(session)
    profile.batch_size = 12
    session.commit()

    assert embedding_batch_size(profile) == 12


def test_external_indexing_bounds_provider_batch(session: Session) -> None:
    profile = _profile(session, external=True)
    profile.batch_size = 32
    session.commit()

    assert embedding_batch_size(profile) == 4


@pytest.mark.asyncio
async def test_external_embeddings_retry_temporary_connection_failure(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    profile = _profile(session, external=True)
    reply = ProviderEmbeddings(
        vectors=[[0.1, 0.2]],
        actual_model_id=profile.model_id,
        usage=ProviderUsage(),
    )
    transport = FakeTransport(
        embeddings=[ProviderError("ai_provider_unavailable", "connection dropped"), reply]
    )

    async def no_wait(_: float) -> None:
        return None

    monkeypatch.setattr("app.retrieval.embeddings.asyncio.sleep", no_wait)

    assert await OpenAIEmbeddingBackend(profile, transport).embed_documents(["текст"]) == [
        [0.1, 0.2]
    ]
    assert len(transport.embed_requests) == 2


def test_activation_switches_indexes_atomically(session: Session) -> None:
    profile = _profile(session)
    first = _index(session, profile)
    second = _index(session, profile)
    activate_index(session, first.id)

    activate_index(session, second.id)

    settings = session.get(RetrievalSettings, 1)
    assert settings is not None and settings.active_index_id == second.id
    assert session.get(RetrievalIndex, first.id).state == RetrievalIndexState.READY
    assert session.get(RetrievalIndex, second.id).state == RetrievalIndexState.ACTIVE


def test_cloud_index_requires_explicit_corpus_consent(session: Session) -> None:
    material = make_material(session, "92")
    profile = _profile(session, external=True)

    with pytest.raises(ProjectConflictError) as excinfo:
        start_index_build(
            session,
            RetrievalIndexBuildWrite(profile_id=profile.id, material_ids=[material.id]),
        )

    assert excinfo.value.code == "retrieval_cloud_consent_required"


def test_revision_change_queues_one_local_incremental_job(session: Session) -> None:
    material = make_material(session, "93")
    profile = _profile(session)
    index = _index(session, profile)
    index.state = RetrievalIndexState.ACTIVE
    index.corpus_manifest = [
        {"material_id": str(material.id), "revision": 1, "name": "M", "size_bytes": 1}
    ]
    session.add(RetrievalSettings(id=1, active_index_id=index.id, default_profile_id=profile.id))
    session.commit()

    queue_incremental_reindex(session, material.id)
    queue_incremental_reindex(session, material.id)
    session.commit()

    jobs = list(
        session.scalars(
            select(BackgroundJob).where(
                BackgroundJob.kind == BackgroundJobKind.RETRIEVAL_INDEX,
                BackgroundJob.material_id == material.id,
            )
        )
    )
    assert len(jobs) == 1
    assert jobs[0].checkpoint["mode"] == "incremental"


def test_add_materials_to_active_index_deduplicates_jobs(session: Session) -> None:
    first, second = make_material(session, "101"), make_material(session, "102")
    profile = _profile(session)
    index = _index(session, profile)
    index.state = RetrievalIndexState.ACTIVE
    session.add(RetrievalSettings(id=1, active_index_id=index.id, default_profile_id=profile.id))
    session.commit()

    command = RetrievalIndexMaterialsWrite(material_ids=[first.id, first.id, second.id])
    first_result = queue_index_materials(session, index.id, command)
    second_result = queue_index_materials(session, index.id, command)

    assert len(first_result.job_ids) == 2
    assert first_result.job_ids == second_result.job_ids
    assert len(list(session.scalars(select(BackgroundJob)))) == 2


def test_add_materials_to_external_index_requires_cloud_consent(session: Session) -> None:
    material = make_material(session, "103")
    profile = _profile(session, external=True)
    index = _index(session, profile)
    index.state = RetrievalIndexState.ACTIVE
    session.add(RetrievalSettings(id=1, active_index_id=index.id, default_profile_id=profile.id))
    session.commit()
    index_id, material_id = index.id, material.id

    with pytest.raises(ProjectConflictError) as excinfo:
        queue_index_materials(
            session, index_id, RetrievalIndexMaterialsWrite(material_ids=[material_id])
        )
    assert excinfo.value.code == "retrieval_cloud_consent_required"
    session.rollback()

    result = queue_index_materials(
        session, index_id,
        RetrievalIndexMaterialsWrite(material_ids=[material_id], cloud_consent=True),
    )
    assert len(result.job_ids) == 1


def test_add_material_to_index_updates_manifest_without_duplicate_chunks(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    material = make_material(session, "104")
    add_page_with_fragments(
        session, material, page_number=1, revision=1, fragments=["Текст источника для индекса"]
    )
    profile = _profile(session)
    index = _index(session, profile)
    index.state = RetrievalIndexState.ACTIVE
    session.add(RetrievalSettings(id=1, active_index_id=index.id, default_profile_id=profile.id))
    session.commit()
    index_id, material_id = index.id, material.id

    class Backend:
        async def embed_documents(self, texts: list[str]) -> list[list[float]]:
            return [[1.0, 0.0] for _ in texts]

    monkeypatch.setattr(indexing_service, "backend_for_profile", lambda *_: Backend())
    for _ in range(2):
        response = queue_index_materials(
            session, index_id, RetrievalIndexMaterialsWrite(material_ids=[material_id])
        )
        job = session.get(BackgroundJob, response.job_ids[0])
        assert job is not None
        process_index_job(session, job)
        session.expire_all()
        saved = session.get(RetrievalIndex, index_id)
        assert saved is not None
        assert saved.indexed_material_count == saved.material_count == 1
        assert saved.chunk_count == 1
        assert len(saved.corpus_manifest) == 1
        assert len(list(session.scalars(select(RetrievalChunk)))) == 1
        session.commit()


def test_index_build_can_pause_resume_and_finish_as_partial_candidate(session: Session) -> None:
    """Управление сбором не выбрасывает candidate и не выдаёт его за полный."""
    profile = _profile(session)
    index = _index(session, profile)
    index.state = RetrievalIndexState.BUILDING
    index.material_count = 5
    index.indexed_material_count = 2
    job = BackgroundJob(
        id=uuid4(),
        kind=BackgroundJobKind.RETRIEVAL_INDEX,
        state=BackgroundJobState.QUEUED,
        total=5,
        done=2,
        checkpoint={"index_id": str(index.id), "profile_id": str(profile.id)},
    )
    session.add(job)
    session.commit()

    assert pause_index_build(session, job.id).state == BackgroundJobState.PAUSED
    assert resume_index_build(session, job.id).state == BackgroundJobState.QUEUED
    assert finish_index_build(session, job.id).state == BackgroundJobState.COMPLETED

    session.expire_all()
    saved = session.get(RetrievalIndex, index.id)
    assert saved is not None
    assert saved.state == RetrievalIndexState.READY
    assert saved.indexed_material_count == 2
    assert "проиндексировано 2 из 5" in saved.diagnostics[-1]


def test_partial_index_controls_reject_incremental_reindex(session: Session) -> None:
    """Остановка одного обновления не должна переводить активный индекс в candidate."""
    profile = _profile(session)
    index = _index(session, profile)
    job = BackgroundJob(
        id=uuid4(),
        kind=BackgroundJobKind.RETRIEVAL_INDEX,
        state=BackgroundJobState.QUEUED,
        checkpoint={"index_id": str(index.id), "mode": "incremental"},
    )
    session.add(job)
    session.commit()

    with pytest.raises(ProjectConflictError) as excinfo:
        finish_index_build(session, job.id)

    assert excinfo.value.code == "retrieval_index_incremental_control_unsupported"


def test_incremental_reindex_cancels_without_changing_active_index(session: Session) -> None:
    """Крестик в общем фоне отменяет один материал, а не partial candidate."""
    material = make_material(session, "96")
    add_page_with_fragments(
        session, material, page_number=1, revision=1, fragments=["Текст для вектора"]
    )
    profile = _profile(session)
    index = _index(session, profile)
    index.state = RetrievalIndexState.ACTIVE
    session.add(RetrievalSettings(id=1, active_index_id=index.id, default_profile_id=profile.id))
    session.commit()

    queue_incremental_reindex(session, material.id)
    session.commit()
    job = session.scalar(
        select(BackgroundJob).where(
            BackgroundJob.kind == BackgroundJobKind.RETRIEVAL_INDEX,
            BackgroundJob.material_id == material.id,
        )
    )
    assert job is not None
    job.state = BackgroundJobState.RUNNING
    session.commit()

    cancelled = cancel_job(session, job.id)
    assert cancelled.state == BackgroundJobState.RUNNING
    assert cancelled.pause_requested is True

    detached = session.get(BackgroundJob, job.id)
    assert detached is not None
    process_index_job(session, detached)

    session.expire_all()
    saved_job = session.get(BackgroundJob, job.id)
    saved_index = session.get(RetrievalIndex, index.id)
    assert saved_job is not None and saved_job.state == BackgroundJobState.CANCELLED
    assert saved_index is not None and saved_index.state == RetrievalIndexState.ACTIVE
    assert saved_index.chunk_count == 0


def test_model_install_survives_another_writer_during_download(
    session: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Скачивание идёт минутами; за это время база уходит вперёд.

    Пока задача держала снимок через всё скачивание, SQLite отказывал в записи
    результата, и успешно скачанная модель отмечалась как провал установки.
    """
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    job_id = local_models.start_install(session, "tentex-test/embeddings", None)

    def fake_download(*args: object, **kwargs: object) -> None:
        assert not session.in_transaction()
        with Session(session.get_bind(), expire_on_commit=False) as other:
            other.add(RetrievalSettings(id=1, preset=RetrievalPreset.FAST))
            other.commit()
        Path(str(kwargs["local_dir"])).mkdir(parents=True, exist_ok=True)
        # Недокачанный каталог не выдаёт себя за установленную модель.
        assert not local_models.model_path("tentex-test/embeddings").exists()
        assert local_models.start_install(session, "tentex-test/embeddings", None) == job_id

    monkeypatch.setattr(local_models, "snapshot_download", fake_download)
    monkeypatch.setattr(local_models, "hf_hub_download", fake_download)
    monkeypatch.setattr(local_models, "list_repo_files", lambda *_, **__: ["model.safetensors"])
    detached = session.get(BackgroundJob, job_id)
    assert detached is not None
    local_models.process_install_job(session, detached)

    session.expire_all()
    job = session.get(BackgroundJob, job_id)
    assert job is not None
    assert job.state == BackgroundJobState.COMPLETED
    assert job.error is None
    assert job.done == job.total
    assert local_models.model_path("tentex-test/embeddings").is_dir()
    assert not local_models._partial_path("tentex-test/embeddings").exists()


def test_exhaustive_run_requires_confirmation_with_corpus_snapshot(session: Session) -> None:
    project = Project(
        id=uuid4(),
        template_key=TemplateKey.FREE,
        workspace_variant=WorkspaceVariant.TEXTBOOK,
        status=ProjectStatus.ACTIVE,
        name="Свободное изучение",
        created_at=utc_now(),
        updated_at=utc_now(),
    )
    material = make_material(session, "94")
    session.add(project)
    session.add(
        ProjectMaterial(
            project_id=project.id,
            material_id=material.id,
            source_role=SourceRole.MAIN,
            purposes=[],
        )
    )
    session.commit()
    chat = chat_service.create_session(session, project.id, None)

    with pytest.raises(ProjectConflictError) as excinfo:
        start_run(
            session,
            project.id,
            chat.id,
            ExhaustiveRunWrite(
                query="Что говорится во всех источниках?",
                scope=RetrievalScope.PROJECT,
            ),
        )

    assert excinfo.value.code == "retrieval_exhaustive_confirmation_required"
    assert excinfo.value.context["material_count"] == 1


def test_first_tested_profile_becomes_default_for_index_build(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Без выбранного профиля кнопка «Собрать кандидат» серая, а причина не видна."""
    import asyncio

    from app.retrieval import settings as retrieval_settings

    first, second = _profile(session), _profile(session)

    class _Backend:
        async def embed_documents(self, texts: list[str]) -> list[list[float]]:
            return [[0.1, 0.2, 0.3] for _ in texts]

    monkeypatch.setattr(retrieval_settings, "backend_for_profile", lambda *_: _Backend())

    asyncio.run(retrieval_settings.test_profile(session, first.id))
    asyncio.run(retrieval_settings.test_profile(session, second.id))

    session.expire_all()
    row = session.get(RetrievalSettings, 1)
    assert row is not None and row.default_profile_id == first.id


def _paragraph(seed: str, words: int) -> str:
    return " ".join(f"{seed}{number}" for number in range(words)) + "."


def _section(
    index: int,
    title: str,
    texts: list[str],
    *,
    heading_only: bool = False,
    level: int | None = None,
):
    from app.retrieval.chunking import Section

    atoms = [ChunkAtom(title, heading=True, section=index)] if heading_only else [
        ChunkAtom(text, uuid4(), section=index) for text in texts
    ]
    return Section(
        block_id=uuid4(), title=title, atoms=atoms, heading_only=heading_only, level=level
    )


def test_vector_search_reads_snapshot_and_sees_replaced_chunks(session: Session) -> None:
    """Векторы читаются из снимка в памяти, но замена кусков видна сразу."""
    from app.retrieval.vector import SqliteVecIndex, vector_blob

    material = make_material(session, "96")
    index = _index(session, _profile(session))

    def add_chunk(order: int, vector: list[float], revision: int = 1) -> UUID:
        chunk_id = uuid4()
        session.add(RetrievalChunk(
            id=chunk_id, index_id=index.id, material_id=material.id, revision=revision,
            kind=RetrievalChunkKind.TEXT, sort_order=order, title="Раздел",
            text=f"кусок {order}", token_count=2, fragment_ids=[], locator={},
            content_hash=str(order) * 64, embedding=vector_blob(vector),
        ))
        session.commit()
        return chunk_id

    near, far = add_chunk(0, [1.0, 0.0]), add_chunk(1, [0.0, 1.0])
    search = SqliteVecIndex().search

    def nearest() -> list[UUID]:
        hits = search(
            session, index_id=index.id, material_ids=[material.id],
            query_vector=[1.0, 0.1], limit=5,
        )
        return [hit.chunk_id for hit in hits]

    assert nearest() == [near, far]

    session.execute(delete(RetrievalChunk).where(RetrievalChunk.id == near))
    replacement = add_chunk(2, [0.9, 0.1])
    add_chunk(3, [1.0, 0.0], revision=2)

    # Кусок старой ревизии материала непригоден, даже если он ближе всех.
    assert nearest() == [replacement, far]


def test_section_parent_follows_numbering_and_chapter_marks() -> None:
    """Раньше родителем была последняя заголовочная секция где угодно выше:
    «Простейшая сеть из двух компьютеров» стояла над всей главой 3."""
    from app.retrieval.chunking import _Outline

    text = [_paragraph("текст", 30)]
    sections = [
        _section(0, "ГЛАВА 2 Общие принципы построения сетей", text),
        _section(1, "Простейшая сеть из двух компьютеров", [], heading_only=True, level=2),
        _section(2, "Совместное использование ресурсов", text, level=3),
        _section(3, "Проблемы связи нескольких компьютеров", text, level=1),
        _section(4, "ГЛАВА 3 Коммутация каналов и пакетов", text, level=1),
        _section(5, "Коммутация пакетов", text, level=2),
        _section(6, "2.2. Функции СУБД", [], heading_only=True),
        _section(7, "2.2.5. Управление транзакциями", text),
        _section(8, "2.2.6. Управление блокировками", text),
        _section(9, "Приложение Б. Основные термины", text),
    ]
    outline = _Outline(sections)

    assert outline.parent(2) == 1
    assert outline.parent(3) == 0
    assert outline.parent(4) is None
    assert outline.parent(5) == 4
    assert outline.parent(8) == 6
    assert outline.parent(9) is None


def test_material_chunks_skip_table_of_contents_and_bibliography(session: Session) -> None:
    material = make_material(session, "95")
    blocks = [
        ("Краткое содержание", ["Глава 1 . Эволюция сетей . . . . . . . . . . 25"]),
        (
            "ГЛАВА 1 Эволюция сетей",
            [
                _paragraph("эволюция", 60),
                "Глава 2 . Принципы построения . . . . . . . . . . . . 41",
            ],
        ),
        ("Рекомендуемая и использованная литература", ["1. Таненбаум Э. Компьютерные сети."]),
    ]
    for order, (title, fragments) in enumerate(blocks):
        page = add_page_with_fragments(
            session, material, page_number=order + 1, revision=1,
            block_title=title, fragments=fragments,
        )
        block = session.get(MaterialBlock, page.block_id)
        assert block is not None
        block.sort_order = 10 + order
        session.flush()

    chunks = material_chunks(session, material, target_tokens=100, max_tokens=160, overlap_tokens=0)
    text = "\n".join(chunk.text for chunk in chunks)

    assert "эволюция0" in text
    assert ". . . ." not in text
    assert "Таненбаум" not in text


def test_typst_preamble_and_graph_code_stay_out_of_chunks(session: Session) -> None:
    material = Material(
        id=uuid4(),
        sha256="6" * 64,
        original_name="main.typ",
        storage_path="typst/main.zip",
        media_type="application/zip",
        source_kind=MaterialSourceKind.TYPST,
        size_bytes=100,
        status=MaterialState.READY,
        active_parse_revision=1,
    )
    session.add(material)
    sources = [
        '#set page(margin: 1cm)\n#let mathbox(kind, body) = {\n  let palette = (\n'
        '    fill: rgb("#F7F9FC"),\n  )\n}',
        "== Раскраска графа // черновик\n\n#definition[\n  *Раскраской* графа называют "
        'приписывание цветов его вершинам.\n]\n#let graph = {\n  "strict graph {\n'
        '  x1 -- x2;\n  x2 -- x3;\n  }"\n}\nЧисло цветов принципиально минимизируют.',
    ]
    for order, source_text in enumerate(sources):
        session.add(
            TypstSourceChunk(
                material_id=material.id,
                revision=1,
                sort_order=order,
                path="main.typ",
                line_from=1 + order * 10,
                line_to=9 + order * 10,
                source_text=source_text,
                source_hash=str(order) * 64,
            )
        )
    session.commit()

    chunks = material_chunks(
        session, material, target_tokens=384, max_tokens=480, overlap_tokens=64
    )
    text = "\n".join(chunk.text for chunk in chunks)

    assert "mathbox" not in text
    assert "x1 -- x2" not in text
    assert "*Раскраской*" in text and "минимизируют" in text
    assert chunks[0].title == "Раскраска графа"
    assert chunks[0].locator["line_from"] == 11


def test_heading_only_section_joins_its_text_instead_of_becoming_a_chunk() -> None:
    """Заголовок родительского раздела раньше был отдельным куском из двух слов."""
    from app.retrieval.chunking import pack_sections

    sections = [
        _section(0, "Введение", [_paragraph("вводный", 150)]),
        _section(1, "Сети OTN", [], heading_only=True),
        _section(2, "Причины создания", [_paragraph("причина", 120)]),
    ]

    chunks = pack_sections(sections, target_tokens=200, max_tokens=260, overlap_tokens=20)

    assert [chunk[0].text for chunk in chunks] == [sections[0].atoms[0].text, "Сети OTN"]
    assert chunks[1][1].section == 2


def test_small_sections_merge_and_large_section_splits_without_tiny_tail() -> None:
    from app.retrieval.chunking import count_tokens, pack_sections

    sections = [
        _section(0, "17.1", [_paragraph("тупик", 20)]),
        _section(1, "17.2", [_paragraph("обход", 25)]),
        _section(
            2,
            "Большой раздел",
            [_paragraph(f"абзац{number}", 60) for number in range(9)],
        ),
    ]

    chunks = pack_sections(sections, target_tokens=200, max_tokens=260, overlap_tokens=20)
    sizes = [sum(count_tokens(atom.text) for atom in chunk) for chunk in chunks]

    assert {atom.section for atom in chunks[0]} >= {0, 1}
    assert max(sizes) <= 260
    assert min(sizes) >= 100


def test_material_chunks_drop_running_headers_and_page_numbers(session: Session) -> None:
    material = make_material(session, "93")
    block_id = None
    for page_number in range(1, 6):
        block_id = add_page_with_fragments(
            session,
            material,
            page_number=page_number,
            revision=1,
            block_title="Раздел 1",
            block_id=block_id,
            fragments=[
                str(100 + page_number),
                "Часть II. Технологии физического уровня",
                _paragraph(f"содержание{page_number}_", 40),
            ],
        ).block_id

    chunks = material_chunks(session, material, target_tokens=100, max_tokens=160, overlap_tokens=0)
    text = "\n".join(chunk.text for chunk in chunks)

    assert "Технологии физического уровня" not in text
    assert "101" not in text.split()
    assert "содержание1_0" in text
    assert chunks[0].embedding_text.startswith("Методичка — Раздел 1")


def test_lexical_hit_opens_the_chunk_that_contains_the_found_fragment(session: Session) -> None:
    """Совпадение в середине раздела раньше показывало первый кусок его блока."""
    import asyncio

    from app.bindings.search import reindex_material
    from app.retrieval.schemas import SearchStrategy
    from app.retrieval.search import HybridRetriever

    material = make_material(session, "94")
    page = add_page_with_fragments(
        session,
        material,
        page_number=1,
        revision=1,
        block_title="Транзакции",
        fragments=[
            "Транзакции и журнал упреждающей записи.",
            "Взаимоблокировка возникает при встречном захвате блокировок.",
            "Колонтитул с блокировкой",
        ],
    )
    reindex_material(session, material.id)
    session.commit()
    index = _index(session, _profile(session))
    index.state = RetrievalIndexState.ACTIVE
    session.add(RetrievalSettings(id=1, active_index_id=index.id))
    first, second = uuid4(), uuid4()
    for order, (chunk_id, fragment_id) in enumerate(
        [(first, page.fragment_ids[0]), (second, page.fragment_ids[1])]
    ):
        session.add(RetrievalChunk(
            id=chunk_id, index_id=index.id, material_id=material.id, revision=1,
            block_id=page.block_id, kind=RetrievalChunkKind.TEXT, sort_order=order,
            text=f"кусок {order}", token_count=2, content_hash=str(order).rjust(64, "0"),
            fragment_ids=[str(fragment_id)],
        ))
    session.commit()

    result = asyncio.run(HybridRetriever().search(session, RetrievalSearchWrite(
        query="блокировка",
        strategy=SearchStrategy.LEXICAL,
        scope=RetrievalScope.SELECTED_MATERIALS,
        material_ids=[material.id],
    )))

    assert [hit.locator.chunk_id for hit in result.results] == [second]


def test_lexical_search_keeps_fts_place_when_index_has_no_fragment_links(
    session: Session,
) -> None:
    """Отдельно индексируемый исходник не должен скрывать PDF-фрагменты из FTS."""
    import asyncio

    from app.bindings.search import reindex_material

    material = make_material(session, "93")
    page = add_page_with_fragments(
        session, material, page_number=1, revision=1,
        block_title="Раскраска графа",
        fragments=["Минимальное число цветов называют хроматическим числом графа."],
    )
    reindex_material(session, material.id)
    index = _index(session, _profile(session))
    index.state = RetrievalIndexState.ACTIVE
    session.add(RetrievalSettings(id=1, active_index_id=index.id))
    session.add(RetrievalChunk(
        index_id=index.id, material_id=material.id, revision=1,
        block_id=page.block_id, kind=RetrievalChunkKind.TEXT, sort_order=0,
        text="Отдельно прочитанный исходник.", token_count=4,
        content_hash="a" * 64, fragment_ids=[],
    ))
    session.commit()

    result = asyncio.run(HybridRetriever().search(session, RetrievalSearchWrite(
        query="хроматическое число", strategy=SearchStrategy.LEXICAL,
        scope=RetrievalScope.SELECTED_MATERIALS, material_ids=[material.id],
    )))

    assert len(result.results) == 1
    assert result.results[0].locator.chunk_id == page.fragment_ids[0]
    assert "Минимальное число цветов" in result.results[0].text


def test_known_embedding_models_get_their_query_and_document_templates(
    session: Session,
) -> None:
    from app.retrieval.schemas import EmbeddingProfileWrite
    from app.retrieval.settings import create_profile

    e5 = create_profile(session, EmbeddingProfileWrite(
        label="E5", backend_kind=EmbeddingBackendKind.LOCAL_HF,
        model_id="intfloat/multilingual-e5-base",
    ))
    qwen = create_profile(session, EmbeddingProfileWrite(
        label="Qwen", backend_kind=EmbeddingBackendKind.LOCAL_HF,
        model_id="Qwen/Qwen3-Embedding-0.6B",
    ))
    manual = create_profile(session, EmbeddingProfileWrite(
        label="Manual", backend_kind=EmbeddingBackendKind.LOCAL_HF,
        model_id="intfloat/multilingual-e5-small", query_template="q {text}",
    ))

    assert (e5.query_template, e5.document_template) == ("query: {text}", "passage: {text}")
    assert qwen.pooling == "last_token" and qwen.query_template.startswith("Instruct: ")
    assert (manual.query_template, manual.document_template) == ("q {text}", "{text}")


def test_search_collapses_duplicate_materials_and_keeps_chat_attribution(
    session: Session,
) -> None:
    first, duplicate, other = [make_material(session, str(number)) for number in (701, 702, 703)]
    first.display_name = "Первый"
    duplicate.display_name = "Копия"
    other.display_name = "Другой"
    index = _index(session, _profile(session))
    chunks = []
    for order, (material, content) in enumerate(
        [(first, "Общий текст"), (duplicate, "Общий  текст"), (other, "Другой текст")]
    ):
        chunk = RetrievalChunk(
            index_id=index.id, material_id=material.id, revision=1,
            kind=RetrievalChunkKind.TEXT, sort_order=order, text=content,
            token_count=2, content_hash=str(order).rjust(64, "0"),
            fragment_ids=[], locator={},
        )
        session.add(chunk)
        chunks.append(chunk)
    session.commit()

    ranking = [(chunk.id, 1.0 / (rank + 1), ["semantic"]) for rank, chunk in enumerate(chunks)]
    hits = HybridRetriever()._read_ranking(
        session, ranking, {chunk.id: chunk for chunk in chunks}, {}, limit=2,
    )
    assert [hit.locator.material_id for hit in hits] == [first.id, other.id]
    assert hits[0].also_in == ["Копия"]

    assembled = ContextAssembler().assemble(
        session,
        RetrievalSearchRead(
            query="общий", strategy=SearchStrategy.HYBRID, index_id=index.id,
            degraded=False, degradation_reasons=[], results=hits,
        ),
        neighbor_window=0,
    )
    assert assembled.also_in[chunks[0].id] == ["Копия"]


def test_chunk_title_uses_section_instead_of_generic_heading() -> None:
    sections = [
        Section(None, "ГЛАВА 3 Коммутация", [], True),
        Section(None, "Коммутация пакетов", [], False),
        Section(None, "ПРИМЕЧАНИЕ", [], False),
    ]
    outline = _Outline(sections)
    assert _chunk_title([ChunkAtom("Содержание примечания", section=2)], outline)[1] == (
        "ГЛАВА 3 Коммутация › Коммутация пакетов"
    )


def test_number_only_heading_joins_following_section_title() -> None:
    sections = [
        Section(None, "ГЛАВА 10 Алгебра", [], True),
        Section(None, "10.1.", [], True),
        Section(None, "Группы", [], False),
        Section(None, "Определение", [], False),
    ]
    outline = _Outline(sections)
    assert _chunk_title([ChunkAtom("Описание группы", section=2)], outline)[1] == (
        "ГЛАВА 10 Алгебра › 10.1. Группы"
    )
    assert _chunk_title([ChunkAtom("Аксиомы группы", section=3)], outline)[1] == (
        "ГЛАВА 10 Алгебра › 10.1. Группы"
    )


@pytest.mark.asyncio
async def test_e5_low_evidence_returns_no_match(session: Session, monkeypatch) -> None:
    """Слабая семантика и шумное слово не превращаются в десять ложных мест."""
    project = make_exam_project(session)
    material = make_material(session, "815")
    link_material(session, project, material)
    profile = _profile(session)
    profile.model_id = "intfloat/multilingual-e5-base"
    profile.query_template = "query: {text}"
    profile.document_template = "passage: {text}"
    index = _index(session, profile)
    index.corpus_manifest = [
        {"material_id": str(material.id), "revision": material.active_parse_revision}
    ]
    session.add(RetrievalSettings(id=1, active_index_id=index.id))
    session.commit()

    async def weak_semantic(*_args):
        return [VectorHit(uuid4(), distance=.19)]

    monkeypatch.setattr(HybridRetriever, "_semantic_ids", weak_semantic)
    monkeypatch.setattr("app.retrieval.search._lexical_candidates", lambda *_args: [])
    result = await HybridRetriever().search(session, RetrievalSearchWrite(
        query="иерархия скоростей OTN", project_id=project.id,
    ))
    assert result.no_relevant_match
    assert result.results == []
    lexical = await HybridRetriever().search(session, RetrievalSearchWrite(
        query="иерархия скоростей OTN", project_id=project.id,
        strategy=SearchStrategy.LEXICAL,
    ))
    assert lexical.no_relevant_match


def test_e5_gate_requires_the_measured_recipe(session: Session) -> None:
    from app.retrieval.search import _is_e5_index

    profile = _profile(session)
    profile.model_id = "intfloat/multilingual-e5-base"
    profile.query_template = "query: {text}"
    profile.document_template = "passage: {text}"
    index = _index(session, profile)

    assert _is_e5_index(session, index)
    profile.query_template = "{text}"
    assert not _is_e5_index(session, index)


def test_term_synonyms_replace_only_the_known_term() -> None:
    from app.materials.lexicon import with_synonyms

    assert with_synonyms("Как предотвратить взаимоблокировку процессов?") == (
        "Как предотвратить тупик процессов?"
    )
    assert with_synonyms("Формула Байеса") == "Формула Байеса"


def test_lexical_rescue_requires_most_query_terms() -> None:
    from types import SimpleNamespace

    partial = SimpleNamespace(text="процессы сети", block_title="Сеть")
    relevant = SimpleNamespace(
        text="Иерархия скоростей OTN описывает уровни передачи",
        block_title="Сети OTN",
    )
    query = "иерархия скоростей OTN"
    assert _lexical_coverage(query, [partial]) < .75
    assert _lexical_coverage(query, [relevant]) >= .75
    assert _lexical_coverage("коммут", [SimpleNamespace(
        text="Коммутатор передаёт кадр", block_title="Сети",
    )]) == 1


def test_formula_query_expands_symbols_only_when_the_answer_signal_is_stronger(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LaTeX-команды помогают формулам, но не вытесняют имена и редкие термины."""
    from types import SimpleNamespace

    formula = SimpleNamespace(
        text=r"Из $\neg A \to B$ и $\neg A \to \neg B$ следует $A$.",
        block_title="Приведение к абсурду",
    )
    weak = SimpleNamespace(text="Из A и B заключают A", block_title="")
    named = SimpleNamespace(
        text="Робинсон открыл правило резолюции: из G и F получают H.",
        block_title="Резолюция",
    )
    symbols_only = SimpleNamespace(text=r"$G \lor F, H \lor \neg F$", block_title="")
    query_with_answer = "Как из ¬A → B и ¬A → ¬B заключить A?"
    query_with_name = "Какое правило вывода открыл Робинсон и что получается из G ∨ F и H ∨ ¬F?"

    def candidates(_session, _ids, query, **_kwargs):
        if "Робинсон" in query:
            return SimpleNamespace(hits=[symbols_only if " lor " in query else named])
        return SimpleNamespace(hits=[formula if " neg " in query else weak])

    monkeypatch.setattr("app.retrieval.search.search_fragments", candidates)
    scope = ScopeFilter([uuid4()], None, "")

    assert _lexical_candidates(None, scope, query_with_answer, 10) == [formula]
    assert _lexical_candidates(None, scope, query_with_name, 10) == [named]
    assert _lexical_coverage(query_with_answer, [formula]) > .75



def test_specific_terms_are_names_acronyms_and_words_outside_the_dictionary() -> None:
    """Общее слово может быть синонимом учебника, имя и аббревиатура — нет."""
    from app.materials.lexicon import specific_terms

    assert specific_terms("Как работает протокол QUIC v2 согласно RFC 9369?") == [
        "QUIC", "v2", "RFC",
    ]
    assert specific_terms("Что такое бутстреп и шардирование?") == ["бутстреп", "шардирование"]
    assert specific_terms("Сформулируйте теорему Тьюринга") == ["Тьюринга"]
    assert specific_terms("Почему привилегии процесса меняются?") == []
    assert specific_terms("Найдите P(x) и F₁ при n = 17") == []
    # Английское слово строчными конспект мог написать по-русски; имя — нет.
    assert specific_terms("Что такое likelihood и self-attention?") == []
    assert specific_terms("Как WireGuard и io_uring работают в Linux?") == [
        "WireGuard", "io_uring", "Linux",
    ]
    # Части через дефис — одно имя, если каждая не короче двух знаков.
    assert specific_terms("Как определяется равновесие в модели IS-LM?") == ["IS-LM"]
    assert specific_terms("Чем B-tree отличается от A-B?") == []


def _economics_material(session: Session) -> Material:
    from app.bindings.search import reindex_material

    material = make_material(session, "92")
    add_page_with_fragments(
        session, material, page_number=1, revision=1, block_title="Безработица",
        fragments=["Закон Оукена связывает рост ВНП и норму безработицы.",
                   "Тупик в распределении ресурсов предотвращают заранее."],
    )
    reindex_material(session, material.id)
    session.commit()
    return material


def test_question_naming_an_absent_term_is_refused_with_that_term(session: Session) -> None:
    """Любое найденное место отвечало бы на другой вопрос — выдача пуста и объяснима."""
    import asyncio

    material = _economics_material(session)

    def search(query: str) -> RetrievalSearchRead:
        return asyncio.run(HybridRetriever().search(session, RetrievalSearchWrite(
            query=query, scope=RetrievalScope.SELECTED_MATERIALS, material_ids=[material.id],
        )))

    absent = search("Как рассчитать индекс Херфиндаля?")
    assert absent.no_relevant_match and absent.results == []
    assert absent.missing_terms == ["Херфиндаля"]
    # Имя через дефис уходит в FTS строкой в кавычках: без них это ошибка синтаксиса.
    assert search("Равновесие в модели IS-LM").missing_terms == ["IS-LM"]
    assert search("Метод Metropolis-Hastings").missing_terms == ["Metropolis-Hastings"]
    # Основа слова находит другую форму: «Оукена» в вопросе, «Оукена» и «Оукен» в тексте.
    assert search("Что утверждает закон Оукена?").results
    # Синоним из словаря терминов не считается отсутствующим словом.
    assert not search("Как предотвратить взаимоблокировку?").missing_terms


def test_unprocessed_material_does_not_switch_off_refusal(session: Session, monkeypatch) -> None:
    """Файл без текста не «устарел»: он не ищется вовсе и отказ по проекту не отменяет."""
    import asyncio

    project = make_exam_project(session)
    material = make_material(session, "816")
    link_material(session, project, material)
    pending = make_material(session, "817")
    pending.display_name = "Хабр.md"
    pending.status = MaterialState.READY_TO_PROCESS
    pending.active_parse_revision = 0
    link_material(session, project, pending)
    profile = _profile(session)
    profile.model_id = "intfloat/multilingual-e5-base"
    profile.query_template = "query: {text}"
    profile.document_template = "passage: {text}"
    index = _index(session, profile)
    index.corpus_manifest = [
        {"material_id": str(material.id), "revision": material.active_parse_revision}
    ]
    session.add(RetrievalSettings(id=1, active_index_id=index.id))
    session.commit()

    async def weak_semantic(*_args):
        return [VectorHit(uuid4(), distance=.19)]

    monkeypatch.setattr(HybridRetriever, "_semantic_ids", weak_semantic)
    monkeypatch.setattr("app.retrieval.search._lexical_candidates", lambda *_args: [])
    result = asyncio.run(HybridRetriever().search(session, RetrievalSearchWrite(
        query="иерархия скоростей передачи", project_id=project.id,
    )))

    assert result.no_relevant_match
    assert result.degradation_reasons == ["Не обработаны и в поиске не участвуют: Хабр.md"]


def test_accurate_preset_refuses_when_reranker_rejects_every_place(
    session: Session, monkeypatch
) -> None:
    """Reranker читает вопрос и кусок вместе; вероятность ниже 0,5 у всех — ответа нет."""
    import asyncio

    material = _economics_material(session)
    session.add(RetrievalSettings(id=1, preset=RetrievalPreset.ACCURATE))
    session.commit()
    probability = .2

    async def rerank(_query, ranking, *_args, **_kwargs):
        return [(item_id, probability, signals) for item_id, _, signals in ranking]

    monkeypatch.setattr("app.retrieval.search._rerank", rerank)

    def search() -> RetrievalSearchRead:
        return asyncio.run(HybridRetriever().search(session, RetrievalSearchWrite(
            query="норма безработицы", strategy=SearchStrategy.LEXICAL,
            scope=RetrievalScope.SELECTED_MATERIALS, material_ids=[material.id],
        )))

    assert search().no_relevant_match
    probability = .9
    assert search().results


def test_reranker_verdict_replaces_the_cosine_threshold(session: Session, monkeypatch) -> None:
    """Прочитав места, reranker решает сам; без него действует порог cosine E5."""
    import asyncio

    material = _economics_material(session)
    profile = _profile(session)
    profile.model_id = "intfloat/multilingual-e5-base"
    profile.query_template = "query: {text}"
    profile.document_template = "passage: {text}"
    index = _index(session, profile)
    index.corpus_manifest = [
        {"material_id": str(material.id), "revision": material.active_parse_revision}
    ]
    session.add(RetrievalSettings(
        id=1, active_index_id=index.id, preset=RetrievalPreset.ACCURATE,
    ))
    session.commit()
    available = True

    async def weak_semantic(*_args):
        return [VectorHit(uuid4(), distance=.19)]

    async def rerank(_query, ranking, *_args, **_kwargs):
        if not available:
            raise ConnectionError("модель не установлена")
        return [(item_id, .9, signals) for item_id, _, signals in ranking]

    monkeypatch.setattr(HybridRetriever, "_semantic_ids", weak_semantic)
    monkeypatch.setattr("app.retrieval.search._rerank", rerank)

    def search() -> RetrievalSearchRead:
        # Покрытие 2/3 ниже 0,75, cosine 0,81 ниже 0,83: без reranker — отказ.
        return asyncio.run(HybridRetriever().search(session, RetrievalSearchWrite(
            query="Как связаны рост ВНП и занятость?",
            scope=RetrievalScope.SELECTED_MATERIALS, material_ids=[material.id],
        )))

    assert search().results
    available = False
    assert search().no_relevant_match
