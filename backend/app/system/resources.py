"""Ресурсы трёх серверов без Docker socket, обхода процессов и проб моделей.

Каждый сервис читает собственный cgroup, включая дочерние процессы, и атомарно
публикует крошечный снимок. CPU: одно полностью занятое ядро = 100%; память
считает working set контейнера, как Docker stats (без inactive file cache).
"""

import logging
import os
import time
from datetime import UTC, datetime
from pathlib import Path
from threading import Event, Thread
from typing import Literal

from app.config import settings
from app.system.schemas import ResourceServiceRead, SystemResourcesRead

type ResourceService = Literal["api", "worker", "retrieval-model"]
SERVICES: tuple[ResourceService, ...] = ("api", "worker", "retrieval-model")
SNAPSHOT_MAX_BYTES = 4096
SNAPSHOT_MAX_AGE_SECONDS = 30
CGROUP_ROOT = Path("/sys/fs/cgroup")
log = logging.getLogger("tentex.resources")


def _counters(root: Path) -> tuple[int, int]:
    """Вернуть working set и накопленное CPU в микросекундах для cgroup v1/v2."""
    if (root / "memory.current").exists():
        used = int((root / "memory.current").read_text())
        stats = dict(line.split() for line in (root / "memory.stat").read_text().splitlines())
        cpu = dict(line.split() for line in (root / "cpu.stat").read_text().splitlines())
        return max(0, used - int(stats.get("inactive_file", 0))), int(cpu["usage_usec"])
    used = int((root / "memory/memory.usage_in_bytes").read_text())
    stats = dict(line.split() for line in (root / "memory/memory.stat").read_text().splitlines())
    cpu_ns = int((root / "cpuacct/cpuacct.usage").read_text())
    return max(0, used - int(stats.get("total_inactive_file", 0))), cpu_ns // 1000


class ResourceSampler:
    """Один спящий поток на сервис; остановка lifespan не оставляет потока."""

    def __init__(self, service: ResourceService) -> None:
        self.service = service
        self._stop = Event()
        self._thread: Thread | None = None

    def start(self) -> None:
        """Запустить счётчики только в контейнере с доступным cgroup."""
        # При прямом Linux-запуске корневой cgroup означает всю машину.
        # Не выдаём её память за память Tentex.
        if not Path("/.dockerenv").exists():
            return
        self._thread = Thread(target=self._run, name="resource-sampler", daemon=True)
        self._thread.start()

    def close(self) -> None:
        """Остановить сбор без ожидания следующего интервала."""
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1)

    def _run(self) -> None:
        """Сэмплировать независимо от запросов UI, без задержки ради CPU-дельты."""
        previous: tuple[float, int] | None = None
        while not self._stop.is_set():
            try:
                memory, cpu = _counters(CGROUP_ROOT)
                now = time.monotonic()
                percent = None if previous is None else max(
                    0, (cpu - previous[1]) / ((now - previous[0]) * 10_000),
                )
                previous = now, cpu
                self._publish(memory, percent)
            except (OSError, ValueError, KeyError) as error:
                log.debug("resource counters unavailable: %s", type(error).__name__)
            self._stop.wait(settings.resource_sample_seconds)

    def _publish(self, memory: int, cpu: float | None) -> None:
        directory = settings.diagnostics_dir / "resources"
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{self.service}.json"
        staging = directory / f"{self.service}.{os.getpid()}.tmp"
        payload = ResourceServiceRead(
            service=self.service, sampled_at=datetime.now(UTC),
            memory_bytes=memory, cpu_percent=round(cpu, 2) if cpu is not None else None,
        )
        staging.write_text(payload.model_dump_json(), encoding="utf-8")
        os.replace(staging, path)


def resource_summary() -> SystemResourcesRead:
    """Читать только свежие снимки: остановленный сервер не показывается нулём."""
    now = datetime.now(UTC)
    services: list[ResourceServiceRead] = []
    for service in SERVICES:
        path = settings.diagnostics_dir / "resources" / f"{service}.json"
        try:
            with path.open(encoding="utf-8") as source:
                payload = ResourceServiceRead.model_validate_json(source.read(SNAPSHOT_MAX_BYTES))
            age = (now - payload.sampled_at).total_seconds()
            if payload.service == service and 0 <= age <= SNAPSHOT_MAX_AGE_SECONDS:
                services.append(payload)
        except (OSError, UnicodeError, ValueError, TypeError):
            continue
    missing = [service for service in SERVICES if service not in {s.service for s in services}]
    cpu_available = services and all(service.cpu_percent is not None for service in services)
    return SystemResourcesRead(
        memory_bytes=sum(service.memory_bytes for service in services) if services else None,
        cpu_percent=round(sum(service.cpu_percent or 0 for service in services), 2)
        if cpu_available else None,
        services=services, missing_services=missing,
    )
