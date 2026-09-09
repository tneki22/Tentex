"""Сквозная проверка вертикали Typst: загрузка → сборка → PDF, код и ответы.

Сценарий целиком: автономный `.typ` собирается и попадает в Библиотеку с
native-страницами и исходными чанками · тот же проект в ZIP дедуплицируется по
хешу bundle · проект с `@preview`-пакетом без разрешения останавливается на
`needs_input`, а не падает · сломанный исходник даёт FAILED с текстом ошибки
компилятора · недостающая картинка называется точным путём и досылается ·
«Собрать заново» при живой задаче отбивается 409 · отмена возвращает материал в
покой · подключённый к проекту Typst-файл ответов проходит автопривязку ·
удаление материала уносит и фоновую задачу, и строку `typst_materials`.

Запускать там, где есть бинарник typst (образ воркера):
    docker compose run --rm --no-deps worker python scripts/check_typst_material.py
"""

import base64
import json
import sqlite3
import sys
import uuid
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.request import Request, urlopen

from check_stage2 import ApiServer, free_port, request
from check_stage4 import create_exam_project
from check_stage5 import run_worker

STANDALONE = """= Индексы
Индекс ускоряет поиск ценой дополнительного места и записи.

= Транзакции
Транзакция объединяет операции в одну логическую единицу.

= Архитектура СУБД
Ядро, буферный пул и журнал образуют экземпляр.
"""
WITH_PACKAGE = '#import "@preview/example-nonexistent:9.9.9": *\n\n= Раздел\nТекст.\n'
BROKEN = '= Раздел\n#panic("так не собирается")\n'
SECOND = "= Другой раздел\n"
WITH_IMAGE = '= Схема\n#image("images/scheme.png")\n'
# Однопиксельный PNG: проверяется путь досылки, а не содержимое картинки.
PIXEL_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAh"
    "KmMIQAAAABJRU5ErkJggg=="
)


def _multipart(
    fields: list[tuple[str, str]], files: list[tuple[str, str, bytes]]
) -> tuple[bytes, str]:
    """Собирает multipart-тело вручную: в проверках нет внешних http-клиентов."""
    boundary = uuid.uuid4().hex
    parts: list[bytes] = []
    for name, value in fields:
        parts.append(
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="{name}"\r\n\r\n'
            f"{value}\r\n".encode()
        )
    for name, filename, data in files:
        parts.append(
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'
            "Content-Type: application/octet-stream\r\n\r\n".encode()
            + data
            + b"\r\n"
        )
    return b"".join(parts) + f"--{boundary}--\r\n".encode(), boundary


