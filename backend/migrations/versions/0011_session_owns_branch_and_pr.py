"""Make the work session own its PR and branch; keep task rows as prompt history."""
import sqlalchemy as sa
from alembic import op

revision = "0011_session_owns_branch_and_pr"
down_revision = "0010_backfill_work_sessions"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint("uq_work_session_repo_pr", "work_sessions", type_="unique")
    op.alter_column("work_sessions", "target_pull_request_number", new_column_name="pull_request_number")

    # Sessions are the canonical PR record. Preserve branch and PR data
    # before dropping the duplicate values formerly copied onto every task.
    op.execute(sa.text("""
        UPDATE work_sessions ws
        SET branch = COALESCE(NULLIF(ws.branch, ''), (
                SELECT at.branch FROM agent_tasks at
                WHERE at.work_session_id = ws.id AND at.branch <> ''
                ORDER BY at.updated_at DESC, at.id DESC LIMIT 1
            ), ''),
            pull_request_number = COALESCE(ws.pull_request_number, (
                SELECT CASE WHEN at.task_mode = 'in_pr' THEN at.target_pull_request_number
                            ELSE at.pull_request_number END
                FROM agent_tasks at
                WHERE at.work_session_id = ws.id
                  AND (at.target_pull_request_number IS NOT NULL OR at.pull_request_number IS NOT NULL)
                ORDER BY at.updated_at DESC, at.id DESC LIMIT 1
            )),
            pull_request_url = COALESCE(NULLIF(ws.pull_request_url, ''), (
                SELECT at.pull_request_url FROM agent_tasks at
                WHERE at.work_session_id = ws.id AND at.pull_request_url <> ''
                ORDER BY at.updated_at DESC, at.id DESC LIMIT 1
            ), '')
    """))
    op.create_unique_constraint("uq_work_session_repo_pr", "work_sessions", ["repository_id", "pull_request_number"])

    op.create_foreign_key(
        "fk_agent_tasks_work_session_id_work_sessions",
        "agent_tasks", "work_sessions", ["work_session_id"], ["id"], ondelete="CASCADE",
    )
    op.alter_column("agent_tasks", "work_session_id", nullable=False)
    for name in ("task_mode", "target_pull_request_number", "branch", "pull_request_number", "pull_request_url"):
        op.drop_column("agent_tasks", name)


def downgrade():
    for name, column in (
        ("task_mode", sa.Column("task_mode", sa.String(length=24), nullable=False, server_default="separate")),
        ("target_pull_request_number", sa.Column("target_pull_request_number", sa.Integer(), nullable=True)),
        ("branch", sa.Column("branch", sa.String(length=255), nullable=False, server_default="")),
        ("pull_request_number", sa.Column("pull_request_number", sa.Integer(), nullable=True)),
        ("pull_request_url", sa.Column("pull_request_url", sa.Text(), nullable=False, server_default="")),
    ):
        op.add_column("agent_tasks", column)
    op.execute(sa.text("""
        UPDATE agent_tasks at
        SET task_mode = CASE WHEN ws.pull_request_number IS NULL THEN 'separate' ELSE 'in_pr' END,
            target_pull_request_number = ws.pull_request_number,
            branch = ws.branch,
            pull_request_number = ws.pull_request_number,
            pull_request_url = ws.pull_request_url
        FROM work_sessions ws
        WHERE at.work_session_id = ws.id
    """))
    op.alter_column("agent_tasks", "work_session_id", nullable=True)
    op.drop_constraint("fk_agent_tasks_work_session_id_work_sessions", "agent_tasks", type_="foreignkey")
    op.drop_constraint("uq_work_session_repo_pr", "work_sessions", type_="unique")
    op.alter_column("work_sessions", "pull_request_number", new_column_name="target_pull_request_number")
    op.create_unique_constraint("uq_work_session_repo_pr", "work_sessions", ["repository_id", "target_pull_request_number"])
