"""Установка и удаление наборов моделей распознавания.

Веса не входят в поставку: их ставит сам пользователь и только те, которые ему
нужны. Качаем с Hugging Face — той же организации PaddlePaddle, что публикует
PaddleOCR; список файлов и их размеры спрашиваем у самого Hugging Face, а не
берём из наших констант, поэтому показанный прогресс настоящий.

Загрузка идёт в фоновом потоке: скачивание учебниковой модели — это два
гигабайта, и держать на нём HTTP-запрос нельзя. Экран опрашивает состояние
через тот же `GET /api/settings/ocr`.
"""

from __future__ import annotations

import logging
import os
import shutil
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from app.config import settings as app_config
from app.ocr.catalog import MODELS_BY_KEY, ModelRepo, OcrModelSpec

log = logging.getLogger("tentex.ocr.downloads")

# Куда PaddleX смотрит за «официальными» моделями и где лежит обычный кеш
# Hugging Face. Оба каталога уже примонтированы и в воркер, и в GPU-сервис.
PADDLEX_DIRNAME = "official_models"
HF_DIRNAME = "huggingface"
COMPLETE_MARKER = ".tentex-complete"

# Одних весов недостаточно: `snapshot_download` кладёт их раньше служебного
# `inference.yml`. Без него PaddleX не сможет открыть модель, хотя старая
# проверка уже показывала её как установленную.
WEIGHT_SUFFIXES = (".pdiparams", ".safetensors", ".pdmodel", ".bin")


@dataclass
class InstallJob:
    model_key: str
    total_bytes: int
    done_bytes: int = 0
    state: str = "running"  # running · done · failed · cancelled
    error: str = ""
    current: str = ""
    cancel_requested: bool = False
    cancel: threading.Event = field(default_factory=threading.Event)


_jobs: dict[str, InstallJob] = {}
_lock = threading.Lock()


def models_root() -> Path:
    return app_config.data_dir / "models"


def _repo_dir(repo: ModelRepo) -> Path:
    if repo.layout == "paddlex":
        return models_root() / PADDLEX_DIRNAME / repo.folder
    org, name = repo.repo_id.split("/", 1)
    return models_root() / HF_DIRNAME / "hub" / f"models--{org}--{name}"


def _has_weights(directory: Path) -> bool:
    if not directory.is_dir():
        return False
    for path in directory.rglob("*"):
        if path.is_file() and path.suffix in WEIGHT_SUFFIXES and path.stat().st_size > 1_000_000:
            return True
    return False


def _completion_marker(repo: ModelRepo) -> Path:
    return _repo_dir(repo) / COMPLETE_MARKER


def mark_repo_complete(repo: ModelRepo) -> None:
    marker = _completion_marker(repo)
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("complete\n", encoding="utf-8")
    _invalidate_repo_cache(repo)


# Экран настроек читает состояние на каждый GET и опрашивает его каждые 1.5
# секунды во время загрузки. Обход каталога установленной модели — это сотни
# stat() на файл весов, а на смонтированном с хоста каталоге (особенно на
# Windows) один такой обход стоит секунды. Установлен ли набор и сколько он
# занимает не меняется вне самой загрузки и удаления, а обе эти операции
# сбрасывают кеш сами.
_CACHE_SECONDS = 20.0
_installed_cache: dict[tuple[str, str], tuple[float, bool]] = {}
_bytes_cache: dict[tuple[str, str], tuple[float, int]] = {}


def _repo_cache_key(repo: ModelRepo) -> tuple[str, str]:
    return (str(models_root()), repo.repo_id)


def _invalidate_repo_cache(repo: ModelRepo) -> None:
    key = _repo_cache_key(repo)
    _installed_cache.pop(key, None)
    _bytes_cache.pop(key, None)


def repo_installed(repo: ModelRepo) -> bool:
    key = _repo_cache_key(repo)
    now = time.monotonic()
    cached = _installed_cache.get(key)
    if cached is not None and now - cached[0] < _CACHE_SECONDS:
        return cached[1]
    if repo.layout == "hf_cache":
        result = _completion_marker(repo).is_file()
    else:
        directory = _repo_dir(repo)
        result = (directory / "inference.yml").is_file() and _has_weights(directory)
    _installed_cache[key] = (now, result)
    return result


def installed(spec: OcrModelSpec) -> bool:
    return all(repo_installed(repo) for repo in spec.repos)


def _scan_repo_bytes(directory: Path) -> int:
    total = 0
    if not directory.is_dir():
        return 0
    for path in directory.rglob("*"):
        if path.is_file():
            try:
                total += path.stat().st_size
            except OSError:  # noqa: PERF203 - файл могли докачать и переименовать
                continue
    return total


def _repo_bytes_on_disk(repo: ModelRepo) -> int:
    key = _repo_cache_key(repo)
    now = time.monotonic()
    cached = _bytes_cache.get(key)
    if cached is not None and now - cached[0] < _CACHE_SECONDS:
        return cached[1]
    total = _scan_repo_bytes(_repo_dir(repo))
    _bytes_cache[key] = (now, total)
    return total


