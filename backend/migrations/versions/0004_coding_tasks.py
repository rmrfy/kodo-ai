"""Persist coding agent tasks and their pull request results."""
import sqlalchemy as sa
from alembic import op

revision = "0004_coding_tasks"
down_revision = "0003_repo_book_sections"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "agent_tasks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("repository_id", sa.Integer(), nullable=False),
        sa.Column("github_user_id", sa.Integer(), nullable=False),
        sa.Column("github_login", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("instructions", sa.Text(), nullable=False),
        sa.Column("state", sa.String(length=24), nullable=False, server_default="queued"),
        sa.Column("branch", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("commit_sha", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("pull_request_number", sa.Integer(), nullable=True),
        sa.Column("pull_request_url", sa.Text(), nullable=False, server_default=""),
        sa.Column("summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("error", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_agent_tasks_repository_id", "agent_tasks", ["repository_id"])
    op.create_index("ix_agent_tasks_github_user_id", "agent_tasks", ["github_user_id"])
    op.create_index("ix_agent_tasks_state", "agent_tasks", ["state"])


def downgrade():
    op.drop_index("ix_agent_tasks_state", table_name="agent_tasks")
    op.drop_index("ix_agent_tasks_github_user_id", table_name="agent_tasks")
    op.drop_index("ix_agent_tasks_repository_id", table_name="agent_tasks")
    op.drop_table("agent_tasks")
