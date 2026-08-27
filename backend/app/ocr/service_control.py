"""Запуск и остановка GPU-сервиса «Учебник» кнопкой, а не командой в терминале.

Раньше экран настроек предлагал пользователю выполнить
`docker compose --profile textbook up`. Для продукта, который ставят из архива,
это не ответ: терминал открывать никто не обязан.

Как это устроено. Сервис живёт в отдельном контейнере, потому что для него
нужен образ с CUDA на несколько гигабайт, а держать его в основном образе ради
одного режима незачем. Управляем контейнером через сокет Docker: создаём при
первом запуске, дальше просто стартуем и останавливаем.

Пути томов берутся не из нашей файловой системы, а из описания **нашего
собственного** контейнера: только там записаны настоящие пути хоста, которые
демон Docker сможет разрешить.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Literal

from app.ocr import docker_engine
from app.ocr.engines import (
    DEFAULT_TEXTBOOK_DEVICE,
    DEFAULT_TEXTBOOK_EXECUTOR,
    DEFAULT_TEXTBOOK_MODEL_ID,
)

log = logging.getLogger("tentex.ocr.service")

SERVICE = "textbook-ocr"
DEFAULT_PROJECT = "tentex"
PORT = "8090"
# Экран настроек читает состояние сервиса на каждый GET, а `describe()` и
# `environment_applied()` внутри одного такого чтения спрашивают Docker о том
# же контейнере заново. Без кэша это лишние round-trip'ы к сокету на каждый
# запрос — который к тому же может быть не мгновенным (Docker Desktop поверх
# WSL2 и подобное).
_CONTAINER_CACHE_SECONDS = 3.0
_self_cache: tuple[dict[str, Any] | None] | None = None
_container_cache: tuple[float, str, dict[str, Any] | None] | None = None
# Id контейнера, который мы сами попросили остановить кнопкой «Остановить».
# PaddleX не обрабатывает SIGTERM: его C++-рантайм ловит сигнал сам, пишет
# трассировку и выходит ненулевым кодом. Без этой пометки такой выход было
# не отличить от настоящего падения — describe() показывал бы «сервис упал»
# после каждой обычной остановки.
_expected_stop_container: str | None = None

ServiceState = Literal["running", "starting", "stopped", "failed", "absent", "unavailable"]


@dataclass(frozen=True)
class ServiceStatus:
    state: ServiceState
    # Что показать пользователю одной строкой.
    summary: str
    # Подробность, если она есть: код выхода, хвост журнала, чего не хватает.
    detail: str = ""
    can_start: bool = False
    can_stop: bool = False


def _labels(project: str) -> dict[str, str]:
    return {
        "com.docker.compose.project": project,
        "com.docker.compose.service": SERVICE,
    }


def _self() -> dict[str, Any] | None:
    """Описание нашего собственного контейнера. Не меняется, пока API работает."""
    global _self_cache
    if _self_cache is None:
        _self_cache = (docker_engine.self_container(),)
    return _self_cache[0]


def _project(own: dict[str, Any] | None) -> str:
    labels = ((own or {}).get("Config") or {}).get("Labels") or {}
    return str(labels.get("com.docker.compose.project") or DEFAULT_PROJECT)


def _image(project: str) -> str:
    return f"{project}-{SERVICE}"


def _host_data_dir(own: dict[str, Any] | None) -> str | None:
    """Настоящий путь хоста для каталога данных — из наших собственных томов."""
    for mount in (own or {}).get("Mounts") or []:
        if isinstance(mount, dict) and mount.get("Destination") == "/data":
            source = str(mount.get("Source") or "")
            return source or None
    return None


def _network(own: dict[str, Any] | None) -> str | None:
    networks = ((own or {}).get("NetworkSettings") or {}).get("Networks") or {}
    for name in networks:
        return str(name)
    return None


def _container(project: str) -> dict[str, Any] | None:
    global _container_cache
    now = time.monotonic()
    if (
        _container_cache is not None
        and _container_cache[1] == project
        and now - _container_cache[0] < _CONTAINER_CACHE_SECONDS
    ):
        return _container_cache[2]
    found = docker_engine.find_container(_labels(project))
    _container_cache = (now, project, found)
    return found


def reset_cache() -> None:
    """Для тестов и сразу после запуска/остановки — статус не должен отставать.

    `_expected_stop_container` сюда не входит: кнопка «Проверить ещё раз» на
    экране настроек вызывает именно этот сброс, и он не должен стирать
    память о том, что последнюю остановку попросили мы сами.
    """
    global _self_cache, _container_cache
    _self_cache = None
    _container_cache = None


def _container_config(
    project: str,
    own: dict[str, Any] | None,
    environment: dict[str, str],
) -> dict[str, Any]:
    host_data = _host_data_dir(own)
    if not host_data:
        raise RuntimeError(
            "Не удалось определить, где на компьютере лежит каталог данных Tentex."
        )
    models = f"{host_data.rstrip('/')}/models"
    network = _network(own)
    config: dict[str, Any] = {
        "Image": _image(project),
        "Env": [f"{key}={value}" for key, value in environment.items()],
        "Labels": {
            **_labels(project),
            "com.docker.compose.container-number": "1",
            "com.docker.compose.oneoff": "False",
        },
        "ExposedPorts": {f"{PORT}/tcp": {}},
        "HostConfig": {
            "Binds": [
                f"{models}:/root/.paddlex",
                f"{models}/huggingface:/root/.cache/huggingface",
            ],
            "PortBindings": {f"{PORT}/tcp": [{"HostPort": PORT}]},
            "ShmSize": 2 * 1024 * 1024 * 1024,
            "RestartPolicy": {"Name": "unless-stopped"},
            # Просим все доступные видеокарты NVIDIA. То же самое, что
            # `deploy.resources.reservations.devices` в docker-compose.yml.
            "DeviceRequests": [
                {"Driver": "nvidia", "Count": -1, "Capabilities": [["gpu"]]}
            ],
        },
    }
    if network:
        config["HostConfig"]["NetworkMode"] = network
        config["NetworkingConfig"] = {
            # Псевдоним обязателен: воркер и API ходят по адресу
            # http://textbook-ocr:8090, а не по имени контейнера с суффиксом.
            "EndpointsConfig": {network: {"Aliases": [SERVICE]}}
        }
    return config


def environment_for(
    model_id: str | None, device: str | None, executor: str | None
) -> dict[str, str]:
    """Настройки движка «Учебник» из базы — в переменные окружения контейнера.

    Профиль «Учебник» фиксирован под видеокарту с 8 ГБ: экран передаёт только
    устройство, а сервис всегда запускает связку для формул.
    """
    return {
        "TENTEX_TEXTBOOK_MODEL": model_id or DEFAULT_TEXTBOOK_MODEL_ID,
        "TENTEX_TEXTBOOK_DEVICE": device or DEFAULT_TEXTBOOK_DEVICE,
        "TENTEX_TEXTBOOK_EXECUTOR": executor or DEFAULT_TEXTBOOK_EXECUTOR,
        "PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK": "True",
        "CUDA_VISIBLE_DEVICES": "0",
        "HF_HUB_DISABLE_XET": "0",
        "HF_XET_HIGH_PERFORMANCE": "1",
        "HOME": "/root",
    }


def describe() -> ServiceStatus:
    if not docker_engine.available():
        return ServiceStatus(
            "unavailable",
            "Управлять сервисом отсюда нельзя",
            "Tentex не видит Docker. Запустите сервис средствами, которыми "
            "запускали само приложение.",
        )
    own = _self()
    project = _project(own)
    found = _container(project)
    if found is None:
        if not docker_engine.image_exists(_image(project)):
            return ServiceStatus(
                "absent",
                "Сервис не собран",
                f"Образ «{_image(project)}» ещё не собран. Он большой (несколько "
                "гигабайт) и собирается один раз при установке с поддержкой видеокарты.",
            )
        return ServiceStatus(
            "stopped",
            "Сервис не запущен",
            "Контейнер создастся при первом запуске.",
            can_start=True,
        )

    state = str(found.get("State") or "")
    if state == "running":
        return ServiceStatus("running", "Сервис работает", can_stop=True)
    if state in {"created", "restarting"}:
        return ServiceStatus("starting", "Сервис запускается", can_stop=True)

    container_id = str(found.get("Id") or "")
    if container_id == _expected_stop_container:
        # Мы сами попросили остановиться через кнопку «Остановить». PaddleX
        # ловит SIGTERM своим обработчиком и всё равно выходит ненулевым
        # кодом — это ожидаемо, а не падение, и хвост журнала тут не причина,
        # а просто трассировка штатного завершения.
        return ServiceStatus("stopped", "Сервис остановлен", can_start=True)
    details = docker_engine.inspect_container(container_id) or {}
    exit_code = ((details.get("State") or {}).get("ExitCode")) if details else None
    if isinstance(exit_code, int) and exit_code != 0:
        return ServiceStatus(
            "failed",
            "Сервис остановился с ошибкой",
            docker_engine.tail_logs(container_id, 30) or f"Код выхода {exit_code}.",
            can_start=True,
        )
    return ServiceStatus("stopped", "Сервис не запущен", can_start=True)


def environment_applied(environment: dict[str, str]) -> bool:
    """Доехали ли настройки движка до уже запущенного контейнера.

    Контейнер читает их один раз при старте, поэтому смена модели или
    исполнителя требует перезапуска — экран должен сказать об этом честно, а не
    показывать «сохранено» и молчать.
    """
    if not docker_engine.available():
        return True
    found = _container(_project(_self()))
    if found is None:
        return True
    details = docker_engine.inspect_container(str(found.get("Id") or "")) or {}
    current = set((details.get("Config") or {}).get("Env") or [])
    return {f"{key}={value}" for key, value in environment.items()}.issubset(current)


def start(environment: dict[str, str]) -> ServiceStatus:
    global _container_cache, _expected_stop_container
    if not docker_engine.available():
        return describe()
    own = _self()
    project = _project(own)
    found = _container(project)
    try:
        if found is not None:
            container_id = str(found.get("Id") or "")
            # Настройки движка приезжают переменными окружения, а они
            # задаются при создании. Изменились — пересоздаём контейнер.
            details = docker_engine.inspect_container(container_id) or {}
            current = set((details.get("Config") or {}).get("Env") or [])
            wanted = {f"{key}={value}" for key, value in environment.items()}
            if not wanted.issubset(current):
                docker_engine.remove_container(container_id)
                found = None
        if found is None:
            if not docker_engine.image_exists(_image(project)):
                return describe()
            container_id = docker_engine.create_container(
                f"{project}-{SERVICE}-1", _container_config(project, own, environment)
            )
        else:
            container_id = str(found.get("Id") or "")
        docker_engine.start_container(container_id)
    except (docker_engine.DockerError, OSError, RuntimeError) as error:
        log.exception("textbook service start failed")
        return ServiceStatus("failed", "Не удалось запустить сервис", str(error), can_start=True)
    finally:
        _container_cache = None
    # Новый запуск — новая история; следующий выход этого контейнера снова
    # нужно будет объяснять, а не считать частью прошлой остановки.
    _expected_stop_container = None
    return ServiceStatus(
        "starting",
        "Сервис запускается",
        "Первый запуск дольше обычного: модель загружается в память видеокарты.",
        can_stop=True,
    )


def stop() -> ServiceStatus:
    global _container_cache, _expected_stop_container
    if not docker_engine.available():
        return describe()
    own = _self()
    found = _container(_project(own))
    if found is None:
        return describe()
    container_id = str(found.get("Id") or "")
    try:
        docker_engine.stop_container(container_id)
    except (docker_engine.DockerError, OSError) as error:
        log.exception("textbook service stop failed")
        return ServiceStatus("failed", "Не удалось остановить сервис", str(error), can_stop=True)
    finally:
        _container_cache = None
    _expected_stop_container = container_id
    return ServiceStatus("stopped", "Сервис остановлен", can_start=True)
