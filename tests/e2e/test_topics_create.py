from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import CreateForumTopic

import settings
from tests.support import fake_claude as fc
from tests.support.fake_claude import write_transcript
from tests.support.helpers import feed, run, wait_for_text, wait_turn_finished
from tests.support.updates import callback_update, text_update

LONG = "Помню контекст исходной сессии и продолжаю работу в ветке, вот достаточно длинный ответ на вопрос. " * 2
LONG2 = "Второй ответ в ветке, форк уже случился и процесс работает с новым идентификатором сессии, длинно. " * 2
LONG3 = "Третий ответ после перезапуска процесса ветки: резюм по новому id без повторного форка, длинно. " * 2
TERM = "aaaaaaaa-1111-4111-8111-111111111111"


async def test_branch_creates_a_topic_that_forks_the_session_once(app, spy, fake_claude):
    fake_claude.text_turn(LONG)
    await feed(app, text_update("первый ход", thread_id=5, topic_name="Проект"))
    await wait_turn_finished(app)
    source = (await app.topics.list_all())[0]
    await run(app, callback_update("branch:1"))
    created = spy.calls("CreateForumTopic")[-1]
    assert created["chat_id"] == 1 and created["name"] == "Проект · ветка" and created["icon_color"] in (0x6FB9F0, 0xFFD67E, 0xCB86DB, 0x8EEE98, 0xFF93B2, 0xFB6F5F)
    new = next(t for t in await app.topics.list_all() if t["id"] != source["id"])
    assert new["thread_id"] == 100 and new["title"] == "Проект · ветка" and new["cwd"] == source["cwd"]
    assert str(new["session_id"]) == str(source["session_id"]) and new["session_resumable"] is True
    assert new["settings"]["fork"] == {"from": str(source["session_id"])}
    assert "🌿 Ветка «Проект · ветка» открыта." in spy.sent_texts()
    assert spy.calls("AnswerCallbackQuery")[-1]["text"] == "Ветка открыта"
    hello = next(p for p in spy.calls("SendMessage") if p["text"].startswith("🌿 Продолжаю"))
    assert hello["message_thread_id"] == 100
    assert app.runtimes.peek(source["id"]).proc is None    # the source process was stopped to flush the transcript
    # the first turn in the branch forks; the CLI reports a new session id which the topic adopts
    new_id = "cccccccc-3333-4333-8333-333333333333"
    fake_claude.enqueue(fc.assistant_text(LONG2), fc.result(session_id=new_id))
    await feed(app, text_update("что мы делали?", thread_id=100, topic_name="Проект · ветка"))
    await wait_for_text(spy, LONG2.strip())
    await wait_turn_finished(app, after=1)
    argv = fake_claude.argv_calls()[-1]
    assert argv[argv.index("--resume") + 1] == str(source["session_id"]) and "--fork-session" in argv
    assert "--name" not in argv
    branch = await app.store.topics.get_by_id(new["id"])
    assert str(branch["session_id"]) == new_id and "fork" not in branch["settings"]
    await app.runtimes.get(branch).stop_process()
    fake_claude.text_turn(LONG3)
    await feed(app, text_update("ещё", thread_id=100, topic_name="Проект · ветка"))
    await wait_for_text(spy, LONG3.strip(), timeout=5)
    argv = fake_claude.argv_calls()[-1]
    assert argv[argv.index("--resume") + 1] == new_id and "--fork-session" not in argv


async def test_branch_callback_with_a_session_id_forks_a_terminal_session(app, spy, fake_claude):
    await run(app, text_update("/status"))
    topic = (await app.topics.list_all())[0]
    write_transcript(settings.CLAUDE_CONFIG_DIR, topic["cwd"], TERM, ["терминальная"], custom_title="Релиз")
    await run(app, callback_update("br:1:aaaaaaaa"))
    assert spy.calls("AnswerCallbackQuery")[-1]["text"] == "Ветка открыта"
    new = next(t for t in await app.topics.list_all() if t["id"] != topic["id"])
    assert str(new["session_id"]) == TERM and new["settings"]["fork"] == {"from": TERM}
    assert new["title"] == "aaaaaaaa · ветка"
    source = await app.store.topics.get_by_id(topic["id"])
    assert str(source["session_id"]) == str(topic["session_id"])   # the source topic is untouched


