"""Сквозная проверка эталонных ответов и удаления проектов этапа 4."""

import sqlite3
import sys
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory

from check_stage2 import ApiServer, free_port, request
from check_stage3 import assert_error, create_saved_draft, draft_payload


def create_exam_project(server: ApiServer) -> tuple[str, dict[str, object]]:
    status, created = request(
        server,
        "POST",
        "/api/wizard-drafts",
        {"template_key": "exam"},
    )
    assert status == 201 and isinstance(created, dict)
    project_id = created["project"]["id"]
    payload = draft_payload(
        0,
        name="Тест эталонных ответов",
        exam_format="questions",
    )
    payload["goal_passport"]["expected_item_count"] = 3
    status, saved = request(
        server,
        "PUT",
        f"/api/wizard-drafts/{project_id}",
        payload,
    )
    assert status == 200 and saved["draft"]["revision"] == 1
    status, imported = request(
        server,
        "POST",
        f"/api/wizard-drafts/{project_id}/exam-import",
        {
            "expected_revision": 1,
            "expected_program_revision": 0,
            "exam_format": "questions",
            "raw_text": (
                "Вопросы:\n"
                "1. Индексы\n"
                "2. Транзакции\n"
                "3. Архитектура СУБД"
            ),
        },
    )
    assert status == 200
    assert imported["counts"] == {"tickets": 0, "questions": 3, "tasks": 0}
    status, activated = request(
        server,
        "POST",
        f"/api/wizard-drafts/{project_id}/activate",
        {"expected_revision": 2},
    )
    assert status == 200 and activated["project"]["status"] == "active"
    return project_id, activated


