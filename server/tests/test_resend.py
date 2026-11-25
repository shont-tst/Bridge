"""A call or card the app sends again after a dropped connection counts once, and never lands at a later moment."""
import asyncio
import os

os.environ["BRIDGE_BOT_DELAY"] = "0"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from bridge.app import app  # noqa: E402
from bridge.game.room import Room  # noqa: E402


@pytest.fixture(autouse=True)
def tmp_data(tmp_path, monkeypatch):
    monkeypatch.setenv("BRIDGE_DATA_DIR", str(tmp_path))


def four_people():
    room = Room("RSND", seed=3)
    room.join("Ann")
    room.join("Bob")
    for name, seat in (("Cy", "E"), ("Di", "W")):
        room.sit(room.join(name)[1], seat)
    room.new_board()
    return room


def at(room):
    t = room.table
    return f"{t.board}/{len(t.actions)}"


def test_the_same_call_sent_twice_counts_once():
    room = four_people()
    seat = room.table.auction.next_to_call
    msg = {"type": "call", "call": "P", "id": "abc", "at": at(room)}

    async def go():
        await room.handle(seat, msg)
        await room.handle(seat, msg)  # the answer got lost, so the app sent it again

    asyncio.run(go())
    assert len(room.table.auction.calls) == 1


def test_a_call_for_a_moment_gone_is_refused():
    room = four_people()
    seat = room.table.auction.next_to_call
    old = at(room)
    nxt = {"N": "E", "E": "S", "S": "W", "W": "N"}

    async def go():
        await room.handle(seat, {"type": "call", "call": "P", "id": "one", "at": old})
        s = nxt[seat]
        await room.handle(s, {"type": "call", "call": "P", "id": "two", "at": at(room)})
        await room.handle(nxt[s], {"type": "call", "call": "P", "id": "three", "at": at(room)})
        # the fourth seat's call, tapped before the others' got there, arrives late: the table has moved on
        with pytest.raises(ValueError, match="moved on"):
            await room.handle(nxt[nxt[s]], {"type": "call", "call": "1C", "id": "four", "at": old})

    asyncio.run(go())
    assert room.table.auction.calls == ["P", "P", "P"]


def test_made_ids_survive_a_restart():
    room = four_people()
    seat = room.table.auction.next_to_call
    msg = {"type": "call", "call": "P", "id": "keep", "at": at(room)}
    asyncio.run(room.handle(seat, msg))
    again = Room.restore(room.snapshot())
    asyncio.run(again.handle(seat, msg))
    assert len(again.table.auction.calls) == 1


def test_the_server_answers_each_call_by_its_id():
    client = TestClient(app)
    code = client.post("/api/rooms").json()["code"]
    with client.websocket_connect(f"/ws/{code}") as ws:
        ws.send_json({"type": "join", "name": "Solo"})
        ws.receive_json()
        ws.send_json({"type": "settings", "solo": True})
        ws.send_json({"type": "next_board"})
        while True:
            msg = ws.receive_json()
            t = msg.get("table") if msg["type"] == "state" else None
            if t and t["your_turn"]:
                break
        step = f"{t['board']}/{t['step']}"
        ws.send_json({"type": "call", "call": "P", "id": "x1", "at": step})
        while (msg := ws.receive_json())["type"] != "ack":
            assert msg["type"] != "error", msg
        assert msg["id"] == "x1"
        ws.send_json({"type": "call", "call": "P", "id": "x1", "at": step})  # sent again: answered, not made twice
        while (msg := ws.receive_json())["type"] != "ack":
            assert msg["type"] != "error", msg
        ws.send_json({"type": "call", "call": "1C", "id": "x2", "at": step})  # tapped for a moment that's gone
        while (msg := ws.receive_json())["type"] not in ("ack", "error"):
            pass
        assert msg["type"] == "error" and msg["id"] == "x2" and "moved on" in msg["message"]
