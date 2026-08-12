"""Сквозная проверка живых проектов и Программы этапа 3."""

import sqlite3
import sys
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory

from check_stage2 import ApiServer, free_port, request


def assert_error(
    response: tuple[int, object], status: int, code: str, context_key: str | None = None
) -> dict[str, object]:
    actual_status, payload = response
    assert actual_status == status, payload
    assert isinstance(payload, dict) and payload.get("code") == code, payload
    if context_key:
        assert context_key in payload.get("context", {}), payload
    return payload


def goal_passport(
    *, target: str = "application", exam_format: str | None = "tickets"
) -> dict[str, object]:
    return {
        "subject": "Базы данных",
        "purpose": "exam" if exam_format else "interest",
        "scope": "whole",
        "starting_level": "familiar",
        "current_knowledge": "Знаком с SQL",
        "target_outcome": target,
        "goal": "Разобраться в теме",
        "success_criterion": "Объяснить без конспекта",
        "important": "Транзакции",
        "excluded": None,
        "study_format": "theory_and_practice",
        "minutes_per_day": 45,
        "days_per_week": 4,
        "session_minutes": 45,
        "exam_format": exam_format,
        "expected_item_count": 2 if exam_format else None,
        "instructor_requirements": None,
    }


def draft_payload(
    revision: int,
    *,
    name: str = "Базы данных — экзамен",
    target: str = "application",
    exam_format: str | None = "tickets",
) -> dict[str, object]:
    return {
        "expected_revision": revision,
        "current_step": 3,
        "max_completed_step": 3,
        "schema_version": 1,
        "project": {
            "name": name,
            "description": None,
            "icon": "database" if exam_format else "book-open",
            "color": 2,
            "deadline": None,
            "enabled_modules": ["cards", "plan", "cards", "repetitions"],
        },
        "goal_passport": goal_passport(target=target, exam_format=exam_format),
        "state": {"input_mode": "text"},
    }


def create_saved_draft(
    server: ApiServer, template: str = "exam"
) -> tuple[str, dict[str, object]]:
    status, created = request(
        server, "POST", "/api/wizard-drafts", {"template_key": template}
    )
    assert status == 201 and isinstance(created, dict)
    project_id = created["project"]["id"]
    payload = draft_payload(
        0,
        name="Учебник по индексам" if template == "textbook" else "Базы данных — экзамен",
        target="understanding" if template == "textbook" else "application",
        exam_format=None if template == "textbook" else "tickets",
    )
    status, saved = request(server, "PUT", f"/api/wizard-drafts/{project_id}", payload)
    assert status == 200 and saved["draft"]["revision"] == 1
    return project_id, saved


def check_import_variants(server: ApiServer) -> None:
    cases = [
        (
            "questions",
            "Вопросы:\n1. Индексы\n2. Транзакции",
            {"tickets": 0, "questions": 2, "tasks": 0},
        ),
        (
            "questions",
            "Архитектура СУБД\nРеляционная модель",
            {"tickets": 0, "questions": 2, "tasks": 0},
        ),
        (
            "questions_tasks",
            "Вопросы\n1. Индексы\nЗадачи\n1. Составить SQL-запрос",
            {"tickets": 0, "questions": 1, "tasks": 1},
        ),
        (
            "tickets",
            (
                "Билет № 1\n1. Транзакции и ACID,\n   уровни изоляции\n"
                "2. Задача: нормализовать отношение"
            ),
            {"tickets": 1, "questions": 1, "tasks": 1},
        ),
    ]
    for exam_format, raw_text, counts in cases:
        project_id, _ = create_saved_draft(server)
        status, imported = request(
            server,
            "POST",
            f"/api/wizard-drafts/{project_id}/exam-import",
            {
                "expected_revision": 1,
                "expected_program_revision": 0,
                "exam_format": exam_format,
                "raw_text": raw_text,
            },
        )
        assert status == 200 and imported["counts"] == counts, imported
        status, _ = request(
            server,
            "DELETE",
            f"/api/wizard-drafts/{project_id}?expected_revision=2",
        )
        assert status == 204


