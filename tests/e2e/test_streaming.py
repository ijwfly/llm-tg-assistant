import asyncio

from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter
from aiogram.methods import SendRichMessageDraft, EditMessageText

import settings
from tests.support import fake_claude as fc
from tests.support.helpers import feed, wait_for_text, wait_outbox_idle, wait_turn_finished
from tests.support.updates import stopped_update, text_update, callback_update

LONG = "Это достаточно длинный фрагмент ответа, чтобы превысить порог короткого сегмента и уйти сразу. " * 2


def drafts(spy):
    return [p["rich_message"]["markdown"] for p in spy.calls("SendRichMessageDraft")]


async def wait_draft(spy, fragment, timeout=3.0):
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        for d in drafts(spy):
            if fragment in d:
                return d
        await asyncio.sleep(0.02)
    raise AssertionError(f"{fragment!r} never in a draft; drafts: {drafts(spy)!r}")


async def test_private_chat_streams_a_draft_with_thinking_and_text(app, spy, fake_claude):
    fake_claude.enqueue(
        fc.thinking_delta("Сначала посмотрю на тесты\n"), fc.thinking_delta("Похоже, падает фикстура таймзоны"),
        fc.tool_use("Grep", {"pattern": "def test_", "path": "tests"}), fc.tool_result(),
        fc.tool_use("Read", {"file_path": "/work/proj/src/a/very/long/path/that/keeps/going/and/going/main.py"}, "toolu_2"), fc.tool_result("toolu_2"),
        fc.text_delta("Нашёл причину: "), fc.text_delta("фикстура использует локальное время, а тест ждёт UTC. "),
        fc.text_delta("Исправление ниже"), {"delay": 0.3},
        fc.assistant_text(LONG), fc.result())
    await feed(app, text_update("почему падает тест?"))
    draft = await wait_draft(spy, "Исправление")
    assert draft.startswith("<tg-thinking>")
    head, body = draft.split("</tg-thinking>", 1)
    assert "Grep → Read …" in head and "main.py" in head and "(2 · " in head
    assert "🧠 Похоже, падает фикстура таймзоны" in head
    assert body.strip().startswith("Нашёл причину: фикстура использует локальное время, а тест ждёт UTC.")
    assert "Исправление" in body and "ниже" not in body  # last unfinished word is held back
    first = spy.calls("SendRichMessageDraft")[0]
    assert first["can_stop"] is True and first["draft_id"] == 1 and first["chat_id"] == 1
    await wait_for_text(spy, LONG.strip())
    assert spy.calls("SendMessage") == [] or all("🛑" not in (p.get("text") or "") for p in spy.calls("SendMessage"))


async def test_native_stop_on_the_draft_cancels_the_turn(app, spy, fake_claude):
    fake_claude.enqueue(fc.text_delta("Начинаю долгую работу над задачей, которую ты поставил, сейчас всё будет"),
                        {"delay": 5})
    await feed(app, text_update("долго"))
    await wait_draft(spy, "Начинаю долгую")
    await feed(app, stopped_update(draft_id=1))
    await wait_for_text(spy, "🛑 Прервано.")
    assert fake_claude.signals() == ["SIGINT"]
    verdict = spy.calls("SendMessage")[-1]
    assert verdict["reply_markup"]["inline_keyboard"][0][0]["callback_data"] == "retry:1"


async def test_rejected_draft_falls_back_to_a_progress_message(app, spy, fake_claude, session):
    session.fail_next("SendRichMessageDraft", TelegramBadRequest(
        method=SendRichMessageDraft(chat_id=1, draft_id=1, rich_message={"markdown": "x"}), message="Bad Request: drafts unavailable"))
    fake_claude.enqueue(fc.tool_use("Bash", {"command": "pytest -q"}), fc.tool_result(), {"delay": 0.3},
                        fc.assistant_text(LONG), fc.result())
    await feed(app, text_update("гони тесты"))
    await wait_for_text(spy, "pytest -q")
    progress = next(p for p in spy.calls("SendMessage") if "pytest -q" in p["text"])
    assert progress["reply_markup"]["inline_keyboard"][0][0]["callback_data"] == "cancel:1"
    await wait_for_text(spy, LONG.strip())
    await wait_turn_finished(app)
    assert spy.calls("DeleteMessage")[-1]["message_id"] == 1000


