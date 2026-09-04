"""Join preparation and cloud OCR migrations; date explicit recall-quality decisions."""

import sqlalchemy as sa
from alembic import op

revision = "20260904_0035"
down_revision = ("20260904_0034", "20260904_0032")
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Unknown historical decision dates remain unknown instead of being reconstructed."""
    op.add_column("preparation_qualities", sa.Column("updated_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("preparation_qualities", "updated_at")
