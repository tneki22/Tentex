"""Безопасная загрузка и воспроизводимая сборка Typst-проектов.

Исходник хранится как нормализованный ZIP. Компилятор видит только распакованный
bundle и собственный кэш пакетов, поэтому ни пути Windows, ни системные шрифты
не становятся неявной зависимостью материала.
"""

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import zipfile
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from fastapi import UploadFile

from app.config import settings
from app.projects.errors import ProjectDomainError

MAX_INPUT_BYTES = 100 * 1024 * 1024
MAX_UNPACKED_BYTES = 250 * 1024 * 1024
MAX_FILES = 2_000
MAX_PATH_DEPTH = 20
MAX_PATH_LENGTH = 240
COMPILE_TIMEOUT_SECONDS = 120
TYPST_COMPILER_VERSION = "0.15.1"
PACKAGE_RE = re.compile(r"@preview/([A-Za-z0-9_-]+):([0-9][A-Za-z0-9._-]*)")
LOCAL_IMPORT_RE = re.compile(r'#(?:import|include)\s+"([^"\n]+)"')
HEADING_RE = re.compile(r"^={1,6}\s+")


@dataclass(frozen=True, slots=True)
class Bundle:
    """Нормализованный проект до записи в общее хранилище."""

    path: Path
    sha256: str
    size_bytes: int
    entrypoint: str | None
    candidates: list[str]
    packages: list[dict[str, str]]


@dataclass(frozen=True, slots=True)
class CompileResult:
    """Результат одного запуска CLI без побочных эффектов в БД."""

    ok: bool
    pdf_path: Path | None
    diagnostics: list[dict[str, object]]
    compiler_version: str


def _invalid(detail: str) -> ProjectDomainError:
    return ProjectDomainError(detail, status=422, code="typst_bundle_invalid")


def _safe_path(raw: str) -> PurePosixPath:
    """Проверяет архивный путь до записи: Windows считает регистр одинаковым."""
    path = PurePosixPath(raw.replace("\\", "/"))
    if path.is_absolute() or ".." in path.parts or not path.parts or path.name in {"", "."}:
        raise _invalid("В проекте Typst недопустимый относительный путь")
    if len(path.parts) > MAX_PATH_DEPTH or len(path.as_posix()) > MAX_PATH_LENGTH:
        raise _invalid("Путь в проекте Typst превышает допустимую глубину или длину")
    return path


def _entrypoint(names: Iterable[str], requested: str | None) -> tuple[str | None, list[str]]:
    typ_files = sorted(name for name in names if name.lower().endswith(".typ"))
    normalized = requested.replace("\\", "/") if requested else None
    if normalized:
        if normalized not in typ_files:
            raise ProjectDomainError(
                "Указанная точка входа отсутствует в проекте",
                status=422,
                code="typst_entrypoint_required",
                context={"entrypoint": normalized, "candidates": typ_files},
            )
        return normalized, typ_files
    if "typst.toml" in names:
        return "main.typ" if "main.typ" in typ_files else None, typ_files
    if "main.typ" in typ_files:
        return "main.typ", typ_files
    if len(typ_files) == 1:
        return typ_files[0], typ_files
    return None, typ_files


def _packages_from_texts(texts: Iterable[str]) -> list[dict[str, str]]:
    return [
        {"namespace": "preview", "name": name, "version": version}
        for name, version in sorted({item for text in texts for item in PACKAGE_RE.findall(text)})
    ]


def _write_normalized_zip(files: dict[str, bytes]) -> tuple[Path, str, int]:
    temp_dir = settings.storage_dir / "tmp"
    temp_dir.mkdir(parents=True, exist_ok=True)
    fd, filename = tempfile.mkstemp(suffix=".zip", dir=temp_dir)
    os.close(fd)
    path = Path(filename)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for name in sorted(files):
            info = zipfile.ZipInfo(name)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, files[name])
    data_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    return path, data_hash, path.stat().st_size


