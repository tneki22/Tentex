"""Перекрывающий индекс проекции покрытия: лёгкие колонки без чтения тяжёлой строки."""

from alembic import op

revision = "20260920_0050"
down_revision = "20260918_0049"
branch_labels = None
depends_on = None

INDEXES = (
    (
        "ix_coverage_results_projection",
        "coverage_block_results",
        [
            "run_id",
            "block_id",
            "work_state",
            "outcome",
            "publication_state",
            "material_id",
            "reason",
            "id",
        ],
    ),
    # Receipts весят сотню байт, но лежат за checkpoint, result и dependencies —
    # четвертью мегабайта на задачу. Бюджет спрашивают перед каждым вызовом модели.
    ("ix_coverage_tasks_run_receipts", "coverage_tasks", ["run_id", "call_receipts"]),
)


def upgrade():
    for name, table, columns in INDEXES:
        op.create_index(name, table, columns)


def downgrade():
    for name, table, _ in reversed(INDEXES):
        op.drop_index(name, table_name=table)
