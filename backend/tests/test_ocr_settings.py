from pathlib import Path

import pytest
from pydantic import ValidationError
from sqlalchemy.exc import StatementError
from sqlalchemy.orm import Session

from app.config import settings as app_settings
from app.materials.parsers import textbook
from app.models import OcrSettings, ParserMode
from app.ocr import downloads, hardware, service_control
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
    assert set(modes) == {"fast", "textbook", "cloud", "maximum", "expert"}
    assert modes["cloud"].configurable is False
    assert modes["cloud"].available is False
    assert modes["cloud"].readiness == "unavailable"
    assert modes["cloud"].status_detail
    assert modes["fast"].trade_off


def test_update_global_settings_persists(session: Session) -> None:
    updated = ocr_settings.update_global_settings(
        session,
        OcrGlobalSettingsWrite(
            default_mode=ParserMode.TEXTBOOK, quality_threshold=0.6, raster_scale=1.5
        ),
    )

    assert updated.default_mode == ParserMode.TEXTBOOK
    assert updated.quality_threshold == 0.6
    assert updated.raster_scale == 1.5
    reread = ocr_settings.read_settings(session)
    assert reread.default_mode == ParserMode.TEXTBOOK
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


def test_update_engine_persists_textbook_fields(session: Session) -> None:
    updated = ocr_settings.update_engine(
        session,
        "textbook",
        OcrEngineWrite(
            model_id="PP-StructureV3 + PP-FormulaNet Plus M",
            device="cpu",
            executor="structure",
            extra={"service_url": "http://gpu-box:8090", "timeout_seconds": 240},
        ),
    )

    engine = next(item for item in updated.engines if item.mode == "textbook")
    assert engine.device == "cpu"
    assert engine.executor == "structure"
    assert engine.extra["service_url"] == "http://gpu-box:8090"


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
    session.rollback()
    ocr_settings.update_engine(
        session,
        "textbook",
        OcrEngineWrite(extra={"service_url": "http://gpu-box:8090", "timeout_seconds": 240}),
    )

    params = ocr_settings.runtime_params(session)

    assert params.quality_threshold == 0.6
    assert params.raster_scale == 3.0
    assert params.fast_language == "ru"
    assert params.fast_model_id == "PP-OCRv4"
    assert params.textbook_base_url == "http://gpu-box:8090"
    assert params.textbook_timeout_seconds == 240


