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


async def wait_for_text(spy, fragment: str, timeout: float = 3.0) -> str:
    """Settle until a shown text contains `fragment`; returns it."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        for t in spy.sent_texts():
            if fragment in t:
                return t
        await asyncio.sleep(0.02)
    raise AssertionError(f"{fragment!r} never shown; shown: {spy.sent_texts()!r}")


async def wait_turn_finished(app, timeout: float = 5.0, after: int | None = None) -> dict:
    """Wait until the newest turn row leaves queued/running; returns it. With `after`, the row must be
    newer than that turn id (a turn that has not been created yet does not count as finished)."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        row = await app.db.fetchrow("SELECT * FROM turns ORDER BY id DESC LIMIT 1")
        if row is not None and (after is None or row["id"] > after) and row["status"] not in ("queued", "running"):
            await wait_outbox_idle(app)
            return dict(row)
        await asyncio.sleep(0.02)
    raise AssertionError("turn did not finish")
