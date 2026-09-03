import asyncio
from pathlib import Path

import settings
from tests.support import fake_claude as fc
from tests.support.helpers import feed, run, wait_for_text, wait_turn_finished
from tests.support.updates import callback_update, text_update


async def set_voice(app, on: bool):
    """Flip the topic's «Голосом» switch on the card until it matches `on`."""
    await run(app, text_update("/status"))
    topic = (await app.topics.list_all())[0]
    if bool((topic.get("settings") or {}).get("voice")) != on:
        await run(app, callback_update("tgl:1:voice", message_id=500))

LONG = ("Правка готова: тест авторизации снова зелёный, а фикстура таймзоны теперь честно использует UTC. "
        "Дальше можно заняться остальными тестами.\n\n```python\nprint('secret code')\n```")


async def wait_voice(spy, timeout=3.0):
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        calls = spy.calls("SendVoice")
        if calls:
            return calls[-1]
        await asyncio.sleep(0.02)
    raise AssertionError("no voice sent")


async def test_voice_on_sends_prose_after_the_text(app, spy, fake_claude, tmp_path):
    settings.TTS_CMD = "cp {text_file} {out}"     # the "synth" copies the prose so the test can read it
    await set_voice(app, True)
    assert (await app.topics.list_all())[0]["settings"]["voice"] is True
    fake_claude.text_turn(LONG)
    await feed(app, text_update("почини"))
    await wait_for_text(spy, "Правка готова")
    voice = await wait_voice(spy)
    await wait_turn_finished(app)
    path = Path(voice["voice"])
    assert path.name == "voice-1.ogg" and voice["chat_id"] == 1
    spoken = path.read_text()
    assert spoken.startswith("Правка готова") and "secret code" not in spoken
    texts = spy.sent_texts()
    assert texts.index(next(t for t in texts if t.startswith("Правка готова"))) < len(texts)
    order = [n for n, _ in spy.session.calls if n in ("SendRichMessage", "SendVoice")]
    assert order == ["SendRichMessage", "SendVoice"]


async def test_voice_off_and_no_text_no_voice(app, spy, fake_claude):
    settings.TTS_CMD = "cp {text_file} {out}"
    await set_voice(app, True)
    await set_voice(app, False)
    assert (await app.topics.list_all())[0]["settings"]["voice"] is False
    fake_claude.text_turn(LONG)
    await feed(app, text_update("почини"))
    await wait_turn_finished(app)
    assert spy.calls("SendVoice") == []
    await set_voice(app, True)
    fake_claude.enqueue(fc.result())      # a turn without text
    await feed(app, text_update("тихо"))
    await wait_for_text(spy, "✔️ Готово")
    await wait_turn_finished(app, after=1)
    assert spy.calls("SendVoice") == []


async def test_failed_tts_is_silent(app, spy, fake_claude):
    settings.TTS_CMD = "exit 3"
    await set_voice(app, True)
    fake_claude.text_turn(LONG)
    await feed(app, text_update("почини"))
    turn = await wait_turn_finished(app)
    assert turn["status"] == "done" and spy.calls("SendVoice") == []
