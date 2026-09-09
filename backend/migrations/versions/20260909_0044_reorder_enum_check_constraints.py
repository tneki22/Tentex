"""Выравнивает порядок значений в CHECK по объявлению перечисления в моделях.

Revision ID: 20260909_0044
Revises: 20260909_0043

`materials.status` (0043) и `background_jobs.kind` (0042) добавляли новое
значение перечисления через `(*OLD_VALUES, "новое")` — значение уезжало в
конец SQL-списка `IN (...)`, а модель объявляет его в середине (`needs_input`
после `paused`, `typst_compile` сразу после `parse`). Список внутри `IN`
семантически множество и работал одинаково в обоих порядках, но начиная с
Alembic 1.19 автогенерация сверяет CHECK type-bound колонок с базой по тексту
выражения (`migrations/env.py::TYPE_BOUND_CHECKS`), а он собирается из
текущей модели literal_binds-компиляцией — то есть в порядке объявления
перечисления. Несовпадение порядка вернуло с виду молчаливую поломку из
исходной задачи: `alembic check` на чистой базе предлагал удалить оба CHECK,
которых явно не было в diff.
"""

import sqlalchemy as sa
from alembic import op

revision = "20260909_0044"
down_revision = "20260909_0043"
branch_labels = None
depends_on = None

MATERIAL_STATES = (
    "ready_to_process",
    "queued",
    "processing",
    "paused",
    "needs_input",
    "ready",
    "failed",
)
PREVIOUS_MATERIAL_STATES = (
    "ready_to_process",
    "queued",
    "processing",
    "paused",
    "ready",
    "failed",
    "needs_input",
)
JOB_KINDS = (
    "parse",
    "typst_compile",
    "ai_grouping",
    "ai_import_repair",
    "ai_preparation",
    "ai_cleanup",
    "link_answers",
    "ai_answer_sections",
)
PREVIOUS_JOB_KINDS = (
    "parse",
    "ai_grouping",
    "ai_import_repair",
    "ai_preparation",
    "ai_cleanup",
    "link_answers",
    "ai_answer_sections",
    "typst_compile",
)


def _replace_check(table: str, column: str, name: str, states: tuple[str, ...]) -> None:
    """Ищет CHECK по выражению, а не по имени: имя не хранит порядок значений."""
    existing = [
        constraint["name"]
        for constraint in sa.inspect(op.get_bind()).get_check_constraints(table)
        if constraint["name"] and f"{column} IN" in (constraint["sqltext"] or "")
    ]
    with op.batch_alter_table(table) as batch:
        for stale in existing:
            batch.drop_constraint(op.f(stale), type_="check")
        batch.create_check_constraint(op.f(name), sa.column(column).in_(states))


def upgrade() -> None:
    """Пересоздать оба CHECK с порядком значений, как в StrEnum моделей."""
    _replace_check("materials", "status", "ck_materials_material_state", MATERIAL_STATES)
    _replace_check(
        "background_jobs", "kind", "ck_background_jobs_background_job_kind", JOB_KINDS
    )


def downgrade() -> None:
    """Вернуть тот же набор значений в прежнем, исторически удвоенном порядке."""
    _replace_check(
        "materials", "status", "ck_materials_material_state", PREVIOUS_MATERIAL_STATES
    )
    _replace_check(
        "background_jobs",
        "kind",
        "ck_background_jobs_background_job_kind",
        PREVIOUS_JOB_KINDS,
    )
