"""Room flow over the real WebSocket endpoint: two phones join, play a board."""
import os

os.environ["BRIDGE_BOT_DELAY"] = "0"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from bridge.app import app  # noqa: E402
from bridge.game.room import Room  # noqa: E402
from bridge.game.table import DONE, PLAYING, Table  # noqa: E402


@pytest.fixture(autouse=True)
def tmp_data(tmp_path, monkeypatch):
    monkeypatch.setenv("BRIDGE_DATA_DIR", str(tmp_path))


def recv_state(ws):
    while True:
        msg = ws.receive_json()
        if msg["type"] == "state":
            return msg
        if msg["type"] == "error":
            raise AssertionError(msg["message"])


def drain_until(ws, pred, limit=400):
    for _ in range(limit):
        st = recv_state(ws)
        if pred(st):
            return st
    raise AssertionError("condition never reached")


def test_create_and_join_two_phones():
    client = TestClient(app)
    code = client.post("/api/rooms").json()["code"]
    with client.websocket_connect(f"/ws/{code}") as a:
        a.send_json({"type": "join", "name": "Ann"})
        joined = a.receive_json()
        assert joined["seat"] == "S" and joined["token"]
        st = recv_state(a)
        assert st["waiting_for_partner"] and st["table"] is None
        with client.websocket_connect(f"/ws/{code}") as b:
            b.send_json({"type": "join", "name": "Bob"})
            assert b.receive_json()["seat"] == "N"
            st_b = recv_state(b)
            assert st_b["table"] is not None and st_b["table"]["board"] == 1
            # each phone sees only its own hand before the play
            hands = st_b["table"]["hands"]
            assert hands["N"] and hands["S"] is None and hands["E"] is None


def test_pages_ask_search_engines_not_to_index():
    client = TestClient(app)
    assert client.get("/api/health").headers["X-Robots-Tag"] == "noindex, nofollow"
    assert client.get("/").headers["X-Robots-Tag"] == "noindex, nofollow"


def test_unknown_room():
    client = TestClient(app)
    with client.websocket_connect("/ws/ZZZZ") as ws:
        msg = ws.receive_json()
        assert msg["type"] == "error" and msg["fatal"]


def test_reconnect_with_token_keeps_seat():
    client = TestClient(app)
    code = client.post("/api/rooms").json()["code"]
    with client.websocket_connect(f"/ws/{code}") as a:
        a.send_json({"type": "join", "name": "Ann"})
        token = a.receive_json()["token"]
    with client.websocket_connect(f"/ws/{code}") as a2:
        a2.send_json({"type": "join", "name": "Ann", "token": token})
        assert a2.receive_json()["seat"] == "S"


def test_solo_room_plays_a_full_board_through_websocket():
    """South alone with a bot partner: bid and play to the end via the socket."""
    client = TestClient(app)
    code = client.post("/api/rooms").json()["code"]
    with client.websocket_connect(f"/ws/{code}") as ws:
        ws.send_json({"type": "join", "name": "Solo"})
        ws.receive_json()
        recv_state(ws)
        ws.send_json({"type": "settings", "solo": True, "difficulty": 1})
        ws.send_json({"type": "next_board"})
        for _ in range(2000):
            st = recv_state(ws)
            t = st["table"]
            if t is None:
                continue
            if t["phase"] == DONE:
                assert t["result"] is not None
                review = t["result"]["review"]
                assert "error" not in review
                assert review["play"] is None or len(review["play"]["cards"]) == 52
                assert all(t["hands"][s] for s in "NESW")  # everything revealed at the end
                break
            if t["your_turn"]:
                if t["phase"] == PLAYING:
                    ws.send_json({"type": "play", "card": t["legal_cards"][0]})
                else:
                    ws.send_json({"type": "call", "call": "P"})
        else:
            raise AssertionError("board never finished")


def test_hint_goes_only_to_the_asking_phone():
    client = TestClient(app)
    code = client.post("/api/rooms").json()["code"]
    with client.websocket_connect(f"/ws/{code}") as ws:
        ws.send_json({"type": "join", "name": "Solo"})
        ws.receive_json()
        recv_state(ws)
        ws.send_json({"type": "settings", "solo": True})
        ws.send_json({"type": "next_board"})
        drain_until(ws, lambda st: st["table"] and st["table"]["your_turn"])
        ws.send_json({"type": "hint"})
        while (msg := ws.receive_json())["type"] == "state":
            pass
        assert msg["type"] == "hint" and msg["call"]


