import asyncio

import settings
from tests.support import fake_claude as fc
from tests.support.helpers import feed, run, wait_for_text, wait_turn_finished
from tests.support.updates import callback_update, text_update
from tests.e2e.test_permissions import button_texts, buttons, card_message_id, wait_card

LONG = "Отлично, делаю в выбранном формате, вот подробный результат, достаточно длинный, чтобы уйти сразу. " * 2


def question_turn(fake, *questions):
    fake.enqueue(fc.tool_use("AskUserQuestion", fc.question(*questions)),
                 fc.prompt_tool("AskUserQuestion", fc.question(*questions)),
                 fc.tool_result(), fc.assistant_text(LONG), fc.result())


async def test_single_choice_question_answers_with_the_label(app, spy, fake_claude):
    question_turn(fake_claude, fc.q("Как оформить вывод?", "Summary", "Detailed", header="Формат",
                                    descriptions={"Summary": "кратко", "Detailed": "с примерами"}))
    await feed(app, text_update("сделай отчёт"))
    card = await wait_card(spy, "❓ Формат")
    assert card["rich_message"]["markdown"] == "❓ Формат\nКак оформить вывод?"
    assert button_texts(card) == ["Summary — кратко", "Detailed — с примерами", "Свой ответ"]
    assert buttons(card) == ["qo:1:1:0", "qo:1:1:1", "qc:1:1"]
    for _ in range(50):
        if any("❓ жду ответа" in p["rich_message"]["markdown"] for p in spy.calls("SendRichMessageDraft")):
            break
        await asyncio.sleep(0.02)
    else:
        raise AssertionError("waiting line never in a draft")
    mid = await card_message_id(app)
    await feed(app, callback_update("qo:1:1:1", message_id=mid))
    await wait_for_text(spy, LONG.strip())
    decision = fake_claude.decisions()[0]
    assert decision["behavior"] == "allow"
    assert decision["updatedInput"]["answers"] == {"Как оформить вывод?": "Detailed"}
    assert decision["updatedInput"]["questions"][0]["question"] == "Как оформить вывод?"
    await wait_turn_finished(app)
    edit = spy.calls("EditMessageText")[-1]
    assert edit["message_id"] == mid and edit["rich_message"]["markdown"].endswith("→ Detailed") and "reply_markup" not in edit
    assert (await app.db.fetchrow("SELECT kind, status FROM pending_prompts"))["kind"] == "question"


async def test_multi_select_toggles_and_done_sends_a_list(app, spy, fake_claude):
    question_turn(fake_claude, fc.q("Что включить?", "Тесты", "Доки", "Бенчмарки", multi=True))
    await feed(app, text_update("собери релиз"))
    card = await wait_card(spy, "❓ Вопрос")
    assert "_(можно выбрать несколько)_" in card["rich_message"]["markdown"]
    assert button_texts(card) == ["☐ Тесты", "☐ Доки", "☐ Бенчмарки", "Готово", "Свой ответ"]
    mid = await card_message_id(app)
    await run(app, callback_update("qo:1:1:0", message_id=mid))
    await run(app, callback_update("qo:1:1:2", message_id=mid))
    kb = spy.calls("EditMessageText")[-1]
    assert button_texts(kb) == ["☑ Тесты", "☐ Доки", "☑ Бенчмарки", "Готово", "Свой ответ"]
    await run(app, callback_update("qo:1:1:2", message_id=mid))          # toggle off again
    assert button_texts(spy.calls("EditMessageText")[-1])[2] == "☐ Бенчмарки"
    assert fake_claude.decisions() == []
    await feed(app, callback_update("qd:1:1", message_id=mid))
    await wait_for_text(spy, LONG.strip())
    assert fake_claude.decisions()[0]["updatedInput"]["answers"] == {"Что включить?": ["Тесты"]}
    await wait_turn_finished(app)
    assert spy.calls("EditMessageText")[-1]["rich_message"]["markdown"].endswith("→ Тесты")


async def test_two_questions_come_one_card_after_another(app, spy, fake_claude):
    question_turn(fake_claude, fc.q("Язык?", "Python", "Rust", header="Язык"), fc.q("Стиль?", "Строгий", "Мягкий", header="Стиль"))
    await feed(app, text_update("начнём"))
    card1 = await wait_card(spy, "❓ Язык (1/2)")
    await feed(app, callback_update("qo:1:1:1", message_id=await card_message_id(app)))
    card2 = await wait_card(spy, "❓ Стиль (2/2)")
    assert card2 is not card1 and fake_claude.decisions() == []
    await feed(app, callback_update("qo:1:1:0", message_id=await card_message_id(app)))
    await wait_for_text(spy, LONG.strip())
    assert fake_claude.decisions()[0]["updatedInput"]["answers"] == {"Язык?": "Rust", "Стиль?": "Строгий"}
    await wait_turn_finished(app)


async def test_custom_answer_takes_the_next_message(app, spy, fake_claude):
    question_turn(fake_claude, fc.q("Какой порт?", "8080", "3000"))
    await feed(app, text_update("подними сервер"))
    await wait_card(spy, "❓ Вопрос")
    await feed(app, callback_update("qc:1:1", message_id=await card_message_id(app)))
    await wait_for_text(spy, "✍ Напиши ответ следующим сообщением.")
    await feed(app, text_update("9999, и слушай только localhost"))
    await wait_for_text(spy, LONG.strip())
    assert fake_claude.decisions()[0]["updatedInput"]["answers"] == {"Какой порт?": "9999, и слушай только localhost"}
    await wait_turn_finished(app)
    assert fake_claude.stdin_texts() == ["подними сервер"]
    assert spy.calls("EditMessageText")[-1]["rich_message"]["markdown"].endswith("→ 9999, и слушай только localhost")


async def test_unanswered_question_times_out_into_a_deny(app, spy, fake_claude):
    settings.QUESTION_TIMEOUT_SECS = 0.5
    question_turn(fake_claude, fc.q("Да?", "Да", "Нет"))
    await feed(app, text_update("спроси"))
    await wait_card(spy, "❓ Вопрос")
    await wait_for_text(spy, LONG.strip(), timeout=4)
    assert fake_claude.decisions() == [{"behavior": "deny", "message": "User did not answer within 1 minutes."}]
    await wait_turn_finished(app)
    assert spy.calls("EditMessageText")[-1]["rich_message"]["markdown"].endswith("⌛ без ответа — отклонено")
