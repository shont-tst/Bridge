"""Your mistakes (puzzles.py) and playing a deal again (game/replay.py)."""
import asyncio
import random

import pytest

from bridge.bidpath import VERSION
from bridge.core.auction import Auction
from bridge.game import room as room_mod
from bridge.game.replay import COME_BACK, RETIRE, check
from bridge.game.room import Room
from bridge.game.table import BIDDING, DONE, PLAYING
from bridge.puzzles import KINDS, Puzzles, kind_of, parse_id, puzzle_id, spots
from bridge.stats import board_facts
from bridge.store import SqliteStore


def played_board(seed: int = 5) -> dict:
    """A real board saved to the account of the person in South, who bids the system's calls and plays their first
    legal card (a bot sits North)."""
    while True:
        room = Room("PLAY", seed=seed)
        room.join("Ann", user="u1")
        room.update_settings(solo=True)
        room.new_board()
        t = room.table
        while t.phase != DONE:
            if t.is_bot_turn():
                t.bot_step()
            elif t.phase == BIDDING:
                t.make_call("S", t.hint("S")["call"])
            else:
                t.play_card(t.controller_to_act(), t.play.legal_cards()[0])
        if t.contract:
            break
        seed += 1
    room.record_result()
    rec = dict(room.finished[-1][1])
    rec["key"] = "0001.000-PLAY-1"
    return rec


@pytest.fixture(scope="module")
def board():
    return played_board()


def with_mistake(rec: dict, all_odds: bool = True) -> tuple[dict, int]:
    """The board with South's first card from trick 3 on marked a Mistake, as the review would."""
    rec = {**rec, "review": {**rec["review"], "play": {**rec["review"]["play"]}}}
    cards = [dict(c) for c in rec["review"]["play"]["cards"]]
    i = next(i for i, c in enumerate(cards) if c["by"] == "S" and c["trick"] >= 3)
    c = cards[i]
    odds = {"goal": "make", "samples": 100, "tricks": 9, "played": 20, "best": c["card"], "best_pct": 80,
            "better": True, "hindsight": None, "hindsight_pct": None}
    if all_odds:  # every legal card's %, as boards keep from now on: the played card worst, every other one best
        odds["all"] = {}
    c.update(lost=1, best=[], odds=odds)
    rec["review"]["play"]["cards"] = cards
    return rec, i


class Accounts:
    """Just the saved boards, as accounts.Accounts keeps them."""

    def __init__(self, *recs):
        self.recs = {r["key"]: r for r in recs}

    def board(self, user, key):
        return self.recs.get(key)

    def facts(self, user):
        return [board_facts(r) for r in self.recs.values()]


def legal_at(spec):
    room = Room("LOOK")
    room.start_replay(spec)
    room.join("Ann")
    room.new_board()
    return room.table


def test_only_your_own_mistakes_and_costly_calls_are_puzzles(board):
    rec, i = with_mistake(board)
    rec["review"]["bidding"] = [
        {"index": 1, "seat": "S", "call": "1N", "system_call": "2N", "outcome": {"avg": {"points_ns": -90},
                                                                                "actual_dd_ns": 0, "system_dd_ns": 0}},
        {"index": 2, "seat": "S", "call": "2C", "system_call": "2D", "outcome": {"avg": {"points_ns": 90},
                                                                                "actual_dd_ns": 0, "system_dd_ns": 0}},
        {"index": 3, "seat": "W", "call": "3C", "system_call": "P", "outcome": {"avg": {"points_ns": 200},
                                                                               "actual_dd_ns": 0, "system_dd_ns": 0}},
    ]
    cards = rec["review"]["play"]["cards"]
    cards[0] = {**cards[0], "lost": 1, "odds": {"better": True}}  # a bot's mistake: not yours
    unlucky = next(j for j, c in enumerate(cards) if c["by"] == "S" and j != i)
    cards[unlucky] = {**cards[unlucky], "lost": 1, "odds": {"better": False, "best": "SA", "played": 60}}
    assert spots(rec, "S") == [{"kind": "call", "index": 1}, {"kind": "card", "index": i}]
    assert board_facts(rec)["puzzles"] == spots(rec, "S")
    pid = puzzle_id(rec["key"], {"kind": "card", "index": i})
    assert parse_id(pid) == (rec["key"], "card", i) and parse_id("nonsense") is None


