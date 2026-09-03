import settings
from tests.support import fake_claude as fc
from tests.support.helpers import feed, run, wait_for_text, wait_turn_finished
from tests.support.updates import callback_update, text_update

LONG = "Сделал файл, вот подробности, достаточно длинные, чтобы ответ ушёл в чат сразу одним сообщением. " * 2


def labels(payload):
    return [b["text"] for row in payload["reply_markup"]["inline_keyboard"] for b in row]


def buttons(payload):
    return [b["callback_data"] for row in payload["reply_markup"]["inline_keyboard"] for b in row]


async def test_checkpoints_are_recorded_and_rewind_runs_a_standalone_claude(app, spy, fake_claude):
    settings.FILE_CHECKPOINTING = True
    fake_claude.text_turn(LONG)
    await feed(app, text_update("создай файл a.txt с ONE"))
    await wait_turn_finished(app)
    fake_claude.text_turn(LONG + " два")
    await feed(app, text_update("перепиши a.txt на TWO"))
    await wait_turn_finished(app, after=1)
    uuids = fake_claude.user_uuids()
    rows = await app.db.fetch("SELECT id, checkpoint_uuid FROM turns ORDER BY id")
    assert [r["checkpoint_uuid"] for r in rows] == uuids and len(uuids) == 2
    await run(app, text_update("/status"))
    await run(app, callback_update("page:1:more", message_id=500))
    assert "Откатить файлы" in labels(spy.calls("EditMessageText")[-1])
    await run(app, callback_update("rwl:1"))
    card = spy.calls("SendMessage")[-1]
    assert card["text"].startswith("Откатить файлы к состоянию")
    assert labels(card) == ["До: «перепиши a.txt на TWO»", "До: «создай файл a.txt с ONE»", "Скрыть"]
    assert buttons(card)[:2] == ["rw:1:2", "rw:1:1"]
    await run(app, callback_update("rw:1:2", message_id=600))
    edit = spy.calls("EditMessageText")[-1]
    assert edit["message_id"] == 600 and edit["text"].startswith("Откатить файлы к моменту «перепиши a.txt на TWO»?")
    assert labels(edit) == ["Да, откатить", "Отмена"]
    await run(app, callback_update("rwc:1:2", message_id=600))
    rewinds = fake_claude.rewinds()
    session_id = str((await app.topics.list_all())[0]["session_id"])
    assert rewinds == [{"rewind": uuids[1], "resume": session_id}]
    done = spy.calls("EditMessageText")[-1]
    assert done["text"] == f"⏪ Files rewound to state at message {uuids[1]}"
    assert spy.calls("AnswerCallbackQuery")[-1]["text"] == "Файлы откачены"
    assert app.runtimes.peek(1).proc is None            # the topic's process was stopped for the standalone run
    env = [rec for rec in fake_claude.log() if "argv" in rec][-1]["env"]
    assert env.get("CLAUDE_CODE_ENABLE_SDK_FILE_CHECKPOINTING") == "true"


async def test_rewind_button_hidden_and_list_empty_without_checkpointing(app, spy, fake_claude):
    fake_claude.text_turn(LONG)
    await feed(app, text_update("привет"))
    await wait_turn_finished(app)
    await run(app, text_update("/status"))
    await run(app, callback_update("page:1:more", message_id=500))
    assert "Откатить файлы" not in labels(spy.calls("EditMessageText")[-1])
    assert (await app.db.fetchrow("SELECT checkpoint_uuid FROM turns"))["checkpoint_uuid"] is not None   # recorded anyway
    env = [rec for rec in fake_claude.log() if "argv" in rec][-1]["env"]
    assert "CLAUDE_CODE_ENABLE_SDK_FILE_CHECKPOINTING" not in env
    await run(app, callback_update("rwl:1"))
    assert labels(spy.calls("SendMessage")[-1])[0].startswith("До:")     # the list itself still works
    await run(app, callback_update("rwc:1:999"))
    assert spy.calls("AnswerCallbackQuery")[-1]["text"] == "Уже неактуально"
