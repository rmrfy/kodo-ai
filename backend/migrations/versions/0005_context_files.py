"""Store maintainer-authored workspace and repository Markdown context."""
import sqlalchemy as sa
from alembic import op

revision = "0005_context_files"
down_revision = "0004_coding_tasks"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "context_files",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("scope", sa.String(length=24), nullable=False),
        sa.Column("scope_id", sa.Integer(), nullable=False),
        sa.Column("markdown", sa.Text(), nullable=False, server_default=""),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("scope", "scope_id", name="uq_context_file_scope"),
    )
    op.create_index("ix_context_files_scope", "context_files", ["scope"])
    op.create_index("ix_context_files_scope_id", "context_files", ["scope_id"])


def downgrade():
    op.drop_index("ix_context_files_scope_id", table_name="context_files")
    op.drop_index("ix_context_files_scope", table_name="context_files")
    op.drop_table("context_files")