async def read_uploads(uploads: list[UploadFile], paths: list[str]) -> dict[str, bytes]:
    """Читает загрузку в память по проверенным путям, не доверяя именам браузера."""
    if len(uploads) != len(paths) or not uploads:
        raise _invalid("Нужны согласованные файлы проекта и их относительные пути")
    files: dict[str, bytes] = {}
    total = 0
    try:
        for upload, raw_path in zip(uploads, paths, strict=True):
            name = _safe_path(raw_path).as_posix()
            key = name.casefold()
            if any(existing.casefold() == key for existing in files):
                raise _invalid("В проекте есть дублирующиеся без учёта регистра пути")
            chunks: list[bytes] = []
            while chunk := await upload.read(1024 * 1024):
                total += len(chunk)
                if total > MAX_INPUT_BYTES:
                    raise ProjectDomainError(
                        "Проект Typst больше 100 МБ", status=413, code="typst_bundle_invalid"
                    )
                chunks.append(chunk)
            files[name] = b"".join(chunks)
    finally:
        for upload in uploads:
            await upload.close()
    return files


async def bundle_uploads(
    uploads: list[UploadFile], paths: list[str], requested_entrypoint: str | None
) -> Bundle:
    """Собирает single/folder запрос в один архив."""
    return _bundle_from_files(await read_uploads(uploads, paths), requested_entrypoint)


async def bundle_zip(upload: UploadFile, requested_entrypoint: str | None) -> Bundle:
    """Безопасно распаковывает ZIP, отбрасывая zip-slip, ссылки и бомбы."""
    temp_dir = settings.storage_dir / "tmp"
    temp_dir.mkdir(parents=True, exist_ok=True)
    fd, filename = tempfile.mkstemp(suffix=".zip", dir=temp_dir)
    os.close(fd)
    path = Path(filename)
    size = 0
    try:
        with path.open("wb") as target:
            while chunk := await upload.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_INPUT_BYTES:
                    raise ProjectDomainError(
                        "Архив Typst больше 100 МБ", status=413, code="typst_bundle_invalid"
                    )
                target.write(chunk)
        files: dict[str, bytes] = {}
        unpacked = 0
        with zipfile.ZipFile(path) as archive:
            for info in archive.infolist():
                if info.is_dir():
                    continue
                name = _safe_path(info.filename).as_posix()
                if info.flag_bits & 0x1 or (info.external_attr >> 16) & 0o170000 == 0o120000:
                    raise _invalid(
                        "Зашифрованные файлы и символические ссылки в ZIP не поддерживаются"
                    )
                if name.casefold() in {value.casefold() for value in files}:
                    raise _invalid("В архиве есть пути, совпадающие без учёта регистра")
                if len(files) >= MAX_FILES:
                    raise _invalid("В проекте Typst больше 2 000 файлов")
                unpacked += info.file_size
                if unpacked > MAX_UNPACKED_BYTES:
                    raise _invalid("После распаковки проект Typst больше 250 МБ")
                files[name] = archive.read(info)
        return _bundle_from_files(files, requested_entrypoint)
    except zipfile.BadZipFile as error:
        raise _invalid("Файл не является корректным ZIP-архивом") from error
    finally:
        path.unlink(missing_ok=True)
        await upload.close()


async def merge_bundle_files(
    bundle_path: Path,
    uploads: list[UploadFile],
    paths: list[str],
    requested_entrypoint: str | None,
) -> Bundle:
    """Добавляет ровно запрошенные зависимости, не переписывая Typst-исходники.

    Точка входа проверяется по объединённому набору, а не по одним новым
    файлам: `main.typ` лежит в старом bundle, и проверка «до слияния»
    отбивала бы каждое добавление недостающей картинки.
    """
    with zipfile.ZipFile(bundle_path) as archive:
        files = {
            _safe_path(info.filename).as_posix(): archive.read(info)
            for info in archive.infolist()
            if not info.is_dir()
        }
    files |= await read_uploads(uploads, paths)
    return _bundle_from_files(files, requested_entrypoint)


def _bundle_from_files(files: dict[str, bytes], requested_entrypoint: str | None) -> Bundle:
    too_large = sum(len(value) for value in files.values()) > MAX_UNPACKED_BYTES
    if not files or len(files) > MAX_FILES or too_large:
        raise _invalid("Проект Typst пуст или содержит слишком много файлов")
    names = set(files)
    entrypoint, candidates = _entrypoint(names, requested_entrypoint)
    texts = [
        data.decode("utf-8", errors="replace")
        for name, data in files.items()
        if name.endswith(".typ")
    ]
    path, sha256, size = _write_normalized_zip(files)
    return Bundle(path, sha256, size, entrypoint, candidates, _packages_from_texts(texts))


def folder_display_name(paths: Iterable[str]) -> str | None:
    """Имя корневой папки браузера — она едина у всех путей `webkitRelativePath`."""
    roots = {raw.replace("\\", "/").split("/", 1)[0] for raw in paths if raw}
    return roots.pop() if len(roots) == 1 else None


