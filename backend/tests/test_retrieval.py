from pathlib import Path
from uuid import uuid4

import pytest
from conftest import add_page_with_fragments, make_material
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.exam import chat as chat_service
from app.exam.router import _citation_error
from app.models import (
    BackgroundJob,
    BackgroundJobKind,
    BackgroundJobState,
    EmbeddingBackendKind,
    EmbeddingProfile,
    Material,
    MaterialSourceKind,
    MaterialState,
    PageQuality,
    Project,
    ProjectMaterial,
    ProjectStatus,
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
from app.retrieval import local_models
from app.retrieval.chunking import ChunkAtom, chunk_atoms, material_chunks
from app.retrieval.embeddings import _validate_vectors
from app.retrieval.exhaustive import start_run
from app.retrieval.indexing import activate_index, queue_incremental_reindex, start_index_build
from app.retrieval.schemas import ExhaustiveRunWrite, RetrievalIndexBuildWrite, RetrievalScope
from app.retrieval.vector import reciprocal_rank_fusion


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


def test_model_install_survives_another_writer_during_download(
    session: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Скачивание идёт минутами; за это время база уходит вперёд.

    Пока задача держала снимок через всё скачивание, SQLite отказывал в записи
    результата, и успешно скачанная модель отмечалась как провал установки.
    """
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    job_id = local_models.start_install(session, "tentex-test/embeddings", None)

    def fake_download(**kwargs: object) -> None:
        assert not session.in_transaction()
        with Session(session.get_bind(), expire_on_commit=False) as other:
            other.add(RetrievalSettings(id=1, preset=RetrievalPreset.FAST))
            other.commit()
        Path(str(kwargs["local_dir"])).mkdir(parents=True, exist_ok=True)
        # Недокачанный каталог не выдаёт себя за установленную модель.
        assert not local_models.model_path("tentex-test/embeddings").exists()
        assert local_models.start_install(session, "tentex-test/embeddings", None) == job_id

    monkeypatch.setattr(local_models, "snapshot_download", fake_download)
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


def test_citation_validator_rejects_missing_and_unknown_ids() -> None:
    manifest = [{"kind": "retrieval_source", "id": "S1"}]

    assert _citation_error("Факт без ссылки.", manifest) is not None
    assert _citation_error("Факт [S2].", manifest) is not None
    assert _citation_error("Факт [S1].", manifest) is None


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
