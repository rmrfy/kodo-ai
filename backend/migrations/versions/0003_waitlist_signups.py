"""Store launch waitlist signups."""
from alembic import op
import sqlalchemy as sa


revision = "0003_waitlist_signups"
down_revision = "0002_github_org_installation"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "waitlist_signups",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email", name="uq_waitlist_signup_email"),
    )


def downgrade():
    op.drop_table("waitlist_signups")
