from pathlib import Path

import pytest
from pydantic import ValidationError
from sqlalchemy.exc import StatementError
from sqlalchemy.orm import Session

from app.config import settings as app_settings
from app.models import OcrSettings, ParserMode
from app.ocr import downloads
from app.ocr import settings as ocr_settings
from app.ocr.catalog import MODELS_BY_KEY, OCR_MODELS, ModelRepo
from app.ocr.engines import OcrRuntimeParams
from app.ocr.schemas import OcrEngineWrite, OcrGlobalSettingsWrite
from app.projects.errors import ProjectDomainError


def test_read_settings_creates_default_row_and_lists_full_registry(session: Session) -> None:
    snapshot = ocr_settings.read_settings(session)

    assert snapshot.default_mode == ParserMode.FAST
    assert snapshot.quality_threshold == 0.75
    assert snapshot.raster_scale == 2.0
    modes = {engine.mode: engine for engine in snapshot.engines}
    assert set(modes) == {"fast", "cloud"}
    assert modes["cloud"].configurable is False
    assert modes["cloud"].available is False
    assert modes["cloud"].readiness == "unavailable"
    assert modes["cloud"].status_detail
    assert modes["fast"].trade_off


def test_update_global_settings_persists(session: Session) -> None:
    updated = ocr_settings.update_global_settings(
        session,
        OcrGlobalSettingsWrite(
            default_mode=ParserMode.FAST, quality_threshold=0.6, raster_scale=1.5
        ),
    )

    assert updated.quality_threshold == 0.6
    assert updated.raster_scale == 1.5
    reread = ocr_settings.read_settings(session)
    assert reread.default_mode == ParserMode.FAST
    assert reread.raster_scale == 1.5


def test_global_settings_reject_unknown_raster_scale() -> None:
    with pytest.raises(ValidationError):
        OcrGlobalSettingsWrite(
            default_mode=ParserMode.FAST, quality_threshold=0.75, raster_scale=2.5
        )


def test_default_mode_column_rejects_invalid_value(session: Session) -> None:
    ocr_settings.read_settings(session)  # гарантирует, что строка id=1 уже создана
    with pytest.raises(StatementError, match="not-a-real-mode"):
        session.execute(
            OcrSettings.__table__.update()
            .where(OcrSettings.id == 1)
            .values(default_mode="not-a-real-mode")
        )
    session.rollback()


def test_update_engine_rejects_unknown_mode(session: Session) -> None:
    with pytest.raises(ProjectDomainError) as caught:
        ocr_settings.update_engine(session, "bogus", OcrEngineWrite())
    assert caught.value.code == "ocr_engine_not_found"


def test_update_engine_rejects_non_configurable_mode(session: Session) -> None:
    with pytest.raises(ProjectDomainError) as caught:
        ocr_settings.update_engine(session, "cloud", OcrEngineWrite())
    assert caught.value.code == "ocr_engine_not_configurable"


def test_runtime_params_defaults_without_saved_rows(session: Session) -> None:
    assert ocr_settings.runtime_params(session) == OcrRuntimeParams()


def test_runtime_params_reflects_saved_settings(session: Session) -> None:
    # Каждый вызов ниже сам открывает и коммитит транзакцию, но заканчивается
    # чтением (`read_settings`), которое неявно открывает новую. Следующему
    # `session.begin()` эта висящая транзакция мешает — тот же приём, что и в
    # test_ai_settings.py, разрывает её явным rollback() между вызовами.
    ocr_settings.update_global_settings(
        session,
        OcrGlobalSettingsWrite(
            default_mode=ParserMode.FAST, quality_threshold=0.6, raster_scale=3.0
        ),
    )
    session.rollback()
    ocr_settings.update_engine(
        session, "fast", OcrEngineWrite(model_id="PP-OCRv4", language="en")
    )

    params = ocr_settings.runtime_params(session)

    assert params.quality_threshold == 0.6
    assert params.raster_scale == 3.0
    assert params.fast_language == "ru"
    assert params.fast_model_id == "PP-OCRv4"


# ── Фазы 2–3: каталог, установка моделей ─────────────────────────────────────


