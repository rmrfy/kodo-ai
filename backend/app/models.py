from datetime import datetime
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from .db import Base

class Installation(Base):
    __tablename__ = "installations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)  # GitHub installation ID
    account: Mapped[str] = mapped_column(String(255), default="")
    account_type: Mapped[str] = mapped_column(String(32), default="User")
    suspended: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class Repository(Base):
    __tablename__ = "repositories"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)  # GitHub repository ID
    installation_id: Mapped[int] = mapped_column(Integer, index=True)
    full_name: Mapped[str] = mapped_column(String(255), index=True)
    private: Mapped[bool] = mapped_column(Boolean, default=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    review_mode: Mapped[str] = mapped_column(String(32), default="standard")

class ContextFile(Base):
    """Maintainer-authored Markdown guidance for an installation or repository."""
    __tablename__ = "context_files"
    __table_args__ = (UniqueConstraint("scope", "scope_id", name="uq_context_file_scope"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scope: Mapped[str] = mapped_column(String(24), index=True)  # installation or repository
    scope_id: Mapped[int] = mapped_column(Integer, index=True)
    markdown: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class PullRequest(Base):
    __tablename__ = "pull_requests"
    __table_args__ = (UniqueConstraint("repository_id", "number", name="uq_pr_repo_number"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    repository_id: Mapped[int] = mapped_column(Integer, index=True)
    number: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(500), default="")
    author: Mapped[str] = mapped_column(String(255), default="")
    state: Mapped[str] = mapped_column(String(32), default="open")
    head_sha: Mapped[str] = mapped_column(String(64), default="")
    analysis_sha: Mapped[str] = mapped_column(String(64), default="")
    url: Mapped[str] = mapped_column(Text, default="")
    summary: Mapped[str] = mapped_column(Text, default="")
    findings_json: Mapped[str] = mapped_column(Text, default="[]")
    status: Mapped[str] = mapped_column(String(32), default="pending")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class WebhookDelivery(Base):
    __tablename__ = "webhook_deliveries"
    delivery_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    received_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class BackgroundJob(Base):
    __tablename__ = "background_jobs"
    __table_args__ = (UniqueConstraint("kind", "dedupe_key", name="uq_job_dedupe"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(32), index=True)
    dedupe_key: Mapped[str] = mapped_column(String(255))
    payload: Mapped[str] = mapped_column(Text)
    state: Mapped[str] = mapped_column(String(32), default="queued", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class BookDocument(Base):
    __tablename__ = "book_documents"
    __table_args__ = (UniqueConstraint("repository_id", "kind", "path", name="uq_book_doc"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    repository_id: Mapped[int] = mapped_column(Integer, index=True)
    kind: Mapped[str] = mapped_column(String(32))  # file, module, chapter, overview
    path: Mapped[str] = mapped_column(String(1024), default="")
    title: Mapped[str] = mapped_column(String(255), default="")
    content: Mapped[str] = mapped_column(Text, default="")
    source_sha: Mapped[str] = mapped_column(String(64), default="")
    stale: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class RepoBookSection(Base):
    __tablename__ = "repo_book_sections"
    __table_args__ = (UniqueConstraint("repository_id", "slug", name="uq_repo_book_section"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    repository_id: Mapped[int] = mapped_column(Integer, index=True)
    slug: Mapped[str] = mapped_column(String(80))
    title: Mapped[str] = mapped_column(String(255))
    category: Mapped[str] = mapped_column(String(80), default="Guide")
    audiences_json: Mapped[str] = mapped_column(Text, default="[]")
    summary: Mapped[str] = mapped_column(Text, default="")
    blocks_json: Mapped[str] = mapped_column(Text, default="[]")
    source_paths_json: Mapped[str] = mapped_column(Text, default="[]")
    source_hash: Mapped[str] = mapped_column(String(64), default="")
    stale: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class RepoChatMessage(Base):
    __tablename__ = "repo_chat_messages"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    repository_id: Mapped[int] = mapped_column(Integer, index=True)
    github_user_id: Mapped[int] = mapped_column(Integer, index=True)
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text)
    sources_json: Mapped[str] = mapped_column(Text, default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class AgentTask(Base):
    __tablename__ = "agent_tasks"
    __table_args__ = (UniqueConstraint("repository_id", "source_pull_request_number", "source_finding_key", name="uq_agent_task_source_finding"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    repository_id: Mapped[int] = mapped_column(Integer, index=True)
    github_user_id: Mapped[int] = mapped_column(Integer, index=True)
    github_login: Mapped[str] = mapped_column(String(255), default="")
    title: Mapped[str] = mapped_column(String(200))
    instructions: Mapped[str] = mapped_column(Text)
    source_pull_request_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_finding_key: Mapped[str] = mapped_column(String(64), default="")
    work_session_id: Mapped[int] = mapped_column(ForeignKey("work_sessions.id", ondelete="CASCADE"), index=True)
    work_session_pull_request_id: Mapped[int] = mapped_column(ForeignKey("work_session_pull_requests.id", ondelete="CASCADE"), index=True)
    state: Mapped[str] = mapped_column(String(24), default="queued", index=True)
    commit_sha: Mapped[str] = mapped_column(String(64), default="")
    summary: Mapped[str] = mapped_column(Text, default="")
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class WorkSession(Base):
    __tablename__ = "work_sessions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    repository_id: Mapped[int] = mapped_column(Integer, index=True)
    github_user_id: Mapped[int] = mapped_column(Integer, index=True)
    title: Mapped[str] = mapped_column(String(200), default="")
    status: Mapped[str] = mapped_column(String(24), default="active", index=True)
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class WorkSessionPullRequest(Base):
    __tablename__ = "work_session_pull_requests"
    __table_args__ = (
        UniqueConstraint("work_session_id", "sequence", name="uq_session_pr_sequence"),
        UniqueConstraint("repository_id", "pull_request_number", name="uq_session_pr_repo_number"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    work_session_id: Mapped[int] = mapped_column(ForeignKey("work_sessions.id", ondelete="CASCADE"), index=True)
    repository_id: Mapped[int] = mapped_column(Integer, index=True)
    sequence: Mapped[int] = mapped_column(Integer)
    branch: Mapped[str] = mapped_column(String(255), default="")
    status: Mapped[str] = mapped_column(String(24), default="planned", index=True)
    pull_request_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pull_request_url: Mapped[str] = mapped_column(Text, default="")
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class UsageRecord(Base):
    __tablename__ = "usage_records"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    repository_id: Mapped[int] = mapped_column(Integer, index=True)
    task: Mapped[str] = mapped_column(String(64))
    model: Mapped[str] = mapped_column(String(128))
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    estimated_cost_usd: Mapped[float] = mapped_column(default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class UserSession(Base):
    __tablename__ = "user_sessions"
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    github_user_id: Mapped[int] = mapped_column(Integer, index=True)
    login: Mapped[str] = mapped_column(String(255))
    access_token: Mapped[str] = mapped_column(String(4096))
    refresh_token: Mapped[str] = mapped_column(String(4096), default="")
    github_token_expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    refresh_token_expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
