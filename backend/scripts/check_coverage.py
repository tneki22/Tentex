"""И3: 100 блоков, два разных процесса worker, ни одного вызова провайдера.

Запуск: python scripts/check_coverage.py. Данные создаются только во временной папке.
Подставной исполнитель использует те же генераторы ответов, что регрессионные тесты.
"""

import json
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import create_engine, event, select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.coverage.lifecycle import control_run  # noqa: E402
from app.coverage.queries import run_read  # noqa: E402
from app.coverage.research import process_coverage_job  # noqa: E402
from app.coverage.schemas import RunControl  # noqa: E402
from app.db import Base  # noqa: E402
from app.materials.worker import claim_job  # noqa: E402
from app.models import CoverageRun, ProgramNode  # noqa: E402
from tests.test_coverage import answer, launch, setup_source  # noqa: E402


def run_phase(database: str, phase: str):
    """Каждая фаза открывает новую SQLite-сессию в отдельном процессе."""
    engine = create_engine(f"sqlite+pysqlite:///{database}")

    @event.listens_for(engine, "connect")
    def foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        if phase == "pause":
            project, topic, material = setup_source(session, 100)
            run_id, job, token, _ = launch(session, project, material)

            def executor(task):
                raw = answer(task, topic.id)
                raw[0]["links"][0]["roles"] = ["invalid_role"]
                raw.pop()
                control_run(
                    session,
                    project.id,
                    run_id,
                    RunControl(action="pause", expected_generation=token.generation),
                )
                return raw

            process_coverage_job(session, job, executor)
        else:
            run = session.scalar(select(CoverageRun))
            topic = session.scalar(select(ProgramNode))
            run_id = run.id
            project = type("ProjectId", (), {"id": run.project_id})
            control_run(
                session,
                project.id,
                run_id,
                RunControl(action="resume", expected_generation=run.execution_generation),
            )
            job = claim_job(session, "new-process", "ai")
            process_coverage_job(session, job, lambda task: answer(task, topic.id))
        status = run_read(session, project.id, run_id)
        print(
            json.dumps(
                {k: status[k] for k in ("state", "execution_generation", "primary", "outcomes")}
            )
        )
        expected = "paused" if phase == "pause" else "completed"
        assert status["state"] == expected
        if phase != "pause":
            assert status["primary"]["total"] == 100
            # И3: сломанное и пропущенное решение изолируются в unresolved этого блока,
            # поэтому учтены все 100, а error остаётся только за транспортным сбоем.
            assert status["primary"]["inspected"] == 100
            assert status["primary"]["error"] == 0
            assert status["outcomes"]["unresolved"] == 2
            assert status["outcomes"]["linked"] == 98
    engine.dispose()


if __name__ == "__main__":
    if len(sys.argv) == 3:
        run_phase(sys.argv[1], sys.argv[2])
    else:
        with TemporaryDirectory(prefix="tentex-coverage-") as temporary:
            for phase in ("pause", "resume"):
                subprocess.run(
                    [sys.executable, __file__, str(Path(temporary) / "test.sqlite"), phase],
                    check=True,
                )
