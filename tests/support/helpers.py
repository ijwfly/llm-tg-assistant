from __future__ import annotations

import asyncio

from aiogram.types import Update


async def feed(app, update: Update) -> None:
    await app.dp.feed_update(app.bot, update)


async def wait_outbox_idle(app, timeout: float = 3.0) -> None:
    """Settle until every due outbox row is delivered or failed (scheduled retries excluded)."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if app.outbox.inflight == 0 and not await app.store.outbox.has_due_pending(set()):
            await asyncio.sleep(0.03)  # let the delivery task finish bookkeeping
            if app.outbox.inflight == 0 and not await app.store.outbox.has_due_pending(set()):
                return
        await asyncio.sleep(0.02)
    raise AssertionError("outbox did not settle")


async def run(app, update: Update) -> None:
    await feed(app, update)
    await wait_outbox_idle(app)
