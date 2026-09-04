"""Remove obsolete parse-only CHECKs left behind by the shared queue migration."""

import sqlalchemy as sa
from alembic import op

revision = "20260904_0034"
down_revision = "20260904_0033"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """New constraints already cover every supported job kind and state."""
    obsolete = {
        "ck_processing_tasks_processing_task_kind",
        "ck_processing_tasks_processing_task_state",
    }
    present = {
        check["name"]
        for check in sa.inspect(op.get_bind()).get_check_constraints("background_jobs")
    }
    if names := obsolete & present:
        with op.batch_alter_table("background_jobs", recreate="always") as batch:
            for name in sorted(names):
                batch.drop_constraint(op.f(name), type_="check")


def downgrade() -> None:
    """Do not restore a constraint that rejects persisted AI jobs on downgrade."""
