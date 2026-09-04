"""Join preparation with the independently deployed cloud CHECK repair."""

revision = "20260904_0036"
down_revision = ("20260904_0035", "20260904_0033")
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Both branches retain their existing data migrations."""
    pass


def downgrade() -> None:
    """The merge revision has no schema changes of its own."""
    pass
