"""Сквозная проверка ядра этапа 2 без тестового фреймворка."""

import json
import os
import socket
import sqlite3
import subprocess
import sys
import time
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

BACKEND_ROOT = Path(__file__).resolve().parent.parent


def alembic_head() -> str:
    """Голова цепочки миграций из файлов, а не зашитая в проверку строка.

    Константа устаревала при каждой новой миграции и роняла проверку по причине,
    к предмету проверки отношения не имеющей.
    """
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "migrations"))
    head = ScriptDirectory.from_config(config).get_current_head()
    assert head is not None
    return head


def free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


class ApiServer:
    def __init__(self, data_dir: Path, port: int, *, seed_demo_project: bool = False) -> None:
        self.data_dir = data_dir
        self.port = port
        self.seed_demo_project = seed_demo_project
        self.process: subprocess.Popen[str] | None = None
        self.stderr_output = ""

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def start(self) -> None:
        environment = os.environ.copy()
        environment["TENTEX_DATA_DIR"] = str(self.data_dir)
        environment["TENTEX_SEED_DEMO_PROJECT"] = "true" if self.seed_demo_project else "false"
        self.process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "app.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(self.port),
                "--log-level",
                "warning",
            ],
            cwd=BACKEND_ROOT,
            env=environment,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                self._raise_startup_error()
            try:
                with urlopen(f"{self.base_url}/api/health", timeout=0.5) as response:
                    if response.status == 200:
                        return
            except (URLError, TimeoutError):
                time.sleep(0.1)
        self.stop()
        raise RuntimeError("API не запустился за 20 секунд")

    def stop(self) -> None:
        if self.process is None:
            return
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
        if self.process.stderr:
            self.stderr_output += self.process.stderr.read()
        self.process = None

    def _raise_startup_error(self) -> None:
        assert self.process is not None
        error = self.process.stderr.read() if self.process.stderr else ""
        raise RuntimeError(f"API завершился при старте:\n{error}")


def request(
    server: ApiServer,
    method: str,
    path: str,
    payload: dict[str, object] | None = None,
) -> tuple[int, object]:
    body = json.dumps(payload).encode() if payload is not None else None
    http_request = Request(
        f"{server.base_url}{path}",
        data=body,
        headers={"Content-Type": "application/json"},
        method=method,
    )
    try:
        with urlopen(http_request, timeout=5) as response:
            response_body = response.read()
            return response.status, json.loads(response_body) if response_body else None
    except HTTPError as error:
        return error.code, json.loads(error.read())


