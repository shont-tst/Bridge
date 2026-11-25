"""The home screen's Your tables: every table a player still has a seat at, to go back to or quit."""
import asyncio
import time

from bridge.core.rubber import Line
from bridge.game.room import Room, Rooms
from bridge.store import SqliteStore


def tables(rooms: Rooms, user: str) -> list[dict]:
    return asyncio.run(rooms.tables_of(user))


def test_every_table_with_a_seat_is_listed_newest_first():
    rooms = Rooms()
    practice = rooms.create()
    practice.join("Ann", None, None, "u1")
    practice.update_settings(solo=True)
    practice.rubber.lines.append(Line(1, "NS", "below", 70, "2♠"))
    practice.rubber.lines.append(Line(2, "EW", "below", 30, "1♣"))
    practice.board_no = 4
    friends = rooms.create()
    friends.join("Ann", None, None, "u1")
    friends.join("Bea", None, None, "u2")
    friends.players["N"].connections.add(lambda *_: None)  # Bea has it open
    friends.players["S"].last = time.time() - 3600  # Ann played there an hour ago
    friends.board_no = 2
    rooms.create().join("Cat", None, None, "u3")  # someone else's table
    tutorial = rooms.create()
    tutorial.join("Ann", None, None, "u1")
    tutorial.settings.tutorial = 6  # Learn to play has its own way back
    tutorial.players["S"].last = time.time() + 60

    got = tables(rooms, "u1")
    assert [t["room"] for t in got] == [practice.code, friends.code]
    assert got[0] | {"last": 0} == {"room": practice.code, "seat": "S", "board": 4, "people": [], "here": [],
                                    "we": 70, "they": 30, "last": 0, "lesson": None}
    assert (got[1]["people"], got[1]["here"], got[1]["board"]) == (["Bea"], ["Bea"], 2)
    assert [t["room"] for t in tables(rooms, "u2")] == [friends.code]

    friends.players["S"].last = time.time() - 3 * 24 * 3600  # 2 days on, it drops off
    assert [t["room"] for t in tables(rooms, "u1")] == [practice.code]


def test_quit_from_the_list_ends_a_bot_table_and_gives_a_seat_with_people_to_a_bot():
    rooms = Rooms()
    practice = rooms.create()
    practice.join("Ann", None, None, "u1")
    friends = rooms.create()
    friends.join("Ann", None, None, "u1")
    friends.join("Bea", None, None, "u2")
    assert asyncio.run(rooms.quit_mine("u1", practice.code))
    assert practice.code not in rooms.rooms
    assert asyncio.run(rooms.quit_mine("u1", friends.code))
    assert [p.name for p in friends.players.values()] == ["Bea"]  # the table goes on for Bea
    assert tables(rooms, "u1") == []
    assert not asyncio.run(rooms.quit_mine("u1", friends.code))  # not seated there any more
    assert not asyncio.run(rooms.quit_mine("u3", friends.code))


def test_a_bot_table_on_another_phone_is_listed_and_can_be_claimed_or_quit():
    rooms = Rooms()
    room = Room("HOME")
    _, token = room.join("Ann", None, None, "u1")
    room.update_settings(solo=True)
    room.new_board()
    rooms.park("u1", room.snapshot(), token)
    got = tables(rooms, "u1")
    assert [(t["room"], t.get("parked")) for t in got] == [("HOME", True)]
    assert asyncio.run(rooms.quit_mine("u1", "parked:HOME"))
    assert tables(rooms, "u1") == []
    assert rooms.was_closed("HOME", token)  # the phone holding it lets it go

    room2 = Room("HOME")
    _, token2 = room2.join("Ann", None, None, "u1")
    room2.update_settings(solo=True)
    room2.new_board()
    rooms.park("u1", room2.snapshot(), token2)
    code = rooms.claim_parked("u1")
    assert code in rooms.rooms
    assert [(t["room"], t.get("parked")) for t in tables(rooms, "u1")] == [(code, None)]


def test_tables_in_storage_after_a_deploy_are_listed(tmp_path):
    store = SqliteStore(tmp_path / "t.db", durable=True)
    rooms = Rooms(store)
    friends = rooms.create()
    friends.join("Ann", None, None, "u1")
    friends.join("Bea", None, None, "u2")
    rooms.save_all()
    after = Rooms(store)  # a new copy of the server: nothing in memory yet
    got = tables(after, "u1")
    assert [(t["room"], t["people"], t["here"]) for t in got] == [(friends.code, ["Bea"], [])]
    asyncio.run(after.quit_mine("u1", friends.code))  # brought into memory, and Ann's seat goes to a bot
    assert tables(after, "u1") == []
