# Kodo AI

Kodo is a GitHub App with a FastAPI backend and Vue 3 dashboard. It stores installations, pull request analyses, Repo Book summaries, and model usage in SQLAlchemy-backed PostgreSQL (SQLite is the local default). GitHub webhook deliveries are HMAC verified and deduplicated. Opened, reopened, synchronized, and ready-for-review pull requests are summarized and reviewed; actionable findings are posted inline only when their line is in the diff.

## Local development

1. Install Python dependencies: `python -m venv backend/.venv && backend/.venv/bin/pip install -r backend/requirements.txt`.
2. Set the environment variables below in `backend/.env`. Keep the private key outside the repository.
3. Start the API from `backend`: `./.venv/bin/uvicorn app.main:app --reload --port 8000` (or activate that venv and run `uvicorn app.main:app --reload --port 8000`). The first run creates a local SQLite database. PostgreSQL deployments should set `DATABASE_URL=postgresql+psycopg://...` and run `alembic upgrade head` from `backend`.
4. Start the Vue dashboard: `cd frontend && npm install && npm run dev`. Vite proxies `/api` to `localhost:8000`. If hosting frontend and API on separate origins, set `VITE_API_URL` at build time and configure `FRONTEND_ORIGIN` on the API.
5. Use `KODO_AI_DISABLED=true` for a no-credit mock flow. It stores placeholder summaries and does not call OpenAI. For a live AI run, set `OPENAI_API_KEY` and optionally `OPENAI_MODEL`.

## Configuration

Existing GitHub App settings are reused: `GITHUB_APP_ID`, `GITHUB_WEBHOOK_SECRET`, and `GITHUB_PRIVATE_KEY_PATH`. Add `GITHUB_CLIENT_ID` and `GITHUB_CLIENT_SECRET` for dashboard OAuth, `GITHUB_APP_SLUG` for the install link, and `KODO_SESSION_SECRET` for signing sessions and encrypting server-side OAuth tokens. Set `KODO_COOKIE_SECURE=true` behind HTTPS. `FRONTEND_ORIGIN` defaults to `http://localhost:5173`. Use `DATABASE_URL` for PostgreSQL, `OPENAI_MODEL` to select a model, and `OPENAI_INPUT_USD_PER_MILLION` / `OPENAI_OUTPUT_USD_PER_MILLION` to tune estimates as pricing changes. `KODO_MAX_DIFF_CHARS` and `KODO_MAX_REPO_FILES` bound analyzed code.

Configure the GitHub App to subscribe to `pull_request`, `push`, `installation`, and `installation_repositories` events. Required repository permissions are Contents: read, Pull requests: read and write, and Issues: read and write. The backend endpoint is `/github-webhook`; set that URL in the App configuration. The OAuth callback can use `/api/auth/callback` (canonical) or `/auth/callback` (compatibility path) on the API host.

## Repo Book and privacy

The initial book indexes text files under 50 KB on the default branch (up to 500 files), summarizes changed blobs only, then refreshes module summaries, architecture/data flow/integrations/business logic chapters, and the repository overview when inputs change. Pushes mark existing notes stale while a refresh is queued. Source contents are sent to the configured OpenAI API for analysis and are not logged. AI output is constrained to JSON and inline comments are filtered to added diff lines. Webhook jobs are persisted, deduplicated, retried up to three times, and resumed after a backend restart. For multiple backend instances or high volume, use a distributed worker queue.

## Tests

From `backend`, run `../backend/.venv/bin/python -m unittest discover -s tests`. The tests cover review diff-line mapping, mode guidance, bounded PR context, and mock mode. They do not need GitHub credentials or OpenAI credits.