def test_illegal_actions_are_rejected():
    room = Room("TEST", seed=1)
    room.join("Ann")
    room.join("Bob")
    room.new_board()
    t = room.table
    wrong = "E" if t.auction.next_to_call != "E" else "S"
    with pytest.raises(ValueError):
        t.make_call(wrong, "1C")


def test_human_declarer_controls_dummy():
    room = Room("TEST", seed=3)
    room.join("Ann")
    room.join("Bob")
    room.new_board()
    t: Table = room.table
    # force an auction: South opens 1NT, everyone passes
    while t.auction.next_to_call != "S":
        t.make_call(t.auction.next_to_call, "P")
    t.make_call("S", "1N")
    for _ in range(3):
        t.make_call(t.auction.next_to_call, "P")
    assert t.phase == PLAYING and t.contract.declarer == "S"
    lead = t.play.legal_cards()[0]
    t.play_card("W", lead)
    # North is dummy: South plays North's card, North can't
    assert t.controller_to_act() == "S"
    with pytest.raises(ValueError):
        t.play_card("N", t.play.legal_cards()[0])
    t.play_card("S", t.play.legal_cards()[0])
    # dummy's hand is visible to East (defender) after the lead
    assert t.state_for("E")["hands"]["N"] is not None
    assert t.state_for("E")["hands"]["W"] is None


def test_solo_human_plays_bot_partners_contract():
    room = Room("SOLO", seed=3)
    room.update_settings(solo=True)
    room.join("Ann")
    room.new_board()
    t: Table = room.table
    # North (a bot) opens 1NT, everyone passes: South is dummy but plays both hands
    while t.auction.next_to_call != "N":
        t.make_call(t.auction.next_to_call, "P")
    t.make_call("N", "1N")
    for _ in range(3):
        t.make_call(t.auction.next_to_call, "P")
    assert t.phase == PLAYING and t.contract.declarer == "N" and t.play.dummy == "S"
    assert t.state_for("S")["hands"]["N"] is not None  # South sees North's hand before the lead
    t.play_card("E", t.play.legal_cards()[0])
    assert t.controller_to_act() == "S" and not t.is_bot_turn()
    st = t.state_for("S")
    assert st["your_turn"] and st["legal_cards"]
    t.play_card("S", t.play.legal_cards()[0])  # North's card, played by South
    assert t.controller_to_act() == "W" and t.is_bot_turn()
    t.play_card("W", t.play.legal_cards()[0])
    assert t.controller_to_act() == "S"  # South's own (dummy) card
    assert t.state_for("E")["hands"]["N"] is None  # defenders still can't see North


def test_trick_pause_setting():
    room = Room("TPSE", seed=1)
    assert room.settings.to_dict()["trick_pause"] == 2.0
    room.update_settings(trick_pause=4)
    assert room.settings.trick_pause == 4.0
    room.update_settings(trick_pause=1)
    assert room.settings.trick_pause == 1.0
    with pytest.raises(ValueError):
        room.update_settings(trick_pause=9)


def test_bots_pause_after_deal_and_finished_trick(monkeypatch):
    import bridge.game.room as room_mod
    monkeypatch.setattr(room_mod, "BOT_DELAY", 0.7)
    room = Room("PAWS", seed=3)
    room.join("Ann")
    room.update_settings(solo=True)
    room.new_board()
    assert room._pause() == room_mod.DEAL_PAUSE  # nobody has called yet
    t = room.table
    while t.phase == "bidding":
        seat = t.auction.next_to_call
        t.make_call(seat, t.engine.choose(t.hands[seat], t.auction).call if seat == "S" else t.bot.bid(t.hands[seat], t.auction).call)
    if t.phase != PLAYING:
        return  # passed out: nothing more to check
    assert room._pause() == 0.0
    for _ in range(4):
        seat = t.play.next_to_play
        t.play_card(t.controller_of(seat), t.play.legal_cards(seat)[0])
    assert room._pause() == room.settings.trick_pause


def _bid_1nt_by_south(t: Table):
    while t.auction.next_to_call != "S":
        t.make_call(t.auction.next_to_call, "P")
    t.make_call("S", "1N")
    for _ in range(3):
        t.make_call(t.auction.next_to_call, "P")


