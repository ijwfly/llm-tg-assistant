from tests.support import fake_claude as fc
from tests.support.helpers import feed, run, wait_for_text, wait_turn_finished
from tests.support.updates import text_update

LONG = "Ответ достаточно длинный, чтобы уйти сразу одним сообщением и не ждать следующего сегмента текста. " * 2


def init_with_model(model):
    return {"type": "system", "subtype": "init", "session_id": "{session_id}", "model": model, "cwd": "{cwd}",
            "permissionMode": "default", "tools": [], "mcp_servers": []}


async def test_usage_card_groups_by_topic_and_model(app, spy, fake_claude):
    fake_claude.enqueue(init_with_model("claude-sonnet-5"), fc.assistant_text(LONG),
                        fc.result(cost=0.25, duration_ms=1000))
    await feed(app, text_update("раз", thread_id=5, topic_name="Проект"))
    await wait_turn_finished(app)
    fake_claude.enqueue(init_with_model("claude-opus-5"), fc.assistant_text(LONG), fc.result(cost=1.0))
    await feed(app, text_update("два", thread_id=6, topic_name="Инфра"))
    await wait_turn_finished(app, after=1)
    fake_claude.enqueue({"type": "rate_limit_event", "session_id": "{session_id}",
                         "rate_limit_info": {"unifiedWindows": {"five_hour": {"utilization": 0.25}, "seven_day": {"utilization": 0.1}}}},
                        fc.assistant_text(LONG), fc.result(cost=0.5))
    await feed(app, text_update("три", thread_id=5, topic_name="Проект"))
    await wait_turn_finished(app, after=2)
    models = await app.db.fetch("SELECT model FROM turns ORDER BY id")
    assert [r["model"] for r in models][:2] == ["claude-sonnet-5", "claude-opus-5"]
    await run(app, text_update("/usage", thread_id=5, topic_name="Проект"))
    card = spy.calls("SendMessage")[-1]
    text = card["text"]
    assert text.startswith("Расход за 20")
    assert "Инфра: 1 ходов · $1.00 · 10 in / 20 out" in text
    assert "Проект: 2 ходов · $0.75 · 20 in / 40 out" in text
    assert "claude-opus-5: 1 ходов · $1.00" in text and "claude-sonnet-5: 1 ходов · $0.25" in text
    assert text.endswith("Итого: 3 ходов · $1.75 · 30 in / 60 out")
    assert card["reply_markup"]["inline_keyboard"][0][0]["text"] == "Скрыть"
    await run(app, text_update("/status", thread_id=5, topic_name="Проект"))
    assert "Лимиты       5 ч: 25% · 7 дн: 10%" in spy.last_text()


async def test_usage_card_when_empty(app, spy, fake_claude):
    await run(app, text_update("/usage"))
    assert spy.last_text().startswith("За 20") and spy.last_text().endswith("ходов ещё не было.")