def bytes_on_disk(spec: OcrModelSpec) -> int:
    return sum(_repo_bytes_on_disk(repo) for repo in spec.repos)


def job_for(model_key: str) -> InstallJob | None:
    with _lock:
        return _jobs.get(model_key)


def _hf_environment() -> None:
    """Кеш Hugging Face — внутри данных установки, а не в домашнем каталоге.

    Xet грузит большие веса частями и параллельно. Прогресс теперь берётся из
    байтовых callback'ов `snapshot_download`, поэтому отдельный кеш Xet не
    скрывает работу от экрана.
    """
    root = models_root() / HF_DIRNAME
    root.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("HF_HOME", str(root))
    os.environ["HF_HUB_DISABLE_XET"] = "0"
    os.environ["HF_XET_HIGH_PERFORMANCE"] = "1"
    os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"


def _repo_files(repo: ModelRepo) -> list[tuple[str, int]]:
    from huggingface_hub import HfApi

    info = HfApi().model_info(repo.repo_id, files_metadata=True)
    result: list[tuple[str, int]] = []
    for sibling in info.siblings or []:
        name = getattr(sibling, "rfilename", "")
        if not name:
            continue
        result.append((name, int(getattr(sibling, "size", 0) or 0)))
    return result


def _progress_class(job: InstallJob):
    """Адаптер прогресса Hugging Face к состоянию, которое опрашивает экран."""
    from tqdm.auto import tqdm

    class JobProgress(tqdm):
        def __init__(self, *args, **kwargs) -> None:
            self._tracks_bytes = kwargs.get("unit") == "B"
            super().__init__(*args, **kwargs)

        def update(self, n=1):
            if job.cancel.is_set():
                raise InterruptedError
            if self._tracks_bytes:
                job.done_bytes += int(n or 0)
            return super().update(n)

    return JobProgress


def _download_repo(repo: ModelRepo, job: InstallJob) -> None:
    from huggingface_hub import snapshot_download

    if job.cancel.is_set():
        raise InterruptedError
    job.current = repo.folder
    options = {
        "repo_id": repo.repo_id,
        "max_workers": 8,
        "tqdm_class": _progress_class(job),
    }
    if repo.layout == "paddlex":
        snapshot_download(local_dir=str(_repo_dir(repo)), **options)
    else:
        snapshot_download(cache_dir=str(models_root() / HF_DIRNAME / "hub"), **options)
    mark_repo_complete(repo)


def _run(spec: OcrModelSpec, job: InstallJob) -> None:
    try:
        _hf_environment()
        total = 0
        plan: list[tuple[ModelRepo, list[tuple[str, int]]]] = []
        for repo in spec.repos:
            if repo_installed(repo):
                continue
            files = _repo_files(repo)
            total += sum(size for _, size in files)
            plan.append((repo, files))
        job.total_bytes = total or spec.size_bytes
        for repo, _files in plan:
            _download_repo(repo, job)
        job.done_bytes = job.total_bytes
        job.state = "done"
        job.current = ""
        log.info("ocr model %s installed", spec.key)
    except InterruptedError:
        job.state = "cancelled"
        job.current = ""
    except Exception as error:  # noqa: BLE001 - причину надо показать на экране
        job.state = "failed"
        job.error = str(error) or error.__class__.__name__
        job.current = ""
        log.exception("ocr model %s download failed", spec.key)


def start_install(model_key: str) -> InstallJob:
    spec = MODELS_BY_KEY[model_key]
    with _lock:
        existing = _jobs.get(model_key)
        if existing is not None and existing.state == "running":
            return existing
        job = InstallJob(model_key=model_key, total_bytes=spec.size_bytes)
        _jobs[model_key] = job
    thread = threading.Thread(
        target=_run, args=(spec, job), name=f"ocr-install-{model_key}", daemon=True
    )
    thread.start()
    return job


def cancel_install(model_key: str) -> InstallJob | None:
    job = job_for(model_key)
    if job is not None and job.state == "running":
        job.cancel_requested = True
        job.current = "Останавливаем загрузку…"
        job.cancel.set()
    return job


def remove(model_key: str) -> None:
    spec = MODELS_BY_KEY[model_key]
    keep = {
        repo.repo_id
        for other in MODELS_BY_KEY.values()
        if other.key != model_key and installed(other)
        for repo in other.repos
    }
    for repo in spec.repos:
        if repo.repo_id in keep:
            continue  # тот же репозиторий нужен другому установленному набору
        shutil.rmtree(_repo_dir(repo), ignore_errors=True)
        _invalidate_repo_cache(repo)
    with _lock:
        _jobs.pop(model_key, None)


def engine_ready(engine: str) -> bool:
    return any(spec.engine == engine and installed(spec) for spec in MODELS_BY_KEY.values())
