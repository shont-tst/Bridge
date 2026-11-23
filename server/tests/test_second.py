"""The second table (game/second.py): the same deal played again with level 10 in a person's seat, in IMPs."""
import asyncio
import random

from bridge.bidding.conventions import ALL_CONVENTIONS, make_engine
from bridge.core.auction import Contract
from bridge.core.cards import deal_random
from bridge.core.scoring import imps
from bridge.game import room as room_mod
from bridge.game.room import Room
from bridge.game.second import YARDSTICK, _controller, add_split, fill_split, second_table, side_score
from bridge.game.table import DONE
from bridge.stats import board_facts, summarize

ENGINE = make_engine({c.id for c in ALL_CONVENTIONS if c.default_on})


def test_the_deal_is_played_again_and_scored_in_imps_for_the_seat():
    hands = deal_random(random.Random(3))
    mine = Contract(1, "N", "E")  # what happened at the person's table: East made 1NT, against South
    out = second_table(ENGINE, hands, "N", "None", None, "S", {"S"}, 4, None, True, None, mine, 7,
                       random.Random(1))
    assert out["seat"] == "S" and out["level"] == YARDSTICK
    assert out["table_score"] == -90
    assert out["imps"] == imps(out["table_score"] - out["score"])
    assert [a["call"] for a in out["auction"]][-3:] == ["P", "P", "P"] and all("meaning" in a for a in out["auction"])
    if out["contract"]:
        assert len(out["play"]) == 52  # a claim is played out too
        c = Contract(out["contract"]["level"], out["contract"]["strain"], out["contract"]["declarer"],
                     out["contract"]["doubled"])
        assert out["score"] == side_score(c, out["tricks"], "None", "S", None)


def test_the_yardstick_plays_both_hands_when_a_bot_partner_declares():
    """As at the table: a person opposite a bot declarer plays both hands, so level 10 does in the replay."""
    c = Contract(4, "S", "N")
    assert _controller("N", c, {"S"}) == "S" and _controller("S", c, {"S"}) == "S"
    assert _controller("N", c, {"S", "N"}) == "N" and _controller("S", c, {"S", "N"}) == "N"
    assert _controller("E", c, {"S"}) == "E"


def test_scores_count_the_rubber_part_score():
    c = Contract(2, "H", "S")
    assert side_score(c, 8, "None", "S", {"NS": 60, "EW": 0}) == 60 + 300  # 2♥ finishes the game: game bonus, not part score
    assert side_score(c, 8, "None", "W", None) == -110
    assert side_score(None, 0, "None", "S", None) == 0


def test_the_board_gets_its_second_table_and_is_saved_again(monkeypatch):
    monkeypatch.setattr(room_mod, "BOT_DELAY", 0)

    async def go():
        room = Room("SECD", seed=4)
        room.join("Ann", user="u1")
        room.new_board()
        t = room.table
        t.bot_claims = False
        while t.phase != DONE:
            if t.is_bot_turn():
                t.bot_step()
            elif t.phase == "bidding":
                t.make_call("S", t.hint("S")["call"])
            else:
                t.play_card(t.controller_to_act(), t.play.legal_cards()[0])
        room.record_result()
        review = t.result.review
        assert review["second_pending"] is True
        room.finished.clear()
        await room._fill_odds(t, review)
        assert review["second_pending"] is False and review["odds_pending"] is False
        s = review["second"]["S"]
        assert s["imps"] == imps(s["table_score"] - s["score"])
        saved = [r for u, r in room.finished if u == "u1"]
        assert len(saved) == 2 and saved[-1]["review"]["second"]["S"] == s  # with the odds, then with this
        assert board_facts(saved[-1])["second_imps"] == s["imps"]
        assert s["bidding_imps"] + s["play_imps"] == s["imps"]

    asyncio.run(go())


def test_no_second_table_in_learn_to_play_or_without_the_helper():
    room = Room("TUTR", seed=1)
    room.join("Ann")
    room.new_board()
    assert room._second_seats(room.table) == ["S"]
    room.settings.tutorial = 6
    assert room._second_seats(room.table) == []
    room.settings.tutorial = None
    room.ahead = False
    assert room._second_seats(room.table) == []


def test_my_stats_averages_the_imps():
    facts = [{"role": role, "lost": 0, "lead_cost": None, "makeable": True, "made": True, "score": 0, "par": None,
              "off_system": [], "hints": 0, "undos": 0, "second_imps": x, "second_bidding": bid, "second_play": play}
             for role, x, bid, play in (("declarer", 3, 1, 2), ("defender", -6, 0, -6), ("dummy", 1, 2, -1),
                                        ("declarer", None, None, None))]
    s = summarize(facts)
    assert s["second_imps"] == round(-2 / 3, 2) and s["second_boards"] == 3
    assert s["second_bidding"] == 1 and s["second_declaring"] == 0.5 and s["second_defending"] == -6


def test_the_imps_split_into_bidding_and_play():
    """The bidding's share compares both contracts played double dummy; the play is the rest."""
    dd = {"tricks": {"N": {"N": 9, "S": 9, "E": 4, "W": 4}}}
    out = {"seat": "S", "contract": {"level": 3, "strain": "N", "declarer": "N", "doubled": 0}, "imps": -5}
    add_split(out, Contract(1, "N", "S"), dd, "None", None)  # 1NT+2 (150) against 3NT= (400): -6 from the bidding
    assert out["bidding_imps"] == -6 and out["play_imps"] == 1
    # a board saved before the split was kept gets it when it's read; one without the deal's tricks goes without
    rec = {"contract": {"level": 1, "strain": "N", "declarer": "S"}, "dd": dd, "vulnerability": "None",
           "review": {"second": {"S": {"seat": "S", "contract": out["contract"], "imps": -5}}}}
    assert fill_split(rec)["review"]["second"]["S"]["bidding_imps"] == -6
    rec = {**rec, "dd": None, "review": {"second": {"S": {"seat": "S", "contract": None, "imps": 2}}}}
    assert "bidding_imps" not in fill_split(rec)["review"]["second"]["S"]


def test_saved_boards_get_their_second_table_once(tmp_path):
    """Boards saved before the second table existed get one in the background, once (backfill.py)."""
    from bridge import backfill
    from bridge.accounts import Accounts
    from bridge.core.cards import SEATS
    from bridge.store import SqliteStore

    accounts = Accounts(SqliteStore(tmp_path / "s.db"))
    accounts.store.put("users", "u", "u1", {"name": "Ann"})
    hands = deal_random(random.Random(8))
    rec = {"room": "OLDB", "board": 1, "seat": "S", "finished_at": 1000.0, "dealer": "N", "vulnerability": "None",
           "hands": {s: hands[s].to_pbn() for s in SEATS}, "contract": {"level": 1, "strain": "N", "declarer": "S",
           "doubled": 0}, "declarer_tricks": 7, "score_ns": 90, "difficulty": 4, "bots": ["N", "E", "W"],
           "scoring": "duplicate", "review": {"bidding": [], "play": None}}
    accounts.save_board("u1", rec)
    accounts.save_board("u1", {**rec, "board": 2, "finished_at": 2000.0, "tutorial": 6})  # Learn to play: none
    assert asyncio.run(backfill.run(accounts, pause=0)) == 1
    saved = {r["board"]: r for r in accounts.boards("u1")}
    s = saved[1]["review"]["second"]["S"]
    assert s["table_score"] == 90 and s["imps"] == imps(90 - s["score"])
    assert "second" not in saved[2]["review"]
    assert asyncio.run(backfill.run(accounts, pause=0)) == 0  # done once: not scanned again
