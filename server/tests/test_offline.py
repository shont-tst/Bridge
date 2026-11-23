"""Playing with no internet: the engine the app downloads, and tables going between the app and the server."""
import io
import re
import zipfile
from pathlib import Path

import pytest

from bridge.game.room import Room, Rooms, TableClosed
from bridge.offline import EXTRA, bundle

SERVER = Path(__file__).resolve().parents[1]


def test_the_engine_holds_the_game_and_not_the_accounts():
    data, tag = bundle()
    names = set(zipfile.ZipFile(io.BytesIO(data)).namelist())
    assert {"bridge/local.py", "bridge/game/room.py", "bridge/bots/calibration.json", "endplay/_dds/libdds.so",
            "more_itertools.py"} <= names
    assert not names & {"bridge/app.py", "bridge/accounts.py", "bridge/admin.py", "bridge/connector.py"}
    assert bundle() == (data, tag)  # made once, the same each time


def test_the_engines_endplay_is_the_servers():
    """The app's solver and card types come from the same endplay as the server's, so both play alike."""
    pinned = re.search(r"^endplay==(\S+)", (SERVER / "requirements.txt").read_text(), re.M).group(1)
    ours = re.search(r'__version__ = "([^"]+)"', (EXTRA / "endplay" / "config.py").read_text()).group(1)
    assert ours == pinned, "rebuild server/offline/endplay with server/offline/dds/build.sh"


def test_the_offline_endplay_calls_dds_by_pointer():
    text = (EXTRA / "endplay" / "_dds" / "__init__.py").read_text()
    assert "_dll.CalcDDtablePtr(ctypes.byref(tableDeal)" in text
    assert "_dll.CalcDDtable(" not in text


def _solo(rooms: Rooms) -> tuple[Room, str]:
    room = rooms.create()
    _, token = room.join("Pat", None, None, "u1")
    room.update_settings(solo=True)
    room.new_board()
    return room, token


def test_a_carried_table_comes_back_with_its_code():
    rooms = Rooms()
    room, token = _solo(rooms)
    snap = room.snapshot()
    snap["rev"] += 5  # played on in the app
    back = rooms.carry_back(snap, token, "u1")
    assert back.code == room.code and rooms.rooms[room.code] is back
    assert back.players["S"].user == "u1"


def test_a_table_started_offline_gets_a_code_and_the_signed_in_account():
    rooms = Rooms()
    room = Room("HOME")
    _, token = room.join("Pat", None, None, "someone-else")
    room.new_board()
    back = rooms.carry_back(room.snapshot(), token, "u1")
    assert back.code != "HOME" and back.code in rooms.rooms
    assert back.players["S"].user == "u1"  # never another account's


def test_only_your_own_table_with_bots_comes_back():
    rooms = Rooms()
    room, token = _solo(rooms)
    with pytest.raises(ValueError):
        rooms.carry_back(room.snapshot(), "not-the-token", None)
    two = Room("ZZZZ")
    _, t2 = two.join("Pat", None, None)
    two.join("Kim", None, None)
    with pytest.raises(ValueError):
        rooms.carry_back(two.snapshot(), t2, None)
    with pytest.raises(ValueError):
        rooms.carry_back({"nonsense": True}, token, None)


def test_someone_elses_table_with_the_same_code_isnt_replaced():
    rooms = Rooms()
    room, token = _solo(rooms)
    other = Room(room.code)  # the server let go of the table and gave its code to someone else
    _, t2 = other.join("Kim", None, None)
    rooms.rooms[room.code] = other
    back = rooms.carry_back(room.snapshot(), token, None)
    assert back.code != room.code and rooms.rooms[room.code] is other


def test_a_solo_table_sends_its_snapshot_to_a_phone_that_asks():
    import asyncio

    async def go():
        room = Room("CARY")
        _, token = room.join("Pat", None, None)
        got: list[dict] = []

        async def send(msg):
            got.append(msg)
        send.carry = True
        room.players["S"].connections.add(send)
        room.new_board()
        await room.broadcast()
        assert [m["type"] for m in got] == ["state", "carry"]
        assert got[1]["snap"]["code"] == "CARY"
        room.join("Kim", None, None)  # with someone else at the table, the phone can't hold the cards
        got.clear()
        await room.broadcast()
        assert [m["type"] for m in got] == ["state"]

    asyncio.run(go())


def test_a_bot_table_on_the_phone_moves_to_the_ipad_and_the_phone_follows():
    import asyncio
    rooms = Rooms()
    room = Room("HOME")
    _, token = room.join("Pat", None, None, "u1")
    room.update_settings(solo=True)
    room.new_board()
    assert rooms.park("u1", room.snapshot(), token) is None
    found = asyncio.run(rooms.table_for("u1"))  # the app opened on the iPad
    assert found["jump"] and found["room"] in rooms.rooms
    assert rooms.rooms[found["room"]].players["S"].user == "u1"
    # the phone's next copy hears where its table went
    assert rooms.park("u1", room.snapshot(), token) == found["room"]
    assert asyncio.run(rooms.table_for("u1"))["room"] == found["room"]  # not claimed twice
    # the iPad gets a copy too, to carry on with if it loses the internet before sitting down
    assert rooms.copy_for("u1", found["room"])["code"] == found["room"]
    assert rooms.copy_for("u2", found["room"]) is None
    rooms.rooms[found["room"]].join("Kim", None, None, "u2")
    assert rooms.copy_for("u1", found["room"]) is None  # with someone else at the table, no


