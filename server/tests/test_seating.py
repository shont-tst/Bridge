"""Up to four people at a table, the bots in the empty seats, and watching."""
import asyncio

import pytest

from bridge.game.room import Room


def test_first_two_sit_north_south_then_others_pick():
    room = Room("SEAT")
    assert room.join("Ann")[0] == "S"
    assert room.join("Bob")[0] == "N"
    seat, carol = room.join("Carol")
    assert seat is None and room.state_for(None, room.watchers[carol])["choosing"]
    room.sit(carol, "E")
    assert room.players["E"].name == "Carol" and room.bot_seats() == {"W"}
    with pytest.raises(ValueError, match="Carol has East"):
        room.sit(room.join("Dan")[1], "E")


def test_taking_a_bots_seat_mid_board_and_watchers_wait_for_the_next():
    room = Room("MIDB")
    room.join("Ann")
    room.join("Bob")
    room.new_board()
    room.table.make_call(room.table.seat_to_act(), "P")  # the board is under way
    _, carol = room.join("Carol")
    room.sit(carol, "W")  # hasn't seen any hands: sits straight away, the bot stops
    assert "W" not in room.table.bot_seats and room.players["W"].since == room.table.board + 1
    _, dan = room.join("Dan", seat=None)
    room.watch(dan)
    state = room.state_for(None, room.watchers[dan])
    # a watcher sees only what everyone sees: a player opening the table again to watch mustn't see the other hands
    assert state["watching"] and not any(state["table"]["hands"].values())
    room.sit(dan, "E")  # has seen this board: sits from the next one
    assert "E" not in room.players and room.state_for(None, room.watchers[dan])["pending"] == "E"
    room.new_board()
    assert room.players["E"].name == "Dan" and room.bot_seats() == set()


def test_standing_up_hands_the_seat_to_the_bot():
    room = Room("STND")
    _, ann = room.join("Ann")
    room.join("Bob")
    room.new_board()
    room.stand(ann)
    assert "S" in room.table.bot_seats and "S" not in room.players
    room.sit(ann, "S")  # has seen this board's hands: back from the next board
    assert "S" not in room.players and room.watchers[ann].pending == "S"


def test_no_undo_with_people_on_both_sides():
    async def go():
        room = Room("UNDO")
        room.join("Ann")
        room.join("Bob")
        _, carol = room.join("Carol")
        room.sit(carol, "E")
        room.new_board()
        t = room.table
        while not t.is_bot_turn() and t.seat_to_act() != "S":
            seat = t.seat_to_act()
            t.make_call(seat, "P")
        assert room.state_for("S")["table"]["can_undo"] is False
        with pytest.raises(ValueError, match="both sides"):
            await room.handle("S", {"type": "undo"})

    asyncio.run(go())


def test_watchers_cannot_play():
    async def go():
        room = Room("WTCH")
        room.join("Ann")
        room.join("Bob")
        room.new_board()
        _, carol = room.join("Carol")
        with pytest.raises(ValueError, match="take a seat"):
            await room.handle(None, {"type": "call", "call": "P"}, carol)

    asyncio.run(go())


def test_east_west_boards_saved_from_their_side():
    room = Room("EWSV")
    room.join("Ann")
    _, bob = room.join("Bob", user="u-bob")
    room.stand(bob)
    room.sit(bob, "E")
    room.new_board()
    t = room.table
    while t.phase != "done":
        seat = t.controller_to_act()
        if t.phase == "bidding":
            t.make_call(t.seat_to_act(), "P")
        else:
            t.play_card(seat, t.play.legal_cards()[0])
    room.record_result()
    assert [(u, r["seat"]) for u, r in room.finished] == [("u-bob", "E")]


def test_snapshot_keeps_who_sits_where():
    room = Room("SNAP")
    room.join("Ann")
    room.join("Bob")
    _, carol = room.join("Carol")
    room.sit(carol, "W")
    room.new_board()
    back = Room.restore(room.snapshot())
    assert {s: p.name for s, p in back.players.items()} == {"S": "Ann", "N": "Bob", "W": "Carol"}
    assert back.table.bot_seats == {"E"}


def test_only_seated_players_change_the_settings():
    room = Room("SETS")
    _, ann = room.join("Ann")
    room.join("Bob")
    _, dan = room.join("Dan")
    room.watch(dan)
    with pytest.raises(ValueError, match="take a seat"):
        asyncio.run(room.handle(None, {"type": "settings", "hints": False}, dan))
    assert room.settings.hints is not False