def run() -> None:
    with TemporaryDirectory(prefix="tentex-stage2-") as temporary_dir:
        data_dir = Path(temporary_dir)
        server = ApiServer(data_dir, free_port())
        try:
            server.start()
            status, draft = request(
                server,
                "POST",
                "/api/wizard-drafts",
                {"template_key": "exam"},
            )
            assert status == 201
            project_id = draft["project"]["id"]

            draft_payload = {
                "expected_revision": 0,
                "current_step": 4,
                "max_completed_step": 4,
                "schema_version": 1,
                "project": {
                    "name": "Базы данных — экзамен",
                    "description": None,
                    "icon": "database",
                    "color": 2,
                    "deadline": "2026-12-15",
                    "enabled_modules": ["plan", "cards", "repetitions"],
                },
                "goal_passport": {
                    "subject": "Базы данных",
                    "purpose": "exam",
                    "scope": None,
                    "starting_level": "familiar",
                    "current_knowledge": "Помню SQL, хуже понимаю нормализацию",
                    "target_outcome": "mastery",
                    "goal": "Уверенно отвечать на вопросы и решать типовые задачи",
                    "success_criterion": "Раскрываю случайный вопрос без конспекта",
                    "important": "Транзакции и индексы",
                    "excluded": None,
                    "study_format": "theory_and_practice",
                    "minutes_per_day": 120,
                    "days_per_week": 6,
                    "session_minutes": 50,
                    "exam_format": "questions_tasks",
                    "expected_item_count": 64,
                    "instructor_requirements": "Нужны определения и примеры",
                },
                "state": {
                    "question_input_mode": "text",
                    "question_text": "1. Архитектура СУБД\n2. Реляционная модель",
                },
            }
            status, saved = request(
                server, "PUT", f"/api/wizard-drafts/{project_id}", draft_payload
            )
            assert status == 200 and saved["draft"]["revision"] == 1
            status, _ = request(
                server, "PUT", f"/api/wizard-drafts/{project_id}", draft_payload
            )
            assert status == 409

            status, section = request(
                server,
                "POST",
                f"/api/projects/{project_id}/program-nodes",
                {
                    "expected_program_revision": 0,
                    "node_type": "section",
                    "title": "Основы СУБД",
                },
            )
            assert status == 201
            section_node = section["changed_node"]
            status, topic = request(
                server,
                "POST",
                f"/api/projects/{project_id}/program-nodes",
                {
                    "expected_program_revision": 1,
                    "parent_id": section_node["id"],
                    "node_type": "topic",
                    "exam_kind": "question",
                    "title": "Архитектура СУБД",
                },
            )
            assert status == 201
            topic_node = topic["changed_node"]
            status, _ = request(
                server,
                "PUT",
                f"/api/projects/{project_id}/workspace-state",
                {
                    "schema_version": 1,
                    "layout": {
                        "selected_node_id": topic_node["id"],
                        "expanded_node_ids": [section_node["id"], section_node["id"]],
                        "tree_width": 320,
                        "groups": [
                            {
                                "id": "main",
                                "tabs": [],
                                "active_tab": None,
                            }
                        ],
                        "group_weights": [1],
                    },
                },
            )
            assert status == 200

            server.stop()
            server.start()
            status, resumed = request(server, "GET", f"/api/wizard-drafts/{project_id}")
            assert status == 200 and resumed["draft"]["revision"] == 3
            assert resumed["draft"]["state"] == draft_payload["state"]

            status, activated = request(
                server,
                "POST",
                f"/api/wizard-drafts/{project_id}/activate",
                {"expected_revision": 3},
            )
            assert status == 200 and activated["project"]["status"] == "active"
            status, activated_again = request(
                server,
                "POST",
                f"/api/wizard-drafts/{project_id}/activate",
                {"expected_revision": 3},
            )
            assert status == 200 and activated_again["project"]["id"] == project_id
            status, drafts = request(server, "GET", "/api/wizard-drafts")
            assert status == 200 and drafts == []

            protected_project_fields = {
                field: activated["project"][field]
                for field in ("template_key", "workspace_variant", "status", "sort_order")
            }
            settings_payload = {
                "project": {
                    "name": "Базы данных — экзамен, зимняя сессия",
                    "description": "Подготовка к зимней сессии",
                    "icon": "book-open",
                    "color": 3,
                    "deadline": "2026-12-18",
                    "enabled_modules": [
                        "cards",
                        "plan",
                        "cards",
                        "sql",
                        "oral_answers",
                        "repetitions",
                    ],
                },
                "goal_passport": {
                    "subject": "Базы данных",
                    "purpose": "exam",
                    "scope": "whole",
                    "starting_level": "familiar",
                    "current_knowledge": "Знаю SQL, путаюсь в нормальных формах",
                    "target_outcome": "application",
                    "goal": "Уверенно ответить на вопросы и решить задачи",
                    "success_criterion": "Не менее 80% пробного билета без подсказок",
                    "important": "Транзакции, индексы, нормализация",
                    "excluded": "Администрирование СУБД",
                    "study_format": "theory_and_practice",
                    "minutes_per_day": 45,
                    "days_per_week": 5,
                    "session_minutes": 45,
                    "exam_format": "tickets",
                    "expected_item_count": 30,
                    "instructor_requirements": "Показывать ход решения",
                },
            }
            status, updated = request(
                server, "PUT", f"/api/projects/{project_id}/settings", settings_payload
            )
            assert status == 200
            assert {
                field: updated["project"][field] for field in protected_project_fields
            } == protected_project_fields
            assert updated["project"]["enabled_modules"] == [
                "plan",
                "cards",
                "repetitions",
                "oral_answers",
                "sql",
            ]
            assert updated["goal_passport"]["target_outcome"] == "application"

            for field_path, invalid_value in (
                (("project", "name"), "   "),
                (("project", "color"), 9),
                (("goal_passport", "days_per_week"), 8),
                (("goal_passport", "target_outcome"), "apply"),
            ):
                invalid_payload = json.loads(json.dumps(settings_payload))
                invalid_payload[field_path[0]][field_path[1]] = invalid_value
                status, _ = request(
                    server,
                    "PUT",
                    f"/api/projects/{project_id}/settings",
                    invalid_payload,
                )
                assert status == 422

            status, draft_for_404 = request(
                server,
                "POST",
                "/api/wizard-drafts",
                {"template_key": "exam"},
            )
            assert status == 201
            status, _ = request(
                server,
                "PUT",
                f"/api/projects/{draft_for_404['project']['id']}/settings",
                settings_payload,
            )
            assert status == 404

            server.stop()
            server.start()
            status, projects = request(server, "GET", "/api/projects")
            assert status == 200 and [project["id"] for project in projects] == [project_id]
            status, project = request(server, "GET", f"/api/projects/{project_id}")
            assert status == 200
            assert project["project"]["name"] == settings_payload["project"]["name"]
            assert project["project"]["description"] == settings_payload["project"]["description"]
            assert project["project"]["icon"] == settings_payload["project"]["icon"]
            assert project["project"]["color"] == settings_payload["project"]["color"]
            assert project["project"]["deadline"] == settings_payload["project"]["deadline"]
            assert {
                field: project["project"][field] for field in protected_project_fields
            } == protected_project_fields
            for field, expected in settings_payload["goal_passport"].items():
                assert project["goal_passport"][field] == expected
            assert [node["title"] for node in project["program"]["nodes"]] == [
                "Основы СУБД",
                "Архитектура СУБД",
            ]
            assert (
                project["workspace_state"]["layout"]["selected_node_id"]
                == topic_node["id"]
            )
            assert project["workspace_state"]["layout"]["groups"] == [
                {"id": "main", "tabs": [], "active_tab": None}
            ]
            assert project["workspace_state"]["layout"]["expanded_node_ids"] == [
                section_node["id"]
            ]

            server.stop()
            database_path = data_dir / "tentex.sqlite"
            with closing(sqlite3.connect(database_path)) as connection:
                connection.execute(
                    "UPDATE projects SET status = 'archived' WHERE id = ?",
                    (project_id.replace("-", ""),),
                )
                connection.commit()
            server.start()
            status, _ = request(
                server, "PUT", f"/api/projects/{project_id}/settings", settings_payload
            )
            assert status == 409
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
            revisions = connection.execute("SELECT version_num FROM alembic_version").fetchall()
            assert len(revisions) == 1

    print("stage 2 smoke check passed")


if __name__ == "__main__":
    run()
