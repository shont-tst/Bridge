"""Learn to play steps 6 and 7: a real table set up as a lesson, kept out of My stats."""
import os

os.environ["BRIDGE_BOT_DELAY"] = "0"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from bridge import app as app_module  # noqa: E402
from bridge.core.auction import Auction  # noqa: E402
from bridge.game.room import Player, Room  # noqa: E402
from bridge.game.table import DONE  # noqa: E402


def play_through(room):
    t = room.table
    while t.phase != DONE:
        if t.is_bot_turn():
            t.bot_step()
        elif t.phase == "bidding":
            seat = t.seat_to_act()
            t.make_call(seat, room.engine.choose(t.hands[seat], t.auction).call)
        else:
            seat = t.seat_to_act()
            t.play_card(t.controller_of(seat), t.play.legal_cards(seat)[0])


def test_step_6_table_settings_and_deals():
    room = Room("TUT6", seed=3)
    room.update_settings(difficulty=9, hints=False, scoring="rubber")  # what the player last chose elsewhere
    room.start_tutorial(6)
    s = room.settings
    assert (s.tutorial, s.difficulty, s.hints, s.undo, s.solo, s.scoring, s.ai_coach) == (6, 2, True, True, True, "duplicate", False)
    room.players["S"] = Player("Pat", "tok", user="u1")
    wanted = [lambda c: c == "P", lambda c: c in ("1H", "1S"), lambda c: c in ("1C", "1D"), lambda c: c == "1N"]
    for board, test in enumerate(wanted, 1):
        room.new_board()
        t = room.table
        assert t.dealer == "S"
        assert test(room.engine.choose(t.hands["S"], Auction("S")).call), board
        # the app is told the cheat sheet's call on South's turn
        assert room.state_for("S", room.players["S"])["tutorial_call"] == room.engine.choose(t.hands["S"], t.auction).call
    room.new_board()  # hand 5: partner opens a major and South raises
    t = room.table
    assert t.dealer == "N"


def test_tutorial_boards_stay_out_of_my_stats():
    room = Room("TUT7", seed=4)
    room.start_tutorial(7)
    assert room.settings.scoring == "rubber"
    room.players["S"] = Player("Pat", "tok", user="u1")
    room.new_board()
    play_through(room)
    room.record_result()
    assert room.finished == [] and room.history[-1]["tutorial"] == 7
    assert room.rubber.lines or room.history[-1]["contract"] is None  # the rubber is still scored


def test_create_route_starts_a_tutorial_table():
    client = TestClient(app_module.app)
    code = client.post("/api/rooms", json={"tutorial": 7}).json()["code"]
    room = app_module.rooms.get(code)
    assert room.settings.tutorial == 7 and room.settings.difficulty == 2
    assert room.settings.to_dict()["tutorial"] == 7


@pytest.mark.parametrize("step", [3, "x"])
def test_create_route_refuses_other_steps(step):
    assert TestClient(app_module.app).post("/api/rooms", json={"tutorial": step}).status_code == 400


def test_a_saved_tutorial_table_comes_back_as_one():
    room = Room("TUTS", seed=6)
    room.start_tutorial(6)
    room.players["S"] = Player("Pat", "tok")
    room.new_board()
    again = Room.restore(room.snapshot())
    assert again.settings.tutorial == 6
