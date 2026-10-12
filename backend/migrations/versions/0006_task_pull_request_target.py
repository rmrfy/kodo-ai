"""Track whether a coding task updates an existing pull request."""
import sqlalchemy as sa
from alembic import op

revision = "0006_task_pull_request_target"
down_revision = "0005_context_files"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("agent_tasks", sa.Column("task_mode", sa.String(length=24), nullable=False, server_default="separate"))
    op.add_column("agent_tasks", sa.Column("target_pull_request_number", sa.Integer(), nullable=True))


def downgrade():
    op.drop_column("agent_tasks", "target_pull_request_number")
    op.drop_column("agent_tasks", "task_mode")
