# Kodo AI

Kodo is a GitHub App with a FastAPI backend and Vue 3 dashboard. It stores installations, pull request analyses, Handbook summaries, per-user Handbook chat history, and model usage in PostgreSQL. `DATABASE_URL` is required; SQLite and implicit database fallbacks are not supported. GitHub webhook deliveries are HMAC verified and deduplicated. Opened, reopened, synchronized, and ready-for-review pull requests are summarized and reviewed; actionable findings are posted inline only when their line is in the diff. Users can ask repository questions against retrieved Handbook notes, with source labels in each answer.

Settings provides Markdown context files for each GitHub App installation and each repository. Workspace context applies across that installation's repositories; repository context supplements it and takes precedence when they conflict. Kodo uses the context when generating Handbook chapters, answering repository questions, and preparing coding tasks. Updating context marks existing Handbook chapters stale; regenerate a Handbook to refresh them.

## Local development

1. Install Python dependencies: `python -m venv backend/.venv && backend/.venv/bin/pip install -r backend/requirements.txt`.
2. Set the environment variables below in `backend/.env`, including a PostgreSQL `DATABASE_URL` such as `postgresql+psycopg://USER:PASSWORD@HOST:5432/kodo_ai`. Keep the private key outside the repository.
3. Create the `kodo_ai` database on your PostgreSQL server, then from `backend` run `./.venv/bin/alembic upgrade head` to create/update its schema.
4. Start the API from `backend`: `./.venv/bin/uvicorn app.main:app --reload --port 8000` (or activate that venv and run `uvicorn app.main:app --reload --port 8000`).
5. Start the Vue dashboard: `cd frontend && npm install && npm run dev`. Vite proxies `/api` to `localhost:8000`. If hosting frontend and API on separate origins, set `VITE_API_URL` at build time and configure `FRONTEND_ORIGIN` on the API.
6. Use `KODO_AI_DISABLED=true` for a no-credit mock flow. It stores placeholder summaries and does not call OpenAI. For a live AI run, set `OPENAI_API_KEY` and optionally `OPENAI_MODEL`.

## Configuration

Existing GitHub App settings are reused: `GITHUB_APP_ID`, `GITHUB_WEBHOOK_SECRET`, and `GITHUB_PRIVATE_KEY_PATH`. `DATABASE_URL` must be a PostgreSQL URL and is required both for the app and Alembic migrations; startup fails if it is missing or points to another database. Add `GITHUB_CLIENT_ID` and `GITHUB_CLIENT_SECRET` for dashboard OAuth, `GITHUB_APP_SLUG` for the install link, and `KODO_SESSION_SECRET` for signing sessions and encrypting server-side OAuth tokens. Set `KODO_COOKIE_SECURE=true` behind HTTPS. `FRONTEND_ORIGIN` defaults to `http://localhost:5173`. Use `OPENAI_MODEL` to select a model, and `OPENAI_INPUT_USD_PER_MILLION` / `OPENAI_OUTPUT_USD_PER_MILLION` to tune estimates as pricing changes. `KODO_MAX_DIFF_CHARS` and `KODO_MAX_REPO_FILES` bound analyzed code.

Configure the GitHub App to subscribe to `pull_request`, `push`, `installation`, and `installation_repositories` events. Required repository permissions are Contents: read and write, Pull requests: read and write, and Issues: read and write. The backend endpoint is `/github-webhook`; set that URL in the App configuration. The OAuth callback can use `/api/auth/callback` (canonical) or `/auth/callback` (compatibility path) on the API host.

## Coding tasks

The Tasks tab runs requests through the configured coding-agent provider in a fresh temporary clone. Codex CLI is the currently supported provider and `codex exec` runs as a bounded background task. Install Codex CLI on the backend host, set `OPENAI_API_KEY`, and configure `KODO_CODING_TASKS_ENABLED`, `KODO_CODING_AGENT_PROVIDER=codex`, `KODO_CODEX_CLI_PATH`, and `KODO_CODING_TASK_TIMEOUT_SECONDS` in `backend/.env`. Kodo passes the key only to the Codex process as `CODEX_API_KEY`; this uses OpenAI API billing and does not rely on a user's ChatGPT/Codex subscription. API-key use is billed through the associated OpenAI Platform account. Kodo creates a task branch, pushes the changes, and opens a draft pull request; it never merges automatically. Only one task per repository can run at a time. Task execution uses Codex's `workspace-write` sandbox with network access disabled, while the clone itself is isolated in a per-task temporary directory. Use a trusted backend host and grant the GitHub App only the repository permissions it needs. Changes and task instructions are sent to the configured coding agent. Progress events and failures are logged without logging command text or credentials. This local process sandbox is not a per-task virtual machine; do not expose task execution to untrusted users without stronger infrastructure isolation.

## Handbook and privacy

The Handbook indexes text files under 50 KB on the default branch, skips generated/vendor/build directories, prioritizes README/docs and project configuration, and caps indexing at `KODO_MAX_REPO_FILES` (default 500). It processes file summaries in small batches, commits each batch, resumes from saved file hashes after transient failures, and reports indexed/eligible counts so a capped index is visible. If GitHub truncates a very large recursive tree, Kodo walks subtrees to enumerate it. Per-file and per-module notes feed handbook chapters based on the repository's own documented subsystems, concepts, and workflows; chapter titles and topics are not preset. A chapter is saved only when it has substantive content and exact supporting paths; unsupported topics are omitted. Handbook sections, their audience labels, structured blocks, and source paths are stored in PostgreSQL alongside the technical index. Pushes mark generated notes stale while a refresh is queued. Source contents are sent to the configured OpenAI API for analysis and are not logged. Webhook jobs are persisted, deduplicated, retried up to three times, and resumed after a backend restart. For multiple backend instances or high volume, use a distributed worker queue.

## Tests

From `backend`, run `../backend/.venv/bin/python -m unittest discover -s tests`. Tests cover review helpers, provider selection, Codex result/progress normalization, failures and timeouts, and task-runner change detection. The tests do not need GitHub credentials or OpenAI credits.
