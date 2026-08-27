"""Что за машина и потянет ли она модель.

Пользователь ставит Tentex из архива и не обязан знать, сколько у него
видеопамяти. Раздел «Распознавание» отвечает на это сам: показывает найденное
железо и рядом с каждым набором моделей — влезет он сюда или нет.

Главное правило модуля: **не выдумывать**. Определить видеокарту из
контейнера API можно не всегда, и тогда честный ответ — «не смогли определить»
с объяснением, а не оптимистичное «подойдёт». Поэтому у каждого замера есть
`source`: пользователь видит, откуда взялась цифра.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger("tentex.ocr.hardware")

MB = 1000 * 1000
# Замер держится полминуты: экран перечитывает настройки после каждого действия,
# а гонять nvidia-smi на каждый GET незачем.
CACHE_SECONDS = 30.0

GpuSource = str


@dataclass(frozen=True)
class Gpu:
    name: str
    vram_mb: int | None
    driver: str | None
    source: GpuSource


@dataclass(frozen=True)
class Hardware:
    cpu_cores: int | None
    ram_mb: int | None
    free_disk_mb: int | None
    gpu: Gpu | None
    # Почему видеокарты нет в ответе: её правда нет или её не удалось увидеть.
    gpu_reason: str = ""
    notes: tuple[str, ...] = field(default_factory=tuple)


_cache: tuple[float, Hardware] | None = None


def _ram_mb() -> int | None:
    meminfo = Path("/proc/meminfo")
    if meminfo.exists():
        for line in meminfo.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("MemTotal:"):
                return int(line.split()[1]) // 1024
        return None
    if os.name == "nt":  # запуск без контейнеров, прямо на Windows
        import ctypes

        class _Status(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        status = _Status()
        status.dwLength = ctypes.sizeof(_Status)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):  # type: ignore[attr-defined]
            return int(status.ullTotalPhys // (1024 * 1024))
    return None


def _free_disk_mb(path: Path) -> int | None:
    probe = path
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    try:
        return int(shutil.disk_usage(probe).free // (1024 * 1024))
    except OSError:
        return None


def _gpu_from_env() -> Gpu | None:
    """Явное указание от того, кто запускал установку.

    Внутри контейнера видеокарты не видно, поэтому скрипт запуска на хосте
    может передать её характеристики: `TENTEX_GPU_NAME`, `TENTEX_GPU_VRAM_MB`.
    """
    name = os.getenv("TENTEX_GPU_NAME", "").strip()
    if not name:
        return None
    raw = os.getenv("TENTEX_GPU_VRAM_MB", "").strip()
    vram = int(raw) if raw.isdigit() else None
    return Gpu(name, vram, os.getenv("TENTEX_GPU_DRIVER") or None, "переменные окружения")


def _gpu_from_nvidia_smi() -> Gpu | None:
    """Работает, когда Tentex запущен прямо на компьютере, а не в контейнере."""
    if shutil.which("nvidia-smi") is None:
        return None
    try:
        output = subprocess.run(  # noqa: S603 - фиксированная команда без пользовательского ввода
            [
                "nvidia-smi",
                "--query-gpu=name,memory.total,driver_version",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    line = output.stdout.strip().splitlines()[0] if output.stdout.strip() else ""
    if not line:
        return None
    parts = [item.strip() for item in line.split(",")]
    if len(parts) < 2:
        return None
    vram = int(parts[1]) if parts[1].isdigit() else None
    driver = parts[2] if len(parts) > 2 else None
    return Gpu(parts[0], vram, driver, "nvidia-smi")


def _gpu_from_textbook_service(base_url: str | None) -> Gpu | None:
    """Сам GPU-сервис уже стоит на видеокарте и знает про неё всё.

    Самый точный источник, но доступен только пока сервис запущен.
    """
    from app.materials.parsers import textbook

    payload = textbook.health_payload(base_url=base_url)
    gpu = payload.get("gpu") if isinstance(payload, dict) else None
    if not isinstance(gpu, dict) or not gpu.get("name"):
        return None
    vram_raw = gpu.get("vram_mb")
    vram = int(vram_raw) if isinstance(vram_raw, (int, float)) else None
    return Gpu(str(gpu["name"]), vram, gpu.get("driver") or None, "GPU-сервис «Учебник»")


def _gpu_from_docker() -> tuple[Gpu | None, str]:
    """Docker знает, зарегистрирован ли у него драйвер NVIDIA.

    Объём видеопамяти отсюда не виден — только сам факт. Этого хватает, чтобы
    не пугать пользователя словами «видеокарта не найдена», когда она есть.
    """
    from app.ocr import docker_engine

    info = docker_engine.info()
    if info is None:
        return None, ""
    runtimes = info.get("Runtimes")
    has_nvidia = isinstance(runtimes, dict) and "nvidia" in runtimes
    if not has_nvidia:
        return None, "Docker не сообщает о драйвере NVIDIA — скорее всего, GPU недоступен."
    return (
        Gpu("Видеокарта NVIDIA", None, None, "Docker"),
        "",
    )


def _probe(textbook_base_url: str | None) -> Hardware:
    notes: list[str] = []
    gpu = _gpu_from_env() or _gpu_from_nvidia_smi()
    reason = ""
    if gpu is None:
        try:
            gpu = _gpu_from_textbook_service(textbook_base_url)
        except Exception:  # noqa: BLE001 - опрос сервиса не должен ронять экран настроек
            log.debug("textbook health probe failed", exc_info=True)
    if gpu is None:
        gpu, reason = _gpu_from_docker()
    if gpu is None and not reason:
        reason = (
            "Видеокарту определить не удалось: Tentex работает в контейнере, "
            "у которого нет доступа к драйверу."
        )
    if gpu is not None and gpu.vram_mb is None:
        notes.append(
            "Видеокарта найдена, но объём её памяти отсюда не виден — "
            "сверьтесь с требованиями набора вручную."
        )
    return Hardware(
        cpu_cores=os.cpu_count(),
        ram_mb=_ram_mb(),
        free_disk_mb=_free_disk_mb(_data_dir()),
        gpu=gpu,
        gpu_reason=reason,
        notes=tuple(notes),
    )


def _data_dir() -> Path:
    from app.config import settings

    return settings.data_dir


def probe(*, textbook_base_url: str | None = None, refresh: bool = False) -> Hardware:
    global _cache
    now = time.monotonic()
    if not refresh and _cache is not None and now - _cache[0] < CACHE_SECONDS:
        return _cache[1]
    result = _probe(textbook_base_url)
    _cache = (now, result)
    return result


def reset_cache() -> None:
    """Для тестов и для кнопки «Проверить ещё раз»."""
    global _cache
    _cache = None


def fits(
    hardware: Hardware,
    *,
    device: str,
    min_vram_mb: int | None,
    min_ram_mb: int,
    size_bytes: int,
) -> tuple[bool | None, str]:
    """Влезет ли набор в эту машину.

    `None` — не смогли проверить; это отдельный ответ, а не «нет». Решение
    остаётся за пользователем, но с объяснением, чего именно мы не знаем.
    """
    need_mb = size_bytes // MB
    if hardware.free_disk_mb is not None and hardware.free_disk_mb < need_mb + 500:
        return False, f"На диске свободно {hardware.free_disk_mb // 1000} ГБ — не хватит места."
    if hardware.ram_mb is not None and hardware.ram_mb + 256 < min_ram_mb:
        return False, (
            f"Нужно {min_ram_mb // 1000} ГБ оперативной памяти, "
            f"а всего {hardware.ram_mb // 1000} ГБ."
        )
    if device == "cpu":
        return True, "Считает на процессоре — подойдёт любой компьютер."
    if hardware.gpu is None:
        return None, hardware.gpu_reason or "Видеокарту определить не удалось."
    if min_vram_mb is None or hardware.gpu.vram_mb is None:
        return None, f"{hardware.gpu.name}: объём видеопамяти неизвестен."
    if hardware.gpu.vram_mb + 256 < min_vram_mb:
        return False, (
            f"{hardware.gpu.name}: {hardware.gpu.vram_mb // 1000} ГБ видеопамяти, "
            f"нужно от {min_vram_mb // 1000} ГБ."
        )
    return True, f"{hardware.gpu.name}: {hardware.gpu.vram_mb // 1000} ГБ видеопамяти — хватает."
