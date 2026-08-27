from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_session
from app.materials.parsers import textbook
from app.ocr import hardware, service_control, settings
from app.ocr.schemas import OcrEngineWrite, OcrGlobalSettingsWrite, OcrSettingsRead

SessionDependency = Annotated[Session, Depends(get_session)]
router = APIRouter(prefix="/api/settings/ocr", tags=["ocr-settings"])


@router.get("", response_model=OcrSettingsRead)
def get_ocr_settings(session: SessionDependency, refresh: bool = False) -> OcrSettingsRead:
    # `refresh=true` — кнопка «Проверить ещё раз»: сбрасывает все замеры,
    # которые обычно держатся несколько секунд, чтобы экран не гонял
    # nvidia-smi, Docker и GPU-сервис на каждый обычный GET.
    if refresh:
        hardware.reset_cache()
        service_control.reset_cache()
        textbook.reset_health_cache()
    return settings.read_settings(session)


@router.put("", response_model=OcrSettingsRead)
def put_ocr_settings(
    command: OcrGlobalSettingsWrite, session: SessionDependency
) -> OcrSettingsRead:
    return settings.update_global_settings(session, command)


@router.put("/engines/{mode}", response_model=OcrSettingsRead)
def put_ocr_engine(
    mode: str, command: OcrEngineWrite, session: SessionDependency
) -> OcrSettingsRead:
    return settings.update_engine(session, mode, command)


# Загрузка отвечает сразу: сама она идёт в фоновом потоке, а прогресс приезжает
# следующим GET. Держать HTTP-запрос на двух гигабайтах нельзя.
@router.post("/models/{model_key}/install", response_model=OcrSettingsRead)
def install_model(model_key: str, session: SessionDependency) -> OcrSettingsRead:
    return settings.install_model(session, model_key)


@router.post("/models/{model_key}/cancel", response_model=OcrSettingsRead)
def cancel_model(model_key: str, session: SessionDependency) -> OcrSettingsRead:
    return settings.cancel_model(session, model_key)


@router.delete("/models/{model_key}", response_model=OcrSettingsRead)
def remove_model(model_key: str, session: SessionDependency) -> OcrSettingsRead:
    return settings.remove_model(session, model_key)


@router.post("/service/start", response_model=OcrSettingsRead)
def start_service(session: SessionDependency) -> OcrSettingsRead:
    return settings.start_service(session)


@router.post("/service/stop", response_model=OcrSettingsRead)
def stop_service(session: SessionDependency) -> OcrSettingsRead:
    return settings.stop_service(session)
