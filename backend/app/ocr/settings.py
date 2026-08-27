from __future__ import annotations

from sqlalchemy.orm import Session

from app.materials.parsers import textbook
from app.models import OcrEngineConfig, OcrSettings, utc_now
from app.ocr import downloads, hardware, service_control
from app.ocr.catalog import (
    LICENSE_TITLE,
    LICENSE_URL,
    MODELS_BY_KEY,
    SOURCE_TITLE,
    SOURCE_URL,
    OcrModelSpec,
    models_for,
)
from app.ocr.engines import OCR_ENGINES, OcrRuntimeParams
from app.ocr.schemas import (
    OcrEngineRead,
    OcrEngineWrite,
    OcrGlobalSettingsWrite,
    OcrGpuRead,
    OcrHardwareRead,
    OcrModelRead,
    OcrServiceRead,
    OcrSettingsRead,
)
from app.projects.errors import ProjectDomainError


def _ensure_settings_row(session: Session) -> OcrSettings:
    row = session.get(OcrSettings, 1)
    if row is None:
        row = OcrSettings(id=1)
        session.add(row)
        session.flush()
    return row


def _ensure_engine_row(session: Session, mode: str) -> OcrEngineConfig:
    row = session.get(OcrEngineConfig, mode)
    if row is None:
        row = OcrEngineConfig(mode=mode)
        session.add(row)
        session.flush()
    return row


def runtime_params(session: Session) -> OcrRuntimeParams:
    """Что реально применить к следующему разбору. Без сети — только БД."""
    defaults = OcrRuntimeParams()
    row = session.get(OcrSettings, 1)
    fast = session.get(OcrEngineConfig, "fast")
    textbook_row = session.get(OcrEngineConfig, "textbook")
    extra = textbook_row.extra if textbook_row else {}
    return OcrRuntimeParams(
        quality_threshold=row.quality_threshold if row else defaults.quality_threshold,
        raster_scale=row.raster_scale if row else defaults.raster_scale,
        fast_language=defaults.fast_language,
        fast_model_id=(fast.model_id if fast and fast.model_id else defaults.fast_model_id),
        textbook_base_url=extra.get("service_url") or None,
        textbook_timeout_seconds=extra.get("timeout_seconds") or None,
    )


def textbook_base_url(session: Session) -> str | None:
    """Настроенный адрес GPU-сервиса, если пользователь его менял. `None` — дефолт конфига."""
    row = session.get(OcrEngineConfig, "textbook")
    return (row.extra.get("service_url") if row else None) or None


def textbook_environment(session: Session) -> dict[str, str]:
    row = session.get(OcrEngineConfig, "textbook")
    return service_control.environment_for(
        None,
        row.device if row else None,
        None,
    )


def update_global_settings(session: Session, command: OcrGlobalSettingsWrite) -> OcrSettingsRead:
    with session.begin():
        row = _ensure_settings_row(session)
        row.default_mode = command.default_mode
        row.quality_threshold = command.quality_threshold
        row.raster_scale = command.raster_scale
        row.updated_at = utc_now()
    return read_settings(session)


def _configurable_spec(mode: str):
    spec = OCR_ENGINES.get(mode)
    if spec is None:
        raise ProjectDomainError(
            "Такого движка распознавания нет",
            status=404,
            code="ocr_engine_not_found",
            context={"mode": mode},
        )
    if not spec.configurable:
        raise ProjectDomainError(
            "Этот режим ещё нельзя настроить",
            status=409,
            code="ocr_engine_not_configurable",
            context={"mode": mode},
        )
    return spec


def update_engine(session: Session, mode: str, command: OcrEngineWrite) -> OcrSettingsRead:
    _configurable_spec(mode)
    with session.begin():
        row = _ensure_engine_row(session, mode)
        row.model_id = command.model_id
        row.device = command.device
        row.language = "ru" if mode == "fast" else command.language
        row.executor = command.executor
        row.extra = command.extra
        row.updated_at = utc_now()
    return read_settings(session)