def test_a_wrong_answer_comes_back_in_three_days_and_two_right_answers_retire_it(board, tmp_path):
    rec, i = with_mistake(board)
    p = Puzzles(SqliteStore(tmp_path / "s.db"), Accounts(rec))
    pid = puzzle_id(rec["key"], {"kind": "card", "index": i})
    assert p.queue("u1") == [pid] and p.summary("u1")["waiting"] == 1
    p.mark("u1", pid, False, now=1000)
    assert p.queue("u1", now=1000 + COME_BACK - 1) == []
    assert p.queue("u1", now=1000 + COME_BACK) == [pid]
    for n in range(RETIRE):
        p.mark("u1", pid, True, now=2000 + n)
    assert p.queue("u1", now=10 ** 12) == []
    assert p.summary("u1") == {"waiting": 0, "kinds": dict.fromkeys(KINDS, 0), "tried": 1, "right": 2, "wrong": 1, "done": 1, "removed": 0}


def test_new_puzzles_come_before_ones_coming_back(board, tmp_path):
    rec, i = with_mistake(board)
    rec["review"]["bidding"] = [{"index": 1, "seat": "S", "call": "1N", "system_call": "2N",
                                 "outcome": {"v": VERSION, "avg": {"points_ns": -90}, "actual_dd_ns": 0, "system_dd_ns": 0}}]
    p = Puzzles(SqliteStore(tmp_path / "s.db"), Accounts(rec))
    call, card = p.queue("u1")
    p.mark("u1", call, False, now=1000)
    assert p.queue("u1", now=1000 + COME_BACK) == [card, call]


def test_puzzles_can_be_picked_by_kind(board, tmp_path):
    rec, i = with_mistake(board)
    rec["review"]["bidding"] = [{"index": 1, "seat": "S", "call": "1N", "system_call": "2N",
                                 "outcome": {"v": VERSION, "avg": {"points_ns": -90}, "actual_dd_ns": 0, "system_dd_ns": 0}}]
    p = Puzzles(SqliteStore(tmp_path / "s.db"), Accounts(rec))
    call, card = p.queue("u1")
    f = board_facts(rec)
    card_kind = kind_of(f, {"kind": "card", "index": i})
    assert p.queue("u1", kinds={"bidding"}) == [call]
    assert p.queue("u1", kinds={card_kind}) == [card]
    kinds = p.summary("u1")["kinds"]
    assert kinds["bidding"] == 1 and kinds[card_kind] == 1 and sum(kinds.values()) == 2


def test_a_card_is_sorted_by_who_played_it_and_the_contract():
    f = {"seat": "S", "contract": {"declarer": "S", "strain": "N"}}
    assert kind_of(f, {"kind": "call", "index": 3}) == "bidding"
    assert kind_of(f, {"kind": "card", "index": 5}) == "notrump"
    assert kind_of({**f, "contract": {"declarer": "S", "strain": "H"}}, {"kind": "card", "index": 5}) == "suit"
    # with a bot partner declaring, the player plays both hands
    assert kind_of({**f, "contract": {"declarer": "N", "strain": "H"}}, {"kind": "card", "index": 5}) == "suit"
    assert kind_of({**f, "contract": {"declarer": "W", "strain": "N"}}, {"kind": "card", "index": 0}) == "leads"
    assert kind_of({**f, "contract": {"declarer": "W", "strain": "N"}}, {"kind": "card", "index": 7}) == "defense"


def test_a_removed_puzzle_never_comes_back(board, tmp_path):
    rec, i = with_mistake(board)
    p = Puzzles(SqliteStore(tmp_path / "s.db"), Accounts(rec))
    pid = puzzle_id(rec["key"], {"kind": "card", "index": i})
    p.mark("u1", pid, False, now=1000)
    p.mark("u1", pid, None, now=1001)
    assert p.queue("u1", now=10 ** 12) == []
    assert p.summary("u1") == {"waiting": 0, "kinds": dict.fromkeys(KINDS, 0), "tried": 1, "right": 0, "wrong": 1, "done": 0, "removed": 1}