def test_engine_status_uses_configured_textbook_url(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    ocr_settings.update_engine(
        session, "textbook", OcrEngineWrite(extra={"service_url": "http://gpu-box:8090"})
    )
    seen_urls: list[str | None] = []

    def fake_status(*, base_url: str | None = None) -> textbook.TextbookStatus:
        seen_urls.append(base_url)
        return textbook.TextbookStatus(True, "PP-StructureV3 + PP-FormulaNet", "")

    monkeypatch.setattr(downloads, "engine_ready", lambda engine: True)
    monkeypatch.setattr(textbook, "status", fake_status)
    monkeypatch.setattr(
        service_control,
        "describe",
        lambda: service_control.ServiceStatus("running", "Сервис работает", can_stop=True),
    )
    monkeypatch.setattr(service_control, "environment_applied", lambda environment: True)

    snapshot = ocr_settings.read_settings(session)

    assert seen_urls == ["http://gpu-box:8090"]
    engine = next(item for item in snapshot.engines if item.mode == "textbook")
    assert engine.available is True


# ── Фазы 2–3: каталог, железо, установка моделей, управление сервисом ────────


@pytest.fixture
def empty_install(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Свежая установка: данные есть, моделей нет — как сразу после распаковки."""
    monkeypatch.setattr(app_settings, "data_dir", tmp_path)
    hardware.reset_cache()
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


def test_cpu_model_fits_any_machine_and_missing_card_is_not_a_no(
    session: Session, empty_install: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        hardware,
        "_probe",
        lambda base_url: hardware.Hardware(
            cpu_cores=8, ram_mb=32000, free_disk_mb=200000, gpu=None, gpu_reason="Карты нет."
        ),
    )
    hardware.reset_cache()

    models = _models(session)

    assert models["fast-ru"].fits is True
    # Видеокарты не видно — это «не знаем», а не «не подойдёт».
    assert models["textbook-formulas"].fits is None
    assert models["textbook-formulas"].min_vram_mb == 6000
    assert models["textbook-formulas"].notes


def test_small_card_is_reported_as_not_enough(
    session: Session, empty_install: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        hardware,
        "_probe",
        lambda base_url: hardware.Hardware(
            cpu_cores=8,
            ram_mb=32000,
            free_disk_mb=200000,
            gpu=hardware.Gpu("NVIDIA RTX 3050", 4000, "550.0", "nvidia-smi"),
        ),
    )
    hardware.reset_cache()

    models = _models(session)

    assert models["textbook-formulas"].fits is False
    assert "RTX 3050" in models["textbook-formulas"].fits_note
    assert models["fast-ru"].fits is True


def test_full_disk_blocks_installation(
    session: Session, empty_install: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        hardware,
        "_probe",
        lambda base_url: hardware.Hardware(
            cpu_cores=8, ram_mb=32000, free_disk_mb=200, gpu=None
        ),
    )
    hardware.reset_cache()

    assert _models(session)["fast-ru"].fits is False
    assert "диске" in _models(session)["fast-ru"].fits_note


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


def test_catalog_keeps_only_one_fast_and_one_textbook_profile(
    session: Session, empty_install: Path
) -> None:
    models = _models(session)

    assert set(models) == {"fast-ru", "textbook-formulas"}
    assert set(MODELS_BY_KEY) == {"fast-ru", "textbook-formulas"}
    assert models["textbook-formulas"].recommended is True
    assert models["textbook-formulas"].recommended_vram_mb == 8000


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


def test_service_start_pushes_engine_settings_into_the_container(
    session: Session, empty_install: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Выбранные модель, устройство и исполнитель доезжают до GPU-сервиса."""
    ocr_settings.update_engine(
        session,
        "textbook",
        OcrEngineWrite(
            model_id="PP-StructureV3 + PP-FormulaNet Plus M", device="gpu", executor="formulas"
        ),
    )
    session.rollback()
    started: list[dict[str, str]] = []

    def fake_start(environment: dict[str, str]) -> service_control.ServiceStatus:
        started.append(environment)
        return service_control.ServiceStatus("starting", "Сервис запускается")

    monkeypatch.setattr(service_control, "start", fake_start)
    monkeypatch.setattr(
        service_control,
        "describe",
        lambda: service_control.ServiceStatus("starting", "Сервис запускается", can_stop=True),
    )

    ocr_settings.start_service(session)

    assert started[0]["TENTEX_TEXTBOOK_EXECUTOR"] == "formulas"
    assert started[0]["TENTEX_TEXTBOOK_MODEL"] == "PP-StructureV3 + PP-FormulaNet Plus M"


def test_changed_settings_ask_for_a_restart(
    session: Session, empty_install: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(downloads, "engine_ready", lambda engine: True)
    monkeypatch.setattr(
        textbook, "status", lambda *, base_url=None: textbook.TextbookStatus(True, "VL", "")
    )
    monkeypatch.setattr(
        service_control,
        "describe",
        lambda: service_control.ServiceStatus("running", "Сервис работает", can_stop=True),
    )
    monkeypatch.setattr(service_control, "environment_applied", lambda environment: False)

    engine = next(
        item for item in ocr_settings.read_settings(session).engines if item.mode == "textbook"
    )

    assert engine.restart_required is True


def test_service_is_reported_unavailable_without_docker(
    session: Session, empty_install: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Без Docker кнопки нет, но экран не падает и объясняет причину."""
    monkeypatch.setattr(service_control.docker_engine, "available", lambda: False)

    engine = next(
        item for item in ocr_settings.read_settings(session).engines if item.mode == "textbook"
    )

    assert engine.service is not None
    assert engine.service.state == "unavailable"
    assert engine.service.can_start is False
    assert engine.service.detail
