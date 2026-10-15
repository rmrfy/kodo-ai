"""Create the complete Kodai schema for a fresh PostgreSQL database.

This is the single pre-launch baseline. Once deployed, preserve this revision
and add forward migrations for subsequent schema changes.
"""
from alembic import op
import sqlalchemy as sa

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('background_jobs',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('kind', sa.String(length=32), nullable=False),
    sa.Column('dedupe_key', sa.String(length=255), nullable=False),
    sa.Column('payload', sa.Text(), nullable=False),
    sa.Column('state', sa.String(length=32), nullable=False),
    sa.Column('attempts', sa.Integer(), nullable=False),
    sa.Column('last_error', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('kind', 'dedupe_key', name='uq_job_dedupe')
    )
    op.create_table('book_documents',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('repository_id', sa.Integer(), nullable=False),
    sa.Column('kind', sa.String(length=32), nullable=False),
    sa.Column('path', sa.String(length=1024), nullable=False),
    sa.Column('title', sa.String(length=255), nullable=False),
    sa.Column('content', sa.Text(), nullable=False),
    sa.Column('source_sha', sa.String(length=64), nullable=False),
    sa.Column('stale', sa.Boolean(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('repository_id', 'kind', 'path', name='uq_book_doc')
    )
    op.create_table('context_files',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('scope', sa.String(length=24), nullable=False),
    sa.Column('scope_id', sa.Integer(), nullable=False),
    sa.Column('markdown', sa.Text(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('scope', 'scope_id', name='uq_context_file_scope')
    )
    op.create_table('pull_requests',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('repository_id', sa.Integer(), nullable=False),
    sa.Column('number', sa.Integer(), nullable=False),
    sa.Column('title', sa.String(length=500), nullable=False),
    sa.Column('author', sa.String(length=255), nullable=False),
    sa.Column('state', sa.String(length=32), nullable=False),
    sa.Column('head_sha', sa.String(length=64), nullable=False),
    sa.Column('analysis_sha', sa.String(length=64), nullable=False),
    sa.Column('url', sa.Text(), nullable=False),
    sa.Column('summary', sa.Text(), nullable=False),
    sa.Column('findings_json', sa.Text(), nullable=False),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('repository_id', 'number', name='uq_pr_repo_number')
    )
    op.create_table('repo_book_sections',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('repository_id', sa.Integer(), nullable=False),
    sa.Column('slug', sa.String(length=80), nullable=False),
    sa.Column('title', sa.String(length=255), nullable=False),
    sa.Column('category', sa.String(length=80), nullable=False),
    sa.Column('audiences_json', sa.Text(), nullable=False),
    sa.Column('summary', sa.Text(), nullable=False),
    sa.Column('blocks_json', sa.Text(), nullable=False),
    sa.Column('source_paths_json', sa.Text(), nullable=False),
    sa.Column('source_hash', sa.String(length=64), nullable=False),
    sa.Column('stale', sa.Boolean(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('repository_id', 'slug', name='uq_repo_book_section')
    )
    op.create_table('usage_records',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('repository_id', sa.Integer(), nullable=False),
    sa.Column('task', sa.String(length=64), nullable=False),
    sa.Column('model', sa.String(length=128), nullable=False),
    sa.Column('input_tokens', sa.Integer(), nullable=False),
    sa.Column('output_tokens', sa.Integer(), nullable=False),
    sa.Column('estimated_cost_usd', sa.Float(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('users',
    sa.Column('id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('email', sa.String(length=320), nullable=True),
    sa.Column('email_verified_at', sa.DateTime(), nullable=True),
    sa.Column('phone', sa.String(length=32), nullable=True),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('avatar_url', sa.Text(), nullable=False),
    sa.Column('job_function', sa.String(length=64), nullable=False),
    sa.Column('is_platform_admin', sa.Boolean(), nullable=False),
    sa.Column('last_login_at', sa.DateTime(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('waitlist_signups',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('email', sa.String(length=320), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('email', name='uq_waitlist_signup_email')
    )
    op.create_table('webhook_deliveries',
    sa.Column('delivery_id', sa.String(length=128), nullable=False),
    sa.Column('received_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('delivery_id')
    )
    op.create_table('auth_identities',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('provider', sa.String(length=32), nullable=False),
    sa.Column('provider_user_id', sa.String(length=320), nullable=False),
    sa.Column('password_hash', sa.String(length=255), nullable=True),
    sa.Column('provider_username', sa.String(length=255), nullable=False),
    sa.Column('access_token', sa.String(length=4096), nullable=False),
    sa.Column('refresh_token', sa.String(length=4096), nullable=False),
    sa.Column('token_expires_at', sa.DateTime(), nullable=True),
    sa.Column('refresh_expires_at', sa.DateTime(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('provider', 'provider_user_id', name='uq_auth_identity_provider_user'),
    sa.UniqueConstraint('user_id', 'provider', name='uq_auth_identity_user_provider')
    )
    op.create_table('email_verifications',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('email', sa.String(length=320), nullable=False),
    sa.Column('purpose', sa.String(length=24), nullable=False),
    sa.Column('token_hash', sa.String(length=64), nullable=False),
    sa.Column('password_hash', sa.String(length=255), nullable=True),
    sa.Column('expires_at', sa.DateTime(), nullable=False),
    sa.Column('consumed_at', sa.DateTime(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('token_hash')
    )
    op.create_table('repo_chat_messages',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('repository_id', sa.Integer(), nullable=False),
    sa.Column('github_user_id', sa.Integer(), nullable=True),
    sa.Column('role', sa.String(length=16), nullable=False),
    sa.Column('content', sa.Text(), nullable=False),
    sa.Column('sources_json', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('user_id', sa.Uuid(as_uuid=False), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('work_sessions',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('repository_id', sa.Integer(), nullable=False),
    sa.Column('github_user_id', sa.Integer(), nullable=True),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('status', sa.String(length=24), nullable=False),
    sa.Column('error', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.Column('user_id', sa.Uuid(as_uuid=False), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('workspaces',
    sa.Column('id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('kind', sa.String(length=24), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('owner_user_id', sa.Uuid(as_uuid=False), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.CheckConstraint("(kind = 'personal' AND owner_user_id IS NOT NULL) OR (kind = 'organization' AND owner_user_id IS NULL)", name='ck_workspace_owner_matches_kind'),
    sa.ForeignKeyConstraint(['owner_user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('owner_user_id', 'kind', name='uq_workspace_owner_kind')
    )
    op.create_table('organizations',
    sa.Column('id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('created_by_user_id', sa.Uuid(as_uuid=False), nullable=True),
    sa.Column('workspace_id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['created_by_user_id'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('workspace_id')
    )
    op.create_table('work_session_pull_requests',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('work_session_id', sa.Integer(), nullable=False),
    sa.Column('repository_id', sa.Integer(), nullable=False),
    sa.Column('sequence', sa.Integer(), nullable=False),
    sa.Column('branch', sa.String(length=255), nullable=False),
    sa.Column('status', sa.String(length=24), nullable=False),
    sa.Column('pull_request_number', sa.Integer(), nullable=True),
    sa.Column('pull_request_url', sa.Text(), nullable=False),
    sa.Column('error', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['work_session_id'], ['work_sessions.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('repository_id', 'pull_request_number', name='uq_session_pr_repo_number'),
    sa.UniqueConstraint('work_session_id', 'sequence', name='uq_session_pr_sequence')
    )
    op.create_table('agent_tasks',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('repository_id', sa.Integer(), nullable=False),
    sa.Column('github_user_id', sa.Integer(), nullable=True),
    sa.Column('github_login', sa.String(length=255), nullable=False),
    sa.Column('instructions', sa.Text(), nullable=False),
    sa.Column('source_pull_request_number', sa.Integer(), nullable=True),
    sa.Column('source_finding_key', sa.String(length=64), nullable=False),
    sa.Column('work_session_id', sa.Integer(), nullable=False),
    sa.Column('work_session_pull_request_id', sa.Integer(), nullable=False),
    sa.Column('state', sa.String(length=24), nullable=False),
    sa.Column('progress_stage', sa.String(length=32), nullable=False),
    sa.Column('progress_message', sa.Text(), nullable=False),
    sa.Column('commit_sha', sa.String(length=64), nullable=False),
    sa.Column('changes_json', sa.Text(), nullable=False),
    sa.Column('summary', sa.Text(), nullable=False),
    sa.Column('error', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.Column('user_id', sa.Uuid(as_uuid=False), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['work_session_id'], ['work_sessions.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['work_session_pull_request_id'], ['work_session_pull_requests.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('repository_id', 'source_pull_request_number', 'source_finding_key', name='uq_agent_task_source_finding')
    )
    op.create_table('installations',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('account', sa.String(length=255), nullable=False),
    sa.Column('account_type', sa.String(length=32), nullable=False),
    sa.Column('suspended', sa.Boolean(), nullable=False),
    sa.Column('organization_id', sa.Uuid(as_uuid=False), nullable=True),
    sa.Column('workspace_id', sa.Uuid(as_uuid=False), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('organization_invites',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('organization_id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('email', sa.String(length=320), nullable=False),
    sa.Column('role', sa.String(length=32), nullable=False),
    sa.Column('audience', sa.String(length=32), nullable=False),
    sa.Column('repository_scope', sa.String(length=16), nullable=False),
    sa.Column('repository_ids_json', sa.Text(), nullable=False),
    sa.Column('invited_by_user_id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('expires_at', sa.DateTime(), nullable=False),
    sa.Column('accepted_at', sa.DateTime(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['invited_by_user_id'], ['users.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('organization_memberships',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('organization_id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('user_id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('role', sa.String(length=32), nullable=False),
    sa.Column('audience', sa.String(length=32), nullable=False),
    sa.Column('repository_scope', sa.String(length=16), nullable=False),
    sa.Column('repository_ids_json', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('organization_id', 'user_id', name='uq_organization_membership')
    )
    op.create_table('repositories',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('installation_id', sa.Integer(), nullable=False),
    sa.Column('full_name', sa.String(length=255), nullable=False),
    sa.Column('private', sa.Boolean(), nullable=False),
    sa.Column('enabled', sa.Boolean(), nullable=False),
    sa.Column('connected', sa.Boolean(), nullable=False),
    sa.Column('review_mode', sa.String(length=32), nullable=False),
    sa.Column('organization_id', sa.Uuid(as_uuid=False), nullable=True),
    sa.Column('workspace_id', sa.Uuid(as_uuid=False), nullable=True),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('user_sessions',
    sa.Column('id', sa.String(length=128), nullable=False),
    sa.Column('expires_at', sa.DateTime(), nullable=False),
    sa.Column('user_id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('active_organization_id', sa.Uuid(as_uuid=False), nullable=True),
    sa.Column('active_workspace_id', sa.Uuid(as_uuid=False), nullable=True),
    sa.ForeignKeyConstraint(['active_organization_id'], ['organizations.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['active_workspace_id'], ['workspaces.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_background_jobs_kind'), 'background_jobs', ['kind'], unique=False)
    op.create_index(op.f('ix_background_jobs_state'), 'background_jobs', ['state'], unique=False)
    op.create_index(op.f('ix_book_documents_repository_id'), 'book_documents', ['repository_id'], unique=False)
    op.create_index(op.f('ix_context_files_scope'), 'context_files', ['scope'], unique=False)
    op.create_index(op.f('ix_context_files_scope_id'), 'context_files', ['scope_id'], unique=False)
    op.create_index(op.f('ix_pull_requests_repository_id'), 'pull_requests', ['repository_id'], unique=False)
    op.create_index(op.f('ix_repo_book_sections_repository_id'), 'repo_book_sections', ['repository_id'], unique=False)
    op.create_index(op.f('ix_usage_records_repository_id'), 'usage_records', ['repository_id'], unique=False)
    op.create_index(op.f('ix_users_email'), 'users', ['email'], unique=True)
    op.create_index(op.f('ix_auth_identities_user_id'), 'auth_identities', ['user_id'], unique=False)
    op.create_index(op.f('ix_email_verifications_email'), 'email_verifications', ['email'], unique=False)
    op.create_index(op.f('ix_email_verifications_user_id'), 'email_verifications', ['user_id'], unique=False)
    op.create_index(op.f('ix_repo_chat_messages_github_user_id'), 'repo_chat_messages', ['github_user_id'], unique=False)
    op.create_index(op.f('ix_repo_chat_messages_repository_id'), 'repo_chat_messages', ['repository_id'], unique=False)
    op.create_index(op.f('ix_repo_chat_messages_user_id'), 'repo_chat_messages', ['user_id'], unique=False)
    op.create_index(op.f('ix_work_sessions_github_user_id'), 'work_sessions', ['github_user_id'], unique=False)
    op.create_index(op.f('ix_work_sessions_repository_id'), 'work_sessions', ['repository_id'], unique=False)
    op.create_index(op.f('ix_work_sessions_status'), 'work_sessions', ['status'], unique=False)
    op.create_index(op.f('ix_work_sessions_user_id'), 'work_sessions', ['user_id'], unique=False)
    op.create_index(op.f('ix_workspaces_owner_user_id'), 'workspaces', ['owner_user_id'], unique=False)
    op.create_index(op.f('ix_work_session_pull_requests_repository_id'), 'work_session_pull_requests', ['repository_id'], unique=False)
    op.create_index(op.f('ix_work_session_pull_requests_status'), 'work_session_pull_requests', ['status'], unique=False)
    op.create_index(op.f('ix_work_session_pull_requests_work_session_id'), 'work_session_pull_requests', ['work_session_id'], unique=False)
    op.create_index(op.f('ix_agent_tasks_github_user_id'), 'agent_tasks', ['github_user_id'], unique=False)
    op.create_index(op.f('ix_agent_tasks_repository_id'), 'agent_tasks', ['repository_id'], unique=False)
    op.create_index(op.f('ix_agent_tasks_state'), 'agent_tasks', ['state'], unique=False)
    op.create_index(op.f('ix_agent_tasks_user_id'), 'agent_tasks', ['user_id'], unique=False)
    op.create_index(op.f('ix_agent_tasks_work_session_id'), 'agent_tasks', ['work_session_id'], unique=False)
    op.create_index(op.f('ix_agent_tasks_work_session_pull_request_id'), 'agent_tasks', ['work_session_pull_request_id'], unique=False)
    op.create_index(op.f('ix_installations_organization_id'), 'installations', ['organization_id'], unique=False)
    op.create_index(op.f('ix_installations_workspace_id'), 'installations', ['workspace_id'], unique=False)
    op.create_index(op.f('ix_organization_invites_email'), 'organization_invites', ['email'], unique=False)
    op.create_index(op.f('ix_organization_invites_organization_id'), 'organization_invites', ['organization_id'], unique=False)
    op.create_index(op.f('ix_organization_memberships_organization_id'), 'organization_memberships', ['organization_id'], unique=False)
    op.create_index(op.f('ix_organization_memberships_user_id'), 'organization_memberships', ['user_id'], unique=False)
    op.create_index(op.f('ix_repositories_full_name'), 'repositories', ['full_name'], unique=False)
    op.create_index(op.f('ix_repositories_installation_id'), 'repositories', ['installation_id'], unique=False)
    op.create_index(op.f('ix_repositories_organization_id'), 'repositories', ['organization_id'], unique=False)
    op.create_index(op.f('ix_repositories_workspace_id'), 'repositories', ['workspace_id'], unique=False)
    op.create_index(op.f('ix_user_sessions_active_organization_id'), 'user_sessions', ['active_organization_id'], unique=False)
    op.create_index(op.f('ix_user_sessions_active_workspace_id'), 'user_sessions', ['active_workspace_id'], unique=False)
    op.create_index(op.f('ix_user_sessions_user_id'), 'user_sessions', ['user_id'], unique=False)


def downgrade():
    op.drop_index(op.f('ix_user_sessions_user_id'), table_name='user_sessions')
    op.drop_index(op.f('ix_user_sessions_active_workspace_id'), table_name='user_sessions')
    op.drop_index(op.f('ix_user_sessions_active_organization_id'), table_name='user_sessions')
    op.drop_index(op.f('ix_repositories_workspace_id'), table_name='repositories')
    op.drop_index(op.f('ix_repositories_organization_id'), table_name='repositories')
    op.drop_index(op.f('ix_repositories_installation_id'), table_name='repositories')
    op.drop_index(op.f('ix_repositories_full_name'), table_name='repositories')
    op.drop_index(op.f('ix_organization_memberships_user_id'), table_name='organization_memberships')
    op.drop_index(op.f('ix_organization_memberships_organization_id'), table_name='organization_memberships')
    op.drop_index(op.f('ix_organization_invites_organization_id'), table_name='organization_invites')
    op.drop_index(op.f('ix_organization_invites_email'), table_name='organization_invites')
    op.drop_index(op.f('ix_installations_workspace_id'), table_name='installations')
    op.drop_index(op.f('ix_installations_organization_id'), table_name='installations')
    op.drop_index(op.f('ix_agent_tasks_work_session_pull_request_id'), table_name='agent_tasks')
    op.drop_index(op.f('ix_agent_tasks_work_session_id'), table_name='agent_tasks')
    op.drop_index(op.f('ix_agent_tasks_user_id'), table_name='agent_tasks')
    op.drop_index(op.f('ix_agent_tasks_state'), table_name='agent_tasks')
    op.drop_index(op.f('ix_agent_tasks_repository_id'), table_name='agent_tasks')
    op.drop_index(op.f('ix_agent_tasks_github_user_id'), table_name='agent_tasks')
    op.drop_index(op.f('ix_work_session_pull_requests_work_session_id'), table_name='work_session_pull_requests')
    op.drop_index(op.f('ix_work_session_pull_requests_status'), table_name='work_session_pull_requests')
    op.drop_index(op.f('ix_work_session_pull_requests_repository_id'), table_name='work_session_pull_requests')
    op.drop_index(op.f('ix_workspaces_owner_user_id'), table_name='workspaces')
    op.drop_index(op.f('ix_work_sessions_user_id'), table_name='work_sessions')
    op.drop_index(op.f('ix_work_sessions_status'), table_name='work_sessions')
    op.drop_index(op.f('ix_work_sessions_repository_id'), table_name='work_sessions')
    op.drop_index(op.f('ix_work_sessions_github_user_id'), table_name='work_sessions')
    op.drop_index(op.f('ix_repo_chat_messages_user_id'), table_name='repo_chat_messages')
    op.drop_index(op.f('ix_repo_chat_messages_repository_id'), table_name='repo_chat_messages')
    op.drop_index(op.f('ix_repo_chat_messages_github_user_id'), table_name='repo_chat_messages')
    op.drop_index(op.f('ix_email_verifications_user_id'), table_name='email_verifications')
    op.drop_index(op.f('ix_email_verifications_email'), table_name='email_verifications')
    op.drop_index(op.f('ix_auth_identities_user_id'), table_name='auth_identities')
    op.drop_index(op.f('ix_users_email'), table_name='users')
    op.drop_index(op.f('ix_usage_records_repository_id'), table_name='usage_records')
    op.drop_index(op.f('ix_repo_book_sections_repository_id'), table_name='repo_book_sections')
    op.drop_index(op.f('ix_pull_requests_repository_id'), table_name='pull_requests')
    op.drop_index(op.f('ix_context_files_scope_id'), table_name='context_files')
    op.drop_index(op.f('ix_context_files_scope'), table_name='context_files')
    op.drop_index(op.f('ix_book_documents_repository_id'), table_name='book_documents')
    op.drop_index(op.f('ix_background_jobs_state'), table_name='background_jobs')
    op.drop_index(op.f('ix_background_jobs_kind'), table_name='background_jobs')
    op.drop_table('user_sessions')
    op.drop_table('repositories')
    op.drop_table('organization_memberships')
    op.drop_table('organization_invites')
    op.drop_table('installations')
    op.drop_table('agent_tasks')
    op.drop_table('work_session_pull_requests')
    op.drop_table('organizations')
    op.drop_table('workspaces')
    op.drop_table('work_sessions')
    op.drop_table('repo_chat_messages')
    op.drop_table('email_verifications')
    op.drop_table('auth_identities')
    op.drop_table('webhook_deliveries')
    op.drop_table('waitlist_signups')
    op.drop_table('users')
    op.drop_table('usage_records')
    op.drop_table('repo_book_sections')
    op.drop_table('pull_requests')
    op.drop_table('context_files')
    op.drop_table('book_documents')
    op.drop_table('background_jobs')