@pytest.fixture
def empty_install(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Свежая установка: данные есть, моделей нет — как сразу после распаковки."""
    monkeypatch.setattr(app_settings, "data_dir", tmp_path)
    return tmp_path


def _models(session: Session) -> dict[str, object]:
    return {
        model.key: model
        for engine in ocr_settings.read_settings(session).engines
        for model in engine.models
    }


def test_catalog_points_at_one_signed_source(session: Session, empty_install: Path) -> None:
    """Веса приходят только из репозиториев PaddlePaddle на Hugging Face."""
    models = _models(session)

    assert set(models) == {spec.key for spec in OCR_MODELS}
    for model in models.values():
        assert model.repos, model.key
        assert all(repo.startswith("PaddlePaddle/") for repo in model.repos), model.key
        assert model.source_url == "https://huggingface.co/PaddlePaddle"
        assert model.license_title == "Apache 2.0"
        assert model.size_bytes > 0
        assert model.installed is False


def test_fast_engine_stays_usable_without_models(session: Session, empty_install: Path) -> None:
    """Текстовый PDF разбирается и на пустой установке — блокировать нечего."""
    engine = next(
        item for item in ocr_settings.read_settings(session).engines if item.mode == "fast"
    )

    assert engine.readiness == "ready"
    assert engine.available is True
    assert "скачаются сами" in engine.status_detail


def test_cpu_model_fits_any_machine(session: Session, empty_install: Path) -> None:
    """Единственный оставшийся движок считает на процессоре — подойдёт всегда."""
    models = _models(session)

    assert models["fast-ru"].fits is True
    assert models["fast-ru"].fits_note


def _install(root: Path, model_key: str) -> None:
    for repo in MODELS_BY_KEY[model_key].repos:
        directory = root / "models" / "official_models" / repo.folder
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "inference.pdiparams").write_bytes(b"0" * 2_000_000)
        (directory / "inference.yml").write_text("Global: {}\n", encoding="utf-8")


def test_installed_model_is_detected_by_weight_file(
    session: Session, empty_install: Path
) -> None:
    _install(empty_install, "fast-ru")

    engine = next(
        item for item in ocr_settings.read_settings(session).engines if item.mode == "fast"
    )
    model = next(item for item in engine.models if item.key == "fast-ru")

    assert model.installed is True
    assert model.installed_bytes > 1_000_000
    assert engine.status_detail == ""
    assert engine.active_label == MODELS_BY_KEY["fast-ru"].title


def test_catalog_keeps_only_one_fast_profile(session: Session, empty_install: Path) -> None:
    models = _models(session)

    assert set(models) == {"fast-ru"}
    assert set(MODELS_BY_KEY) == {"fast-ru"}
    assert models["fast-ru"].recommended is True


def test_partial_huggingface_cache_is_not_an_installed_model(
    session: Session, empty_install: Path
) -> None:
    repo = ModelRepo("PaddlePaddle/example-vl", 2_000_000, layout="hf_cache")
    directory = downloads._repo_dir(repo) / "blobs"
    directory.mkdir(parents=True)
    (directory / "partial.safetensors").write_bytes(b"0" * 2_000_000)

    assert downloads.repo_installed(repo) is False

    downloads.mark_repo_complete(repo)

    assert downloads.repo_installed(repo) is True


def test_partial_paddlex_model_is_not_an_installed_model(empty_install: Path) -> None:
    repo = ModelRepo("PaddlePaddle/example-layout", 2_000_000)
    directory = downloads._repo_dir(repo)
    directory.mkdir(parents=True)
    (directory / "inference.pdiparams").write_bytes(b"0" * 2_000_000)

    assert downloads.repo_installed(repo) is False


def test_cancel_marks_the_job_before_the_next_download_chunk(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    job = downloads.InstallJob(model_key="fast-ru", total_bytes=96_000_000, current="weights.bin")
    monkeypatch.setattr(downloads, "_jobs", {"fast-ru": job})

    downloads.cancel_install("fast-ru")

    assert job.cancel_requested is True
    assert job.cancel.is_set()
    assert job.current == "Останавливаем загрузку…"


def test_unknown_model_key_is_a_domain_error(session: Session) -> None:
    with pytest.raises(ProjectDomainError) as caught:
        ocr_settings.install_model(session, "bogus")
    assert caught.value.code == "ocr_model_not_found"