def test_a_card_puzzle_is_set_up_at_the_spot_and_judged_without_playing_the_card(board, tmp_path, monkeypatch):
    monkeypatch.setattr(room_mod, "BOT_DELAY", 0)
    rec, i = with_mistake(board)
    p = Puzzles(SqliteStore(tmp_path / "s.db"), Accounts(rec))
    pid = p.queue("u1")[0]
    spec = p.spec("u1", pid)
    assert spec["seat"] == "S" and spec["from"] == len(rec["calls"]) + i and spec["puzzle"]["card"] == rec["play"][i][1]
    original = rec["play"][i][1]
    t = legal_at(spec)
    other = next((c for c in t.play.legal_cards() if c != original), None)
    if other is None:
        pytest.skip("only one card to play there")
    spec["puzzle"]["odds"]["all"] = {original: 20, other: 80}

    async def go():
        room = Room("PUZZ", seed=1)
        room.start_replay(spec, [pid], 0, "u1")
        seat, _ = room.join("Ann", user="u1")
        assert seat == "S"
        room.new_board()
        t = room.table
        assert t.fixed == len(t.actions) == spec["from"] and t.phase == PLAYING
        assert not room.carriable() and room.state_for("S")["can_skip"] is False
        with pytest.raises(ValueError):
            await room.hint("S")
        await room.handle("S", {"type": "play", "card": original})
        answer = room.settings.replay["answer"]
        assert answer["right"] is False and answer["better"] == other and answer["original"] == original
        assert answer["pct"] == {original: 20, other: 80} and answer["right_count"] == 0
        assert len(t.actions) == spec["from"]  # nothing was played
        state = room.state_for("S")
        assert state["table"]["your_turn"] is False and state["table"]["legal_cards"] == []
        assert state["settings"]["replay"]["answer"] == answer and "hands" not in state["settings"]["replay"]
        assert room.puzzle_marks == [("u1", pid, False)]
        # Don't show this again: they disagree it was a mistake (saved once)
        await room.handle("S", {"type": "puzzle_remove"})
        await room.handle("S", {"type": "puzzle_remove"})
        assert room.settings.replay["answer"]["removed"] is True
        assert room.puzzle_marks == [("u1", pid, False), ("u1", pid, None)]
        # Try again: the same spot, judged again but not saved, since the first answer is the one that counts
        await room.handle("S", {"type": "puzzle_retry"})
        assert room.settings.replay["answer"] is None and room.state_for("S")["table"]["your_turn"] is True
        await room.handle("S", {"type": "play", "card": other})
        again = room.settings.replay["answer"]
        assert again["right"] is True and again["retry"] is True and again["retired"] is False
        assert again["right_count"] == 0 and again["removed"] is True and len(t.actions) == spec["from"]
        assert len(room.puzzle_marks) == 2
        for kind in ("puzzle_retry", "puzzle_remove"):  # only after a wrong answer
            with pytest.raises(ValueError):
                await room.handle("S", {"type": kind})
        await room.handle("S", {"type": "play_on"})
        await room.handle("S", {"type": "play", "card": other})
        assert room.table.actions[-1][2] == other  # playing on: cards are played
        await room.handle("S", {"type": "replay"})  # Play this deal again: from the first call
        assert room.table.fixed == 0 and room.table.board == rec["board"]

    asyncio.run(go())


def test_card_puzzle_works_out_odds_older_boards_did_not_keep(board, monkeypatch):
    """Boards saved before Your mistakes kept only the played and best cards' %: every card's is worked out again."""
    monkeypatch.setattr(room_mod, "BOT_DELAY", 0)
    rec, i = with_mistake(board, all_odds=False)
    p = Puzzles(SqliteStore(":memory:"), Accounts(rec))
    spec = p.spec("u1", p.queue("u1")[0])
    spec["puzzle"]["reach"] = rec["review"]["play"]["cards"][i].get("reach")

    async def go():
        room = Room("PUZ2", seed=1)
        room.start_replay(spec, ["x"], 0, None)
        room.join("Ann")
        room.new_board()
        card = room.table.play.legal_cards()[0]
        await room.handle("S", {"type": "play", "card": card})
        a = room.settings.replay["answer"]
        assert card in a["pct"] and card in a["dd"] and isinstance(a["right"], bool)
        assert room.puzzle_marks == []  # nobody's to save

    asyncio.run(go())


