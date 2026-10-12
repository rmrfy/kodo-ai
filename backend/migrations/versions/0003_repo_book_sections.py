"""Store structured, audience-aware Repo Book handbook sections."""
import sqlalchemy as sa
from alembic import op

revision = "0003_repo_book_sections"
down_revision = "0002_repo_chat"
branch_labels = None
depends_on = None

def upgrade():
    op.create_table(
        "repo_book_sections",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("repository_id", sa.Integer(), nullable=False),
        sa.Column("slug", sa.String(length=80), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("category", sa.String(length=80), nullable=False, server_default="Guide"),
        sa.Column("audiences_json", sa.Text(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("blocks_json", sa.Text(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("source_paths_json", sa.Text(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("source_hash", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("stale", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("repository_id", "slug", name="uq_repo_book_section"),
    )
    op.create_index("ix_repo_book_sections_repository_id", "repo_book_sections", ["repository_id"])

def downgrade():
    op.drop_index("ix_repo_book_sections_repository_id", table_name="repo_book_sections")
    op.drop_table("repo_book_sections")
