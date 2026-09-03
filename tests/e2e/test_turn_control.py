import asyncio

import settings
from tests.support import fake_claude as fc
from tests.support.helpers import feed, wait_for_text, wait_turn_finished
from tests.support.updates import text_update


async def test_cancel_interrupts_the_turn_and_next_turn_resumes(app, spy, fake_claude):
    fake_claude.enqueue(fc.assistant_text("начинаю"), {"delay": 5})
    fake_claude.text_turn("после отмены")
    await feed(app, text_update("долгая задача"))
    await wait_for_text(spy, "начинаю")
    await feed(app, text_update("/cancel"))
    await wait_for_text(spy, "🛑 Прервано.")
    turn = await wait_turn_finished(app)
    assert turn["status"] == "cancelled"
    assert fake_claude.signals() == ["SIGINT"]
    session_id = str((await app.topics.list_all())[0]["session_id"])
    await feed(app, text_update("продолжай"))
    await wait_for_text(spy, "после отмены")
    argvs = fake_claude.argv_calls()
    assert len(argvs) == 2 and argvs[1][argvs[1].index("--resume") + 1] == session_id


async def test_cancel_without_a_turn_says_so(app, spy, fake_claude):
    await feed(app, text_update("/cancel"))
    await wait_for_text(spy, "Нечего прерывать.")


async def test_turn_timeout_interrupts_and_keeps_context(app, spy, fake_claude):
    settings.TURN_TIMEOUT_SECS = 0.4
    fake_claude.enqueue({"delay": 5})
    await feed(app, text_update("зависни"))
    await wait_for_text(spy, "⏱ Ход шёл дольше лимита")
    turn = await wait_turn_finished(app)
    assert turn["status"] == "timeout"


async def test_crash_is_retried_once_silently(app, spy, fake_claude):
    fake_claude.enqueue({"exit": 2, "stderr": "segfault"})
    fake_claude.text_turn("со второй попытки")
    await feed(app, text_update("привет"))
    await wait_for_text(spy, "со второй попытки")
    assert len(fake_claude.argv_calls()) == 2
    assert not any(t.startswith("💥") for t in spy.sent_texts())
    turn = await wait_turn_finished(app)
    assert turn["status"] == "done"


async def test_double_crash_is_reported_with_stderr(app, spy, fake_claude):
    fake_claude.enqueue({"exit": 2, "stderr": "boom one"})
    fake_claude.enqueue({"exit": 2, "stderr": "boom two"})
    await feed(app, text_update("привет"))
    await wait_for_text(spy, "💥 Процесс claude завершился (код 2)")
    verdict = next(t for t in spy.sent_texts() if t.startswith("💥"))
    assert "boom two" in verdict and "/retry" in verdict
    turn = await wait_turn_finished(app)
    assert turn["status"] == "crashed"


async def test_retry_resends_the_last_prompt(app, spy, fake_claude):
    fake_claude.enqueue({"exit": 2, "stderr": "boom"})
    fake_claude.enqueue({"exit": 2, "stderr": "boom"})
    fake_claude.text_turn("теперь получилось")
    await feed(app, text_update("сделай дело"))
    await wait_for_text(spy, "💥")
    await feed(app, text_update("/retry"))
    await wait_for_text(spy, "теперь получилось")
    assert fake_claude.stdin_texts()[-1] == "сделай дело"
    assert await app.db.fetchval("SELECT count(*) FROM turns") == 2


async def test_retry_without_turns_says_so(app, spy, fake_claude):
    await feed(app, text_update("/retry"))
    await wait_for_text(spy, "Нечего повторять")
