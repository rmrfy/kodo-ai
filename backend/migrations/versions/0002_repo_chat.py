"""Persist per-user Repo Book conversations."""
import sqlalchemy as sa
from alembic import op

revision = "0002_repo_chat"
down_revision = "0001_initial"
branch_labels = None
depends_on = None

def upgrade():
    op.create_table(
        "repo_chat_messages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("repository_id", sa.Integer(), nullable=False),
        sa.Column("github_user_id", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("sources_json", sa.Text(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_repo_chat_messages_repository_id", "repo_chat_messages", ["repository_id"])
    op.create_index("ix_repo_chat_messages_github_user_id", "repo_chat_messages", ["github_user_id"])
    op.create_index("ix_repo_chat_owner_created", "repo_chat_messages", ["repository_id", "github_user_id", "created_at"])

def downgrade():
    op.drop_index("ix_repo_chat_owner_created", table_name="repo_chat_messages")
    op.drop_index("ix_repo_chat_messages_github_user_id", table_name="repo_chat_messages")
    op.drop_index("ix_repo_chat_messages_repository_id", table_name="repo_chat_messages")
    op.drop_table("repo_chat_messages")
