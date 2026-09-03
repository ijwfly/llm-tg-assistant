"""Root test configuration: settings overrides BEFORE the app is imported, DB and app fixtures."""
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import settings  # noqa: E402

settings.TELEGRAM_BOT_TOKEN = "123456:TESTTOKEN"
settings.ALLOWED_USERS = [1]
settings.ALLOWED_CHATS = []
settings.NOTIFY_CHAT = None
settings.DATABASE_URL = os.environ.get("TEST_DATABASE_URL", "postgresql://app:app@localhost:55432/app_test")
settings.WORK_ROOT = "/work"
settings.DEFAULT_CWD = "/work"
settings.DEFAULT_PERMISSION_MODE = "prompt"
settings.OUTBOX_POLL_INTERVAL = 0.02
settings.OUTBOX_RETRY_BASE_SECS = 0.02
settings.OUTBOX_RETRY_MAX_SECS = 0.2
settings.OUTBOX_MAX_AGE_SECS = 600.0
settings.SHUTDOWN_DRAIN_SECS = 1.0
settings.IDLE_TIMEOUT_SECS = 60.0
settings.TURN_TIMEOUT_SECS = 30.0
settings.TYPING_INTERVAL = 0.2
settings.PROCESS_STOP_GRACE_SECS = 2.0
settings.CLAUDE_BIN = str(ROOT / "tests" / "fake_claude" / "claude")
settings.CLAUDE_CONFIG_DIR = None
settings.DRAFT_MIN_INTERVAL = 0.05
settings.EDIT_MIN_INTERVAL = 0.05
settings.DRAFT_KEEPALIVE = 0.3
settings.PROGRESS_DELAY = 0.0
settings.BATCH_WINDOW_MS = 60
settings.TRANSCRIBE_CMD = None

from aiogram import Bot  # noqa: E402

from app.app import App  # noqa: E402
from app.store.db import Database  # noqa: E402
from tests.support.fake_claude import FakeClaude  # noqa: E402
from tests.support.session import RecordingSession  # noqa: E402
from tests.support.spy import TelegramSpy  # noqa: E402

TABLES = ["message_links", "outbox", "turns", "staging_items", "inbox_files", "processed_updates", "topics", "users"]


@pytest.fixture(autouse=True)
def restore_settings():
    snapshot = {k: v for k, v in vars(settings).items() if k.isupper()}
    yield
    for k, v in snapshot.items():
        setattr(settings, k, v)


@pytest.fixture(scope="session")
async def db():
    database = await Database.connect(settings.DATABASE_URL)
    await database.migrate()
    yield database
    await database.close()


@pytest.fixture(autouse=True)
async def clean_db(db):
    yield
    await db.execute("TRUNCATE " + ", ".join(TABLES) + " RESTART IDENTITY CASCADE")


@pytest.fixture(autouse=True)
def fake_claude(tmp_path) -> FakeClaude:
    """Every test talks to the fake claude; an empty scenario queue makes a turn crash loudly."""
    fake = FakeClaude(tmp_path)
    work = tmp_path / "work"
    work.mkdir()
    settings.CLAUDE_ENV = fake.env
    settings.WORK_ROOT = str(work)
    settings.DEFAULT_CWD = str(work)
    settings.INBOX_DIR = str(tmp_path / "inbox")
    return fake


@pytest.fixture
def session() -> RecordingSession:
    return RecordingSession()


@pytest.fixture
def spy(session) -> TelegramSpy:
    return TelegramSpy(session)


@pytest.fixture
async def app(db, session):
    bot = Bot(token=settings.TELEGRAM_BOT_TOKEN, session=session)
    application = App(bot, db)
    await application.start()
    yield application
    await application.stop()
    await bot.session.close()
