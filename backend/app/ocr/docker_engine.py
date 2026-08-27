"""Минимальный клиент Docker Engine API поверх локального сокета.

Зачем свой, а не библиотека: нужно ровно пять вызовов (найти контейнер,
создать, запустить, остановить, прочитать хвост журнала), а `docker` SDK тянет
`requests` и полтора десятка зависимостей в лёгкий образ API. Это тот случай,
когда «готовое» дороже написанного.

Почему сокет, а не команда `docker compose`: команда внутри контейнера
подставила бы daemon'у **свои** пути (`/app/data`), а тот разрешает их в
файловой системе хоста — получились бы пустые тома. Запуск и остановка уже
созданного контейнера, наоборот, путей не касаются вовсе, а при создании мы
берём настоящие пути хоста из описания собственного контейнера.
"""

from __future__ import annotations

import json
import logging
import os
import re
import socket
from http.client import HTTPConnection
from typing import Any
from urllib.parse import quote

log = logging.getLogger("tentex.ocr.docker")

API_VERSION = "v1.43"
DEFAULT_SOCKET = "/var/run/docker.sock"
_ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def socket_path() -> str:
    """Путь к сокету. `DOCKER_HOST=unix:///…` уважается, остальные схемы — нет."""
    host = os.getenv("DOCKER_HOST", "").strip()
    if host.startswith("unix://"):
        return host[len("unix://") :]
    return os.getenv("TENTEX_DOCKER_SOCKET", DEFAULT_SOCKET)


def available() -> bool:
    path = socket_path()
    try:
        return os.path.exists(path)
    except OSError:
        return False


class _SocketConnection(HTTPConnection):
    def __init__(self, path: str, timeout: float) -> None:
        super().__init__("localhost", timeout=timeout)
        self._path = path

    def connect(self) -> None:  # pragma: no cover - тонкая обёртка над socket
        connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        connection.settimeout(self.timeout)
        connection.connect(self._path)
        self.sock = connection


class DockerError(RuntimeError):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


def request(
    method: str,
    path: str,
    body: dict[str, Any] | None = None,
    *,
    timeout: float = 10.0,
    raw: bool = False,
) -> Any:
    payload = json.dumps(body).encode("utf-8") if body is not None else None
    connection = _SocketConnection(socket_path(), timeout)
    try:
        connection.request(
            method,
            f"/{API_VERSION}{path}",
            body=payload,
            headers={"Content-Type": "application/json", "Host": "localhost"},
        )
        response = connection.getresponse()
        data = response.read()
        if response.status >= 400:
            detail = ""
            try:
                detail = str(json.loads(data.decode("utf-8")).get("message") or "")
            except (ValueError, AttributeError):
                detail = data.decode("utf-8", errors="replace")[:400]
            raise DockerError(response.status, detail or f"Docker ответил {response.status}")
        if raw:
            return data
        return json.loads(data.decode("utf-8")) if data else None
    finally:
        connection.close()


def _safe(method: str, path: str, **kwargs: Any) -> Any:
    try:
        return request(method, path, **kwargs)
    except (OSError, DockerError, ValueError):
        log.debug("docker %s %s failed", method, path, exc_info=True)
        return None


def info() -> dict[str, Any] | None:
    result = _safe("GET", "/info", timeout=5.0)
    return result if isinstance(result, dict) else None


def self_container() -> dict[str, Any] | None:
    """Описание контейнера, в котором мы сами работаем.

    Docker кладёт короткий идентификатор контейнера в `HOSTNAME`. Если Tentex
    запущен не в контейнере, ответа не будет — и это нормально.
    """
    name = os.getenv("HOSTNAME", "").strip()
    if not name:
        return None
    result = _safe("GET", f"/containers/{quote(name)}/json", timeout=5.0)
    return result if isinstance(result, dict) else None


def find_container(labels: dict[str, str]) -> dict[str, Any] | None:
    filters = quote(json.dumps({"label": [f"{key}={value}" for key, value in labels.items()]}))
    result = _safe("GET", f"/containers/json?all=1&filters={filters}", timeout=5.0)
    if isinstance(result, list) and result:
        return result[0]
    return None


def inspect_container(container_id: str) -> dict[str, Any] | None:
    result = _safe("GET", f"/containers/{quote(container_id)}/json", timeout=5.0)
    return result if isinstance(result, dict) else None


def inspect_image(reference: str) -> dict[str, Any] | None:
    result = _safe("GET", f"/images/{quote(reference, safe='')}/json", timeout=5.0)
    return result if isinstance(result, dict) else None


def image_exists(reference: str) -> bool:
    return inspect_image(reference) is not None


def create_container(name: str, config: dict[str, Any]) -> str:
    result = request("POST", f"/containers/create?name={quote(name)}", config, timeout=30.0)
    if not isinstance(result, dict) or not result.get("Id"):
        raise DockerError(500, "Docker не вернул идентификатор созданного контейнера")
    return str(result["Id"])


def start_container(container_id: str) -> None:
    request("POST", f"/containers/{quote(container_id)}/start", timeout=30.0)


def stop_container(container_id: str, *, seconds: int = 15) -> None:
    request("POST", f"/containers/{quote(container_id)}/stop?t={seconds}", timeout=seconds + 15.0)


def remove_container(container_id: str) -> None:
    request("DELETE", f"/containers/{quote(container_id)}?force=1", timeout=30.0)


def tail_logs(container_id: str, lines: int = 40) -> str:
    """Хвост журнала контейнера — чтобы показать причину, а не «не запустилось».

    Поток мультиплексирован: перед каждым куском идёт заголовок из восьми байт
    (поток, три нуля, длина). Разбираем его сами — ради этого библиотеку не берут.
    """
    data = _safe(
        "GET",
        f"/containers/{quote(container_id)}/logs?stdout=1&stderr=1&tail={lines}",
        timeout=10.0,
        raw=True,
    )
    if not isinstance(data, bytes):
        return ""
    chunks: list[str] = []
    offset = 0
    while offset + 8 <= len(data):
        size = int.from_bytes(data[offset + 4 : offset + 8], "big")
        chunk = data[offset + 8 : offset + 8 + size]
        if not size or not chunk:
            break
        chunks.append(chunk.decode("utf-8", errors="replace"))
        offset += 8 + size
    text = "".join(chunks) if chunks else data.decode("utf-8", errors="replace")
    # Библиотеки внутри контейнера красят вывод под терминал; в HTML-теге
    # `<pre>` эти коды рисуются нечитаемыми прямоугольниками, а не цветом.
    return _ANSI_ESCAPE.sub("", text).strip()