async def test_group_shows_progress_message_edits_it_and_deletes_after_the_answer(app, spy, fake_claude):
    fake_claude.enqueue(fc.tool_use("Grep", {"pattern": "TODO"}), fc.tool_result(), {"delay": 0.15},
                        fc.tool_use("Bash", {"command": "git status"}, "t2"), fc.tool_result("t2"), {"delay": 0.15},
                        fc.assistant_text(LONG), fc.result())
    await feed(app, text_update("что тут", chat_id=-100500, chat_type="supergroup", thread_id=42, topic_name="proj"))
    await wait_for_text(spy, "Grep → Bash git status")
    assert spy.calls("SendRichMessageDraft") == []
    progress = [p for p in spy.calls("SendMessage") if p.get("reply_markup")]
    assert progress and progress[0]["message_thread_id"] == 42
    assert spy.calls("EditMessageText")  # at least one in-place edit
    await wait_for_text(spy, LONG.strip())
    await wait_turn_finished(app)
    names = [n for n, _ in spy.session.calls]
    assert names.index("DeleteMessage") > names.index("SendRichMessage")


async def test_stop_button_on_progress_message_cancels(app, spy, fake_claude):
    fake_claude.enqueue(fc.tool_use("Bash", {"command": "sleep 100"}), {"delay": 5})
    await feed(app, text_update("жди", chat_id=-100500, chat_type="supergroup", thread_id=42, topic_name="proj"))
    await wait_for_text(spy, "sleep 100")
    await feed(app, callback_update("cancel:1", chat_id=-100500, chat_type="supergroup"))
    await wait_for_text(spy, "🛑 Прервано.")
    assert spy.calls("AnswerCallbackQuery")[-1]["text"] == "Прерываю…"


async def test_short_segment_is_merged_with_the_next_one(app, spy, fake_claude):
    fake_claude.enqueue(fc.assistant_text("Посмотрю файл."), fc.tool_use("Read", {"file_path": "a.py"}), fc.tool_result(),
                        fc.assistant_text(LONG), fc.result())
    await feed(app, text_update("глянь a.py"))
    await wait_turn_finished(app)
    rich = [p["rich_message"]["markdown"] for p in spy.calls("SendRichMessage")]
    assert len(rich) == 1 and rich[0].startswith("Посмотрю файл.\n\n" + LONG[:20])


async def test_rate_limit_on_draft_does_not_break_the_turn(app, spy, fake_claude, session):
    session.fail_next("SendRichMessageDraft", TelegramRetryAfter(
        method=SendRichMessageDraft(chat_id=1, draft_id=1, rich_message={"markdown": "x"}), message="flood", retry_after=1))
    fake_claude.enqueue(fc.text_delta("Первая порция текста, которую Telegram не примет из-за лимита, но ход продолжится"),
                        {"delay": 0.2}, fc.assistant_text(LONG), fc.result())
    await feed(app, text_update("привет"))
    await wait_for_text(spy, LONG.strip())
    turn = await wait_turn_finished(app)
    assert turn["status"] == "done"
    assert len(session.failed_calls) == 1


async def test_very_long_answer_is_sent_as_a_file(app, spy, fake_claude):
    settings.ANSWER_FILE_THRESHOLD = 300
    text = "# Отчёт\n\n" + ("строка отчёта номер N с деталями\n" * 40)
    fake_claude.enqueue(fc.assistant_text(text), fc.result())
    await feed(app, text_update("отчёт"))
    await wait_for_text(spy, "Ответ целиком — в файле.")
    doc = spy.calls("SendDocument")[-1]
    assert doc["caption"] == "Ответ целиком — в файле." and doc["document"].endswith("answer-1.md")
    rich = spy.calls("SendRichMessage")[-1]["rich_message"]["markdown"]
    assert rich.startswith("# Отчёт") and rich.endswith("…")
    with open(doc["document"]) as f:
        assert f.read() == text
