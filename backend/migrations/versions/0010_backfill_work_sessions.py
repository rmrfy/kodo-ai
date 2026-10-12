"""Attach existing coding tasks and pull requests to work sessions."""
from collections import defaultdict

import sqlalchemy as sa
from alembic import op

revision = "0010_backfill_work_sessions"
down_revision = "0009_work_sessions"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    metadata = sa.MetaData()
    tasks = sa.Table("agent_tasks", metadata, autoload_with=bind)
    sessions = sa.Table("work_sessions", metadata, autoload_with=bind)
    repositories = sa.Table("repositories", metadata, autoload_with=bind)

    rows = bind.execute(
        sa.select(tasks).where(tasks.c.work_session_id.is_(None)).order_by(tasks.c.created_at, tasks.c.id)
    ).mappings().all()
    grouped = defaultdict(list)
    for task in rows:
        pr_number = task["target_pull_request_number"] if task["task_mode"] == "in_pr" else task["pull_request_number"]
        # Older tasks with no PR yet remain their own session so queued/failed work can resume safely.
        key = (task["repository_id"], "pr", pr_number) if pr_number else (task["repository_id"], "task", task["id"])
        grouped[key].append(task)

    for key, session_tasks in grouped.items():
        first = session_tasks[0]
        latest = session_tasks[-1]
        pr_number = key[2] if key[1] == "pr" else None
        repository = bind.execute(sa.select(repositories.c.full_name).where(repositories.c.id == first["repository_id"])).scalar_one_or_none()
        pr_url = next((item["pull_request_url"] for item in reversed(session_tasks) if item["pull_request_url"]), "")
        if not pr_url and pr_number and repository:
            pr_url = f"https://github.com/{repository}/pull/{pr_number}"
        failed = any(item["state"] == "failed" for item in session_tasks)
        result = bind.execute(sessions.insert().values(
            repository_id=first["repository_id"],
            github_user_id=first["github_user_id"],
            title=first["title"] or (f"PR #{pr_number}" if pr_number else "Work session"),
            status="paused" if failed else "active",
            branch=next((item["branch"] for item in reversed(session_tasks) if item["branch"]), ""),
            target_pull_request_number=pr_number,
            pull_request_url=pr_url,
            error=next((item["error"] for item in reversed(session_tasks) if item["state"] == "failed" and item["error"]), ""),
            created_at=first["created_at"],
            updated_at=latest["updated_at"],
        ))
        session_id = result.inserted_primary_key[0]
        bind.execute(
            tasks.update()
            .where(tasks.c.id.in_([item["id"] for item in session_tasks]))
            .values(work_session_id=session_id)
        )


def downgrade():
    # Keep the generated session associations; dropping them would orphan completed task history.
    pass
