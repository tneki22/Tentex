r"""Путь на компьютере пользователя для папки, которую процесс видит под другим именем.

API работает в контейнере, где рабочие данные лежат в `/data`, а на компьютере это
`C:\Users\…\Tentex\data`. Хост подсмотреть нельзя, но Docker Desktop на Windows
монтирует папку через 9p/drvfs, и `/proc/self/mountinfo` хранит её исходный путь.
Не получилось определить — показывается путь процесса: он верен для запуска без контейнера.
"""

import os
import re
from functools import lru_cache
from pathlib import Path, PurePosixPath, PureWindowsPath

from app.config import settings

# `path=C:\` в опциях 9p-монтирования; в mountinfo обратный слеш экранирован как `\134`.
_DRVFS_PATH = re.compile(r"path=([A-Za-z]:)(?:\\|\\134)?(?:;|,|$)")
# Старые сборки Docker Desktop монтируют диск как /host_mnt/c/… или /run/desktop/mnt/host/c/….
_HOST_MOUNT = re.compile(r"^(?:/host_mnt|/run/desktop/mnt/host)/([A-Za-z])(/.*)?$")


def _windows_path(drive: str, tail: str) -> str:
    return str(PureWindowsPath(f"{drive.upper()}:/", *PurePosixPath(tail).parts[1:]))


def _from_mountinfo(mountinfo: str, mount_point: str) -> str | None:
    for line in mountinfo.splitlines():
        head, separator, tail = line.partition(" - ")
        fields = head.split()
        if not separator or len(fields) < 5 or fields[4] != mount_point:
            continue
        root = fields[3].replace("\\040", " ")
        super_options = " ".join(tail.split()[2:])
        drvfs = _DRVFS_PATH.search(super_options)
        if drvfs:
            return _windows_path(drvfs.group(1)[0], root)
        host_mount = _HOST_MOUNT.match(root)
        if host_mount:
            return _windows_path(host_mount.group(1), host_mount.group(2) or "/")
    return None


@lru_cache(maxsize=1)
def _host_data_dir() -> str | None:
    explicit = os.environ.get("TENTEX_HOST_DATA_DIR")
    if explicit:
        return explicit
    try:
        mountinfo = Path("/proc/self/mountinfo").read_text(encoding="utf-8")
    except OSError:
        return None
    return _from_mountinfo(mountinfo, settings.data_dir.resolve().as_posix())


def host_path(path: Path) -> str:
    """Путь, который пользователь найдёт в своём проводнике; иначе путь процесса."""
    resolved = path.resolve()
    host_root = _host_data_dir()
    if host_root is None or not resolved.is_relative_to(settings.data_dir.resolve()):
        return str(resolved)
    relative = resolved.relative_to(settings.data_dir.resolve())
    separator = "\\" if "\\" in host_root else "/"
    return separator.join([host_root.rstrip("\\/"), *relative.parts])
