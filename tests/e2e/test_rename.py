from datetime import datetime, timezone

from aiogram.types import ForumTopicCreated, Message, Update

from tests.support import fake_claude as fc
from tests.support.helpers import feed, run, wait_for_text, wait_outbox_idle, wait_turn_finished
from tests.support.updates import chat, message, text_update

LONG = "Вот ответ на первый вопрос в новой теме, достаточно длинный, чтобы уйти сразу одним сообщением. " * 2


def implicit_topic_update(text: str, thread_id: int = 7) -> Update:
    created = Message(message_id=thread_id, date=datetime.now(timezone.utc), chat=chat(1),
                      forum_topic_created=ForumTopicCreated(name="Тема 1", icon_color=0x6FB9F0, is_name_implicit=True))
    msg = message(text, thread_id=thread_id, is_topic=True, reply_to=created)
    return Update(update_id=90000 + thread_id + hash(text) % 1000, message=msg)


async def test_rename_updates_the_thread_the_db_and_the_session_quietly(app, spy, fake_claude):
    fake_claude.text_turn(LONG)
    await feed(app, text_update("привет", thread_id=5, topic_name="Проект"))
    await wait_turn_finished(app)
    fake_claude.enqueue(fc.result())                     # /rename in Claude Code answers with no text
    await feed(app, text_update("/rename Новое имя", thread_id=5, topic_name="Проект"))
    await wait_for_text(spy, "✏️ Новое имя")
    await wait_turn_finished(app, after=1)
    edit = spy.calls("EditForumTopic")[-1]
    assert edit["message_thread_id"] == 5 and edit["name"] == "Новое имя"
    assert (await app.topics.list_all())[0]["title"] == "Новое имя"
    assert fake_claude.stdin_texts()[-1] == "/rename Новое имя"
    assert "✔️ Готово — в ответе не было ни слова текста." not in spy.sent_texts()


async def test_rename_without_a_name_explains(app, spy, fake_claude):
    await run(app, text_update("/rename"))
    assert spy.last_text() == "Как назвать? /rename <имя>."


async def test_implicit_topic_is_named_after_its_folder_at_once(app, spy, fake_claude):
    fake_claude.text_turn(LONG)
    await feed(app, implicit_topic_update("Разберись, почему падает тест авторизации в CI и почини"))
    await wait_turn_finished(app)
    edit = spy.calls("EditForumTopic")[-1]
    assert edit["message_thread_id"] == 7 and edit["name"] == "work"          # basename of DEFAULT_CWD
    topic = (await app.topics.list_all())[0]
    assert topic["title"] == "work" and topic["settings"]["title_implicit"] is True   # still follows the folder
    assert fake_claude.stdin_texts() == ["Разберись, почему падает тест авторизации в CI и почини"]   # no /rename turn
    fake_claude.text_turn("Второй ответ, тоже достаточно длинный, чтобы уйти сразу и не ждать следующего сегмента текста. " * 2)
    await feed(app, implicit_topic_update("второй вопрос"))
    await wait_turn_finished(app, after=1)
    assert len(spy.calls("EditForumTopic")) == 1


async def test_explicit_topic_name_is_kept(app, spy, fake_claude):
    fake_claude.text_turn(LONG)
    await feed(app, text_update("вопрос", thread_id=5, topic_name="Моя тема"))
    await wait_turn_finished(app)
    assert spy.calls("EditForumTopic") == []
    assert (await app.topics.list_all())[0]["title"] == "Моя тема"
