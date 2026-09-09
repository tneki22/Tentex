from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.schemas import AiDefaultWrite, AiModelSelection
from app.ai.settings import credential_status, set_default
from app.models import (
    AiModelCatalogEntry,
    AiProviderConnection,
    AiSettings,
    OcrEngineConfig,
    OcrSettings,
    utc_now,
)
from app.ocr import cloud_catalog, downloads
from app.ocr.catalog import (
    LICENSE_TITLE,
    LICENSE_URL,
    MODELS_BY_KEY,
    SOURCE_TITLE,
    SOURCE_URL,
    OcrModelSpec,
    models_for,
)
from app.ocr.engines import (
    CLOUD_STRATEGY_HINTS,
    CLOUD_STRATEGY_TITLES,
    DEFAULT_CLOUD_STRATEGY,
    OCR_ENGINES,
    CloudStrategy,
    OcrRuntimeParams,
)
from app.ocr.schemas import (
    OcrCloudModelRead,
    OcrCloudRead,
    OcrCloudSettingsWrite,
    OcrCloudStrategyRead,
    OcrEngineRead,
    OcrEngineWrite,
    OcrGlobalSettingsWrite,
    OcrModelRead,
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
    return OcrRuntimeParams(
        quality_threshold=row.quality_threshold if row else defaults.quality_threshold,
        raster_scale=row.raster_scale if row else defaults.raster_scale,
        fast_language=defaults.fast_language,
        fast_model_id=(fast.model_id if fast and fast.model_id else defaults.fast_model_id),
        cloud_strategy=_cloud_strategy(session),
    )


def _cloud_strategy(session: Session) -> CloudStrategy:
    """Как режим «Облако» делит работу между файлом и моделью."""
    row = session.get(OcrEngineConfig, "cloud")
    value = row.extra.get("strategy") if row else None
    return value if value in CLOUD_STRATEGY_TITLES else DEFAULT_CLOUD_STRATEGY


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
    if spec.runtime == "cloud":
        raise ProjectDomainError(
            "Облачный режим настраивается отдельно: провайдер, модель и стратегия",
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


def _model_fit(spec: OcrModelSpec) -> tuple[bool | None, str]:
    """Подойдёт ли набор этой машине.

    Оставшиеся движки считают на процессоре, поэтому вопрос закрыт заранее —
    отдельного замера железа (видеопамять, диск) в проекте больше нет.
    """
    if spec.device == "cpu":
        return True, "Считает на процессоре — подойдёт любой компьютер."
    return None, "Не удалось проверить."


def _model_read(spec: OcrModelSpec) -> OcrModelRead:
    job = downloads.job_for(spec.key)
    is_installed = downloads.installed(spec)
    fits, fits_note = _model_fit(spec)
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


def _vision_selection(session: Session) -> tuple[UUID | None, str | None]:
    """Какая модель сейчас распознаёт страницы. Источник один — настройки шлюза."""
    row = session.get(AiSettings, 1)
    if row is None:
        return None, None
    return row.default_vision_provider_id, row.default_vision_model_id


def _external_models_enabled(session: Session) -> bool:
    row = session.get(AiSettings, 1)
    return bool(row and row.external_models_enabled)


def _cloud_readiness(session: Session) -> tuple[str, str, str]:
    """Готов ли режим «Облако» прямо сейчас и чего ему не хватает.

    Порядок проверок повторяет порядок действий пользователя: сначала общий
    выключатель внешних моделей, потом выбранная модель, потом ключ провайдера.
    Иначе экран советовал бы выбрать модель тому, у кого весь раздел выключен.
    """
    if not _external_models_enabled(session):
        return (
            "unavailable",
            "Внешние модели выключены. Включите их в разделе «Модели» — там же ключи и лимиты.",
            "",
        )
    provider_id, model_id = _vision_selection(session)
    if provider_id is None or model_id is None:
        return "needs_models", "Выберите модель, которая принимает изображения.", ""
    if not credential_status(session, provider_id):
        return "error", "У провайдера этой модели нет ключа доступа.", model_id
    return "ready", "", model_id


def _model_price(
    session: Session, provider_id: UUID | None, model_id: str | None
) -> Decimal | None:
    if provider_id is None or model_id is None:
        return None
    row = session.get(AiModelCatalogEntry, (provider_id, model_id))
    if row is None:
        return None
    return cloud_catalog.price_per_page(row.prompt_price_usd, row.completion_price_usd)


def _cloud_read(session: Session) -> OcrCloudRead:
    """Состояние режима «Облако» для экрана: модель, стратегия и цена страницы."""
    provider_id, model_id = _vision_selection(session)
    provider = session.get(AiProviderConnection, provider_id) if provider_id else None
    return OcrCloudRead(
        external_models_enabled=_external_models_enabled(session),
        provider_id=provider_id,
        provider_label=provider.label if provider else "",
        model_id=model_id,
        strategy=_cloud_strategy(session),
        strategies=[
            OcrCloudStrategyRead(
                value=value,  # type: ignore[arg-type]
                title=title,
                hint=CLOUD_STRATEGY_HINTS[value],  # type: ignore[index]
            )
            for value, title in CLOUD_STRATEGY_TITLES.items()
        ],
        price_per_page_usd=_model_price(session, provider_id, model_id),
    )


def cloud_models(session: Session) -> list[OcrCloudModelRead]:
    """Кандидаты в распознаватели страниц из уже добавленных моделей.

    Список строится по локальному каталогу, а не запросом к провайдеру: модели
    добавляются в разделе «Модели», и распознавание не должно заводить второй
    способ их искать. Непригодные не прячутся — рядом с ними написано, чем
    именно они не подошли, иначе выбор выглядит произволом.
    """
    rows = session.execute(
        select(AiModelCatalogEntry, AiProviderConnection)
        .join(AiProviderConnection, AiProviderConnection.id == AiModelCatalogEntry.provider_id)
        .where(AiModelCatalogEntry.is_available.is_(True))
        .order_by(AiProviderConnection.label, AiModelCatalogEntry.display_name)
    ).all()
    result: list[OcrCloudModelRead] = []
    for model, provider in rows:
        decision = cloud_catalog.verdict(
            model_id=model.model_id,
            input_modalities=model.input_modalities,
            supported_parameters=model.supported_parameters,
            context_length=model.context_length,
            max_completion_tokens=model.max_completion_tokens,
            prompt_price_usd=model.prompt_price_usd,
            completion_price_usd=model.completion_price_usd,
        )
        if not decision.suitable and "image" not in model.input_modalities:
            # Текстовая модель в списке распознавателей — просто шум.
            continue
        result.append(
            OcrCloudModelRead(
                provider_id=provider.id,
                provider_label=provider.label,
                model_id=model.model_id,
                display_name=model.display_name,
                context_length=model.context_length,
                suitable=decision.suitable,
                reason=decision.reason,
                recommended_note=decision.recommended_note,
                price_per_page_usd=decision.price_per_page_usd,
            )
        )
    result.sort(key=lambda item: (not item.suitable, not item.recommended_note, item.display_name))
    return result


def update_cloud(session: Session, command: OcrCloudSettingsWrite) -> OcrSettingsRead:
    """Сохранить выбор модели и стратегию режима «Облако».

    Модель уезжает в настройки шлюза (`AiSettings.default_vision_*`), а не в
    строку движка: ключи, лимиты и учёт стоимости живут там, и раздваивать этот
    факт нельзя. В строке движка остаётся только то, что кроме распознавания
    никому не нужно, — стратегия.
    """
    selection = (
        AiModelSelection(provider_id=command.provider_id, model_id=command.model_id)
        if command.provider_id and command.model_id
        else None
    )
    # `set_default` сам проверяет, принимает ли модель картинки, и пишет выбор
    # одной транзакцией: непригодная модель не сохранится ни там, ни здесь.
    set_default(session, "vision", AiDefaultWrite(selection=selection))
    # Чтение в конце `set_default` оставляет открытую транзакцию, и следующий
    # `begin()` на неё натыкается. Разрываем явно — как между вызовами в тестах.
    session.rollback()
    with session.begin():
        row = _ensure_engine_row(session, "cloud")
        row.model_id = command.model_id
        row.extra = {**row.extra, "strategy": command.strategy}
        row.updated_at = utc_now()
    return read_settings(session)

def _engine_row(session: Session, mode: str) -> OcrEngineConfig | None:
    return session.get(OcrEngineConfig, mode)


def read_settings(session: Session) -> OcrSettingsRead:
    row = _ensure_settings_row(session)

    engines: list[OcrEngineRead] = []
    for spec in OCR_ENGINES.values():
        config_row = _engine_row(session, spec.key)
        models = [_model_read(model) for model in models_for(spec.key)]

        if spec.key == "fast":
            readiness, detail, active = _fast_readiness(models)
        elif spec.key == "cloud":
            readiness, detail, active = _cloud_readiness(session)
        else:
            readiness, detail, active = "unavailable", spec.unavailable_reason or "", ""

        engines.append(
            OcrEngineRead(
                mode=spec.key,
                title=spec.title,
                description=spec.description,
                trade_off=spec.trade_off,
                runtime=spec.runtime,
                enabled=config_row.enabled if config_row else True,
                available=readiness == "ready",
                readiness=readiness,  # type: ignore[arg-type]
                status_detail=detail,
                active_label=active,
                model_id=config_row.model_id if config_row else None,
                device=config_row.device if config_row else None,
                language=config_row.language if config_row else None,
                executor=config_row.executor if config_row else None,
                extra=config_row.extra if config_row else {},
                updated_at=config_row.updated_at if config_row else None,
                models=models,
            )
        )

    return OcrSettingsRead(
        default_mode=row.default_mode,
        quality_threshold=row.quality_threshold,
        raster_scale=row.raster_scale,
        engines=engines,
        cloud=_cloud_read(session),
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