def test_the_table_answers_a_ping():
    """The app pings to tell a dead connection (an iPhone back from sleep) from a live one."""
    from fastapi.testclient import TestClient

    from bridge import app as server
    client = TestClient(server.app)
    code = client.post("/api/rooms").json()["code"]
    with client.websocket_connect(f"/ws/{code}") as ws:
        ws.send_json({"type": "join", "name": "Ann"})
        while ws.receive_json()["type"] != "state":
            pass
        ws.send_json({"type": "ping"})
        assert ws.receive_json()["type"] == "pong"


async def _listening(_msg):  # an open app, taking the table's updates
    pass


def test_next_board_waits_for_everyone_at_the_table():
    """Nobody loses the score or review they're reading: the next deal waits until every person has tapped Next board,
    except someone who has closed the app or left."""
    async def go():
        room = Room("NEXT")
        room.join("Ann")
        room.join("Bob")
        for p in room.players.values():
            p.connections.add(_listening)  # both have the app open
        room.new_board()
        t = room.table
        while t.phase != "done":  # passed out
            t.make_call(t.seat_to_act(), "P")
        await room.handle("S", {"type": "next_board"})
        assert room.table is t  # still on the board Bob is looking at
        assert room.state_for("S")["next_ready"] and room.state_for("S")["next_waiting"] == ["Bob"]
        assert room.state_for("N")["next_waiting"] == ["Bob"] and not room.state_for("N")["next_ready"]
        await room.handle("N", {"type": "next_board"})
        assert room.table is not t and room.table.board == t.board + 1 and not room.ready
        # Bob closes the app: Ann needn't wait for him
        t = room.table
        while t.phase != "done":
            t.make_call(t.seat_to_act(), "P")
        room.players["N"].connections.clear()
        await room.handle("S", {"type": "next_board"})
        assert room.table.board == t.board + 1

    asyncio.run(go())


def test_someone_leaving_deals_for_those_waiting():
    async def go():
        room = Room("LEFT")
        room.join("Ann")
        room.join("Bob")
        for p in room.players.values():
            p.connections.add(_listening)
        room.new_board()
        t = room.table
        while t.phase != "done":
            t.make_call(t.seat_to_act(), "P")
        await room.handle("S", {"type": "next_board"})
        assert room.table is t
        room.players["N"].away = True  # Bob tapped Leave
        await room.recheck_ready()
        assert room.table.board == t.board + 1

    asyncio.run(go())


def test_watchers_see_all_four_hands_only_once_the_board_is_over():
    room = Room("WDON")
    room.join("Ann")
    room.join("Bob")
    room.new_board()
    _, spy = room.join("Spy", seat=None)
    room.watch(spy)
    seen = lambda: room.state_for(None, room.watchers[spy])["table"]["hands"]
    t = room.table
    for c in ["1C", "P", "P", "P"]:
        t.make_call(t.seat_to_act(), c)
    assert not any(seen().values())  # the opening lead isn't out: nothing showing
    t.play_card(t.controller_to_act(), t.play.legal_cards(t.seat_to_act())[0])
    assert [s for s, h in seen().items() if h] == [t.play.dummy]  # dummy, as everyone at the table sees it
    while t.phase != "done":
        t.play_card(t.controller_to_act(), t.play.legal_cards(t.seat_to_act())[0])
    assert all(seen().values())  # the board is over: every hand


def test_someone_who_left_can_be_covered_by_a_bot_until_they_are_back():
    """When a player taps Leave or has closed the app for 3 minutes, their partner chooses to
    play on with a bot in that seat or to wait; the player gets the seat back on returning."""
    import time

    room = Room("GONE", seed=4)
    _, ann = room.join("Ann")
    _, bob = room.join("Bob")
    room.new_board()
    n = room.person(bob)[0]
    p = room.person(bob)[1]
    assert room.gone() == {}
    with pytest.raises(ValueError):
        room.cover("S", n)  # Bob is still here
    p.away = True  # tapped Leave
    assert room.gone()[n]["left"] and not room.gone()[n]["bot"]
    room.cover("S", n)
    assert n in room.table.bot_seats and room.gone()[n]["bot"]
    restored = Room.restore(room.snapshot())
    assert restored.players[n].covered
    room.join("Bob", bob)  # back
    assert n not in room.table.bot_seats and room.gone() == {}

    # closing the app counts once 3 minutes have passed
    p.last = time.time() - room.AWAY + 5
    assert room.gone() == {}
    p.last = time.time() - room.AWAY - 1
    assert not room.gone()[n]["left"]
    room.new_board()
    room.cover("S", n)
    room.new_board()  # the bot stays on for the next board while they're gone
    assert n in room.table.bot_seats
