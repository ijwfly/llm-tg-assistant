import asyncio
import json
from pathlib import Path

import settings
from tests.support import fake_claude as fc
from tests.support.helpers import feed, run, wait_for_text, wait_outbox_idle, wait_turn_finished
from tests.support.updates import edited_update, message_update, text_update, user

LONG = "Готово, вот ответ на всё, что ты прислал, достаточно длинный, чтобы уйти сразу одним сообщением. " * 2


def stdin_contents(fake):
    """Content blocks of every user message the fake claude received."""
    out = []
    for rec in fake.log():
        msg = rec.get("stdin")
        if msg:
            c = msg["message"]["content"]
            out.append(c if isinstance(c, list) else [{"type": "text", "text": c}])
    return out


async def wait_staged(app, n, timeout=2.0):
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if await app.db.fetchval("SELECT count(*) FROM staging_items") == n:
            await wait_outbox_idle(app)
            return
        await asyncio.sleep(0.02)
    raise AssertionError("staging count never reached %s" % n)


async def test_album_with_caption_is_one_turn_with_two_images(app, spy, fake_claude, session):
    session.files["p1"] = b"\xff\xd8photo-one"
    session.files["p2"] = b"\xff\xd8photo-two"
    fake_claude.text_turn(LONG)
    await feed(app, message_update(photo_id="p1", caption="что на картинках?", media_group_id="g1"))
    await feed(app, message_update(photo_id="p2", media_group_id="g1"))
    await wait_for_text(spy, LONG.strip())
    contents = stdin_contents(fake_claude)
    assert len(contents) == 1
    blocks = contents[0]
    assert [b["type"] for b in blocks] == ["text", "image", "text", "image"]
    assert "[фото сохранено:" in blocks[0]["text"] and "что на картинках?" in blocks[0]["text"]
    assert blocks[1]["source"]["media_type"] == "image/jpeg"
    files = await app.inbox.list_recent(1)
    assert len(files) == 2 and all(Path(f["path"]).exists() for f in files)
    assert Path(files[-1]["path"]).read_bytes() == b"\xff\xd8photo-one"


async def test_text_photo_and_voice_within_the_window_form_one_turn_in_order(app, spy, fake_claude):
    fake_claude.text_turn(LONG)
    await feed(app, message_update(text="сначала текст"))
    await feed(app, message_update(photo_id="p9"))
    await feed(app, message_update(voice_id="v9"))
    await wait_for_text(spy, LONG.strip())
    blocks = stdin_contents(fake_claude)[0]
    texts = [b["text"] for b in blocks if b["type"] == "text"]
    # strictly in Telegram order (message ids)
    assert texts[0].startswith("сначала текст")
    assert "[фото сохранено:" in texts[0]
    assert "[голосовое:" in texts[-1]   # no TRANSCRIBE_CMD -> path only
    assert len(fake_claude.stdin_texts()) == 1


async def test_forward_without_question_is_staged_and_reacted(app, spy, fake_claude):
    author = user(77)
    author = author.model_copy(update={"first_name": "Иван", "last_name": "Петров", "username": "ivan"})
    await feed(app, message_update(text="встречаемся в пятницу", forward_from=author))
    await wait_staged(app, 1)
    assert spy.sent_texts() == []
    reaction = spy.calls("SetMessageReaction")[-1]
    assert reaction["reaction"][0]["emoji"] == "👀"
    assert fake_claude.stdin_texts() == []
    fake_claude.text_turn(LONG)
    await feed(app, text_update("что он имел в виду?"))
    await wait_for_text(spy, LONG.strip())
    assert fake_claude.stdin_texts() == ["[переслано от Иван Петров (@ivan)]\nвстречаемся в пятницу\n\nчто он имел в виду?"]
    assert await app.db.fetchval("SELECT count(*) FROM staging_items") == 0


async def test_forward_from_channel_gets_chat_attribution(app, spy, fake_claude):
    await feed(app, message_update(text="новости", forward_channel="Дайджест"))
    await wait_staged(app, 1)
    fake_claude.text_turn(LONG)
    await feed(app, text_update("перескажи"))
    await wait_for_text(spy, LONG.strip())
    assert fake_claude.stdin_texts()[0].startswith('[переслано от Chat name "Дайджест"]\nновости')


async def test_forward_as_prompt_setting_makes_forwards_ordinary_messages(app, spy, fake_claude):
    await app.store.users.upsert(1, "Test User", "tester")
    await app.store.users.update_settings(1, forward_as_prompt=True)
    fake_claude.text_turn(LONG)
    await feed(app, message_update(text="пересланный вопрос", forward_from=user(77)))
    await wait_for_text(spy, LONG.strip())
    assert fake_claude.stdin_texts() == ["пересланный вопрос"]


async def test_document_without_caption_is_staged_and_with_caption_is_a_prompt(app, spy, fake_claude, session):
    session.files["d1"] = b"col,val\n1,2\n"
    await feed(app, message_update(document=("d1", "data (1).csv", 12)))
    await wait_staged(app, 1)
    files = await app.inbox.list_recent(1)
    assert files[0]["path"].endswith("data__1_.csv")
    fake_claude.text_turn(LONG)
    await feed(app, message_update(document=("d2", "notes.txt", 5), caption="сделай выжимку"))
    await wait_for_text(spy, LONG.strip())
    text = fake_claude.stdin_texts()[0]
    assert text.startswith("[файл ") and ".csv" in text
    assert "[файл notes.txt: " in text and text.endswith("сделай выжимку")