def bundle_packages(root: Path) -> list[dict[str, str]]:
    """`@preview`-пакеты распакованного проекта — тем же разбором, что при загрузке."""
    return _packages_from_texts(
        path.read_text(encoding="utf-8", errors="replace") for path in root.rglob("*.typ")
    )


def entrypoint_candidates(bundle_path: Path) -> list[str]:
    """Все `.typ` уже сохранённого проекта — из чего выбирать точку входа.

    Читается из архива, а не из отдельной колонки: список нужен только пока
    точка входа не выбрана, а лишнее поле в таблице разъезжается с содержимым
    bundle при каждой досылке файлов.
    """
    with zipfile.ZipFile(bundle_path) as archive:
        return sorted(
            info.filename
            for info in archive.infolist()
            if not info.is_dir() and info.filename.lower().endswith(".typ")
        )


def store_bundle(bundle: Bundle) -> str:
    """Кладёт нормализованный bundle по хешу, сохраняя дедупликацию исходника."""
    relative = Path("typst") / bundle.sha256[:2] / f"{bundle.sha256}.zip"
    destination = settings.storage_dir / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        bundle.path.unlink(missing_ok=True)
    else:
        bundle.path.replace(destination)
    return relative.as_posix()


def extract_bundle(bundle_path: Path, destination: Path) -> None:
    """Распаковывает уже нормализованный ZIP в одноразовый build-root."""
    with zipfile.ZipFile(bundle_path) as archive:
        for info in archive.infolist():
            if info.is_dir():
                continue
            safe = _safe_path(info.filename)
            target = destination.joinpath(*safe.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as source, target.open("wb") as output:
                shutil.copyfileobj(source, output)


def missing_packages(packages: list[dict[str, str]]) -> list[dict[str, str]]:
    """Находит пакеты, которых нет в постоянном cache и которые нельзя качать молча."""
    cache = settings.typst_package_cache_dir
    return [
        item
        for item in packages
        if not (cache / item["namespace"] / item["name"] / item["version"]).is_dir()
    ]


def package_issues(packages: list[dict[str, str]]) -> list[dict[str, object]]:
    """Недостающие пакеты в виде проблем материала — одна формулировка на всех."""
    return [
        {"kind": "package", "message": f"Нужен {item['name']} {item['version']}", **item}
        for item in packages
    ]


def compile_bundle(bundle_path: Path, entrypoint: str, *, allow_download: bool) -> CompileResult:
    """Собирает PDF в изолированном root; сборку с загрузкой пакетов подтверждают явно.

    `allow_download` — не переключатель сети: у CLI typst 0.15 режима «без сети»
    нет. Это подтверждение вызывающего, и оно проверяется здесь же — недостающий
    пакет без разрешения останавливает сборку до запуска компилятора, а не
    надеется на то, что проверку не забудут на новом месте вызова.
    """
    (settings.storage_dir / "tmp").mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="tentex-typst-", dir=settings.storage_dir / "tmp"
    ) as raw:
        root = Path(raw) / "project"
        root.mkdir()
        extract_bundle(bundle_path, root)
        if not allow_download and (blocked := missing_packages(bundle_packages(root))):
            return CompileResult(False, None, package_issues(blocked), TYPST_COMPILER_VERSION)
        output = Path(raw) / "rendered.pdf"
        deps = Path(raw) / "deps.json"
        command = [
            str(settings.typst_binary),
            "compile",
            "--root",
            str(root),
            "--ignore-system-fonts",
            "--font-path",
            str(root),
            "--package-cache-path",
            str(settings.typst_package_cache_dir),
            "--deps",
            str(deps),
            "--diagnostic-format",
            "short",
            "--creation-timestamp",
            "0",
            "--jobs",
            "2",
            str(root / entrypoint),
            str(output),
        ]
        environment = {
            **os.environ,
            "TYPST_PACKAGE_CACHE_PATH": str(settings.typst_package_cache_dir),
        }
        try:
            completed = subprocess.run(
                command,
                cwd=root,
                env=environment,
                capture_output=True,
                text=True,
                timeout=COMPILE_TIMEOUT_SECONDS,
                start_new_session=True,
            )
        except subprocess.TimeoutExpired:
            return CompileResult(
                False,
                None,
                [{"kind": "timeout", "message": "Сборка Typst превысила 120 секунд"}],
                TYPST_COMPILER_VERSION,
            )
        diagnostics = _diagnostics(completed.stderr, root)
        if completed.returncode != 0 or not output.exists():
            return CompileResult(
                False,
                None,
                diagnostics or [{"kind": "compile", "message": "Typst не создал PDF"}],
                TYPST_COMPILER_VERSION,
            )
        final = (
            settings.storage_dir / "tmp" / f"{hashlib.sha256(output.read_bytes()).hexdigest()}.pdf"
        )
        shutil.copy2(output, final)
        return CompileResult(True, final, diagnostics, TYPST_COMPILER_VERSION)


