from pathlib import Path

import settings
from tests.support import fake_claude as fc
from tests.support.helpers import feed, run, wait_for_text, wait_turn_finished
from tests.support.updates import callback_update, text_update

LONG = "Ответ достаточно длинный, чтобы уйти в чат сразу одним сообщением без ожидания следующего сегмента текста. " * 2


def buttons(payload):
    return [b["callback_data"] for row in payload["reply_markup"]["inline_keyboard"] for b in row]


def labels(payload):
    return [b["text"] for row in payload["reply_markup"]["inline_keyboard"] for b in row]


def argv_value(argv, flag):
    return argv[argv.index(flag) + 1] if flag in argv else None


async def test_card_switches_cycle_and_redraw_in_place(app, spy, fake_claude):
    await run(app, text_update("/status"))
    card = spy.calls("SendMessage")[-1]
    assert labels(card)[2:5] == ["Права: prompt", "Модель: по умолчанию", "Усилие: по умолчанию"]
    assert "cyc:1:perm" in buttons(card) and "page:1:more" in buttons(card)
    await run(app, callback_update("cyc:1:perm", message_id=500))
    edit = spy.calls("EditMessageText")[-1]
    assert edit["message_id"] == 500 and labels(edit)[2] == "Права: acceptEdits"
    assert spy.calls("AnswerCallbackQuery")[-1]["text"] == "Переключено"
    assert not any(t.startswith("🔐 Права") for t in spy.sent_texts())        # no extra chat message
    await run(app, callback_update("cyc:1:model", message_id=500))
    await run(app, callback_update("cyc:1:model", message_id=500))
    assert labels(spy.calls("EditMessageText")[-1])[3] == "Модель: opus"
    await run(app, callback_update("cyc:1:effort", message_id=500))
    assert labels(spy.calls("EditMessageText")[-1])[4] == "Усилие: low"
    fake_claude.text_turn(LONG)
    await feed(app, text_update("привет"))
    await wait_for_text(spy, LONG.strip())
    argv = fake_claude.argv_calls()[-1]
    assert argv_value(argv, "--permission-mode") == "acceptEdits"
    assert argv_value(argv, "--model") == "opus" and argv_value(argv, "--effort") == "low"


async def test_cycles_wrap_to_default_and_bypass_needs_the_setting(app, spy, fake_claude):
    await run(app, text_update("/status"))
    for _ in range(4):
        await run(app, callback_update("cyc:1:perm", message_id=500))
    assert labels(spy.calls("EditMessageText")[-1])[2] == "Права: dontAsk"
    await run(app, callback_update("cyc:1:perm", message_id=500))
    assert labels(spy.calls("EditMessageText")[-1])[2] == "Права: prompt"      # bypass skipped
    settings.ALLOW_BYPASS = True
    for _ in range(5):
        await run(app, callback_update("cyc:1:perm", message_id=500))
    assert labels(spy.calls("EditMessageText")[-1])[2] == "Права: bypass"
    for _ in range(4):
        await run(app, callback_update("cyc:1:model", message_id=500))
    assert labels(spy.calls("EditMessageText")[-1])[3] == "Модель: по умолчанию"
    assert (await app.topics.list_all())[0]["model"] is None


async def test_more_page_toggles_topic_and_user_flags(app, spy, fake_claude):
    await run(app, text_update("/status"))
    await run(app, callback_update("page:1:more", message_id=500))
    more = spy.calls("EditMessageText")[-1]
    assert labels(more) == ["Превью ответа: вкл", "Размышления: вкл", "Статистика хода: выкл", "Голосом: выкл",
                            "Голос = вопрос: вкл", "Форвард = вопрос: выкл", "Реакции: вкл", "Назад"]
    await run(app, callback_update("tgl:1:stream_preview", message_id=500))
    edit = spy.calls("EditMessageText")[-1]
    assert labels(edit)[0] == "Превью ответа: выкл" and labels(edit)[-1] == "Назад"
    assert (await app.topics.list_all())[0]["settings"]["stream_preview"] is False
    await run(app, callback_update("tgl:1:reactions", message_id=500))
    assert labels(spy.calls("EditMessageText")[-1])[6] == "Реакции: выкл"
    assert (await app.store.users.settings(1))["reactions"] is False
    await run(app, callback_update("tgl:1:show_turn_stats", message_id=500))
    assert (await app.topics.list_all())[0]["settings"]["show_turn_stats"] is True
    await run(app, callback_update("page:1:main", message_id=500))
    assert labels(spy.calls("EditMessageText")[-1])[0] == "Новый контекст"
    fake_claude.text_turn(LONG, duration_ms=61000, cost=0.5, num_turns=3)
    await feed(app, text_update("привет"))
    await wait_for_text(spy, LONG.strip())
    await wait_turn_finished(app)
    assert any(t.startswith("_1 м 1 с · $0.50 · 3 шагов_") for t in spy.sent_texts())


