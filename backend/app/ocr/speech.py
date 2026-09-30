"""Режимы расшифровки аудиоматериала: локальный Whisper и внешняя модель речи.

Живёт рядом с реестром распознавания страниц, потому что отвечает на тот же
вопрос — «можно ли сейчас запустить разбор этим способом», — и запуск разбора в
Библиотеке спрашивает его у одного места. Режимы называются так же, как у
страниц (`fast`/`cloud`): в задаче и в материале это то же поле `parser_mode`,
а вот смысл у аудио свой — `fast` это Whisper на процессоре, `cloud` — модель
речи из «Параметров ИИ».
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.ai.settings import AiGatewayError, credential_status, resolve_model
from app.config import settings
from app.models import AiProviderConnection, ParserMode
from app.ocr.schemas import SpeechEngineRead

# Роль шлюза, под которой уходят куски записи. Отдельная от диктовки: её можно
# выключить в «Параметрах ИИ», не отбирая у человека микрофон в чате, и в
# журнале расходов видно, что это расшифровка материала, а не реплика.
SPEECH_ROLE = "material_audio_transcription"

LOCAL_TITLE = "Локально"
CLOUD_TITLE = "Облако"

# Причина по коду отказа шлюза: человеку нужно «что сделать», а не «что упало».
_CLOUD_REASONS = {
    "ai_disabled": "Внешние модели выключены. Включите их в «Параметрах ИИ».",
    "ai_role_disabled": "Функция «Расшифровка аудио» выключена в «Параметрах ИИ».",
    "ai_model_not_configured": (
        "Не выбрана модель распознавания речи. Выберите её в «Параметрах ИИ» → «Для речи»."
    ),
    "ai_capability_unsupported": "Выбранная модель речи недоступна в каталоге провайдера.",
}


def local_model_label() -> str:
    return f"Whisper {settings.whisper_model}"


def _cloud_state(session: Session) -> tuple[bool, str, str, str]:
    """Готов ли облачный путь, что мешает, какая модель и чей провайдер."""
    try:
        resolved = resolve_model(session, SPEECH_ROLE)
    except AiGatewayError as error:
        reason = _CLOUD_REASONS.get(error.code, str(error))
        return False, reason, "", ""
    provider: AiProviderConnection = resolved.provider
    if not credential_status(session, provider.id):
        missing_key = "У провайдера модели речи нет ключа доступа."
        return False, missing_key, resolved.model_id, provider.label
    return True, "", resolved.model_id, provider.label


def cloud_model_label(session: Session) -> str:
    """Название модели речи для подписи задачи; пустая строка, если её нет."""
    return _cloud_state(session)[2]


def mode_label(session: Session, mode: ParserMode | None) -> str:
    """Чем расшифровывается запись: подпись для строки фоновой задачи."""
    if mode == ParserMode.CLOUD:
        return cloud_model_label(session) or "внешняя модель речи"
    return local_model_label()


def speech_engines(session: Session) -> list[SpeechEngineRead]:
    """Два способа расшифровки с готовностью каждого.

    Локальный «готов всегда»: пакет и веса живут в образе воркера, а не API, и
    из API проверить их нельзя. Осечку — нет пакета, не скачались веса —
    воркер сообщит текстом ошибки задачи.
    """
    cloud_ok, cloud_reason, model_id, provider_label = _cloud_state(session)
    return [
        SpeechEngineRead(
            mode=ParserMode.FAST,
            title=LOCAL_TITLE,
            description=(
                f"{local_model_label()} считает на процессоре: бесплатно, без интернета, "
                "запись не покидает компьютер. Точность заметно ниже облачной — на "
                "разговорной речи и голосовых сообщениях путает слова."
            ),
            available=True,
            status_detail="",
            model_label=local_model_label(),
            provider_label="",
        ),
        SpeechEngineRead(
            mode=ParserMode.CLOUD,
            title=CLOUD_TITLE,
            description=(
                "Запись уходит внешней модели речи частями по несколько минут. Заметно "
                "точнее и быстрее, но запись покидает компьютер и расшифровка стоит денег."
            ),
            available=cloud_ok,
            status_detail=cloud_reason,
            model_label=model_id,
            provider_label=provider_label,
        ),
    ]


def engine_ready(session: Session, mode: ParserMode) -> tuple[bool, str]:
    """Можно ли прямо сейчас расшифровывать запись выбранным способом."""
    for engine in speech_engines(session):
        if engine.mode == mode:
            return engine.available, engine.status_detail
    return False, "Такого способа расшифровки нет"