async def test_voice_is_transcribed_and_echoed(app, spy, fake_claude, session):
    settings.TRANSCRIBE_CMD = "cat {file}"
    session.files["v1"] = "распознанный текст вопроса".encode()
    fake_claude.text_turn(LONG)
    await feed(app, message_update(voice_id="v1"))
    await wait_for_text(spy, "🎤 _распознанный текст вопроса_")
    echo = spy.calls("SendRichMessage")[0]
    assert echo["reply_parameters"]["message_id"] is not None
    await wait_for_text(spy, LONG.strip())
    assert fake_claude.stdin_texts() == ["распознанный текст вопроса"]


async def test_voice_as_prompt_off_stages_the_transcript(app, spy, fake_claude, session):
    settings.TRANSCRIBE_CMD = "cat {file}"
    session.files["v2"] = "надиктовал в контекст".encode()
    await app.store.users.upsert(1, "Test User", "tester")
    await app.store.users.update_settings(1, voice_as_prompt=False)
    await feed(app, message_update(voice_id="v2"))
    await wait_staged(app, 1)
    assert fake_claude.stdin_texts() == []
    fake_claude.text_turn(LONG)
    await feed(app, text_update("что я сказал?"))
    await wait_for_text(spy, LONG.strip())
    assert fake_claude.stdin_texts() == ["надиктовал в контекст\n\nчто я сказал?"]


async def test_failed_transcription_falls_back_to_the_path(app, spy, fake_claude, session):
    settings.TRANSCRIBE_CMD = "exit 1"
    fake_claude.text_turn(LONG)
    await feed(app, message_update(voice_id="v3"))
    await wait_for_text(spy, LONG.strip())
    assert fake_claude.stdin_texts()[0].startswith("[голосовое: ")


async def test_edited_message_becomes_a_new_turn_with_a_marker(app, spy, fake_claude):
    fake_claude.text_turn(LONG)
    fake_claude.text_turn("Второй ответ на правку, тоже достаточно длинный, чтобы уйти сразу, без ожидания. " * 2)
    await feed(app, message_update(text="сделай A", message_id=300))
    await wait_for_text(spy, LONG.strip())
    await wait_turn_finished(app)
    await feed(app, edited_update("сделай B", message_id=300))
    await wait_for_text(spy, "✏️ Вижу правку — отвечаю на неё.")
    await wait_for_text(spy, "Второй ответ на правку")
    assert fake_claude.stdin_texts()[-1] == "[правка предыдущего сообщения]\nсделай B"


async def test_too_big_file_is_skipped_but_the_question_goes(app, spy, fake_claude):
    fake_claude.text_turn(LONG)
    await feed(app, message_update(document=("big", "huge.bin", 30 * 1024 * 1024), caption="что это?"))
    await wait_for_text(spy, "⚠️ Файл больше 20 МБ")
    await wait_for_text(spy, LONG.strip())
    assert fake_claude.stdin_texts() == ["что это?"]
    assert spy.calls("GetFile") == []


async def test_new_clears_staging_and_card_shows_it(app, spy, fake_claude):
    await feed(app, message_update(text="раз", forward_from=user(5)))
    await feed(app, message_update(text="два", forward_from=user(5)))
    await wait_staged(app, 2)
    await run(app, text_update("/status"))
    spy.assert_shown_text_contains("Staging      2")
    await run(app, text_update("/new"))
    assert await app.db.fetchval("SELECT count(*) FROM staging_items") == 0


async def test_files_lists_recent_inbox_files(app, spy, fake_claude):
    await run(app, text_update("/files"))
    assert spy.last_text() == "В этой теме файлов пока нет."
    await feed(app, message_update(document=("d7", "report.pdf", 10)))
    await wait_staged(app, 1)
    await run(app, text_update("/files"))
    assert "document:" in spy.last_text() and spy.last_text().endswith("report.pdf")


async def test_inbox_cleanup_removes_old_files(app, fake_claude):
    await feed(app, message_update(document=("d8", "old.txt", 3)))
    await wait_staged(app, 1)
    row = (await app.inbox.list_recent(1))[0]
    assert Path(row["path"]).exists()
    assert await app.inbox.cleanup() == 0
    await app.store.inbox.touch_created(row["id"], 0)
    assert await app.inbox.cleanup() == 1
    assert not Path(row["path"]).exists() and await app.inbox.list_recent(1) == []


async def test_reply_quote_uses_the_batch_anchor(app, spy, fake_claude):
    from tests.support.updates import message
    from datetime import datetime, timezone
    from aiogram.types import Message, User
    from tests.support.updates import chat
    bot_msg = Message(message_id=77, date=datetime.now(timezone.utc), chat=chat(1),
                      from_user=User(id=app.bot.id, is_bot=True, first_name="bot"), text="Мой ответ")
    fake_claude.text_turn(LONG)
    await feed(app, message_update(text="а это?", reply_to=bot_msg))
    await feed(app, message_update(text="и вот это"))
    await wait_for_text(spy, LONG.strip())
    assert fake_claude.stdin_texts() == ["[в ответ на твой ответ: «Мой ответ»]\n\nа это?\n\nи вот это"]


async def test_batch_keeps_telegram_message_order(app, spy, fake_claude):
    """A forward's comment arrives first and stays first: message ids are the source of truth."""
    fake_claude.text_turn(LONG)
    await feed(app, message_update(text="о чём это?"))
    await feed(app, message_update(text="первое", forward_from=user(5)))
    await feed(app, message_update(text="второе", forward_from=user(5)))
    await wait_for_text(spy, LONG.strip())
    text = fake_claude.stdin_texts()[0]
    assert text.startswith("о чём это?") and text.index("первое") < text.index("второе")
