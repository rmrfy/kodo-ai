"""Create Kodo persistence tables."""
from alembic import op
from app.db import Base
from app import models  # noqa: F401

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None

def upgrade():
    Base.metadata.create_all(bind=op.get_bind(), tables=[table for table in Base.metadata.sorted_tables if table.name not in {"repo_chat_messages", "repo_book_sections", "agent_tasks", "context_files"}])

def downgrade():
    Base.metadata.drop_all(bind=op.get_bind())
