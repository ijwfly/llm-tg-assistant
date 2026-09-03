from tests.support.helpers import run
from tests.support.updates import text_update


async def test_same_update_id_is_handled_once(app, spy):
    update = text_update("/help", update_id=777)
    await run(app, update)
    await run(app, update)
    assert len(spy.calls("SendMessage")) == 1
    assert await app.db.fetchval("SELECT count(*) FROM processed_updates") == 1