def test_dummy_sees_declarers_hand():
    room = Room("DUMY", seed=3)
    room.join("Ann")
    room.join("Bob")
    room.new_board()
    t: Table = room.table
    _bid_1nt_by_south(t)
    assert t.state_for("N")["hands"]["S"] is not None  # North (dummy) can follow South's play
    assert t.state_for("E")["hands"]["S"] is None


def test_undo_goes_back_to_the_start_of_the_board():
    room = Room("UNDO", seed=3)
    room.join("Ann")
    room.join("Bob")
    room.new_board()
    t: Table = room.table
    assert not t.can_undo()
    _bid_1nt_by_south(t)
    lead = t.play.legal_cards()[0]
    t.play_card("W", lead)
    t.play_card("S", t.play.legal_cards()[0])  # dummy's card, played by South
    room.undo()  # takes back South's card: back to South's turn after the lead
    assert t.phase == PLAYING and t.controller_to_act() == "S" and len(t.play.played_cards()) == 1
    room.undo()  # the passes and 1NT, one person's call at a time, back to the first
    while t.can_undo():
        room.undo()
    # what's left is only the bots' calls before South's first one
    assert t.phase == "bidding" and all(seat in t.bot_seats for seat, _, _ in t.actions)
    with pytest.raises(ValueError):
        room.undo()


def test_undo_can_be_switched_off():
    room = Room("NOUN", seed=3)
    room.join("Ann")
    room.join("Bob")
    room.new_board()
    room.update_settings(undo=False)
    _bid_1nt_by_south(room.table)
    with pytest.raises(ValueError):
        room.undo()


def test_rubber_scoring_sets_vulnerability_and_scores_boards():
    room = Room("RUBR", seed=3)
    room.update_settings(scoring="rubber")
    room.join("Ann")
    room.join("Bob")
    room.new_board()
    t: Table = room.table
    assert t.vulnerability == "None"
    _bid_1nt_by_south(t)
    while t.phase == PLAYING:
        t.play_card(t.controller_to_act(), t.play.legal_cards()[0])
    room.record_result()
    st = room.state_for("S")
    assert st["settings"]["scoring"] == "rubber" and st["rubber"]["lines"]
    assert st["history"][-1]["score_ns"] == room.rubber.totals()["NS"] - room.rubber.totals()["EW"]
    # undoing the last card takes the board back out of the rubber
    room.undo()
    assert room.history == [] and room.rubber.lines == []


def test_a_card_can_be_played_while_a_hint_is_thinking():
    import asyncio

    from bridge.game.room import Room

    async def go():
        room = Room("HINT")
        room.join("Solo", None, None)
        room.update_settings(solo=True)
        room.new_board()
        t = room.table
        while t.phase == "bidding" or t.is_bot_turn():  # bid it out and get to one of our cards
            if t.is_bot_turn():
                t.bot_step()
            else:
                t.make_call(t.controller_to_act(), t.hint(t.controller_to_act())["call"])
            if t.phase == "done":
                return  # passed out: nothing to play
        me = t.controller_to_act()
        first = asyncio.ensure_future(room.hint(me))
        second = asyncio.ensure_future(room.hint(me))
        await asyncio.sleep(0)
        assert not room.lock.locked()  # the hint thinks without holding the room
        await room.handle(me, {"type": "play", "card": t.play.legal_cards()[0]})
        assert len(t.actions) and t.actions[-1][1] == "card"
        a, b = await asyncio.gather(first, second)
        assert a is b and a["card"]  # the second tap reused the first answer

    asyncio.run(go())


def test_skip_deals_a_fresh_hand_only_when_playing_alone():
    import asyncio

    import pytest

    from bridge.game.room import Room

    async def go():
        room = Room("SKIP")
        room.join("Solo", None, None)
        _, partner = room.join("Partner", None, None)
        room.new_board()
        with pytest.raises(ValueError):
            await room.handle("S", {"type": "skip"})  # someone else is playing
        room.stand(partner)
        room.update_settings(solo=True)
        before = room.table
        await room.handle("S", {"type": "skip"})
        assert room.table is not before and room.table.board == before.board + 1
        assert room.history == []  # the skipped hand isn't scored

    asyncio.run(go())


