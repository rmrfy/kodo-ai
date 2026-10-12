"""Group related agent tasks into a shared branch and pull request."""
import sqlalchemy as sa
from alembic import op

revision = "0009_work_sessions"
down_revision = "0008_github_token_refresh"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "work_sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("repository_id", sa.Integer(), nullable=False),
        sa.Column("github_user_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="active"),
        sa.Column("branch", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("target_pull_request_number", sa.Integer(), nullable=True),
        sa.Column("pull_request_url", sa.Text(), nullable=False, server_default=""),
        sa.Column("error", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("repository_id", "target_pull_request_number", name="uq_work_session_repo_pr"),
    )
    op.create_index("ix_work_sessions_repository_id", "work_sessions", ["repository_id"])
    op.create_index("ix_work_sessions_github_user_id", "work_sessions", ["github_user_id"])
    op.create_index("ix_work_sessions_status", "work_sessions", ["status"])
    op.add_column("agent_tasks", sa.Column("work_session_id", sa.Integer(), nullable=True))
    op.create_index("ix_agent_tasks_work_session_id", "agent_tasks", ["work_session_id"])


def downgrade():
    op.drop_index("ix_agent_tasks_work_session_id", table_name="agent_tasks")
    op.drop_column("agent_tasks", "work_session_id")
    op.drop_index("ix_work_sessions_status", table_name="work_sessions")
    op.drop_index("ix_work_sessions_github_user_id", table_name="work_sessions")
    op.drop_index("ix_work_sessions_repository_id", table_name="work_sessions")
    op.drop_table("work_sessions")