def _post_typst(server: ApiServer, body: bytes, boundary: str) -> dict[str, str]:
    http_request = Request(
        f"{server.base_url}/api/materials/typst",
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    with urlopen(http_request, timeout=60) as response:
        return json.loads(response.read())


def upload_typst(server: ApiServer, files: dict[str, bytes]) -> dict[str, str]:
    """Загрузка одного файла или дерева: `paths` идут парой к `files` по порядку."""
    fields = [("input_kind", "single" if len(files) == 1 else "folder")]
    fields += [("paths", name) for name in files]
    body, boundary = _multipart(fields, [("files", name, data) for name, data in files.items()])
    return _post_typst(server, body, boundary)


def upload_zip(server: ApiServer, files: dict[str, bytes]) -> dict[str, str]:
    with TemporaryDirectory() as raw:
        archive = Path(raw) / "project.zip"
        with zipfile.ZipFile(archive, "w") as target:
            for name, data in files.items():
                target.writestr(name, data)
        body, boundary = _multipart(
            [("input_kind", "zip")], [("file", "project.zip", archive.read_bytes())]
        )
    return _post_typst(server, body, boundary)


def build_and_read(server: ApiServer, data_dir: Path, started: dict[str, str]) -> dict:
    run_worker(data_dir)
    status, material = request(server, "GET", f"/api/materials/{started['material_id']}")
    assert status == 200, material
    return material


def check_standalone(server: ApiServer, data_dir: Path) -> str:
    started = upload_typst(server, {"main.typ": STANDALONE.encode()})
    material = build_and_read(server, data_dir, started)
    assert material["status"] == "ready", material["error"]
    assert material["presentation_kind"] == "typst"
    assert material["page_count"] == material["native_page_count"] == 1, material
    assert material["ocr_page_count"] == 0, "Typst не должен трогать OCR"
    assert material["typst"]["entrypoint"] == "main.typ"
    assert material["typst"]["has_rendered_pdf"] is True
    assert material["typst"]["issues"] == []
    assert material["capabilities"]["can_edit_text"] is False
    assert material["capabilities"]["can_run_ocr"] is False

    status, page = request(server, "GET", f"/api/materials/{material['id']}/pages/1")
    assert status == 200 and "Индекс ускоряет поиск" in page["text"], page

    with urlopen(f"{server.base_url}/api/materials/{material['id']}/rendered", timeout=15) as pdf:
        assert pdf.read(5) == b"%PDF-", "собранный PDF должен отдаваться как есть"

    with sqlite3.connect(data_dir / "tentex.sqlite") as connection:
        chunks = connection.execute(
            "SELECT path, source_text FROM typst_source_chunks"
            " WHERE material_id = ? ORDER BY sort_order",
            (uuid.UUID(material["id"]).hex,),
        ).fetchall()
    assert len(chunks) == 3, chunks
    assert all(path == "main.typ" for path, _ in chunks)
    assert "= Транзакции" in chunks[1][1], "модели уходит исходный код, а не текст PDF"
    return material["id"]


def check_zip_deduplicates(server: ApiServer, data_dir: Path, material_id: str) -> None:
    """Тот же набор файлов в ZIP даёт тот же bundle: материал не удваивается."""
    started = upload_zip(server, {"main.typ": STANDALONE.encode()})
    assert started["material_id"] == material_id, "нормализованный ZIP обязан совпасть по хешу"
    run_worker(data_dir)


def check_missing_package(server: ApiServer, data_dir: Path) -> None:
    started = upload_typst(server, {"packaged.typ": WITH_PACKAGE.encode()})
    material = build_and_read(server, data_dir, started)
    assert material["status"] == "needs_input", material
    kinds = [issue["kind"] for issue in material["typst"]["issues"]]
    assert kinds == ["package"], material["typst"]["issues"]
    assert material["error"] is None, "ожидание решения — не ошибка материала"


def check_broken_source(server: ApiServer, data_dir: Path) -> None:
    started = upload_typst(server, {"broken.typ": BROKEN.encode()})
    material = build_and_read(server, data_dir, started)
    assert material["status"] == "failed", material
    assert material["error"], "текст ошибки компилятора обязан дойти до интерфейса"
    assert "так не собирается" in material["error"], material["error"]

    path = f"/api/materials/{material['id']}/typst/build"
    status, first = request(server, "POST", path, {"download_packages": False})
    assert status == 200, first
    status, second = request(server, "POST", path, {"download_packages": False})
    assert status == 409 and second["code"] == "material_processing_active", second
    run_worker(data_dir)


def check_missing_file(server: ApiServer, data_dir: Path) -> None:
    """Нехватка картинки — состояние «нужны файлы» с точным путём, а не тупик."""
    started = upload_typst(server, {"withimage.typ": WITH_IMAGE.encode()})
    material = build_and_read(server, data_dir, started)
    assert material["status"] == "needs_input", material
    missing = [issue for issue in material["typst"]["issues"] if issue["kind"] == "missing_file"]
    assert missing, material["typst"]["issues"]
    assert missing[0]["missing_path"] == "images/scheme.png", missing[0]

    body, boundary = _multipart(
        [("target_paths", "images/scheme.png")], [("files", "scheme.png", PIXEL_PNG)]
    )
    http_request = Request(
        f"{server.base_url}/api/materials/{material['id']}/typst/files",
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    with urlopen(http_request, timeout=60) as response:
        assert json.loads(response.read())["material_id"] == material["id"]
    run_worker(data_dir)
    status, rebuilt = request(server, "GET", f"/api/materials/{material['id']}")
    assert status == 200 and rebuilt["status"] == "ready", rebuilt
    assert rebuilt["typst"]["has_rendered_pdf"] is True


def check_entrypoint_choice(server: ApiServer, data_dir: Path) -> None:
    """Проект из нескольких `.typ` без `main.typ` ждёт выбора, а не падает."""
    started = upload_typst(
        server,
        {"first.typ": STANDALONE.encode(), "second.typ": SECOND.encode()},
    )
    status, material = request(server, "GET", f"/api/materials/{started['material_id']}")
    assert status == 200 and material["status"] == "needs_input", material
    assert material["typst"]["entrypoint"] is None, material["typst"]
    assert material["typst"]["entrypoint_candidates"] == ["first.typ", "second.typ"], material

    status, queued = request(
        server,
        "POST",
        f"/api/materials/{material['id']}/typst/build",
        {"entrypoint": "first.typ", "download_packages": False},
    )
    assert status == 200, queued
    built = build_and_read(server, data_dir, started)
    assert built["status"] == "ready", built["error"]
    assert built["typst"]["entrypoint"] == "first.typ", built["typst"]
    assert built["typst"]["entrypoint_candidates"] == [], built["typst"]


def check_cancel_releases_material(server: ApiServer, data_dir: Path) -> None:
    """Отмена из панели задач возвращает материал в покой, а не в вечную очередь."""
    started = upload_typst(server, {"cancelled.typ": STANDALONE.encode()})
    status, cancelled = request(
        server, "POST", f"/api/background-jobs/{started['job_id']}/cancel"
    )
    assert status == 200 and cancelled["state"] == "cancelled", cancelled
    status, material = request(server, "GET", f"/api/materials/{started['material_id']}")
    assert status == 200 and material["status"] != "queued", material
    assert material["task"] is None, material["task"]

    # Отменённая задача не должна дождаться воркера: очередь пуста.
    run_worker(data_dir)
    status, after = request(server, "GET", f"/api/materials/{started['material_id']}")
    assert status == 200 and after["status"] != "ready", after


def check_reference_answers(server: ApiServer, data_dir: Path) -> None:
    """Typst в роли файла ответов ложится на вопросы тем же путём, что и PDF."""
    project_id, _ = create_exam_project(server)
    started = upload_typst(server, {"answers.typ": STANDALONE.encode()})
    material = build_and_read(server, data_dir, started)
    assert material["status"] == "ready", material["error"]

    status, attached = request(
        server,
        "POST",
        f"/api/materials/{material['id']}/project-links",
        {
            "project_id": project_id,
            "source_role": "reference",
            "purposes": ["reference_answers"],
        },
    )
    assert status == 201, attached

    link_path = f"/api/projects/{project_id}/materials/{material['id']}/link-answers"
    status, started_link = request(server, "POST", link_path, {})
    assert status == 202, started_link
    run_worker(data_dir)
    status, job = request(server, "GET", f"/api/background-jobs/{started_link['job_id']}")
    assert status == 200 and job["state"] == "completed", job

    # Результат автопривязки проверяется по её следу в проекте: у задачи
    # LINK_ANSWERS сохранённого отчёта нет, а «Ответы» — это ровно то, ради
    # чего файл ответов подключают.
    status, coverage = request(server, "GET", f"/api/projects/{project_id}/coverage-map")
    assert status == 200, coverage
    assert coverage["totals"]["with_answer"] == 3, coverage["totals"]


def check_delete_cleans_up(server: ApiServer, data_dir: Path, material_id: str) -> None:
    status, _ = request(server, "DELETE", f"/api/materials/{material_id}")
    assert status == 204
    with sqlite3.connect(data_dir / "tentex.sqlite") as connection:
        key = uuid.UUID(material_id).hex
        assert not connection.execute(
            "SELECT 1 FROM typst_materials WHERE material_id = ?", (key,)
        ).fetchall(), "строка typst_materials пережила удаление материала"
        assert not connection.execute(
            "SELECT 1 FROM background_jobs WHERE material_id = ?", (key,)
        ).fetchall(), "фоновая задача удалённого материала осталась в очереди"


def run() -> None:
    with TemporaryDirectory(prefix="tentex-typst-") as temporary_dir:
        data_dir = Path(temporary_dir)
        server = ApiServer(data_dir, free_port())
        try:
            server.start()
            material_id = check_standalone(server, data_dir)
            check_zip_deduplicates(server, data_dir, material_id)
            check_missing_package(server, data_dir)
            check_broken_source(server, data_dir)
            check_missing_file(server, data_dir)
            check_entrypoint_choice(server, data_dir)
            check_cancel_releases_material(server, data_dir)
            check_reference_answers(server, data_dir)
            check_delete_cleans_up(server, data_dir, material_id)
        finally:
            server.stop()
    print("check_typst_material: ok")


if __name__ == "__main__":
    sys.exit(run())