def test_third_phone_picks_a_seat_and_a_fourth_watches():
    client = TestClient(app)
    code = client.post("/api/rooms").json()["code"]
    with client.websocket_connect(f"/ws/{code}") as a, client.websocket_connect(f"/ws/{code}") as b:
        a.send_json({"type": "join", "name": "Ann"})
        assert recv_state(a)["you"] == "S"
        b.send_json({"type": "join", "name": "Bob"})
        assert drain_until(b, lambda s: s["table"] is not None)["you"] == "N"
        with client.websocket_connect(f"/ws/{code}") as c, client.websocket_connect(f"/ws/{code}") as d:
            c.send_json({"type": "join", "name": "Carol"})
            assert recv_state(c)["choosing"]
            c.send_json({"type": "sit", "seat": "E"})
            st = drain_until(c, lambda s: s["you"] == "E")
            assert "E" not in st["bots"] and st["players"]["E"] == "Carol"
            d.send_json({"type": "join", "name": "Dan", "watch": True})
            st = drain_until(d, lambda s: s["watching"])
            assert st["you"] is None and not any(st["table"]["hands"].values())  # only what all can see
            d.send_json({"type": "call", "call": "P"})
            assert d.receive_json() == {"type": "error", "message": "take a seat to play"}


def test_version_is_the_built_clients(tmp_path, monkeypatch):
    import bridge.app as app_mod
    monkeypatch.setattr(app_mod, "WEB_DIST", tmp_path)
    client = TestClient(app)
    r = client.get("/api/version")
    assert r.json() == {"version": None} and r.headers["cache-control"] == "no-store"  # no build yet
    (tmp_path / "version.json").write_text('{"version": "1.41"}')
    assert client.get("/api/version").json() == {"version": "1.41"}


def test_a_missed_update_is_noticed_from_the_pong_and_sent_again():
    """A player's table showed an old trick (2026-11-06): the server had stopped sending one phone updates, while its
    socket still answered pings and took taps. The pong carries the room's update number, so the phone sees it is
    behind and asks for the table again."""
    from bridge.app import rooms

    client = TestClient(app)
    code = client.post("/api/rooms").json()["code"]
    with client.websocket_connect(f"/ws/{code}") as ws:
        ws.send_json({"type": "join", "name": "Solo"})
        token = ws.receive_json()["token"]
        st = recv_state(ws)
        ws.send_json({"type": "ping"})
        assert ws.receive_json() == {"type": "pong", "rev": st["rev"]}
        room = rooms.rooms[code]
        me = room.person(token)[1]
        lost = set(me.connections)
        me.connections.clear()  # as after a failed send: this phone hears nothing more
        ws.send_json({"type": "settings", "trick_pause": 3})
        ws.send_json({"type": "ping"})
        pong = ws.receive_json()
        assert pong["type"] == "pong" and pong["rev"] > st["rev"]
        ws.send_json({"type": "sync"})
        fresh = recv_state(ws)
        assert fresh["rev"] == pong["rev"] and fresh["settings"]["trick_pause"] == 3
        assert me.connections == lost  # and it gets the updates after this one again


def test_a_failed_update_closes_that_connection():
    import asyncio

    room = Room("FAIL", seed=1)
    _, token = room.join("Ann")
    closed = []

    async def broken(msg):
        raise RuntimeError("gone")

    async def close():
        closed.append(True)

    broken.close = close
    room.person(token)[1].connections.add(broken)

    async def go():
        await room.broadcast()
        await asyncio.sleep(0)

    asyncio.run(go())
    assert closed and not room.person(token)[1].connections


def test_health_reports_storage_and_backup_age(monkeypatch):
    from bridge import app as server
    client = TestClient(server.app)
    monkeypatch.setattr(server.store, "durable", False)
    assert client.get("/api/health").json()["storage"] == "local"

    monkeypatch.setattr(server.store, "durable", True)
    check = server.StorageCheck()
    monkeypatch.setattr(server, "storage_check", check)
    assert client.get("/api/health").json()["storage"] == "checking"  # first answer comes from the background
    check._ask()
    assert client.get("/api/health").json()["storage"] == "ok"

    def broken(*_args):
        raise OSError("storage unreachable")
    monkeypatch.setattr(server.store, "get", broken)
    check._ask()
    got = client.get("/api/health")
    assert got.status_code == 200 and got.json()["storage"] == "down"  # still 200, so Azure doesn't restart it

    monkeypatch.setattr(server.backups, "last", None)
    assert client.get("/api/health").json()["backup_days"] is None
    monkeypatch.setattr(server.backups, "last", (server.pacific_today() - server.dt.timedelta(days=3)).isoformat())
    assert client.get("/api/health").json()["backup_days"] == 3
