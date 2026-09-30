"""Добавить пользовательское имя и канонический предмет материала."""

import sqlalchemy as sa
from alembic import op

revision = "20260920_0052"
down_revision = "20260920_0051"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("materials", sa.Column("display_name", sa.String(), nullable=True))
    op.add_column("materials", sa.Column("subject", sa.String(), nullable=True))
    op.execute("UPDATE materials SET display_name = original_name")
    with op.batch_alter_table("materials") as batch:
        batch.alter_column("display_name", existing_type=sa.String(), nullable=False)
        batch.create_index("ix_materials_subject", ["subject"], unique=False)


def downgrade():
    with op.batch_alter_table("materials") as batch:
        batch.drop_index("ix_materials_subject")
        batch.drop_column("subject")
        batch.drop_column("display_name")