def run() -> None:
    with TemporaryDirectory(prefix="tentex-stage3-") as temporary_dir:
        data_dir = Path(temporary_dir)
        server = ApiServer(data_dir, free_port(), seed_demo_project=True)
        try:
            server.start()
            status, projects = request(server, "GET", "/api/projects")
            assert status == 200 and len(projects) == 1
            demo = projects[0]
            assert demo["name"] == "Базы данных — экзамен (пример)"
            demo_id = demo["id"]
            status, demo_detail = request(server, "GET", f"/api/projects/{demo_id}")
            assert status == 200
            assert len(demo_detail["program"]["nodes"]) == 6
            assert demo_detail["program"]["revision"] == 0
            assert demo_detail["latest_undoable_action"] is None
            assert demo_detail["workspace_state"]["layout"]["tree_width"] == 320
            demo_updated_at = demo_detail["project"]["updated_at"]

            server.stop()
            server.start()
            status, restarted_demo = request(server, "GET", f"/api/projects/{demo_id}")
            assert status == 200
            assert restarted_demo["project"]["updated_at"] == demo_updated_at
            assert len(restarted_demo["program"]["nodes"]) == 6

            assert_error(
                request(server, "POST", "/api/wizard-drafts", {"template_key": "free"}),
                409,
                "unsupported_template",
            )
            status, _ = request(
                server,
                "POST",
                "/api/wizard-drafts",
                {"template_key": "exam", "workspace_variant": "exam"},
            )
            assert status == 422

            project_id, saved = create_saved_draft(server)
            assert saved["project"]["workspace_variant"] == "exam"
            assert saved["project"]["enabled_modules"] == ["plan", "cards", "repetitions"]
            assert_error(
                request(
                    server,
                    "PUT",
                    f"/api/wizard-drafts/{project_id}",
                    draft_payload(0),
                ),
                409,
                "stale_draft_revision",
                "current_draft_revision",
            )
            invalid_icon = draft_payload(1)
            invalid_icon["project"]["icon"] = "rocket"
            status, _ = request(
                server, "PUT", f"/api/wizard-drafts/{project_id}", invalid_icon
            )
            assert status == 422

            invalid_tickets = {
                "expected_revision": 1,
                "expected_program_revision": 0,
                "exam_format": "tickets",
                "raw_text": "1. Вопрос без заголовка билета",
            }
            status, _ = request(
                server,
                "POST",
                f"/api/wizard-drafts/{project_id}/exam-import",
                invalid_tickets,
            )
            assert status == 422
            too_large = dict(invalid_tickets, raw_text="x" * 1_000_001)
            status, _ = request(
                server,
                "POST",
                f"/api/wizard-drafts/{project_id}/exam-import",
                too_large,
            )
            assert status == 422

            ticket_text = (
                "Билет 1\n1. Реляционная модель\n2. Задача: нормализовать отношение\n\n"
                "Билет 2\n1. Транзакции и свойства ACID\n2. Реляционная модель"
            )
            status, imported = request(
                server,
                "POST",
                f"/api/wizard-drafts/{project_id}/exam-import",
                {
                    "expected_revision": 1,
                    "expected_program_revision": 0,
                    "exam_format": "tickets",
                    "raw_text": ticket_text,
                },
            )
            assert status == 200 and imported["revision"] == 2
            assert imported["program"]["revision"] == 1
            assert imported["warnings"]
            first_import_ids = [node["id"] for node in imported["program"]["nodes"]]
            import_sequence = imported["latest_undoable_action"]["sequence"]

            server.stop()
            server.start()
            status, resumed = request(server, "GET", f"/api/wizard-drafts/{project_id}")
            assert status == 200 and resumed["draft"]["revision"] == 2
            assert [node["id"] for node in resumed["program"]["nodes"]] == first_import_ids
            status, undone = request(
                server,
                "POST",
                f"/api/projects/{project_id}/actions/undo",
                {"expected_action_sequence": import_sequence},
            )
            assert status == 200 and undone["program"]["nodes"] == []
            assert undone["program"]["revision"] == 2 and undone["draft_revision"] == 3
            assert_error(
                request(
                    server,
                    "POST",
                    f"/api/projects/{project_id}/actions/undo",
                    {"expected_action_sequence": import_sequence},
                ),
                409,
                "stale_action_sequence",
                "current_action_sequence",
            )

            status, imported = request(
                server,
                "POST",
                f"/api/wizard-drafts/{project_id}/exam-import",
                {
                    "expected_revision": 3,
                    "expected_program_revision": 2,
                    "exam_format": "tickets",
                    "raw_text": ticket_text,
                },
            )
            assert status == 200 and imported["revision"] == 4
            assert imported["program"]["revision"] == 3
            status, activated = request(
                server,
                "POST",
                f"/api/wizard-drafts/{project_id}/activate",
                {"expected_revision": 4},
            )
            assert status == 200 and activated["project"]["status"] == "active"
            assert activated["program"]["revision"] == 3
            status, drafts = request(server, "GET", "/api/wizard-drafts")
            assert status == 200 and all(item["project_id"] != project_id for item in drafts)

            status, created = request(
                server,
                "POST",
                f"/api/projects/{project_id}/program-nodes",
                {
                    "expected_program_revision": 3,
                    "position": 0,
                    "node_type": "section",
                    "title": "Дополнительный раздел",
                },
            )
            assert status == 201 and created["program"]["revision"] == 4
            section = created["changed_node"]
            assert section["target_level"] == "application"
            assert created["draft_revision"] is None
            assert_error(
                request(
                    server,
                    "POST",
                    f"/api/projects/{project_id}/program-nodes",
                    {
                        "expected_program_revision": 3,
                        "node_type": "section",
                        "title": "Устаревшее изменение",
                    },
                ),
                409,
                "stale_program_revision",
                "current_program_revision",
            )

            study_node = next(
                node for node in created["program"]["nodes"] if node["exam_kind"] == "question"
            )
            status, moved = request(
                server,
                "POST",
                f"/api/projects/{project_id}/program-nodes/{study_node['id']}/move",
                {
                    "expected_program_revision": 4,
                    "parent_id": section["id"],
                    "position": 0,
                },
            )
            assert status == 200 and moved["program"]["revision"] == 5
            swap_target = next(
                node
                for node in moved["program"]["nodes"]
                if node["exam_kind"] == "question" and node["id"] != study_node["id"]
            )
            status, swapped = request(
                server,
                "POST",
                f"/api/projects/{project_id}/program-nodes/{study_node['id']}/swap",
                {
                    "expected_program_revision": 5,
                    "target_node_id": swap_target["id"],
                },
            )
            assert status == 200 and swapped["program"]["revision"] == 6
            swapped_nodes = {node["id"]: node for node in swapped["program"]["nodes"]}
            assert swapped_nodes[study_node["id"]]["parent_id"] == swap_target["parent_id"]
            assert swapped_nodes[swap_target["id"]]["parent_id"] == section["id"]
            swap_sequence = swapped["latest_undoable_action"]["sequence"]
            status, undone_swap = request(
                server,
                "POST",
                f"/api/projects/{project_id}/actions/undo",
                {"expected_action_sequence": swap_sequence},
            )
            assert status == 200 and undone_swap["program"]["revision"] == 7
            restored_nodes = {node["id"]: node for node in undone_swap["program"]["nodes"]}
            assert restored_nodes[study_node["id"]]["parent_id"] == section["id"]
            assert restored_nodes[swap_target["id"]]["parent_id"] == swap_target["parent_id"]
            status, swapped = request(
                server,
                "POST",
                f"/api/projects/{project_id}/program-nodes/{study_node['id']}/swap",
                {
                    "expected_program_revision": 7,
                    "target_node_id": swap_target["id"],
                },
            )
            assert status == 200 and swapped["program"]["revision"] == 8
            status, targeted = request(
                server,
                "POST",
                f"/api/projects/{project_id}/program-nodes/{section['id']}/target-level",
                {
                    "expected_program_revision": 8,
                    "target_level": "mastery",
                    "include_descendants": True,
                },
            )
            assert status == 200 and targeted["program"]["revision"] == 9
            assert all(
                node["target_level"] == "mastery"
                for node in targeted["program"]["nodes"]
                if node["id"] in {section["id"], swap_target["id"]}
            )
            status, removed = request(
                server,
                "POST",
                f"/api/projects/{project_id}/program-nodes/{section['id']}/remove",
                {"expected_program_revision": 9},
            )
            assert status == 200 and removed["program"]["revision"] == 10
            status, _ = request(
                server,
                "POST",
                f"/api/projects/{project_id}/program-nodes/{swap_target['id']}/restore",
                {"expected_program_revision": 10},
            )
            assert status == 422
            status, restored = request(
                server,
                "POST",
                f"/api/projects/{project_id}/program-nodes/{section['id']}/restore",
                {"expected_program_revision": 10},
            )
            assert status == 200 and restored["program"]["revision"] == 11
            restore_sequence = restored["latest_undoable_action"]["sequence"]
            status, undo_restore = request(
                server,
                "POST",
                f"/api/projects/{project_id}/actions/undo",
                {"expected_action_sequence": restore_sequence},
            )
            assert status == 200 and undo_restore["program"]["revision"] == 12

            status, project_list = request(server, "GET", "/api/projects")
            active_ids = [item["id"] for item in project_list if item["status"] == "active"]
            assert len(active_ids) == 2 and len(set(active_ids)) == 2
            status, ordered = request(
                server, "PUT", "/api/projects/order", {"project_ids": active_ids[::-1]}
            )
            assert status == 200 and [item["id"] for item in ordered] == active_ids[::-1]
            status, _ = request(
                server,
                "PUT",
                "/api/projects/order",
                {"project_ids": [active_ids[0], active_ids[0]]},
            )
            assert status == 422

            status, archived = request(
                server, "POST", f"/api/projects/{project_id}/archive"
            )
            assert status == 200 and archived["status"] == "archived"
            status, archived_again = request(
                server, "POST", f"/api/projects/{project_id}/archive"
            )
            assert status == 200 and archived_again["status"] == "archived"
            status, restored_project = request(
                server, "POST", f"/api/projects/{project_id}/restore"
            )
            assert status == 200 and restored_project["status"] == "active"
            status, restored_again = request(
                server, "POST", f"/api/projects/{project_id}/restore"
            )
            assert status == 200 and restored_again["status"] == "active"

            status, before_layout = request(server, "GET", f"/api/projects/{project_id}")
            assert status == 200
            selected_id = next(
                node["id"]
                for node in before_layout["program"]["nodes"]
                if node["node_type"] == "topic" and node["is_in_current_program"]
            )
            project_updated_at = before_layout["project"]["updated_at"]
            status, _ = request(
                server,
                "PUT",
                f"/api/projects/{project_id}/workspace-state",
                {
                    "schema_version": 1,
                    "layout": {
                        "selected_node_id": selected_id,
                        "expanded_node_ids": [],
                        "tree_width": 360,
                        "groups": [
                            {
                                "id": "main",
                                "tabs": ["answer", "source"],
                                "active_tab": "source",
                            }
                        ],
                        "group_weights": [1],
                    },
                },
            )
            assert status == 200
            status, after_layout = request(server, "GET", f"/api/projects/{project_id}")
            assert status == 200 and after_layout["project"]["updated_at"] == project_updated_at

            textbook_id, textbook = create_saved_draft(server, "textbook")
            assert textbook["project"]["workspace_variant"] == "textbook"
            status, textbook_node = request(
                server,
                "POST",
                f"/api/projects/{textbook_id}/program-nodes",
                {
                    "expected_program_revision": 0,
                    "node_type": "topic",
                    "exam_kind": None,
                    "title": "Устройство индекса",
                },
            )
            assert status == 201
            assert textbook_node["draft_revision"] == 2
            assert textbook_node["changed_node"]["target_level"] == "understanding"
            sequence = textbook_node["latest_undoable_action"]["sequence"]
            server.stop()
            server.start()
            status, textbook_undo = request(
                server,
                "POST",
                f"/api/projects/{textbook_id}/actions/undo",
                {"expected_action_sequence": sequence},
            )
            assert status == 200 and textbook_undo["draft_revision"] == 3
            status, _ = request(
                server,
                "DELETE",
                f"/api/wizard-drafts/{textbook_id}?expected_revision=3",
            )
            assert status == 204

            check_import_variants(server)

            status, _ = request(server, "DELETE", f"/api/projects/{project_id}")
            assert status == 204
            assert_error(
                request(server, "GET", f"/api/projects/{project_id}"),
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
            assert connection.execute("SELECT COUNT(*) FROM materials").fetchone()[0] == 0
            assert connection.execute(
                """
                SELECT COUNT(*) FROM project_action_log
                WHERE payload_version != 1 OR phase NOT IN ('draft', 'active')
                """
            ).fetchone()[0] == 0
            duplicate_orders = connection.execute(
                """
                SELECT project_id, parent_id, sort_order, COUNT(*)
                FROM program_nodes
                GROUP BY project_id, parent_id, sort_order
                HAVING COUNT(*) > 1
                """
            ).fetchall()
            assert duplicate_orders == []
            migration = connection.execute(
                "SELECT version_num FROM alembic_version"
            ).fetchone()[0]
            assert migration == "20260812_0011"

    print("stage 3 smoke check passed")


if __name__ == "__main__":
    run()
