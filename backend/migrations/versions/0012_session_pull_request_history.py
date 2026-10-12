"""Let a work session contain multiple pull requests and target tasks to one."""
import sqlalchemy as sa
from alembic import op

revision = "0012_session_pr_history"
down_revision = "0011_session_owns_branch_and_pr"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "work_session_pull_requests",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("work_session_id", sa.Integer(), sa.ForeignKey("work_sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("repository_id", sa.Integer(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("branch", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="planned"),
        sa.Column("pull_request_number", sa.Integer(), nullable=True),
        sa.Column("pull_request_url", sa.Text(), nullable=False, server_default=""),
        sa.Column("error", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("work_session_id", "sequence", name="uq_session_pr_sequence"),
        sa.UniqueConstraint("repository_id", "pull_request_number", name="uq_session_pr_repo_number"),
    )
    op.create_index("ix_work_session_pull_requests_work_session_id", "work_session_pull_requests", ["work_session_id"])
    op.create_index("ix_work_session_pull_requests_repository_id", "work_session_pull_requests", ["repository_id"])
    op.create_index("ix_work_session_pull_requests_status", "work_session_pull_requests", ["status"])

    # Preserve each existing session's branch and PR as its first PR destination.
    op.execute(sa.text("""
        INSERT INTO work_session_pull_requests
            (work_session_id, repository_id, sequence, branch, status,
             pull_request_number, pull_request_url, error, created_at, updated_at)
        SELECT id, repository_id, 1, branch,
               CASE WHEN pull_request_number IS NULL THEN 'planned'
                    WHEN status = 'closed' THEN 'closed'
                    ELSE 'open' END,
               pull_request_number, pull_request_url, error, created_at, updated_at
        FROM work_sessions
    """))

    op.add_column("agent_tasks", sa.Column("work_session_pull_request_id", sa.Integer(), nullable=True))
    op.create_index("ix_agent_tasks_work_session_pull_request_id", "agent_tasks", ["work_session_pull_request_id"])
    op.create_foreign_key(
        "fk_agent_tasks_session_pull_request",
        "agent_tasks", "work_session_pull_requests",
        ["work_session_pull_request_id"], ["id"], ondelete="CASCADE",
    )
    op.execute(sa.text("""
        UPDATE agent_tasks task
        SET work_session_pull_request_id = destination.id
        FROM work_session_pull_requests destination
        WHERE destination.work_session_id = task.work_session_id
    """))
    op.alter_column("agent_tasks", "work_session_pull_request_id", nullable=False)

    op.drop_constraint("uq_work_session_repo_pr", "work_sessions", type_="unique")
    for column in ("branch", "pull_request_number", "pull_request_url"):
        op.drop_column("work_sessions", column)
    op.execute(sa.text("UPDATE work_sessions SET status = 'complete' WHERE status = 'closed'"))


def downgrade():
    op.add_column("work_sessions", sa.Column("branch", sa.String(length=255), nullable=False, server_default=""))
    op.add_column("work_sessions", sa.Column("pull_request_number", sa.Integer(), nullable=True))
    op.add_column("work_sessions", sa.Column("pull_request_url", sa.Text(), nullable=False, server_default=""))
    op.execute(sa.text("""
        UPDATE work_sessions ws
        SET branch = COALESCE(destination.branch, ''),
            pull_request_number = destination.pull_request_number,
            pull_request_url = COALESCE(destination.pull_request_url, '')
        FROM work_session_pull_requests destination
        WHERE destination.work_session_id = ws.id
          AND destination.sequence = (
              SELECT MAX(latest.sequence) FROM work_session_pull_requests latest
              WHERE latest.work_session_id = ws.id
          )
    """))
    op.create_unique_constraint("uq_work_session_repo_pr", "work_sessions", ["repository_id", "pull_request_number"])
    op.drop_constraint("fk_agent_tasks_session_pull_request", "agent_tasks", type_="foreignkey")
    op.drop_index("ix_agent_tasks_work_session_pull_request_id", table_name="agent_tasks")
    op.drop_column("agent_tasks", "work_session_pull_request_id")
    op.drop_index("ix_work_session_pull_requests_status", table_name="work_session_pull_requests")
    op.drop_index("ix_work_session_pull_requests_repository_id", table_name="work_session_pull_requests")
    op.drop_index("ix_work_session_pull_requests_work_session_id", table_name="work_session_pull_requests")
    op.drop_table("work_session_pull_requests")
