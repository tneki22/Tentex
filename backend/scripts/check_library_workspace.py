"""Сквозная проверка глобальной рабочей области материала в Библиотеке.

Проверяется то, ради чего вертикаль делалась: общий материал создаётся без
проекта, читается и обрабатывается без `project_id`, частичный повтор даёт
полную новую версию, старая версия остаётся читаемой, восстановление добавляет
следующий номер, а привязки при этом остаются проектными.

База поднимается отдельная, во временной папке: живой bind-mounted SQLite в WAL
с хоста читать нельзя (см. AGENTS.md).
"""

import os
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

import pymupdf as fitz
from check_stage2 import ApiServer, free_port, request
from check_stage4 import create_exam_project

BACKEND_ROOT = Path(__file__).resolve().parent.parent


def run_worker(data_dir: Path) -> None:
    environment = os.environ.copy()
    environment["TENTEX_DATA_DIR"] = str(data_dir)
    environment["TENTEX_SEED_DEMO_PROJECT"] = "false"
    completed = subprocess.run(
        [sys.executable, "-m", "app.materials.worker", "--once"],
        cwd=BACKEND_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr


def build_pdf(path: Path) -> None:
    """Два разворота с закладками: оглавление и вторая страница нужны обе.

    Текст латиницей намеренно: встроенные шрифты PDF не несут кириллицы, и
    проверка сломалась бы на кодировке шрифта, а не на предмете проверки.
    """
    document = fitz.open()
    for heading, body in [
        ("Chapter 1. Indexes", "Index speeds up lookups by key."),
        ("Chapter 2. Transactions", "Transaction moves the database between whole states."),
    ]:
        page = document.new_page(width=420, height=595)
        page.insert_text((50, 80), heading, fontsize=18, fontname="helv")
        page.insert_text((50, 130), body, fontsize=11, fontname="helv")
    document.set_toc([[1, "Chapter 1. Indexes", 1], [1, "Chapter 2. Transactions", 2]])
    document.save(path)
    document.close()


def read_bytes(server: ApiServer, path: str) -> bytes:
    from urllib.request import urlopen

    with urlopen(f"{server.base_url}{path}", timeout=30) as response:  # noqa: S310
        return response.read()


def upload(server: ApiServer, path: Path) -> dict:
    import mimetypes
    import uuid
    from urllib.request import Request, urlopen

    boundary = uuid.uuid4().hex
    media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    body = b"".join(
        [
            f"--{boundary}\r\n".encode(),
            f'Content-Disposition: form-data; name="file"; filename="{path.name}"\r\n'.encode(),
            f"Content-Type: {media_type}\r\n\r\n".encode(),
            path.read_bytes(),
            f"\r\n--{boundary}--\r\n".encode(),
        ]
    )
    api_request = Request(
        f"{server.base_url}/api/materials/upload",
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    with urlopen(api_request, timeout=30) as response:  # noqa: S310 — локальный сервер проверки
        import json

        assert response.status == 202, response.status
        return json.loads(response.read())


def run() -> None:
    with TemporaryDirectory(prefix="tentex-library-") as temporary_dir:
        data_dir = Path(temporary_dir)
        pdf_path = data_dir / "Методичка.pdf"
        build_pdf(pdf_path)
        server = ApiServer(data_dir, free_port())
        try:
            server.start()

            # 1. Материал создаётся без единого проекта.
            material = upload(server, pdf_path)
            material_id = material["id"]
            assert material["presentation_kind"] == "pdf", material["presentation_kind"]
            assert material["usage"] == []
            assert material["capabilities"]["can_run_ocr"] is True
            assert material["capabilities"]["can_refresh_source"] is False

            # 2. Подключение к двум проектам — отдельное действие.
            first_project, _ = create_exam_project(server)
            second_project, _ = create_exam_project(server)
            for project_id in (first_project, second_project):
                status, _ = request(
                    server,
                    "POST",
                    f"/api/materials/{material_id}/project-links",
                    {"project_id": project_id, "purposes": ["study_source"]},
                )
                assert status == 201, status
            status, detail = request(server, "GET", f"/api/materials/{material_id}")
            assert status == 200
            assert len(detail["usage"]) == 2, detail["usage"]

            # 3. Полная подготовка.
            status, _ = request(
                server,
                "POST",
                f"/api/materials/{material_id}/processing",
                {"parser_mode": "fast", "scope": "all"},
            )
            assert status == 200, status
            run_worker(data_dir)

            status, detail = request(server, "GET", f"/api/materials/{material_id}")
            assert detail["status"] == "ready", detail["status"]
            assert detail["active_parse_revision"] == 1
            assert detail["outline_source"] == "embedded", detail["outline_source"]
            assert len(detail["outline"]) == 2
            assert detail["native_page_count"] + detail["ocr_page_count"] == 2

            status, page = request(server, "GET", f"/api/materials/{material_id}/pages/2")
            assert status == 200 and page["page_number"] == 2
            assert "Transaction" in page["text"], page["text"]

            status, revisions = request(server, "GET", f"/api/materials/{material_id}/revisions")
            assert [row["revision"] for row in revisions] == [1]
            assert revisions[0]["origin"] == "imported"
            assert revisions[0]["is_current"] is True

            # 4. Поиск не требует проекта и открывает точную страницу.
            status, found = request(
                server, "GET", f"/api/materials/{material_id}/search?q=transaction"
            )
            assert status == 200
            assert found["hits"], found
            assert found["hits"][0]["page_number"] == 2, found["hits"][0]

            # 5. Ручная правка первой страницы — новая версия, старая читается.
            status, corrected = request(
                server,
                "PUT",
                f"/api/materials/{material_id}/pages/1",
                {"text": "Chapter 1. Indexes\n\nCorrected first page text."},
            )
            assert status == 200, corrected
            status, detail = request(server, "GET", f"/api/materials/{material_id}")
            assert detail["active_parse_revision"] == 2
            status, old_page = request(
                server, "GET", f"/api/materials/{material_id}/pages/1?revision=1"
            )
            assert status == 200 and "Index speeds up" in old_page["text"], old_page["text"]

            # 6. Повтор диапазона одной страницы даёт полную новую версию.
            status, _ = request(
                server,
                "POST",
                f"/api/materials/{material_id}/processing",
                {"parser_mode": "fast", "scope": "range", "page_from": 2, "page_to": 2},
            )
            assert status == 200, status
            run_worker(data_dir)
            status, detail = request(server, "GET", f"/api/materials/{material_id}")
            assert detail["active_parse_revision"] == 3, detail["active_parse_revision"]
            status, page_one = request(server, "GET", f"/api/materials/{material_id}/pages/1")
            assert "Corrected first page" in page_one["text"], page_one["text"]
            status, page_two = request(server, "GET", f"/api/materials/{material_id}/pages/2")
            assert "Transaction" in page_two["text"]
            status, revisions = request(server, "GET", f"/api/materials/{material_id}/revisions")
            assert [row["revision"] for row in revisions] == [3, 2, 1]
            assert revisions[0]["scope"]["kind"] == "range"
            assert revisions[0]["summary"]["changed_pages"] == 1

            # 7. Восстановление первой версии как новой: номера растут монотонно.
            status, restored = request(
                server, "POST", f"/api/materials/{material_id}/revisions/1/restore", {}
            )
            assert status == 200, restored
            assert restored["active_parse_revision"] == 4
            status, page_one = request(server, "GET", f"/api/materials/{material_id}/pages/1")
            assert "Index speeds up" in page_one["text"], page_one["text"]

            # 8. Исходник отдаётся целиком и без проекта.
            source = read_bytes(server, f"/api/materials/{material_id}/source")
            assert source[:5] == b"%PDF-", source[:16]

            # 9. Текстовый материал Библиотеки: без проекта, без OCR-режимов.
            status, note = request(
                server,
                "POST",
                "/api/materials/text",
                {"name": "Конспект.md", "text": "# Заметка\n\nСвой текст."},
            )
            assert status == 201, note
            assert note["presentation_kind"] == "plain_text"
            assert note["capabilities"]["can_run_ocr"] is False
            assert note["usage"] == []

            # 10. Предпросмотр удаления называет оба проекта.
            status, preview = request(
                server, "GET", f"/api/materials/{material_id}/delete-preview"
            )
            assert status == 200
            assert len(preview["material"]["usage"]) == 2, preview["material"]["usage"]
        except Exception:
            server.stop()
            if server.stderr_output:
                print(server.stderr_output, file=sys.stderr)
            raise
        finally:
            server.stop()

    print("check_library_workspace: OK")


if __name__ == "__main__":
    run()
