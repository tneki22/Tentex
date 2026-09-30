"""Публичные схемы сводки «Состояние»."""

from datetime import datetime
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

#: `danger` — серьёзный сбой, `warning` — замечание, `unknown` — проверить не
#: удалось, `info` — нейтральная настройка, `ok` — проверено и работает.
type StatusLevel = Literal["danger", "warning", "unknown", "info", "ok"]
#: Проблемы любого домена поднимаются в `attention`; `storage` и
#: `capabilities` держат спокойные строки своего блока.
type StatusSection = Literal["attention", "storage", "capabilities"]
type StatusOverall = Literal["attention", "warning", "ok"]
#: Команды, которые панель выполняет сама, без перехода в Параметры.
type StatusCommand = Literal[
    "probe_database", "create_backup", "verify_storage", "open_background_jobs"
]


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SystemStatusTarget(ApiModel):
    """Куда ведёт строка: ссылка в Параметры или команда самой панели."""

    kind: Literal["link", "command"]
    label: str
    href: str | None = None
    command: StatusCommand | None = None


class SystemStatusItem(ApiModel):
    #: Устойчивый машинный код строки — по нему фронтенд и тесты узнают случай.
    code: str
    level: StatusLevel
    section: StatusSection
    #: Что произошло — одной короткой фразой.
    title: str
    #: Что сделать; у нейтральных и зелёных строк — пояснение.
    action: str | None = None
    target: SystemStatusTarget | None = None
    #: Для сбоев из журнала и упавших операций — когда это случилось последний раз.
    last_failure_at: datetime | None = None
    occurrences: int | None = None


class SystemStorageRead(ApiModel):
    """Две постоянные строки блока «Хранилище»."""

    #: Сколько занимает Tentex; `None`, если база не ответила.
    used_bytes: int | None
    free_bytes: int
    total_bytes: int
    last_backup_at: datetime | None
    backup_in_progress: bool
    #: Расписание; `None`, если база не ответила.
    automatic_enabled: bool | None
    daily_time: str | None
    retention_days: int | None


class ResourceServiceRead(ApiModel):
    """Working set всего контейнера и CPU, включая процессы OCR/диагностики."""

    service: Literal["api", "worker", "retrieval-model"]
    sampled_at: AwareDatetime
    memory_bytes: int = Field(ge=0)
    cpu_percent: float | None = Field(default=None, ge=0, allow_inf_nan=False)


class SystemResourcesRead(ApiModel):
    """Сумма только измеренных серверов; пропуски сохраняются явно."""

    memory_bytes: int | None
    cpu_percent: float | None
    services: list[ResourceServiceRead]
    missing_services: list[str]


class SystemStatusRead(ApiModel):
    checked_at: datetime
    overall: StatusOverall
    #: Сколько строк требуют действия — число на кнопке «Состояние».
    attention_count: int
    items: list[SystemStatusItem]
    storage: SystemStorageRead | None
    resources: SystemResourcesRead | None = None


class SystemProbeRead(ApiModel):
    """Итог короткой пробы записи и свежая сводка после неё."""

    ok: bool
    status: SystemStatusRead