async def test_project_creates_a_topic_for_an_alias_and_a_path(app, spy, fake_claude, tmp_path):
    (tmp_path / "work" / "infra").mkdir()
    (tmp_path / "work" / "web app").mkdir()
    settings.PROJECTS = {"infra": str(tmp_path / "work" / "infra")}
    await run(app, text_update("/project infra"))
    assert spy.calls("CreateForumTopic")[-1]["name"] == "infra"
    assert "✅ Тема «infra» открыта." in spy.sent_texts()
    hello = next(p for p in spy.calls("SendMessage") if p["text"].startswith("📁"))
    assert hello["message_thread_id"] == 100 and hello["text"].endswith("Тема готова, контекст чистый. Пиши сюда.")
    infra = next(t for t in await app.topics.list_all() if t["thread_id"] == 100)
    assert infra["cwd"] == str((tmp_path / "work" / "infra").resolve()) and infra["session_resumable"] is False
    await run(app, text_update(f"/project {tmp_path / 'work' / 'web app'}"))
    assert spy.calls("CreateForumTopic")[-1]["name"] == "web app"
    fake_claude.text_turn(LONG)
    await feed(app, text_update("что тут?", thread_id=100, topic_name="infra"))
    await wait_for_text(spy, LONG.strip())
    assert fake_claude.cwds()[-1] == infra["cwd"]


async def test_project_new_creates_folder_session_and_topic(app, spy, fake_claude, tmp_path):
    await run(app, text_update("/project new demo-app"))
    path = (tmp_path / "work" / "demo-app").resolve()
    assert path.is_dir()
    assert f"📁 Создала папку {path}." in spy.sent_texts() and "✅ Тема «demo-app» открыта." in spy.sent_texts()
    assert spy.calls("CreateForumTopic")[-1]["name"] == "demo-app"
    new = next(t for t in await app.topics.list_all() if t["thread_id"] == 100)
    assert new["cwd"] == str(path) and new["session_resumable"] is False
    fake_claude.text_turn(LONG)
    await feed(app, text_update("создай README", thread_id=100, topic_name="demo-app"))
    await wait_for_text(spy, LONG.strip())
    assert fake_claude.cwds()[-1] == str(path)
    argv = fake_claude.argv_calls()[-1]
    assert argv[argv.index("--session-id") + 1] == str(new["session_id"])
    await run(app, text_update("/project new demo-app"))               # existing folder: just a topic
    assert not spy.last_text().startswith("📁 Создала") and spy.calls("CreateForumTopic")[-1]["name"] == "demo-app"


async def test_project_new_rejects_bad_names_and_explains_usage(app, spy, fake_claude, tmp_path):
    settings.NEW_PROJECTS_DIR = str(tmp_path / "work" / "projects")
    await run(app, text_update("/project new"))
    assert spy.last_text() == f"Как назвать? /project new <имя> создаст папку в {(tmp_path / 'work' / 'projects').resolve()}."
    await run(app, text_update("/project new ../evil"))
    assert spy.last_text().startswith("Имя папки — одно слово")
    assert spy.calls("CreateForumTopic") == []
    await run(app, text_update("/project new ok"))
    assert (tmp_path / "work" / "projects" / "ok").is_dir()


async def test_project_usage_bad_path_and_telegram_refusal(app, spy, fake_claude, tmp_path):
    settings.PROJECTS = {"app": "/work/app"}
    await run(app, text_update("/project"))
    assert spy.last_text().startswith("Куда? /project") and "/project new <имя>" in spy.last_text() and "/go app — /work/app" in spy.last_text()
    await run(app, text_update("/project /nope"))
    assert spy.last_text().startswith("⚠️ нет такой директории")
    (tmp_path / "work" / "x").mkdir()
    app.bot.session.fail_next("CreateForumTopic", TelegramBadRequest(method=CreateForumTopic(chat_id=1, name="x"),
                                                                     message="Bad Request: the chat is not a forum"))
    await run(app, text_update(f"/project {tmp_path / 'work' / 'x'}"))
    assert spy.last_text().startswith("⚠️ Не могу создать тему: Bad Request: the chat is not a forum")
    assert len(await app.topics.list_all()) == 1
