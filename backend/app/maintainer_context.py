"""Load and format maintainer-authored kodai context files."""
from sqlalchemy import select

from .models import ContextFile

MAX_CONTEXT_CHARS = 20000


def load_context(db, installation_id: int, repository_id: int) -> tuple[str, str]:
    organization = db.scalar(select(ContextFile).where(
        ContextFile.scope == "installation", ContextFile.scope_id == installation_id,
    ))
    repository = db.scalar(select(ContextFile).where(
        ContextFile.scope == "repository", ContextFile.scope_id == repository_id,
    ))
    return (
        (organization.markdown if organization else "")[:MAX_CONTEXT_CHARS],
        (repository.markdown if repository else "")[:MAX_CONTEXT_CHARS],
    )


def format_context(organization_markdown: str, repository_markdown: str) -> str:
    parts = []
    if organization_markdown.strip():
        parts.append("ORGANIZATION MAINTAINER CONTEXT:\n" + organization_markdown.strip()[:MAX_CONTEXT_CHARS])
    if repository_markdown.strip():
        parts.append("REPOSITORY MAINTAINER CONTEXT (takes precedence over organization context when they conflict):\n" + repository_markdown.strip()[:MAX_CONTEXT_CHARS])
    if not parts:
        return ""
    return "\n\n".join(parts)
