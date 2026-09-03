import asyncio

import settings
from tests.support import fake_claude as fc
from tests.support.helpers import feed, wait_for_text, wait_turn_finished
from tests.support.updates import callback_update, text_update


async def _first_turn(app, spy, fake_claude, answer="раз"):
    fake_claude.text_turn(answer)
    await feed(app, text_update("первый"))
    await wait_for_text(spy, answer)
    await wait_turn_finished(app)
    return (await app.topics.list_all())[0]


async def test_idle_process_is_stopped_and_next_turn_resumes(app, spy, fake_claude):
    settings.IDLE_TIMEOUT_SECS = 0.3
    topic = await _first_turn(app, spy, fake_claude)
    rt = app.runtimes.peek(topic["id"])
    for _ in range(40):
        if rt.proc is None:
            break
        await asyncio.sleep(0.05)
    assert rt.proc is None
    fake_claude.text_turn("два")
    await feed(app, text_update("второй"))
    await wait_for_text(spy, "два")
    argvs = fake_claude.argv_calls()
    assert len(argvs) == 2 and argvs[1][argvs[1].index("--resume") + 1] == str(topic["session_id"])
    assert "--session-id" not in argvs[1]


async def test_stop_kills_the_process_and_keeps_the_session(app, spy, fake_claude):
    topic = await _first_turn(app, spy, fake_claude)
    await feed(app, callback_update("stop:1"))
    await wait_for_text(spy, "⏸ Процесс остановлен")
    assert app.runtimes.peek(topic["id"]).proc is None
    fake_claude.text_turn("снова")
    await feed(app, text_update("ещё"))
    await wait_for_text(spy, "снова")
    assert "--resume" in fake_claude.argv_calls()[1]
    assert str((await app.topics.list_all())[0]["session_id"]) == str(topic["session_id"])


async def test_new_gives_a_fresh_session_id(app, spy, fake_claude):
    topic = await _first_turn(app, spy, fake_claude)
    await feed(app, text_update("/new"))
    await wait_for_text(spy, "🆕 Новый контекст")
    after = (await app.topics.list_all())[0]
    assert after["session_id"] != topic["session_id"] and after["session_resumable"] is False


async def test_result_with_another_session_id_is_adopted(app, spy, fake_claude):
    fake_claude.enqueue(fc.assistant_text("ок"), fc.result(session_id="11111111-2222-3333-4444-555555555555"))
    await feed(app, text_update("привет"))
    await wait_for_text(spy, "ок")
    await wait_turn_finished(app)
    assert str((await app.topics.list_all())[0]["session_id"]) == "11111111-2222-3333-4444-555555555555"


async def test_daemon_stop_mid_turn_reports_and_kills_process(app, spy, fake_claude):
    fake_claude.enqueue(fc.assistant_text("работаю " + "над длинной задачей, которую ты поставил, " * 4), {"delay": 5})
    await feed(app, text_update("долго"))
    await wait_for_text(spy, "работаю")
    topic = (await app.topics.list_all())[0]
    rt = app.runtimes.peek(topic["id"])
    await app.stop()
    assert any(t.startswith("⏹ Демон остановлен посреди хода") for t in spy.sent_texts())
    assert rt.proc is None
    assert await app.db.fetchval("SELECT status FROM turns") == "aborted"


async def test_status_shows_process_and_last_turn(app, spy, fake_claude):
    await _first_turn(app, spy, fake_claude)
    await feed(app, text_update("/status"))
    await wait_for_text(spy, "Процесс      живой")
    assert any("Последний" in t and "$0.01" in t for t in spy.sent_texts())