def install_model(session: Session, model_key: str) -> OcrSettingsRead:
    if model_key not in MODELS_BY_KEY:
        raise ProjectDomainError(
            "Такого набора моделей нет",
            status=404,
            code="ocr_model_not_found",
            context={"model": model_key},
        )
    downloads.start_install(model_key)
    return read_settings(session)


def cancel_model(session: Session, model_key: str) -> OcrSettingsRead:
    if model_key not in MODELS_BY_KEY:
        raise ProjectDomainError(
            "Такого набора моделей нет",
            status=404,
            code="ocr_model_not_found",
            context={"model": model_key},
        )
    downloads.cancel_install(model_key)
    return read_settings(session)


def remove_model(session: Session, model_key: str) -> OcrSettingsRead:
    if model_key not in MODELS_BY_KEY:
        raise ProjectDomainError(
            "Такого набора моделей нет",
            status=404,
            code="ocr_model_not_found",
            context={"model": model_key},
        )
    job = downloads.job_for(model_key)
    if job is not None and job.state == "running":
        raise ProjectDomainError(
            "Сначала остановите загрузку этого набора",
            status=409,
            code="ocr_model_busy",
            context={"model": model_key},
        )
    downloads.remove(model_key)
    return read_settings(session)


def start_service(session: Session) -> OcrSettingsRead:
    service_control.start(textbook_environment(session))
    hardware.reset_cache()
    textbook.reset_health_cache()
    return read_settings(session)


def stop_service(session: Session) -> OcrSettingsRead:
    service_control.stop()
    textbook.reset_health_cache()
    return read_settings(session)


def _model_read(spec: OcrModelSpec, machine: hardware.Hardware) -> OcrModelRead:
    job = downloads.job_for(spec.key)
    is_installed = downloads.installed(spec)
    fits, fits_note = hardware.fits(
        machine,
        device=spec.device,
        min_vram_mb=spec.min_vram_mb,
        min_ram_mb=spec.min_ram_mb,
        size_bytes=spec.size_bytes,
    )
    return OcrModelRead(
        key=spec.key,
        engine=spec.engine,
        title=spec.title,
        summary=spec.summary,
        good_for=spec.good_for,
        source_title=SOURCE_TITLE,
        source_url=SOURCE_URL,
        repos=[repo.repo_id for repo in spec.repos],
        license_title=LICENSE_TITLE,
        license_url=LICENSE_URL,
        size_bytes=spec.size_bytes,
        device=spec.device,
        languages=spec.languages,
        min_vram_mb=spec.min_vram_mb,
        recommended_vram_mb=spec.recommended_vram_mb,
        min_ram_mb=spec.min_ram_mb,
        notes=list(spec.notes),
        recommended=spec.recommended,
        installed=is_installed,
        installed_bytes=downloads.bytes_on_disk(spec),
        fits=fits,
        fits_note=fits_note,
        job_state=job.state if job else None,  # type: ignore[arg-type]
        job_cancel_requested=job.cancel_requested if job else False,
        job_done_bytes=job.done_bytes if job else 0,
        job_total_bytes=job.total_bytes if job else 0,
        job_current=job.current if job else "",
        job_error=job.error if job else "",
    )


def _downloading(models: list[OcrModelRead]) -> bool:
    return any(model.job_state == "running" for model in models)


def _fast_readiness(models: list[OcrModelRead]) -> tuple[str, str, str]:
    """«Быстро» готов всегда, и это не поблажка.

    Он умеет две разные вещи: забрать готовый текст из PDF — для этого моделей
    не нужно вовсе — и распознать скан. Во втором случае PaddleOCR докачает
    веса сам при первом обращении. Блокировать запуск из-за отсутствующих
    моделей значило бы запретить разбирать обычные текстовые PDF.
    """
    if _downloading(models):
        return "downloading", "Модели загружаются.", ""
    ready = [model for model in models if model.installed]
    if not ready:
        return (
            "ready",
            "Моделей на диске нет. Готовый текст из PDF разберётся и так, а перед "
            "первым сканом они скачаются сами — поставьте набор заранее, чтобы "
            "выбрать язык и не ждать посреди работы.",
            "Только готовый текст из файла",
        )
    return "ready", "", ", ".join(model.title for model in ready)


