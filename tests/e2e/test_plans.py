from tests.support import fake_claude as fc
from tests.support.helpers import feed, run, wait_for_text, wait_turn_finished
from tests.support.updates import callback_update, text_update
from tests.e2e.test_permissions import button_texts, buttons, card_message_id, wait_card

LONG = "План принят, приступаю к реализации по шагам, вот что сделано на первом этапе, подробно и длинно. " * 2
PLAN = "# Рефакторинг\n\n1. Вынести парсер\n2. Добавить тесты\n\n```python\ndef parse(): ...\n```"


def plan_turn(fake):
    fake.enqueue(fc.tool_use("ExitPlanMode", {"plan": PLAN, "planFilePath": "/tmp/plan.md"}),
                 fc.prompt_tool("ExitPlanMode", {"plan": PLAN, "planFilePath": "/tmp/plan.md"}),
                 fc.tool_result(), fc.assistant_text(LONG), fc.result())


async def test_plan_card_accept_switches_to_accept_edits(app, spy, fake_claude):
    await run(app, text_update("/perm plan"))
    plan_turn(fake_claude)
    await feed(app, text_update("спланируй рефакторинг"))
    card = await wait_card(spy, "📋 **План готов**")
    md = card["rich_message"]["markdown"]
    assert "# Рефакторинг" in md and "```python\ndef parse(): ...\n```" in md
    assert buttons(card) == ["pl:1:1:accept", "pl:1:1:ask", "pl:1:1:rework"]
    assert button_texts(card)[0] == "✅ Выполнять (правки без вопросов)"
    argv = fake_claude.argv_calls()[-1]
    assert argv[argv.index("--permission-mode") + 1] == "plan" and "--permission-prompt-tool" in argv
    mid = await card_message_id(app)
    await feed(app, callback_update("pl:1:1:accept", message_id=mid))
    await wait_for_text(spy, LONG.strip())
    decision = fake_claude.decisions()[0]
    assert decision["behavior"] == "allow" and decision["updatedInput"]["plan"] == PLAN
    assert decision["updatedPermissions"] == [{"type": "setMode", "mode": "acceptEdits", "destination": "session"}]
    await wait_turn_finished(app)
    assert (await app.topics.list_all())[0]["permission_mode"] == "acceptEdits"
    assert spy.calls("EditMessageText")[-1]["rich_message"]["markdown"].endswith("✅ выполняю, правки без вопросов")
    assert (await app.db.fetchrow("SELECT kind FROM pending_prompts"))["kind"] == "plan"


async def test_plan_accept_with_questions_sets_default_mode(app, spy, fake_claude):
    await run(app, text_update("/perm plan"))
    plan_turn(fake_claude)
    await feed(app, text_update("спланируй"))
    await wait_card(spy, "📋 **План готов**")
    await feed(app, callback_update("pl:1:1:ask", message_id=await card_message_id(app)))
    await wait_for_text(spy, LONG.strip())
    assert fake_claude.decisions()[0]["updatedPermissions"] == [{"type": "setMode", "mode": "default", "destination": "session"}]
    await wait_turn_finished(app)
    assert (await app.topics.list_all())[0]["permission_mode"] == "prompt"
    assert spy.calls("EditMessageText")[-1]["rich_message"]["markdown"].endswith("✅ выполняю, про правки буду спрашивать")


async def test_plan_rework_denies_with_the_next_message(app, spy, fake_claude):
    await run(app, text_update("/perm plan"))
    plan_turn(fake_claude)
    await feed(app, text_update("спланируй"))
    await wait_card(spy, "📋 **План готов**")
    await feed(app, callback_update("pl:1:1:rework", message_id=await card_message_id(app)))
    await wait_for_text(spy, "✏️ Напиши следующим сообщением, что поправить в плане.")
    await feed(app, text_update("сначала тесты, потом парсер"))
    await wait_for_text(spy, LONG.strip())
    assert fake_claude.decisions() == [{"behavior": "deny", "message": "User asked to rework the plan: сначала тесты, потом парсер"}]
    await wait_turn_finished(app)
    assert (await app.topics.list_all())[0]["permission_mode"] == "plan"
    assert fake_claude.stdin_texts() == ["спланируй"]
    assert spy.calls("EditMessageText")[-1]["rich_message"]["markdown"].endswith("✏️ на доработку: «сначала тесты, потом парсер»")
