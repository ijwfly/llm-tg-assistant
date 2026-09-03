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


def button_texts(payload):
    return [b["text"] for row in payload["reply_markup"]["inline_keyboard"] for b in row]


async def test_sessions_card_lists_the_whole_machine_own_folder_first(app, spy, fake_claude, tmp_path):
    await run(app, text_update("/status"))
    topic = (await app.topics.list_all())[0]
    now = time.time()
    other = tmp_path / "work" / "other"
    other.mkdir()
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    write_transcript(settings.CLAUDE_CONFIG_DIR, topic["cwd"], str(topic["session_id"]), ["мой вопрос из темы"], mtime=now - 300)
    write_transcript(settings.CLAUDE_CONFIG_DIR, topic["cwd"], TERM, ["терминальная задача"], custom_title="Починить auth",
                     mtime=now - 600)
    write_transcript(settings.CLAUDE_CONFIG_DIR, str(other), OTHER, ["в другом проекте"], mtime=now - 30)
    write_transcript(settings.CLAUDE_CONFIG_DIR, str(outside), "dddddddd-4444-4444-8444-444444444444", ["вне корня"], mtime=now)
    await run(app, callback_update("sessions:1"))
    card = spy.calls("SendMessage")[-1]
    lines = card["text"].splitlines()
    assert lines[0] == f"Сессии Claude Code в {settings.WORK_ROOT}:"
    assert lines[1] == f"▸ . · {str(topic['session_id'])[:8]} · 5 мин назад · «мой вопрос из темы» · эта тема"
    assert lines[2] == "▸ . · aaaaaaaa · 10 мин назад · «Починить auth»"
    assert lines[3] == "▸ other · bbbbbbbb · только что · «в другом проекте»"
    assert lines[4] == f"ещё 1 вне {settings.WORK_ROOT} — бот туда не ходит"
    assert buttons(card) == [f"rs:1:{str(topic['session_id'])[:8]}", "rs:1:aaaaaaaa", "ns:1:bbbbbbbb", "hide:1"]
    assert button_texts(card) == [f"Продолжить здесь {str(topic['session_id'])[:8]}", "Продолжить здесь aaaaaaaa",
                                  "Новая тема bbbbbbbb", "Скрыть"]


async def test_sessions_card_pages_through_the_machine(app, spy, fake_claude, tmp_path):
    await run(app, text_update("/status"))
    topic = (await app.topics.list_all())[0]
    size = settings.SESSIONS_PAGE_SIZE
    now = time.time()
    other = tmp_path / "work" / "other"
    other.mkdir()
    for i in range(size + 2):                 # newest first: s00 is the newest, s09 the oldest
        write_transcript(settings.CLAUDE_CONFIG_DIR, str(other), f"{i:02d}aaaaaa-1111-4111-8111-111111111111",
                         [f"задача {i}"], mtime=now - i * 60)
    await run(app, callback_update("sessions:1"))
    card = spy.calls("SendMessage")[-1]
    lines = card["text"].splitlines()
    assert lines[0] == f"Сессии Claude Code в {settings.WORK_ROOT} · стр. 1/2:"
    assert len(lines) == size + 1 and "«задача 0»" in lines[1] and f"«задача {size - 1}»" in lines[-1]
    assert buttons(card)[-2:] == ["sp:1:1", "hide:1"] and button_texts(card)[-2] == "Дальше"
    await run(app, callback_update("sp:1:1", message_id=777))
    edit = spy.calls("EditMessageText")[-1]
    assert edit["message_id"] == 777
    lines = edit["text"].splitlines()
    assert lines[0] == f"Сессии Claude Code в {settings.WORK_ROOT} · стр. 2/2:"
    assert [l.split("«")[1] for l in lines[1:]] == [f"задача {size}»", f"задача {size + 1}»"]
    assert buttons(edit)[-2:] == ["sp:1:0", "hide:1"] and button_texts(edit)[-2] == "Назад"
    await run(app, callback_update("sp:1:0", message_id=777))
    assert spy.calls("EditMessageText")[-1]["text"].splitlines()[0].endswith("стр. 1/2:")


async def test_new_topic_button_creates_a_topic_bound_to_the_sessions_folder(app, spy, fake_claude, tmp_path):
    await run(app, text_update("/status"))
    other = tmp_path / "work" / "other"
    other.mkdir()
    write_transcript(settings.CLAUDE_CONFIG_DIR, str(other), OTHER, ["в другом проекте"], custom_title="Релиз 2.0")
    await run(app, callback_update("ns:1:bbbbbbbb"))
    assert spy.calls("CreateForumTopic")[-1]["name"] == "other"           # topics are named after their folder
    new = next(t for t in await app.topics.list_all() if t["thread_id"] == 100)
    assert new["cwd"] == str(other.resolve()) and str(new["session_id"]) == OTHER and new["session_resumable"] is True
    assert new["settings"]["title_implicit"] is True
    hello = next(p for p in spy.calls("SendMessage") if p["text"].startswith("Продолжаю сессию bbbbbbbb"))
    assert hello["message_thread_id"] == 100 and f"Папка: {other.resolve()}" in hello["text"]
    fake_claude.text_turn(LONG)
    await feed(app, text_update("что мы делали?", thread_id=100, topic_name="other: Релиз 2.0"))
    await wait_for_text(spy, LONG.strip())
    argv = fake_claude.argv_calls()[-1]
    assert argv[argv.index("--resume") + 1] == OTHER and fake_claude.cwds()[-1] == str(other.resolve())


