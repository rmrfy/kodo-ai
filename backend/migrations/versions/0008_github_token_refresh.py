"""Store rotating GitHub App user-token refresh credentials."""
import sqlalchemy as sa
from alembic import op

revision = "0008_github_token_refresh"
down_revision = "0007_link_tasks_to_findings"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("user_sessions", sa.Column("refresh_token", sa.String(length=4096), nullable=False, server_default=""))
    op.add_column("user_sessions", sa.Column("github_token_expires_at", sa.DateTime(), nullable=True))
    op.add_column("user_sessions", sa.Column("refresh_token_expires_at", sa.DateTime(), nullable=True))


def downgrade():
    op.drop_column("user_sessions", "refresh_token_expires_at")
    op.drop_column("user_sessions", "github_token_expires_at")
    op.drop_column("user_sessions", "refresh_token")
