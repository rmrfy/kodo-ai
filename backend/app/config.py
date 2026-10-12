"""Environment-backed configuration for Kodo."""
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is required. Configure a PostgreSQL connection string in backend/.env.")
if DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg://", 1)
if not DATABASE_URL.startswith("postgresql+psycopg://"):
    raise RuntimeError("Only PostgreSQL is supported. Set DATABASE_URL to postgresql+psycopg://...")

GITHUB_APP_ID = os.getenv("GITHUB_APP_ID", "")
GITHUB_PRIVATE_KEY_PATH = os.getenv("GITHUB_PRIVATE_KEY_PATH", "")
GITHUB_WEBHOOK_SECRET = os.getenv("GITHUB_WEBHOOK_SECRET", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-6-luna")
AI_DISABLED = os.getenv("KODO_AI_DISABLED", "false").lower() == "true"
MAX_DIFF_CHARS = int(os.getenv("KODO_MAX_DIFF_CHARS", "70000"))
MAX_REPO_FILES = int(os.getenv("KODO_MAX_REPO_FILES", "500"))
CODING_TASKS_ENABLED = os.getenv("KODO_CODING_TASKS_ENABLED", "true").lower() == "true"
CODEX_CLI_PATH = os.getenv("KODO_CODEX_CLI_PATH", "codex")
CODEX_TASK_TIMEOUT_SECONDS = int(os.getenv("KODO_CODEX_TASK_TIMEOUT_SECONDS", "1800"))
FRONTEND_ORIGIN = os.getenv("FRONTEND_ORIGIN", "http://localhost:5173")