def test_a_bidding_puzzle_takes_the_systems_call(board):
    rec = dict(board)
    calls = rec["calls"]
    i = next(j for j in range(len(calls)) if "NESW"[("NESW".index(rec["dealer"]) + j) % 4] == "S")
    system = next(c for c in Auction(rec["dealer"], calls[:i]).legal_calls() if c != calls[i])
    rec["review"] = {**rec["review"], "bidding": [
        {"index": i, "seat": "S", "call": calls[i], "system_call": system, "meaning": "what it meant",
         "outcome": {"v": VERSION, "avg": {"points_ns": -120}, "actual_dd_ns": 0, "system_dd_ns": 0}}]}
    p = Puzzles(SqliteStore(":memory:"), Accounts(rec))
    spec = p.spec("u1", p.queue("u1")[0])
    assert spec["from"] == i and spec["puzzle"]["cost"] == 120 and spec["puzzle"]["average"] is True

    async def go(answer):
        room = Room("BIDS", seed=1)
        room.start_replay(spec, ["b"], 0, "u1")
        room.join("Ann", user="u1")
        room.new_board()
        assert room.table.phase == BIDDING and len(room.table.auction.calls) == i
        await room.handle("S", {"type": "call", "call": answer})
        assert len(room.table.auction.calls) == i
        return room.settings.replay["answer"]

    a = asyncio.run(go(system))
    assert a["right"] is True and a["right_count"] == 1 and a["retired"] is False and a["cost"] == 120
    a = asyncio.run(go(calls[i]))
    assert a["right"] is False and a["original_meaning"] == "what it meant" and a["system_call"] == system


def test_replays_stay_out_of_my_stats_and_off_the_way_back(board, monkeypatch):
    monkeypatch.setattr(room_mod, "BOT_DELAY", 0)
    spec = {k: board[k] for k in ("board", "dealer", "vulnerability", "hands", "calls", "play")}
    spec.update(seat="S", **{"from": len(board["calls"]) + 4})
    room = Room("AGAIN", seed=2)
    room.start_replay(spec)
    room.join("Ann", user="u1")
    room.new_board()
    t = room.table
    assert len(t.play.played_cards()) == 4 and t.fixed == len(t.actions)
    with pytest.raises(ValueError):
        t.undo()  # the cards it starts from can't be taken back
    while t.phase != DONE:
        if t.is_bot_turn():
            t.bot_step()
        else:
            t.play_card(t.controller_to_act(), t.play.legal_cards()[0])
    room.record_result()
    assert room.finished == [] and room._second_seats(t) == []
    rooms = room_mod.Rooms()
    rooms._adopt(room)
    assert asyncio.run(rooms.table_for("u1")) is None


def test_a_deal_from_the_app_is_checked():
    good = {"hands": {"N": "AKQJ.AKQ.AKQ.AKQ", "E": "T987.JT9.JT9.JT9", "S": "6543.876.876.876",
                      "W": "2.5432.5432.5432"}, "dealer": "N", "vulnerability": "None", "seat": "S"}
    assert check(good)["from"] == 0
    for bad in ({**good, "hands": {**good["hands"], "W": good["hands"]["S"]}}, {**good, "seat": "X"},
                {**good, "dealer": None}, {**good, "calls": ["1C", "8Z"], "from": 2}):
        with pytest.raises((ValueError, KeyError)):
            Room("BAD").start_replay(bad)


def test_the_ai_coach_gets_a_summary_it_can_read(board, tmp_path):
    from test_connector_fields import undescribed
    rec, i = with_mistake(board)
    p = Puzzles(SqliteStore(tmp_path / "s.db"), Accounts(rec))
    p.mark("u1", p.queue("u1")[0], False)
    assert not undescribed("coaching_overview", {"your_mistakes": p.summary("u1")})