async def test_past_session_of_the_topic_is_labelled(app, spy, fake_claude):
    await run(app, text_update("/status"))
    old = str((await app.topics.list_all())[0]["session_id"])
    topic = (await app.topics.list_all())[0]
    write_transcript(settings.CLAUDE_CONFIG_DIR, topic["cwd"], old, ["первая жизнь темы"])
    await run(app, text_update("/new"))
    assert (await app.topics.list_all())[0]["settings"]["past_sessions"] == [old]
    await run(app, callback_update("sessions:1"))
    assert f"▸ . · {old[:8]} · только что · «первая жизнь темы» · эта тема, раньше" in spy.last_text()


async def test_sessions_card_when_empty(app, spy, fake_claude):
    await run(app, text_update("/status"))
    await run(app, callback_update("sessions:1"))
    assert spy.last_text() == f"Внутри {settings.WORK_ROOT} сессий Claude Code пока нет."


async def test_resume_by_prefix_switches_the_topic_and_resumes_on_the_next_turn(app, spy, fake_claude):
    await run(app, text_update("/status"))
    topic = (await app.topics.list_all())[0]
    write_transcript(settings.CLAUDE_CONFIG_DIR, topic["cwd"], TERM, ["терминальная задача"])
    await run(app, callback_update("rs:1:aaaaaaaa"))
    assert spy.last_text() == f"🔗 Подключилась к сессии aaaaaaaa · «терминальная задача»\nДиректория: {topic['cwd']}"
    updated = (await app.topics.list_all())[0]
    assert str(updated["session_id"]) == TERM and updated["session_resumable"] is True
    fake_claude.text_turn(LONG)
    await feed(app, text_update("что мы делали?"))
    await wait_for_text(spy, LONG.strip())
    argv = fake_claude.argv_calls()[-1]
    assert argv[argv.index("--resume") + 1] == TERM and "--fork-session" not in argv


async def test_folder_named_topic_follows_a_resume_into_another_folder(app, spy, fake_claude, tmp_path):
    await run(app, text_update("/status", thread_id=5, topic_name="Тема 1"))
    await app.store.topics.update_settings(1, title_implicit=True)          # never named by the user
    other = tmp_path / "work" / "other"
    other.mkdir()
    write_transcript(settings.CLAUDE_CONFIG_DIR, str(other), OTHER, ["в другом проекте"])
    await run(app, callback_update("rs:1:bbbbbbbb"))
    edit = spy.calls("EditForumTopic")[-1]
    assert edit["name"] == "other" and (await app.topics.list_all())[0]["title"] == "other"
    await run(app, text_update("/rename Моё имя", thread_id=5, topic_name="other"))
    write_transcript(settings.CLAUDE_CONFIG_DIR, str(tmp_path / "work"), TERM, ["в корне"])
    await run(app, callback_update("rs:1:aaaaaaaa"))
    assert (await app.topics.list_all())[0]["title"] == "Моё имя"         # an explicit name is pinned


async def test_resume_moves_the_topic_into_the_sessions_directory(app, spy, fake_claude, tmp_path):
    await run(app, text_update("/status"))
    other = tmp_path / "work" / "other"
    other.mkdir()
    write_transcript(settings.CLAUDE_CONFIG_DIR, str(other), OTHER, ["в другом проекте"])
    await run(app, callback_update("rs:1:bbbbbbbb"))
    assert (await app.topics.list_all())[0]["cwd"] == str(other.resolve())
    assert f"Директория: {other.resolve()}" in spy.last_text()


async def test_resume_keeps_the_directory_when_the_sessions_cwd_is_unusable(app, spy, fake_claude, tmp_path):
    await run(app, text_update("/status"))
    topic = (await app.topics.list_all())[0]
    write_transcript(settings.CLAUDE_CONFIG_DIR, "/nonexistent/host/path", OTHER, ["с хоста"])
    await run(app, callback_update("rs:1:bbbbbbbb"))
    assert (await app.topics.list_all())[0]["cwd"] == topic["cwd"]
    assert spy.last_text().startswith("⚠️ Директория сессии /nonexistent/host/path недоступна")


async def test_resume_of_an_unknown_session_explains(app, spy, fake_claude):
    await run(app, text_update("/status"))
    await run(app, callback_update("rs:1:zzzzzzzz"))
    assert spy.last_text() == "Не нашла сессию «zzzzzzzz». /sessions покажет, что есть."
    assert spy.calls("AnswerCallbackQuery")[-1]["text"].startswith("Не нашла")


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
