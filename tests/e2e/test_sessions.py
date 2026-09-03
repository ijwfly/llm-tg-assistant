import time

import settings
from tests.support import fake_claude as fc
from tests.support.fake_claude import write_transcript
from tests.support.helpers import feed, run, wait_for_text, wait_turn_finished
from tests.support.updates import callback_update, text_update

LONG = "Продолжаю из подключённой сессии, вот что помню из её контекста, достаточно длинный ответ. " * 2
TERM = "aaaaaaaa-1111-4111-8111-111111111111"
OTHER = "bbbbbbbb-2222-4222-8222-222222222222"


def buttons(payload):
    return [b["callback_data"] for row in payload["reply_markup"]["inline_keyboard"] for b in row]


async def test_sessions_card_lists_transcripts_with_marks_and_buttons(app, spy, fake_claude):
    await run(app, text_update("/status"))
    topic = (await app.topics.list_all())[0]
    now = time.time()
    write_transcript(settings.CLAUDE_CONFIG_DIR, topic["cwd"], str(topic["session_id"]), ["мой вопрос из темы"], mtime=now - 30)
    write_transcript(settings.CLAUDE_CONFIG_DIR, topic["cwd"], TERM, ["терминальная задача"], custom_title="Починить auth",
                     mtime=now - 600)
    await run(app, text_update("/sessions"))
    card = spy.calls("SendMessage")[-1]
    lines = card["text"].splitlines()
    assert lines[0] == f"Сессии в {topic['cwd']}:"
    assert lines[1] == f"▸ {str(topic['session_id'])[:8]} · только что · «мой вопрос из темы» · эта тема"
    assert lines[2] == "▸ aaaaaaaa · 10 мин назад · «Починить auth» · терминал"
    assert buttons(card) == [f"rs:1:{str(topic['session_id'])[:8]}", f"br:1:{str(topic['session_id'])[:8]}",
                             "rs:1:aaaaaaaa", "br:1:aaaaaaaa"]


async def test_sessions_card_when_empty(app, spy, fake_claude):
    await run(app, text_update("/sessions"))
    assert spy.last_text().startswith("В ") and spy.last_text().endswith("сессий пока нет.")


async def test_resume_by_prefix_switches_the_topic_and_resumes_on_the_next_turn(app, spy, fake_claude):
    await run(app, text_update("/status"))
    topic = (await app.topics.list_all())[0]
    write_transcript(settings.CLAUDE_CONFIG_DIR, topic["cwd"], TERM, ["терминальная задача"])
    await run(app, text_update("/resume aaaa"))
    assert spy.last_text() == f"🔗 Подключилась к сессии aaaaaaaa · «терминальная задача»\nДиректория: {topic['cwd']}"
    updated = (await app.topics.list_all())[0]
    assert str(updated["session_id"]) == TERM and updated["session_resumable"] is True
    fake_claude.text_turn(LONG)
    await feed(app, text_update("что мы делали?"))
    await wait_for_text(spy, LONG.strip())
    argv = fake_claude.argv_calls()[-1]
    assert argv[argv.index("--resume") + 1] == TERM and "--fork-session" not in argv


async def test_resume_moves_the_topic_into_the_sessions_directory(app, spy, fake_claude, tmp_path):
    await run(app, text_update("/status"))
    other = tmp_path / "work" / "other"
    other.mkdir()
    write_transcript(settings.CLAUDE_CONFIG_DIR, str(other), OTHER, ["в другом проекте"])
    await run(app, text_update(f"/resume {OTHER}"))
    assert (await app.topics.list_all())[0]["cwd"] == str(other.resolve())
    assert f"Директория: {other.resolve()}" in spy.last_text()


async def test_resume_keeps_the_directory_when_the_sessions_cwd_is_unusable(app, spy, fake_claude, tmp_path):
    await run(app, text_update("/status"))
    topic = (await app.topics.list_all())[0]
    write_transcript(settings.CLAUDE_CONFIG_DIR, "/nonexistent/host/path", OTHER, ["с хоста"])
    await run(app, text_update("/resume bbbbbbbb"))
    assert (await app.topics.list_all())[0]["cwd"] == topic["cwd"]
    assert spy.last_text().startswith("⚠️ Директория сессии /nonexistent/host/path недоступна")


async def test_resume_unknown_ambiguous_and_by_name(app, spy, fake_claude):
    await run(app, text_update("/status"))
    topic = (await app.topics.list_all())[0]
    await run(app, text_update("/resume"))
    assert spy.last_text().startswith("Какую? /resume")
    await run(app, text_update("/resume zzzz"))
    assert spy.last_text() == "Не нашла сессию «zzzz». /sessions покажет, что есть."
    write_transcript(settings.CLAUDE_CONFIG_DIR, topic["cwd"], TERM, ["a"], custom_title="Релиз")
    write_transcript(settings.CLAUDE_CONFIG_DIR, topic["cwd"], "aaaaaaaa-9999-4999-8999-999999999999", ["b"], custom_title="релиз")
    await run(app, text_update("/resume релиз"))
    assert spy.last_text().startswith("Под «релиз» подходят несколько сессий:") and "▸ aaaaaaaa · «Релиз»" in spy.last_text()
    assert str((await app.topics.list_all())[0]["session_id"]) == str(topic["session_id"])
    await run(app, text_update(f"/resume {TERM}"))
    assert str((await app.topics.list_all())[0]["session_id"]) == TERM


async def test_resume_button_on_the_sessions_card(app, spy, fake_claude):
    await run(app, text_update("/status"))
    topic = (await app.topics.list_all())[0]
    write_transcript(settings.CLAUDE_CONFIG_DIR, topic["cwd"], TERM, ["терминальная"])
    await run(app, callback_update("rs:1:aaaaaaaa"))
    assert spy.calls("AnswerCallbackQuery")[-1]["text"] == "Подключилась"
    assert str((await app.topics.list_all())[0]["session_id"]) == TERM


async def test_status_shows_the_session_title(app, spy, fake_claude):
    await run(app, text_update("/status"))
    topic = (await app.topics.list_all())[0]
    write_transcript(settings.CLAUDE_CONFIG_DIR, topic["cwd"], str(topic["session_id"]), ["починить тесты"])
    await run(app, text_update("/status"))
    assert f"Сессия       {topic['session_id']} · «починить тесты»" in spy.last_text()
