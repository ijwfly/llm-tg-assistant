"""Application defaults. Secrets and machine-specific values live in settings_local.py
(gitignored) or in environment variables (docker-compose). See settings_local.py.example.
"""
import os


def _env_list(name: str) -> list[int]:
    raw = os.environ.get(name, "")
    return [int(x) for x in raw.replace(";", ",").split(",") if x.strip()]


# --- Required -----------------------------------------------------------------
TELEGRAM_BOT_TOKEN: str = os.environ.get("TELEGRAM_BOT_TOKEN", "")
ALLOWED_USERS: list[int] = _env_list("ALLOWED_USERS")      # Telegram user ids; must be non-empty
DATABASE_URL: str = os.environ.get("DATABASE_URL", "postgresql://app:app@localhost:5432/app")

# --- Access ---------------------------------------------------------------------
ALLOWED_CHATS: list[int] = _env_list("ALLOWED_CHATS")      # empty = any chat an allowed user writes from
NOTIFY_CHAT: str | None = os.environ.get("NOTIFY_CHAT") or None   # "chat_id" or "chat_id:thread_id"

# --- Projects -------------------------------------------------------------------
WORK_ROOT: str = os.environ.get("WORK_ROOT", "/work")      # /cd never leaves this directory
DEFAULT_CWD: str | None = os.environ.get("DEFAULT_CWD") or None   # None -> WORK_ROOT
PROJECTS: dict[str, str] = {}                             # alias -> path, for /go and /project

# --- Claude Code ----------------------------------------------------------------
CLAUDE_BIN: str = os.environ.get("CLAUDE_BIN", "claude")
CLAUDE_CONFIG_DIR: str | None = os.environ.get("CLAUDE_CONFIG_DIR") or None
DEFAULT_PERMISSION_MODE: str = os.environ.get("DEFAULT_PERMISSION_MODE", "prompt")
ALLOW_BYPASS: bool = False                                # allow /perm bypass (full shell from the phone)
DEFAULT_MODEL: str | None = None
DEFAULT_EFFORT: str | None = None

# --- Outbox / delivery ----------------------------------------------------------
OUTBOX_POLL_INTERVAL: float = 0.5        # seconds between idle polls of the outbox
OUTBOX_RETRY_BASE_SECS: float = 1.0      # backoff base for non-429 delivery errors
OUTBOX_RETRY_MAX_SECS: float = 30.0
OUTBOX_MAX_AGE_SECS: float = 600.0       # a row older than this is marked failed
SHUTDOWN_DRAIN_SECS: float = 10.0        # how long to keep delivering on shutdown

LOG_LEVEL: str = os.environ.get("LOG_LEVEL", "INFO")

try:
    from settings_local import *  # noqa: F401,F403
except ImportError:
    pass

# --- Derived (only when not set explicitly above / in settings_local) ----------
if DEFAULT_CWD is None:
    DEFAULT_CWD = WORK_ROOT