async def test_thinking_preview_off_hides_the_thinking_line_in_the_draft(app, spy, fake_claude):
    await run(app, text_update("/status"))
    await run(app, callback_update("tgl:1:thinking_preview", message_id=500))
    fake_claude.enqueue(fc.thinking_delta("Секретная мысль номер один\n"), fc.text_delta("Начинаю писать длинный ответ на этот вопрос"),
                        {"delay": 0.3}, fc.assistant_text(LONG), fc.result())
    await feed(app, text_update("думай"))
    await wait_for_text(spy, LONG.strip())
    drafts = [p["rich_message"]["markdown"] for p in spy.calls("SendRichMessageDraft")]
    assert drafts and not any("🧠" in d for d in drafts)


async def test_voice_toggle_needs_tts(app, spy, fake_claude):
    await run(app, text_update("/status"))
    await run(app, callback_update("tgl:1:voice", message_id=500))
    assert "Синтез не настроен: задай TTS_CMD в settings_local.py." in spy.sent_texts()
    assert "voice" not in (await app.topics.list_all())[0]["settings"]


async def test_model_and_effort_commands(app, spy, fake_claude):
    await run(app, text_update("/model"))
    assert spy.last_text() == "Модель темы: по умолчанию. /model <имя|default> — сменить; варианты: sonnet, opus, haiku."
    await run(app, text_update("/model sonnet"))
    assert spy.last_text().startswith("🤖 Модель: sonnet.")
    await run(app, text_update("/effort nope"))
    assert spy.last_text().startswith("Не знаю усилие nope")
    await run(app, text_update("/effort xhigh"))
    assert spy.last_text().startswith("🎚 Усилие: xhigh.")
    fake_claude.text_turn(LONG)
    await feed(app, text_update("привет"))
    await wait_for_text(spy, LONG.strip())
    argv = fake_claude.argv_calls()[-1]
    assert argv_value(argv, "--model") == "sonnet" and argv_value(argv, "--effort") == "xhigh"
    await run(app, text_update("/model default"))
    assert (await app.topics.list_all())[0]["model"] is None
    await run(app, text_update("/effort"))
    assert spy.last_text().startswith("Усилие темы: xhigh.")


async def test_preamble_and_soul_go_into_one_system_prompt_file(app, spy, fake_claude, tmp_path):
    soul = tmp_path / "work" / "SOUL.md"
    soul.write_text("Отвечай как пират.\n")
    await run(app, text_update(f"/soul {soul}"))
    assert spy.last_text() == f"🎭 Характер: {soul.resolve()}. Вступит в силу со следующего процесса."
    fake_claude.text_turn(LONG)
    await feed(app, text_update("привет"))
    await wait_for_text(spy, LONG.strip())
    await wait_turn_finished(app)
    argv = fake_claude.argv_calls()[-1]
    text = Path(argv_value(argv, "--append-system-prompt-file")).read_text()
    assert text.startswith("# Telegram bridge") and text.rstrip().endswith("Отвечай как пират.")
    await run(app, text_update("/soul off"))
    assert spy.last_text() == "🎭 Характер выключен для этой темы."
    fake_claude.text_turn(LONG)
    await feed(app, text_update("ещё"))
    await wait_turn_finished(app, after=1)
    text = Path(argv_value(fake_claude.argv_calls()[-1], "--append-system-prompt-file")).read_text()
    assert "пират" not in text and "# Telegram bridge" in text
    await run(app, text_update("/soul /etc/passwd"))
    assert spy.last_text().startswith("⚠️ Нет такого файла")
    await run(app, text_update("/soul"))
    assert spy.last_text() == "Характер темы: выключен. /soul <путь|off|default>."


async def test_soul_default_comes_from_settings(app, spy, fake_claude, tmp_path):
    soul = tmp_path / "work" / "default-soul.md"
    soul.write_text("Кратко и по делу.")
    settings.SOUL_PATH = str(soul)
    fake_claude.text_turn(LONG)
    await feed(app, text_update("привет"))
    await wait_for_text(spy, LONG.strip())
    text = Path(argv_value(fake_claude.argv_calls()[-1], "--append-system-prompt-file")).read_text()
    assert text.rstrip().endswith("Кратко и по делу.")
    await run(app, text_update("/soul"))
    assert spy.last_text() == f"Характер темы: {soul}. /soul <путь|off|default>."