def _textbook_readiness(
    models: list[OcrModelRead], service: OcrServiceRead, base_url: str | None
) -> tuple[str, str, str]:
    if _downloading(models):
        return "downloading", "Модели загружаются.", ""
    if not downloads.engine_ready("textbook"):
        return "needs_models", "Ни один набор моделей не установлен.", ""
    current = textbook.status(base_url=base_url)
    if current.available:
        return "ready", "", current.label
    if service.state == "running":
        return "starting", current.reason, ""
    if service.state == "starting":
        return "starting", "Сервис поднимается.", ""
    if service.state == "failed":
        return "error", service.detail or service.summary, ""
    return "needs_service", service.detail or service.summary, ""


def _engine_row(session: Session, mode: str) -> OcrEngineConfig | None:
    return session.get(OcrEngineConfig, mode)


def read_settings(session: Session) -> OcrSettingsRead:
    row = _ensure_settings_row(session)
    base_url = textbook_base_url(session)
    machine = hardware.probe(textbook_base_url=base_url)
    service: OcrServiceRead | None = None

    engines: list[OcrEngineRead] = []
    for spec in OCR_ENGINES.values():
        config_row = _engine_row(session, spec.key) if spec.configurable else None
        models = [_model_read(model, machine) for model in models_for(spec.key)]
        engine_service: OcrServiceRead | None = None
        restart_required = False

        if spec.key == "fast":
            readiness, detail, active = _fast_readiness(models)
        elif spec.key == "textbook":
            raw = service_control.describe()
            service = OcrServiceRead(
                state=raw.state,
                summary=raw.summary,
                detail=raw.detail,
                can_start=raw.can_start,
                can_stop=raw.can_stop,
            )
            engine_service = service
            readiness, detail, active = _textbook_readiness(models, service, base_url)
            restart_required = raw.state == "running" and not service_control.environment_applied(
                textbook_environment(session)
            )
        else:
            readiness, detail, active = "unavailable", spec.unavailable_reason or "", ""

        engines.append(
            OcrEngineRead(
                mode=spec.key,
                title=spec.title,
                description=spec.description,
                trade_off=spec.trade_off,
                runtime=spec.runtime,
                configurable=spec.configurable,
                enabled=spec.configurable and (config_row.enabled if config_row else True),
                available=readiness == "ready",
                readiness=readiness,  # type: ignore[arg-type]
                status_detail=detail,
                active_label=active,
                restart_required=restart_required,
                model_id=config_row.model_id if config_row else None,
                device=config_row.device if config_row else None,
                language=config_row.language if config_row else None,
                executor=config_row.executor if config_row else None,
                extra=config_row.extra if config_row else {},
                updated_at=config_row.updated_at if config_row else None,
                models=models,
                service=engine_service,
            )
        )

    return OcrSettingsRead(
        default_mode=row.default_mode,
        quality_threshold=row.quality_threshold,
        raster_scale=row.raster_scale,
        hardware=OcrHardwareRead(
            cpu_cores=machine.cpu_cores,
            ram_mb=machine.ram_mb,
            free_disk_mb=machine.free_disk_mb,
            gpu=(
                OcrGpuRead(
                    name=machine.gpu.name,
                    vram_mb=machine.gpu.vram_mb,
                    driver=machine.gpu.driver,
                    source=machine.gpu.source,
                )
                if machine.gpu
                else None
            ),
            gpu_reason=machine.gpu_reason,
            notes=list(machine.notes),
        ),
        engines=engines,
    )


def engine_ready(session: Session, mode: str) -> tuple[bool, str]:
    """Можно ли прямо сейчас запускать разбор этим движком.

    Одна проверка на всех: и экран настроек, и запуск обработки в Библиотеке
    отвечают на этот вопрос одинаково, иначе кнопка «Подготовить материал» и
    статус движка разъезжаются.
    """
    for engine in read_settings(session).engines:
        if engine.mode == mode:
            return engine.available, engine.status_detail
    return False, "Такого движка распознавания нет"