def run() -> None:
    with TemporaryDirectory(prefix="tentex-stage4-") as temporary_dir:
        data_dir = Path(temporary_dir)
        server = ApiServer(data_dir, free_port(), seed_demo_project=True)
        try:
            server.start()

            status, projects = request(server, "GET", "/api/projects")
            assert status == 200 and len(projects) == 1
            demo_id = projects[0]["id"]
            status, demo_map = request(
                server,
                "GET",
                f"/api/projects/{demo_id}/coverage-map",
            )
            assert status == 200
            assert demo_map["totals"] == {
                "study_nodes": 4,
                "with_answer": 4,
                "confirmed": 4,
                "needs_review": 0,
                "missing": 0,
            }
            row_indexes = {row["node_id"]: index for index, row in enumerate(demo_map["rows"])}
            assert all(
                row["parent_id"] is None
                or row_indexes[row["parent_id"]] < row_indexes[row["node_id"]]
                for row in demo_map["rows"]
            )

            project_id, activated = create_exam_project(server)
            nodes = activated["program"]["nodes"]
            by_title = {node["title"]: node for node in nodes}
            index_id = by_title["Индексы"]["id"]
            transaction_id = by_title["Транзакции"]["id"]
            architecture_id = by_title["Архитектура СУБД"]["id"]

            status, imported_answers = request(
                server,
                "POST",
                f"/api/projects/{project_id}/reference-answers/import",
                {
                    "source_label": "Вставленный конспект",
                    "raw_text": (
                        "Пояснение перед первым вопросом\n\n"
                        "1. Индексы\n"
                        "Ответ: Индекс ускоряет поиск ценой дополнительного места и записи.\n\n"
                        "2. Транзакции\n"
                        "Ответ:\n"
                        "Транзакция объединяет операции в одну логическую единицу.\n\n"
                        "3. Архитектура СУБД\n"
                        "Ответ:"
                    ),
                },
            )
            assert status == 200, imported_answers
            assert imported_answers["created"] == 2
            assert len(imported_answers["unmatched_sections"]) == 1
            assert imported_answers["empty_sections"] == ["3. Архитектура СУБД"]
            assert imported_answers["coverage_map"]["totals"]["with_answer"] == 2

            status, index_slot = request(
                server,
                "GET",
                f"/api/projects/{project_id}/program-nodes/{index_id}/reference-answer",
            )
            assert status == 200 and index_slot["status"] == "auto_matched"
            assert index_slot["answer"]["revision"] == 0
            status, confirmed = request(
                server,
                "POST",
                f"/api/projects/{project_id}/program-nodes/{index_id}/reference-answer/confirm",
                {"expected_revision": 0},
            )
            assert status == 200 and confirmed["status"] == "confirmed"
            assert confirmed["answer"]["revision"] == 1

            status, renamed = request(
                server,
                "PATCH",
                f"/api/projects/{project_id}/program-nodes/{index_id}",
                {
                    "expected_program_revision": activated["program"]["revision"],
                    "title": "Индексы и структуры поиска",
                },
            )
            assert status == 200
            status, renamed_slot = request(
                server,
                "GET",
                f"/api/projects/{project_id}/program-nodes/{index_id}/reference-answer",
            )
            assert status == 200 and renamed_slot["status"] == "needs_review"

            status, section_result = request(
                server,
                "POST",
                f"/api/projects/{project_id}/program-nodes",
                {
                    "expected_program_revision": renamed["program"]["revision"],
                    "node_type": "section",
                    "title": "Дополнительный раздел",
                },
            )
            assert status == 201
            section_id = section_result["changed_node"]["id"]
            status, moved = request(
                server,
                "POST",
                f"/api/projects/{project_id}/program-nodes/{index_id}/move",
                {
                    "expected_program_revision": section_result["program"]["revision"],
                    "parent_id": section_id,
                    "position": 0,
                },
            )
            assert status == 200
            status, moved_slot = request(
                server,
                "GET",
                f"/api/projects/{project_id}/program-nodes/{index_id}/reference-answer",
            )
            assert status == 200 and moved_slot["answer"]["program_node_id"] == index_id
            assert moved_slot["status"] == "needs_review"
            status, reconfirmed = request(
                server,
                "POST",
                f"/api/projects/{project_id}/program-nodes/{index_id}/reference-answer/confirm",
                {"expected_revision": 1},
            )
            assert status == 200 and reconfirmed["status"] == "confirmed"
            assert_error(
                request(
                    server,
                    "POST",
                    f"/api/projects/{project_id}/program-nodes/{index_id}/reference-answer/confirm",
                    {"expected_revision": 1},
                ),
                409,
                "stale_reference_answer_revision",
                "current_reference_answer_revision",
            )

            status, removed_node = request(
                server,
                "POST",
                f"/api/projects/{project_id}/program-nodes/{index_id}/remove",
                {"expected_program_revision": moved["program"]["revision"]},
            )
            assert status == 200
            status, outside_slot = request(
                server,
                "GET",
                f"/api/projects/{project_id}/program-nodes/{index_id}/reference-answer",
            )
            assert status == 200
            assert outside_slot["answer"]["program_node_id"] == index_id
            assert outside_slot["status"] == "confirmed"
            status, restored_node = request(
                server,
                "POST",
                f"/api/projects/{project_id}/program-nodes/{index_id}/restore",
                {"expected_program_revision": removed_node["program"]["revision"]},
            )
            assert status == 200
            assert restored_node["changed_node"]["is_in_current_program"] is True
            status, restored_slot = request(
                server,
                "GET",
                f"/api/projects/{project_id}/program-nodes/{index_id}/reference-answer",
            )
            assert status == 200
            assert restored_slot["answer"]["program_node_id"] == index_id
            assert restored_slot["status"] == "confirmed"

            status, manual = request(
                server,
                "PUT",
                f"/api/projects/{project_id}/program-nodes/{architecture_id}/reference-answer",
                {
                    "expected_revision": None,
                    "text": "СУБД разделяет обработку запросов, транзакций и хранение данных.",
                },
            )
            assert status == 200 and manual["status"] == "manual"
            assert manual["answer"]["revision"] == 0

            status, removed = request(
                server,
                "DELETE",
                (
                    f"/api/projects/{project_id}/program-nodes/{transaction_id}"
                    "/reference-answer?expected_revision=0"
                ),
            )
            assert status == 200 and removed["status"] == "missing"
            assert removed["answer"]["is_active"] is False
            assert removed["answer"]["revision"] == 1
            assert_error(
                request(
                    server,
                    "PUT",
                    f"/api/projects/{project_id}/program-nodes/{transaction_id}/reference-answer",
                    {"expected_revision": None, "text": "Нельзя создать поверх снятого"},
                ),
                409,
                "reference_answer_exists",
                "current_reference_answer_revision",
            )
            status, reactivated = request(
                server,
                "PUT",
                f"/api/projects/{project_id}/program-nodes/{transaction_id}/reference-answer",
                {"expected_revision": 1, "text": "Транзакция — единица работы с БД."},
            )
            assert status == 200 and reactivated["status"] == "manual"
            assert reactivated["answer"]["revision"] == 2

            status, repeated = request(
                server,
                "POST",
                f"/api/projects/{project_id}/reference-answers/import",
                {
                    "raw_text": (
                        "Индексы и структуры поиска\nНовый текст не должен заменить ответ.\n"
                        "Транзакции\nНовый текст не должен заменить ответ."
                    )
                },
            )
            assert status == 200 and repeated["created"] == 0
            assert set(repeated["skipped_existing"]) == {index_id, transaction_id}

            status, duplicate = request(
                server,
                "POST",
                f"/api/projects/{project_id}/program-nodes",
                {
                    "expected_program_revision": restored_node["program"]["revision"],
                    "node_type": "topic",
                    "exam_kind": "question",
                    "title": "Транзакции",
                },
            )
            assert status == 201
            status, ambiguous = request(
                server,
                "POST",
                f"/api/projects/{project_id}/reference-answers/import",
                {"raw_text": "Транзакции\nНеоднозначный ответ"},
            )
            assert status == 200 and ambiguous["created"] == 0
            assert len(ambiguous["ambiguous"]) == 1
            assert len(ambiguous["ambiguous"][0]["candidate_node_ids"]) == 2

            status, coverage = request(
                server,
                "GET",
                f"/api/projects/{project_id}/coverage-map",
            )
            assert status == 200
            assert coverage["totals"] == {
                "study_nodes": 4,
                "with_answer": 3,
                "confirmed": 3,
                "needs_review": 0,
                "missing": 1,
            }

            status, archived = request(
                server,
                "POST",
                f"/api/projects/{project_id}/archive",
            )
            assert status == 200 and archived["status"] == "archived"
            status, _ = request(
                server,
                "GET",
                f"/api/projects/{project_id}/coverage-map",
            )
            assert status == 200
            assert_error(
                request(
                    server,
                    "PUT",
                    f"/api/projects/{project_id}/program-nodes/{architecture_id}/reference-answer",
                    {
                        "expected_revision": manual["answer"]["revision"],
                        "text": "Архив нельзя менять",
                    },
                ),
                409,
                "project_read_only",
            )

            textbook_id, _ = create_saved_draft(server, "textbook")
            status, textbook_project = request(
                server,
                "POST",
                f"/api/wizard-drafts/{textbook_id}/activate",
                {"expected_revision": 1},
            )
            assert status == 200 and textbook_project["project"]["status"] == "active"
            assert textbook_project["program"]["nodes"] == []
            assert_error(
                request(server, "GET", f"/api/projects/{textbook_id}/coverage-map"),
                409,
                "reference_answers_require_exam_project",
            )

            status, _ = request(server, "DELETE", f"/api/projects/{project_id}")
            assert status == 204
            status, _ = request(server, "DELETE", f"/api/projects/{textbook_id}")
            assert status == 204

            demo_answer_row = next(
                row for row in demo_map["rows"] if row["answer_revision"] is not None
            )
            status, demo_removed = request(
                server,
                "DELETE",
                (
                    f"/api/projects/{demo_id}/program-nodes/{demo_answer_row['node_id']}"
                    "/reference-answer?expected_revision=0"
                ),
            )
            assert status == 200 and demo_removed["answer"]["revision"] == 1
            server.stop()
            server.start()
            status, after_restart = request(
                server,
                "GET",
                (
                    f"/api/projects/{demo_id}/program-nodes/{demo_answer_row['node_id']}"
                    "/reference-answer"
                ),
            )
            assert status == 200
            assert after_restart["status"] == "missing"
            assert after_restart["answer"]["revision"] == 1

            status, _ = request(server, "DELETE", f"/api/projects/{demo_id}")
            assert status == 204
            server.stop()
            server.start()
            assert_error(
                request(server, "GET", f"/api/projects/{demo_id}"),
                404,
                "not_found",
            )
        except Exception:
            server.stop()
            if server.stderr_output:
                print(server.stderr_output, file=sys.stderr)
            raise
        finally:
            server.stop()

        database_path = data_dir / "tentex.sqlite"
        with closing(sqlite3.connect(database_path)) as connection:
            assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
            assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
            assert connection.execute("SELECT COUNT(*) FROM projects").fetchone()[0] == 0
            assert connection.execute(
                "SELECT COUNT(*) FROM reference_answers"
            ).fetchone()[0] == 0
            migration = connection.execute(
                "SELECT version_num FROM alembic_version"
            ).fetchone()[0]
            assert migration == "20260812_0014"

    print("stage 4 smoke check passed")


if __name__ == "__main__":
    run()
