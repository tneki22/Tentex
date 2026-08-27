"""Сквозная проверка конвейера материалов этапа 5 без OCR-зависимостей."""

import os
import sqlite3
import subprocess
import sys
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory

from check_stage2 import ApiServer, alembic_head, free_port, request
from check_stage3 import create_saved_draft, draft_payload
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
        # `--once` разбирает весь материал за один вызов; реальный экзаменационный
        # PDF на полсотни страниц (см. check_manual_binding.py) укладывается в
        # минуту, но не всегда в 30 секунд.
        timeout=90,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr


def run() -> None:
    with TemporaryDirectory(prefix="tentex-stage5-") as temporary_dir:
        data_dir = Path(temporary_dir)
        server = ApiServer(data_dir, free_port())
        try:
            server.start()
            draft_project_id, draft = create_saved_draft(server)
            status, draft_material = request(
                server,
                "POST",
                f"/api/projects/{draft_project_id}/materials/text",
                {
                    "name": "Билеты из мастера.txt",
                    "text": "Билет 1\n1. Индексы\n2. Транзакции",
                    "source_role": "reference",
                    "purposes": ["exam_structure"],
                },
            )
            assert status == 201
            status, _ = request(
                server,
                "POST",
                f"/api/projects/{draft_project_id}/materials/{draft_material['id']}/processing",
                {"parser_mode": "fast"},
            )
            assert status == 200
            run_worker(data_dir)
            status, preview = request(
                server,
                "GET",
                f"/api/projects/{draft_project_id}/materials/{draft_material['id']}/exam-program-preview",
            )
            assert status == 200 and preview["counts"] == {
                "tickets": 1,
                "questions": 2,
                "tasks": 0,
            }
            status, imported_draft = request(
                server,
                "POST",
                f"/api/projects/{draft_project_id}/materials/{draft_material['id']}/exam-draft-import",
                {
                    "expected_draft_revision": draft["draft"]["revision"],
                    "expected_program_revision": draft["program"]["revision"],
                },
            )
            assert status == 200 and imported_draft["draft_revision"] == 2
            assert all(
                node["origin_material_id"] == draft_material["id"]
                for node in imported_draft["program"]["nodes"]
            )
            status, imported_project = request(
                server,
                "POST",
                f"/api/wizard-drafts/{draft_project_id}/activate",
                {"expected_revision": imported_draft["draft_revision"]},
            )
            assert status == 200 and len(imported_project["program"]["nodes"]) == 3

            empty_project_id, empty_draft = create_saved_draft(server)
            status, empty_draft = request(
                server,
                "PUT",
                f"/api/wizard-drafts/{empty_project_id}",
                draft_payload(1, exam_format="unknown"),
            )
            assert status == 200
            status, study_material = request(
                server,
                "POST",
                f"/api/projects/{empty_project_id}/materials/text",
                {
                    "name": "Методичка без списка.txt",
                    "text": "# Индексы\nУчебный материал для будущей программы.",
                    "source_role": "main",
                    "purposes": ["study_source"],
                },
            )
            assert status == 201
            status, empty_project = request(
                server,
                "POST",
                f"/api/wizard-drafts/{empty_project_id}/activate",
                {"expected_revision": empty_draft["draft"]["revision"]},
            )
            assert status == 200 and empty_project["project"]["status"] == "active"
            assert empty_project["program"]["nodes"] == []
            status, _ = request(
                server,
                "POST",
                f"/api/projects/{empty_project_id}/materials/{study_material['id']}/processing",
                {"parser_mode": "fast"},
            )
            assert status == 200
            run_worker(data_dir)
            status, study_ready = request(
                server,
                "GET",
                f"/api/projects/{empty_project_id}/materials/{study_material['id']}",
            )
            assert status == 200 and study_ready["status"] == "ready"

            project_id, _ = create_exam_project(server)
            status, ocr_settings = request(server, "GET", "/api/settings/ocr")
            assert status == 200
            ocr_engines = {engine["mode"]: engine for engine in ocr_settings["engines"]}
            assert ocr_engines["fast"]["available"] is True
            assert ocr_engines["textbook"]["available"] is False

            status, material = request(
                server,
                "POST",
                f"/api/projects/{project_id}/materials/text",
                {
                    "name": "Эталонные ответы.txt",
                    "text": (
                        "1. Индексы\n"
                        "Индекс ускоряет поиск строк по выбранным столбцам.\n"
                        "2. Транзакции\n"
                        "Транзакция объединяет изменения в атомарную единицу работы.\n"
                        "3. Архитектура СУБД\n"
                        "СУБД разделяет хранение, выполнение запросов и управление транзакциями."
                    ),
                    "source_role": "reference",
                    "purposes": ["reference_answers"],
                },
            )
            assert status == 201 and material["status"] == "ready_to_process"
            material_id = material["id"]

            status, queued = request(
                server,
                "POST",
                f"/api/projects/{project_id}/materials/{material_id}/processing",
                {"parser_mode": "fast"},
            )
            assert status == 200 and queued["task"]["state"] == "queued"
            run_worker(data_dir)

            status, ready = request(
                server, "GET", f"/api/projects/{project_id}/materials/{material_id}"
            )
            assert status == 200 and ready["status"] == "ready", ready
            assert ready["active_parse_revision"] == 1
            status, page = request(
                server, "GET", f"/api/projects/{project_id}/materials/{material_id}/pages/1"
            )
            assert status == 200 and page["quality"] == "native"
            assert [block["title"] for block in page["blocks"]] == [
                "1. Индексы",
                "2. Транзакции",
                "3. Архитектура СУБД",
            ]
            assert len(page["fragments"]) == 6

            # Файл эталонных ответов после разбора привязывается сам и сам заполняет
            # эталоны (см. materials-viewer-and-answers-autolink.md), поэтому ручной
            # импорт к этому моменту уже ничего не создаёт.
            status, coverage = request(server, "GET", f"/api/projects/{project_id}/coverage-map")
            assert status == 200
            filled = [row for row in coverage["rows"] if row["answer_status"] != "missing"]
            assert len(filled) == 3, filled
            status, auto_bindings = request(
                server, "GET", f"/api/projects/{project_id}/bindings?material_id={material_id}"
            )
            assert status == 200 and auto_bindings, auto_bindings
            assert {binding["mechanism"] for binding in auto_bindings} == {"answers_file"}

            status, imported = request(
                server,
                "POST",
                f"/api/projects/{project_id}/materials/{material_id}/reference-answer-import",
            )
            assert status == 200 and imported["created"] == 0
            assert imported["skipped_existing"] == 3
            assert imported["empty_sections"] == []

            status, question_material = request(
                server,
                "POST",
                f"/api/projects/{project_id}/materials/text",
                {
                    "name": "Вопросы.txt",
                    "text": "1. Индексы\n2. Новая тема",
                    "source_role": "reference",
                    "purposes": ["exam_structure"],
                },
            )
            assert status == 201
            question_material_id = question_material["id"]
            status, _ = request(
                server,
                "POST",
                f"/api/projects/{project_id}/materials/{question_material_id}/processing",
                {"parser_mode": "fast"},
            )
            assert status == 200
            run_worker(data_dir)
            status, preview = request(
                server,
                "GET",
                f"/api/projects/{project_id}/materials/{question_material_id}/exam-program-preview",
            )
            assert status == 200 and preview["counts"]["questions"] == 2
            assert [item["title"] for item in preview["nodes"]] == ["Индексы", "Новая тема"]
            status, project = request(server, "GET", f"/api/projects/{project_id}")
            assert status == 200
            status, replaced = request(
                server,
                "POST",
                f"/api/projects/{project_id}/materials/{question_material_id}/exam-program-import",
                {"expected_program_revision": project["program"]["revision"]},
            )
            assert status == 200
            current = [
                node
                for node in replaced["program"]["nodes"]
                if node["is_in_current_program"] and not node["is_archived"]
            ]
            assert [node["title"] for node in current] == ["Индексы", "Новая тема"]
            assert all(node["origin_material_id"] == question_material_id for node in current)

            status, corrected = request(
                server,
                "PUT",
                f"/api/projects/{project_id}/materials/{question_material_id}/pages/1",
                {"text": "1. Индексы\n2. Новая тема исправлена"},
            )
            assert status == 200
            assert [block["title"] for block in corrected["page"]["blocks"]] == [
                "1. Индексы",
                "2. Новая тема исправлена",
            ]
            assert corrected["transferred_bindings"] == 0
            assert corrected["orphaned_binding_ids"] == []

            status, library = request(server, "GET", "/api/materials")
            assert status == 200
            question_row = next(item for item in library if item["id"] == question_material_id)
            assert question_row["usage"][0]["project_id"] == project_id

            status, deletion = request(
                server, "GET", f"/api/materials/{material_id}/delete-preview"
            )
            assert status == 200 and deletion["reference_answer_count"] == 3
            # Файл ответов привязался сам (без строки заголовка — она повторяет вопрос,
            # а не отвечает на него), поэтому удаление честно предупреждает, какие узлы
            # останутся без материала.
            assert deletion["binding_count"] == 3
            assert deletion["affected_projects"][0]["project_id"] == project_id
            assert sorted(deletion["affected_projects"][0]["nodes_losing_material"]) == [
                "Архитектура СУБД",
                "Индексы",
                "Транзакции",
            ]
            status, _ = request(server, "DELETE", f"/api/materials/{material_id}")
            assert status == 204

            status, second = request(
                server,
                "POST",
                f"/api/projects/{project_id}/materials/text",
                {"name": "Повторный запуск.txt", "text": "# Заголовок\nТекст блока"},
            )
            assert status == 201
            status, _ = request(
                server,
                "POST",
                f"/api/projects/{project_id}/materials/{second['id']}/processing",
                {"parser_mode": "fast"},
            )
            assert status == 200
            with closing(sqlite3.connect(data_dir / "tentex.sqlite")) as connection:
                connection.execute(
                    """
                    UPDATE processing_tasks
                    SET state = 'running', lease_owner = 'dead-worker', lease_expires_at = ?
                    WHERE material_id = ?
                    """,
                    ("2000-01-01 00:00:00.000000", second["id"].replace("-", "")),
                )
                connection.commit()
            run_worker(data_dir)
            status, recovered = request(
                server, "GET", f"/api/projects/{project_id}/materials/{second['id']}"
            )
            assert status == 200 and recovered["status"] == "ready", recovered
        except Exception:
            server.stop()
            if server.stderr_output:
                print(server.stderr_output, file=sys.stderr)
            raise
        finally:
            server.stop()

        with closing(sqlite3.connect(data_dir / "tentex.sqlite")) as connection:
            assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
            assert (
                connection.execute("SELECT version_num FROM alembic_version").fetchone()[0]
                == alembic_head()
            )
            assert connection.execute("SELECT COUNT(*) FROM material_pages").fetchone()[0] == 5
            assert (
                connection.execute(
                    "SELECT COUNT(*) FROM reference_answers WHERE source_material_id IS NOT NULL"
                ).fetchone()[0]
                == 0
            )
            assert connection.execute("SELECT COUNT(*) FROM reference_answers").fetchone()[0] == 3

    print("stage 5 smoke check passed")


if __name__ == "__main__":
    run()