def test_a_parked_table_someone_left_is_offered_but_not_jumped_to():
    import asyncio
    rooms = Rooms()
    room = Room("HOME")
    _, token = room.join("Pat", None, None, "u1")
    room.new_board()
    room.players["S"].away = True
    rooms.park("u1", room.snapshot(), token)
    found = asyncio.run(rooms.table_for("u1"))
    assert found and not found["jump"]
    rooms.unpark("u2")
    assert asyncio.run(rooms.table_for("u2")) is None


def test_a_table_closed_on_the_admin_page_ends_on_the_phone_too(tmp_path):
    import asyncio
    from bridge.store import SqliteStore
    store = SqliteStore(tmp_path / "t.db")
    rooms = Rooms(store)
    room = Room("HOME")
    _, token = room.join("Pat", None, None, "u1")
    room.update_settings(solo=True)
    room.new_board()
    rooms.park("u1", room.snapshot(), token)
    found = asyncio.run(rooms.table_for("u1"))  # the iPad picked it up
    code = found["room"]
    snap = rooms.rooms[code].snapshot()
    rooms.close(code)
    assert code not in rooms.rooms and "u1" not in rooms.parked
    assert asyncio.run(rooms.table_for("u1")) is None
    with pytest.raises(TableClosed):  # the phone's next copy hears it was closed
        rooms.park("u1", snap, token)
    with pytest.raises(TableClosed):  # and it can't come back
        rooms.carry_back(snap, token, "u1")
    assert Rooms(store).was_closed(code)  # still known after a restart
    assert not rooms.was_closed("ZZZZ")
    rooms.close("HOME")  # the code every table on a phone starts with: never closed for everyone
    assert not rooms.was_closed("HOME")


def test_a_table_that_came_back_to_a_device_isnt_sent_back_to_the_server():
    import asyncio
    rooms = Rooms()
    room = Room("HOME")
    _, token = room.join("Pat", None, None, "u1")
    room.update_settings(solo=True)
    room.new_board()
    rooms.park("u1", room.snapshot(), token, "phone")
    code = asyncio.run(rooms.table_for("u1"))["room"]  # the iPad picked it up
    assert rooms.park("u1", room.snapshot(), token, "phone") == code  # the phone follows
    # between boards the table moves onto the iPad: its copies are parked, not sent back to the server
    assert rooms.park("u1", rooms.rooms[code].snapshot(), token, "ipad") is None
    assert rooms.park("u1", rooms.rooms[code].snapshot(), token, "ipad") is None


def test_two_devices_playing_the_same_table_meet_at_the_one_further_on():
    import asyncio
    rooms = Rooms()
    room = Room("HOME")
    _, token = room.join("Pat", None, None, "u1")
    room.update_settings(solo=True)
    room.new_board()
    a, b = room.snapshot(), room.snapshot()  # both devices carried on with the same copy, with no internet
    b["rev"] = a["rev"] + 5  # the iPad played further
    assert rooms.park("u1", a, token, "phone") is None
    code = rooms.park("u1", b, token, "ipad")  # back online: two devices at once
    assert code and rooms.rooms[code].rev >= b["rev"]
    assert rooms.park("u1", a, token, "phone") == code  # the phone follows too
    assert rooms.park("u1", rooms.rooms[code].snapshot(), token, "ipad") is None  # later, back on the iPad: fine
    assert asyncio.run(rooms.table_for("u1"))["room"] == code


def test_closing_the_table_an_ipad_picked_up_ends_the_phones_own_copy():
    import asyncio
    rooms = Rooms()
    room = Room("HOME")  # started on the phone: "HOME" there
    _, token = room.join("Pat", None, None, "u1")
    room.update_settings(solo=True)
    room.new_board()
    rooms.park("u1", room.snapshot(), token, "phone")
    code = asyncio.run(rooms.table_for("u1"))["room"]  # the iPad picked it up: a code here
    assert code != "HOME"
    rooms.close(code)
    assert rooms.was_closed("HOME", token)  # the phone's copy, found by its seat
    assert not rooms.was_closed("HOME") and not rooms.was_closed("HOME", "someone else")
    with pytest.raises(TableClosed):
        rooms.park("u1", room.snapshot(), token, "phone")


def test_quitting_a_bot_table_ends_it_everywhere_and_a_table_with_people_goes_on():
    import asyncio
    rooms = Rooms()
    room = rooms.create()
    _, token = room.join("Pat", None, None, "u1")
    room.update_settings(solo=True)
    room.new_board()
    rooms.park("u1", room.snapshot(), token, "phone")
    asyncio.run(rooms.quit(room.code, token))
    assert room.code not in rooms.rooms and "u1" not in rooms.parked
    assert rooms.was_closed("HOME", token)  # a copy on a phone ends too
    with pytest.raises(TableClosed):
        rooms.park("u1", room.snapshot(), token, "phone")
    # with someone else at the table, it goes on for them and the bot takes the seat
    shared = rooms.create()
    _, mine = shared.join("Pat", None, None, "u1")
    _, theirs = shared.join("Kim", None, None, "u2")
    asyncio.run(rooms.quit(shared.code, mine))
    assert shared.code in rooms.rooms and shared.person(mine)[0] is None and shared.person(theirs)[0] is not None
    assert shared.person(mine)[1] is None and shared.carriable()  # not left watching: the table can go to Kim's phone
    assert asyncio.run(rooms.table_for("u1")) is None
    # a table only on a phone (never here) ends by its seat, and nobody else's "HOME" table does
    asyncio.run(rooms.quit("HOME", "phone-seat"))
    assert rooms.was_closed("HOME", "phone-seat") and not rooms.was_closed("HOME", "other-seat")