def _relative_to_root(raw: str, root: Path) -> str | None:
    """Путь диагностики относительно build-root; None — если он вне проекта."""
    try:
        return str(Path(raw).resolve().relative_to(root.resolve()))
    except (ValueError, OSError):
        return None


def _diagnostics(stderr: str, root: Path) -> list[dict[str, object]]:
    """Разбирает `stderr` компилятора в структурированные проблемы.

    При `allow_download` тот же поток несёт живой прогресс загрузки пакета
    («downloading …», «12.0 KiB / 20.6 KiB (58 %), …») — это не диагностика,
    а разговор CLI с человеком у терминала. Настоящая диагностика typst всегда
    маркирована `error:` или `warning:`; всё остальное отбрасывается, иначе
    успешная сборка после докачки показывала бы в «Нужно внимание» технический
    шум и выглядела бы как незавершённая.
    """
    issues: list[dict[str, object]] = []
    for raw in stderr.splitlines():
        line = raw.strip()
        if not line or not re.search(r"\b(error|warning):", line, re.IGNORECASE):
            continue
        kind = "warning" if "warning" in line.lower() else "compile"
        match = re.search(r"(.+\.typ):(\d+):(\d+)", line)
        issue: dict[str, object] = {"kind": kind, "message": line}
        if match:
            # Typst показывает и файлы из кэша пакетов: они лежат вне build-root,
            # и relative_to на них падает — тогда путь просто не уточняем.
            relative = _relative_to_root(match.group(1), root)
            issue |= {"line": int(match.group(2)), "column": int(match.group(3))}
            if relative is not None:
                issue["path"] = relative
        if "file not found" in line.lower():
            issue["kind"] = "missing_file"
            # Typst пишет, где именно искал: этот путь и есть тот, под которым
            # файл должен лечь в bundle. Без него интерфейсу нечего предложить,
            # кроме «что-то не найдено».
            searched = re.search(r"searched at (.+?)\)?$", line)
            if searched:
                raw = searched.group(1)
                issue["missing_path"] = _relative_to_root(raw, root) or raw
        if "unknown font family" in line.lower():
            issue["kind"] = "missing_font"
        issues.append(issue)
    return issues


def source_chunks(root: Path, entrypoint: str, page_count: int) -> list[dict[str, object]]:
    """Берёт только достижимые `.typ`; разрезает по заголовкам и границам строк."""
    pending = [entrypoint]
    seen: set[str] = set()
    chunks: list[dict[str, object]] = []
    while pending:
        path = pending.pop(0)
        if path in seen:
            continue
        seen.add(path)
        source = root / path
        if not source.exists() or source.suffix != ".typ":
            continue
        text = source.read_text(encoding="utf-8")
        for imported in LOCAL_IMPORT_RE.findall(text):
            candidate = _safe_path(str(PurePosixPath(path).parent / imported)).as_posix()
            if candidate.endswith(".typ"):
                pending.append(candidate)
        lines = text.splitlines(keepends=True)
        starts = [
            0,
            *[index for index, line in enumerate(lines[1:], 1) if HEADING_RE.match(line)],
            len(lines),
        ]
        for start, end in zip(starts, starts[1:], strict=False):
            if start == end:
                continue
            code = "".join(lines[start:end])
            chunks.append(
                {
                    "path": path,
                    "line_from": start + 1,
                    "line_to": end,
                    "source_text": code,
                    "source_hash": hashlib.sha256(code.encode()).hexdigest(),
                    "page_from": 1 if page_count else None,
                    "page_to": page_count or None,
                    "diagnostic": "page_mapping_coarse",
                }
            )
    return chunks


def dependency_json(path: Path) -> dict[str, object]:
    """Читает `--deps` только как диагностический артефакт, не как источник модели."""
    return json.loads(path.read_text()) if path.exists() else {}
