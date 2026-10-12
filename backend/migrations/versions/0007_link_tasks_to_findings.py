"""Link coding tasks to the actionable finding that created them."""
import hashlib
import json
import sqlalchemy as sa
from alembic import op

revision = "0007_link_tasks_to_findings"
down_revision = "0006_task_pull_request_target"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("agent_tasks", sa.Column("source_pull_request_number", sa.Integer(), nullable=True))
    op.add_column("agent_tasks", sa.Column("source_finding_key", sa.String(length=64), nullable=False, server_default=""))
    op.create_unique_constraint(
        "uq_agent_task_source_finding",
        "agent_tasks",
        ["repository_id", "source_pull_request_number", "source_finding_key"],
    )

    # Backfill tasks created by the existing finding action before this link was persisted.
    connection = op.get_bind()
    tasks = sa.table(
        "agent_tasks",
        sa.column("id", sa.Integer), sa.column("repository_id", sa.Integer),
        sa.column("title", sa.String), sa.column("instructions", sa.Text),
    )
    pulls = sa.table(
        "pull_requests",
        sa.column("repository_id", sa.Integer), sa.column("number", sa.Integer),
        sa.column("title", sa.String), sa.column("findings_json", sa.Text),
    )
    task_rows = connection.execute(sa.select(tasks).order_by(tasks.c.id)).mappings().all()
    pull_rows = connection.execute(sa.select(pulls)).mappings().all()
    candidates = {}
    for pull in pull_rows:
        try:
            findings = json.loads(pull["findings_json"] or "[]")
        except (TypeError, json.JSONDecodeError):
            continue
        for finding in findings:
            if not isinstance(finding, dict):
                continue
            title = f"Fix: {finding.get('title', '')}"[:200]
            instructions = "\n\n".join((
                f"Address this actionable finding from pull request #{pull['number']}: {pull['title']}",
                f"Severity: {finding.get('severity')}",
                f"Location: {finding.get('path')}:{finding.get('line')}",
                f"Finding: {finding.get('body')}",
                "Inspect the surrounding code, implement an appropriate fix, and add or update tests where useful.",
            ))
            canonical = {key: finding.get(key) for key in ("title", "path", "line", "severity", "body")}
            key = hashlib.sha256(json.dumps(canonical, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
            candidates[(pull["repository_id"], title, instructions)] = (pull["number"], key)
    linked_findings = set()
    for task in task_rows:
        match = candidates.get((task["repository_id"], task["title"], task["instructions"]))
        unique_key = (task["repository_id"], match[0], match[1]) if match else None
        if match and unique_key not in linked_findings:
            connection.execute(
                sa.text("UPDATE agent_tasks SET source_pull_request_number = :pr, source_finding_key = :key WHERE id = :id"),
                {"pr": match[0], "key": match[1], "id": task["id"]},
            )
            linked_findings.add(unique_key)


def downgrade():
    op.drop_constraint("uq_agent_task_source_finding", "agent_tasks", type_="unique")
    op.drop_column("agent_tasks", "source_finding_key")
    op.drop_column("agent_tasks", "source_pull_request_number")
