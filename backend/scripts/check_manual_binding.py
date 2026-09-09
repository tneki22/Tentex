"""Сквозная проверка подготовительной вертикали: поиск и ручная привязка.

Сценарий целиком, по плану
docs/superpowers/plans/2026-08-11-pre-stage-6-search-and-manual-binding.md:
экзаменационный проект → реальный материал из Exam-NDB → разбор → поиск по
формулировке → привязка по одному и пачкой (блок целиком) → снятие → восстановление →
отмена через общий журнал → правка текста страницы и перенос привязок →
предпросмотр удаления → перезапуск API → foreign_key_check.
"""

import json
import mimetypes
import sqlite3
import sys
import time
import uuid
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import quote
from urllib.request import Request, urlopen

from check_stage2 import ApiServer, free_port, request
from check_stage4 import create_exam_project
from check_stage5 import run_worker

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
EXAM_MATERIAL = REPO_ROOT / "Exam-NDB" / "Подготовка к экзамену НБД.pdf"
SEARCH_BUDGET_MS = 300  # NFR-4


def upload_file(server: ApiServer, project_id: str, path: Path) -> dict:
    boundary = uuid.uuid4().hex
    media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    data = path.read_bytes()
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{path.name}"\r\n'
        f"Content-Type: {media_type}\r\n\r\n"
    ).encode() + data + f"\r\n--{boundary}--\r\n".encode()
    http_request = Request(
        f"{server.base_url}/api/projects/{project_id}/materials",
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    with urlopen(http_request, timeout=60) as response:
        return json.loads(response.read())


def process_material(server: ApiServer, data_dir: Path, project_id: str, material_id: str) -> dict:
    status, queued = request(
        server,
        "POST",
        f"/api/projects/{project_id}/materials/{material_id}/processing",
        {"parser_mode": "fast"},
    )
    assert status == 200, queued
    deadline = time.monotonic() + 120
    current: dict = {}
    material_path = f"/api/projects/{project_id}/materials/{material_id}"
    while time.monotonic() < deadline:
        run_worker(data_dir)
        status, current = request(server, "GET", material_path)
        assert status == 200
        if current["status"] in {"ready", "failed"}:
            break
    assert current.get("status") == "ready", current
    return current


def run() -> None:
    assert EXAM_MATERIAL.exists(), f"Демонстрационный материал не найден: {EXAM_MATERIAL}"
    with TemporaryDirectory(prefix="tentex-manual-binding-") as temporary_dir:
        data_dir = Path(temporary_dir)
        server = ApiServer(data_dir, free_port())
        project_id = ""
        node_id = ""
        try:
            server.start()
            project_id, activated = create_exam_project(server)
            node = next(
                item for item in activated["program"]["nodes"] if item["title"] == "Транзакции"
            )
            node_id = node["id"]

            material = upload_file(server, project_id, EXAM_MATERIAL)
            material_id = material["id"]
            assert material["status"] == "ready_to_process", material
            process_material(server, data_dir, project_id, material_id)

            # Первый запрос в свежем процессе строит MorphAnalyzer (~секунда, см.
            # lexicon.py) — это одноразовая цена холодного старта процесса, а не
            # времени поиска. NFR-4 измеряет установившееся время, поэтому прогрев
            # не засчитывается в замер.
            search_path = f"/api/projects/{project_id}/search"
            status, _ = request(server, "GET", f"{search_path}?q={quote('прогрев')}")
            assert status == 200

            start = time.monotonic()
            status, found = request(server, "GET", f"{search_path}?q={quote('транзакция')}")
            elapsed_ms = (time.monotonic() - start) * 1000
            assert status == 200, found
            hits = found["results"]
            assert len(hits) >= 1, found
            assert "транзакция" in found["terms"], found["terms"]
            assert elapsed_ms < SEARCH_BUDGET_MS, (
                f"поиск занял {elapsed_ms:.1f} мс (бюджет {SEARCH_BUDGET_MS})"
            )
            print(f"поиск «транзакция»: {len(hits)} результатов за {elapsed_ms:.1f} мс")
            best_hit = hits[0]
            fragment_id = best_hit["fragment_ids"][0]
            block_id = best_hit["block_id"]
            page_number = best_hit["page_from"]

            status, single_bound = request(
                server,
                "POST",
                f"/api/projects/{project_id}/bindings",
                {"program_node_id": node_id, "fragment_ids": [fragment_id], "mechanism": "search"},
            )
            assert status == 200 and len(single_bound["bindings"]) == 1, single_bound
            binding_id = single_bound["bindings"][0]["id"]

            status, block_bound = request(
                server,
                "POST",
                f"/api/projects/{project_id}/bindings",
                {"program_node_id": node_id, "block_id": block_id, "mechanism": "manual"},
            )
            assert status == 200 and len(block_bound["bindings"]) >= 1, block_bound

            status, duplicate = request(
                server,
                "POST",
                f"/api/projects/{project_id}/bindings",
                {"program_node_id": node_id, "fragment_ids": [fragment_id], "mechanism": "search"},
            )
            assert status == 200, duplicate
            assert duplicate["bindings"][0]["id"] == binding_id, (
                "повторная привязка не идемпотентна"
            )

            status, summary = request(
                server, "GET", f"/api/projects/{project_id}/bindings/summary"
            )
            assert status == 200 and any(
                item["program_node_id"] == node_id for item in summary
            ), summary
            node_summary = next(item for item in summary if item["program_node_id"] == node_id)
            print(
                f"сводка узла: {node_summary['fragment_count']} фрагм. "
                f"из {node_summary['material_count']} файлов"
            )

            material_pages_path = f"/api/projects/{project_id}/materials/{material_id}/pages"
            status, page_before = request(server, "GET", f"{material_pages_path}/{page_number}")
            assert status == 200
            status, corrected = request(
                server,
                "PUT",
                f"{material_pages_path}/{page_number}",
                {"text": page_before["text"] + "\n\nРучная правка для проверки переноса привязок."},
            )
            assert status == 200, corrected
            assert corrected["transferred_bindings"] >= 1, corrected
            print(
                f"перенос при правке: {corrected['transferred_bindings']} перенесено, "
                f"{len(corrected['orphaned_binding_ids'])} потеряно"
            )

            bindings_path = f"/api/projects/{project_id}/bindings"
            status, removed = request(server, "DELETE", f"{bindings_path}/{binding_id}")
            assert status == 200 and removed["bindings"][0]["status"] == "removed", removed

            status, restored = request(server, "POST", f"{bindings_path}/{binding_id}/restore")
            assert status == 200 and restored["bindings"][0]["status"] == "manual", restored

            undo_sequence = restored["latest_undoable_action"]["sequence"]
            status, undone = request(
                server,
                "POST",
                f"/api/projects/{project_id}/actions/undo",
                {"expected_action_sequence": undo_sequence},
            )
            assert status == 200 and undone["undone_action_type"] == "binding_create", undone
            status, removed_list = request(
                server, "GET", f"{bindings_path}?node_id={node_id}&status=removed"
            )
            assert status == 200 and any(
                item["id"] == binding_id for item in removed_list
            ), removed_list
            print("undo через общий журнал отменил восстановление привязки")

            status, delete_preview = request(
                server, "GET", f"/api/materials/{material_id}/delete-preview"
            )
            assert status == 200
            assert delete_preview["binding_count"] >= 1, delete_preview
            assert any(
                item["project_id"] == project_id for item in delete_preview["affected_projects"]
            ), delete_preview
            print(
                f"предпросмотр удаления: {delete_preview['binding_count']} привязок, "
                f"{len(delete_preview['affected_projects'])} затронутых проектов"
            )

            status, page_bindings_before = request(
                server, "GET", f"{bindings_path}?material_id={material_id}&page={page_number}"
            )
            assert status == 200 and len(page_bindings_before) >= 1, page_bindings_before
            expected_removed = len(page_bindings_before)

            status, bulk_removed = request(
                server,
                "POST",
                f"{bindings_path}/bulk-remove",
                {"material_id": material_id, "page_number": page_number},
            )
            removed_count = len(bulk_removed["bindings"])
            assert status == 200 and removed_count == expected_removed, bulk_removed
            removed_statuses = [item["status"] for item in bulk_removed["bindings"]]
            assert all(status_value == "removed" for status_value in removed_statuses), bulk_removed

            status, page_bindings_after = request(
                server, "GET", f"{bindings_path}?material_id={material_id}&page={page_number}"
            )
            assert status == 200 and page_bindings_after == [], page_bindings_after
            print(
                f"массовое снятие: {expected_removed} привязок страницы {page_number} "
                "сняты разом"
            )

            bulk_undo_sequence = bulk_removed["latest_undoable_action"]["sequence"]
            status, bulk_undone = request(
                server,
                "POST",
                f"/api/projects/{project_id}/actions/undo",
                {"expected_action_sequence": bulk_undo_sequence},
            )
            undone_type = bulk_undone["undone_action_type"]
            assert status == 200 and undone_type == "binding_remove", bulk_undone
            status, page_bindings_restored = request(
                server, "GET", f"{bindings_path}?material_id={material_id}&page={page_number}"
            )
            restored_count = len(page_bindings_restored)
            assert status == 200 and restored_count == expected_removed, page_bindings_restored
            print("undo вернул массовое снятие одной операцией")
        finally:
            server.stop()
            if server.stderr_output and "Traceback" in server.stderr_output:
                print(server.stderr_output, file=sys.stderr)

        server_restarted = ApiServer(data_dir, free_port())
        try:
            server_restarted.start()
            status, after_restart = request(
                server_restarted, "GET", f"/api/projects/{project_id}/bindings?node_id={node_id}"
            )
            assert status == 200 and len(after_restart) >= 1, after_restart
            status, search_after_restart = request(
                server_restarted,
                "GET",
                f"/api/projects/{project_id}/search?q={quote('транзакция')}",
            )
            assert status == 200 and len(search_after_restart["results"]) >= 1, search_after_restart
            print(f"после перезапуска API: {len(after_restart)} активных привязок, поиск работает")
        finally:
            server_restarted.stop()
            if server_restarted.stderr_output and "Traceback" in server_restarted.stderr_output:
                print(server_restarted.stderr_output, file=sys.stderr)

        with closing(sqlite3.connect(data_dir / "tentex.sqlite")) as connection:
            violations = connection.execute("PRAGMA foreign_key_check").fetchall()
            assert violations == [], violations

        print("check_manual_binding: OK")


if __name__ == "__main__":
    run()
