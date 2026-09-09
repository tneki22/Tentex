"""Оставляет у `materials.status` ровно один CHECK — тот, где есть `needs_input`.

Revision ID: 20260909_0043
Revises: 20260909_0042

`batch_alter_table` на SQLite пересобирает таблицу из отражения, поэтому
`alter_column` в 0042 добавил новый CHECK со статусом `needs_input`
(`ck_materials_material_state`), а старый, названный по имени перечисления
(`material_state`), уцелел рядом. Любая попытка выставить материалу
`needs_input` падала с `CHECK constraint failed: material_state` — Typst-проект
с недостающим пакетом не мог дойти до состояния «нужно решение».

Ограничения ищутся по выражению, а не по имени: в разных базах уцелело разное
имя, и адресоваться к нему значит починить одну установку и сломать другую.
Autogenerate тут не помощник — alembic не сравнивает CHECK-ограничения вовсе.
"""

import sqlalchemy as sa
from alembic import op

revision = "20260909_0043"
down_revision = "20260909_0042"
branch_labels = None
depends_on = None

CANONICAL = "ck_materials_material_state"
CURRENT_STATES = (
    "ready_to_process",
    "queued",
    "processing",
    "paused",
    "ready",
    "failed",
    "needs_input",
)
LEGACY_STATES = CURRENT_STATES[:-1]


def _status_checks() -> list[str]:
    """Имена всех CHECK, ограничивающих `materials.status`, как они лежат в базе."""
    return [
        constraint["name"]
        for constraint in sa.inspect(op.get_bind()).get_check_constraints("materials")
        if constraint["name"] and "status IN" in (constraint["sqltext"] or "")
    ]


def _replace_status_check(states: tuple[str, ...], name: str) -> None:
    existing = _status_checks()
    with op.batch_alter_table("materials") as batch:
        for stale in existing:
            # op.f: имена уже приведены к виду, в котором лежат в базе; без него
            # соглашение об именах превратило бы `material_state` в
            # `ck_materials_material_state` — то есть в соседнее ограничение.
            batch.drop_constraint(op.f(stale), type_="check")
        batch.create_check_constraint(op.f(name), sa.column("status").in_(states))


def upgrade() -> None:
    """Свести все CHECK статуса к одному, разрешающему `needs_input`."""
    _replace_status_check(CURRENT_STATES, CANONICAL)


def downgrade() -> None:
    """Вернуть перечисление без `needs_input` под историческим именем."""
    op.execute(
        sa.text("UPDATE materials SET status = 'failed' WHERE status = 'needs_input'")
    )
    _replace_status_check(LEGACY_STATES, "material_state")
