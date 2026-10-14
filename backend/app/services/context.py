"""Maintainer-authored organization and repository context persistence."""
from datetime import datetime

from sqlalchemy import select

from ..models import ContextFile

def _save_context_file(db, scope: str, scope_id: int, markdown: str):
    row = db.scalar(select(ContextFile).where(ContextFile.scope == scope, ContextFile.scope_id == scope_id))
    if row:
        row.markdown = markdown
        row.updated_at = datetime.utcnow()
    else:
        db.add(ContextFile(scope=scope, scope_id=scope_id, markdown=markdown, updated_at=datetime.utcnow()))
