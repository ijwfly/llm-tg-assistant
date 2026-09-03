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
NEW_PROJECTS_DIR: str | None = None                       # /project new <name> creates folders here (None -> WORK_ROOT)

# --- Claude Code ----------------------------------------------------------------
CLAUDE_BIN: str = os.environ.get("CLAUDE_BIN", "claude")
CLAUDE_CONFIG_DIR: str | None = os.environ.get("CLAUDE_CONFIG_DIR") or None
DEFAULT_PERMISSION_MODE: str = os.environ.get("DEFAULT_PERMISSION_MODE", "prompt")
ALLOW_BYPASS: bool = False                                # allow /perm bypass (full shell from the phone)
DEFAULT_MODEL: str | None = None
DEFAULT_EFFORT: str | None = None
MODEL_CHOICES: list[str] = ["sonnet", "opus", "haiku"]   # the «Модель» button cycles through these (+ default)
SOUL_PATH: str | None = None                             # persona file appended to the system prompt (topics can override)
BRIDGE_PREAMBLE_PATH: str | None = None                  # None -> bridge_preamble.md in the repository
FALLBACK_MODEL: str | None = None
MAX_BUDGET_USD_PER_TURN: float | None = None
ALLOWED_TOOLS: list[str] = []                             # passed as --allowed-tools (permission rule syntax)
DISALLOWED_TOOLS: list[str] = []                          # passed as --disallowed-tools
CLAUDE_SETTINGS: str | None = None                        # --settings <file or JSON>
ADD_DIRS: list[str] = []                                  # --add-dir, extra directories the model may touch
BRIDGE_SEND_FILE_TOOL: bool = True                        # mcp__tgbridge__send_file: the model can send a file to the topic
VERBOSE_TOOL_OUTPUT: bool = False                         # default for the topic flag «Вывод инструментов»
FORWARD_SUBAGENT_TEXT: bool = False                       # --forward-subagent-text; subagent text shown in <details>
CLAUDE_ENV: dict[str, str] = {}                           # extra environment for the claude process

# --- Permissions, questions, plans (PROJECT_SPEC 4.6-4.7) ------------------------
BRIDGE_SOCKET: str = os.environ.get("BRIDGE_SOCKET", "/tmp/tgbridge.sock")   # unix socket: MCP prompt tool -> daemon
PERMISSION_TIMEOUT_SECS: float = 600.0   # unanswered permission card -> deny
QUESTION_TIMEOUT_SECS: float = 1800.0    # unanswered question / plan card -> deny
PERMISSION_DIFF_LINES: int = 60          # diff lines shown on Edit/Write cards

# --- Turns / processes ------------------------------------------------------------
IDLE_TIMEOUT_SECS: float = 1800.0    # idle process is stopped after this; next turn resumes the session
TURN_TIMEOUT_SECS: float = 3600.0    # a turn longer than this is interrupted
TURN_QUEUE_MAX: int = 32             # messages waiting behind a running turn, per topic
PROCESS_STOP_GRACE_SECS: float = 10.0
TYPING_INTERVAL: float = 4.0         # sendChatAction cadence while a turn runs
SHOW_TURN_STATS: bool = False        # italic "1 м 12 с · $0.08 · 3 шага" under the answer

# --- Live view / rendering ----------------------------------------------------------
USE_DRAFTS: bool = True              # rich drafts with <tg-thinking> in private chats
STREAM_PREVIEW: bool = True          # text tail in the progress message (groups)
THINKING_PREVIEW: bool = True        # last thinking line inside the draft
DRAFT_MIN_INTERVAL: float = 1.0      # trailing-edge gate for draft updates
EDIT_MIN_INTERVAL: float = 3.0       # gate for progress-message edits (edits share the chat rate limit)
DRAFT_KEEPALIVE: float = 20.0        # drafts live ~30 s: resend during long tool calls
PROGRESS_DELAY: float = 1.5          # show the progress message only if the turn takes longer
PREVIEW_TAIL: int = 600              # chars of text tail in the progress message
MIN_SEGMENT_CHARS: int = 120         # shorter text before a tool call is merged with the next segment
ANSWER_FILE_THRESHOLD: int = 50_000  # longer answers go as a file
INBOX_DIR: str = os.environ.get("INBOX_DIR", "/data/inbox")   # downloaded and generated files

# --- Voice out ------------------------------------------------------------------
TTS_CMD: str | None = None           # e.g. "say -o {wav} --data-format=LEI16@22050 -f {text_file} && ffmpeg -y -loglevel error -i {wav} -c:a libopus {out}"
TTS_TIMEOUT: float = 120.0
TTS_MAX_CHARS: int = 900             # prose read aloud per turn, cut at a sentence boundary

# --- Ingest ----------------------------------------------------------------------
BATCH_WINDOW_MS: int = 300           # sliding window: messages of a topic within it form one turn
TRANSCRIBE_CMD: str | None = None    # e.g. "opusdec --quiet --rate 16000 --force-wav {file} {wav} && whisper-cli -m … -f {wav} -nt"
TRANSCRIBE_TIMEOUT: float = 180.0
INBOX_TTL_DAYS: float = 7.0
REACTIONS: bool = True               # 👀 on staged messages
FILE_MAX_MB: int = 20                # Bot API download limit
VOICE_MAX_MB: int = 25

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
