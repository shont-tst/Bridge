"""The table in the app (bridge/local.py): the same game the server runs, spoken to as a WebSocket would be."""
import asyncio
import json

import pytest

from bridge.game import room as room_mod
from bridge.local import HelperExecutor, InlineExecutor, LocalHost, helper_run


@pytest.fixture(autouse=True)
def _quick_bots(monkeypatch):
    monkeypatch.setattr(room_mod, "BOT_DELAY", 0)


class Phone:
    """What the app sees on one connection."""

    def __init__(self):
        self.got: list[dict] = []

    def last(self, kind: str) -> dict | None:
        return next((m for m in reversed(self.got) if m.get("type") == kind), None)


def _host(helper=False, **kw):
    phones: dict[int, Phone] = {}
    saved: list[dict] = []
    jobs: list[str] = []
    host = None

    def to_helper(n: int, call: bytes) -> None:
        """The helper is another engine in another worker: here, the same process a moment later."""
        import pickle
        fn, args = pickle.loads(call)
        jobs.append((args[1] if len(args) > 1 and callable(args[1]) else fn).__name__)
        asyncio.get_running_loop().call_soon(lambda: host.helper_done(n, helper_run(call)))

    def post(conn: int, text: str) -> None:
        msg = json.loads(text)
        if conn == 0:
            saved.append(msg)
        else:
            phones.setdefault(conn, Phone()).got.append(msg)

    host = LocalHost(post, helper=to_helper if helper else None, **kw)
    if helper:
        return host, phones, saved, jobs
    return host, phones, saved


async def _settle(host: LocalHost) -> None:
    """Let the bots finish whatever they're doing."""
    for _ in range(400):
        task = host.room._bot_task
        if not (task and not task.done()) and not (host.room._odds_task and not host.room._odds_task.done()):
            return
        await asyncio.sleep(0)
    await asyncio.sleep(0.01)


def test_inline_executor_runs_at_once():
    f = InlineExecutor().submit(lambda a, b: a + b, 2, 3)
    assert f.done() and f.result() == 5
    bad = InlineExecutor().submit(lambda: 1 / 0)
    assert isinstance(bad.exception(), ZeroDivisionError)


def test_a_solo_board_is_played_and_handed_back_for_the_account():
    async def go():
        host, phones, saved = _host(settings={"difficulty": 3, "scoring": "duplicate"})
        await host.receive(1, json.dumps({"type": "join", "name": "Avery", "solo": True,
                                          "user": {"id": "u1", "name": "Avery"}}))
        me = phones[1]
        assert me.last("joined")["seat"] == "S"
        room = host.room
        assert room.settings.solo and room.players["S"].user == "u1"
        assert room.ahead is False  # nothing worked out before it's asked for
        for _ in range(200):
            await _settle(host)
            t = room.table
            if t.phase == "done":
                break
            seat = t.controller_to_act()
            if t.phase == "bidding":
                await host.receive(1, json.dumps({"type": "call", "call": t.hint(seat)["call"]}))
            else:
                await host.receive(1, json.dumps({"type": "play", "card": t.play.legal_cards()[0]}))
        await _settle(host)
        assert room.table.phase == "done"
        state = me.last("state")
        assert state["table"]["board"] == 1 and state["you"] == "S"
        boards = [b for m in saved for b in m.get("boards", [])]
        assert boards and boards[0]["user"] == "u1" and boards[0]["rec"]["board"] == 1
        assert saved[-1]["snap"]["code"] == room.code  # the table to keep on the phone

    asyncio.run(go())


def test_the_table_carries_on_from_a_snapshot():
    async def go():
        host, phones, saved = _host()
        await host.receive(1, json.dumps({"type": "join", "name": "Pat", "solo": True}))
        token = phones[1].last("joined")["token"]
        await _settle(host)
        t = host.room.table
        while t.phase == "bidding" and not t.is_bot_turn():
            await host.receive(1, json.dumps({"type": "call", "call": t.hint(t.controller_to_act())["call"]}))
            await _settle(host)
        snap = json.loads(host.snapshot())
        again, phones2, _ = _host(snapshot=snap)
        await again.receive(7, json.dumps({"type": "join", "name": "Pat", "token": token}))
        assert phones2[7].last("joined")["seat"] == "S"
        assert again.room.table.actions == host.room.table.actions
        assert again.room.ahead is False

    asyncio.run(go())


def test_a_partner_joins_and_errors_go_to_the_phone_that_asked():
    async def go():
        host, phones, _ = _host()
        await host.receive(1, json.dumps({"type": "join", "name": "Avery"}))
        await host.receive(2, json.dumps({"type": "join", "name": "Casey", "seat": "N"}))
        assert phones[2].last("joined")["seat"] == "N"
        assert set(host.room.players) == {"S", "N"}
        await host.receive(2, json.dumps({"type": "play", "card": "SA"}))
        assert phones[2].last("error") and not phones[1].last("error")
        await host.receive(1, json.dumps({"type": "ping"}))
        assert phones[1].last("pong")["rev"] == host.room.rev
        await host.close(2)
        assert not host.room.players["N"].connections

    asyncio.run(go())


def test_the_helper_works_out_hints_and_odds_ahead_without_holding_up_the_game():
    async def go():
        host, phones, saved, jobs = _host(helper=True, settings={"difficulty": 3, "scoring": "duplicate"})
        assert isinstance(host.executor, HelperExecutor) and host.room.ahead
        await host.receive(1, json.dumps({"type": "join", "name": "Pat", "solo": True}))
        room = host.room
        asked = False
        for _ in range(300):
            await _settle(host)
            for _ in range(50):  # let the helper's answers come back
                await asyncio.sleep(0)
            t = room.table
            if t.phase == "done":
                break
            seat = t.controller_to_act()
            if t.phase == "bidding":
                await host.receive(1, json.dumps({"type": "call", "call": t.hint(seat)["call"]}))
            elif not asked:
                asked = True
                await host.receive(1, json.dumps({"type": "hint"}))
                assert phones[1].last("hint")["card"]
            else:
                await host.receive(1, json.dumps({"type": "play", "card": t.play.legal_cards()[0]}))
        for _ in range(200):
            await _settle(host)
            await asyncio.sleep(0)
        assert room.table.phase == "done"
        assert "card_hint" in jobs and "odds_ahead" in jobs and "second_table" in jobs
        assert not room.table.result.review.get("odds_pending")
        assert room.table.result.review["second"]["S"]["level"] == 10  # the second table, played in the helper

    asyncio.run(go())


def test_a_hint_for_a_card_already_played_is_dropped_before_it_starts():
    sent = []
    ex = HelperExecutor(lambda n, call: sent.append(n))
    from bridge.game.room import at
    from bridge.game.table import card_hint
    from bridge.solver import HINT, WARM, Job
    stale, tapped = Job(WARM), Job(WARM)
    first = ex.submit(at, Job(WARM), card_hint, None, None, None)
    a = ex.submit(at, stale, card_hint, None, None, None)
    b = ex.submit(at, tapped, card_hint, None, None, None)
    assert sent == [1] and not first.done()
    stale.cancel()
    tapped.priority = HINT
    import pickle
    ex.done(1, pickle.dumps((True, "first")))
    assert first.result() == "first" and a.exception() is not None and sent == [1, 3]
    ex.done(3, pickle.dumps((True, "tapped")))
    assert b.result() == "tapped"
