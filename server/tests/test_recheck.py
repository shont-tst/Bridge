"""Saved boards checked again after a change of the bidding rules (recheck.py)."""
import asyncio
import random

from bridge import recheck
from bridge.accounts import Accounts
from bridge.bidding.conventions import make_engine
from bridge.core.auction import Auction
from bridge.core.cards import SEATS, deal_random
from bridge.store import SqliteStore


def _board(seed: int = 1) -> dict:
    """A board bid by today's system in every seat, South a person, with a review row the old rules wrote: it says the
    system would have passed where South made today's system call."""
    hands = deal_random(random.Random(seed))
    engine, a = make_engine(), Auction("N")
    while not a.is_complete():
        a.add(engine.choose(hands[a.next_to_call], a, None, "None").call)
    south = next(i for i, (s, c) in enumerate(a.with_seats()) if s == "S" and c != "P")
    return {"room": "OLDR", "board": 1, "seat": "S", "finished_at": 1000.0, "dealer": "N", "vulnerability": "None",
            "hands": {s: hands[s].to_pbn() for s in SEATS}, "calls": list(a.calls), "bots": ["N", "E", "W"],
            "scoring": "duplicate", "contract": None, "play": [],
            "review": {"bidding": [{"index": south, "seat": "S", "call": a.calls[south], "system_call": "P",
                                    "meaning": "", "system_meaning": "", "minor": False, "convention": None}],
                       "play": None}}


def test_a_call_the_system_now_makes_drops_out_of_the_review():
    rec = _board()
    assert recheck.recheck(rec)
    assert rec["review"]["bidding"] == [] and rec["rules"] == recheck.RULES
    assert rec["calls"] == _board()["calls"]  # the calls themselves are never touched
    assert not recheck.recheck(rec)  # nothing more to change


def test_saved_boards_are_checked_once_per_change_of_the_rules(tmp_path):
    accounts = Accounts(SqliteStore(tmp_path / "s.db"))
    accounts.store.put("users", "u", "u1", {"name": "Ann"})
    accounts.save_board("u1", _board())
    accounts.save_board("u1", {**_board(), "board": 2, "finished_at": 2000.0, "tutorial": 6})  # Learn to play: left
    assert asyncio.run(recheck.run(accounts, pause=0)) == 1
    saved = {r["board"]: r for r in accounts.boards("u1")}
    assert saved[1]["review"]["bidding"] == [] and saved[1]["rules"] == recheck.RULES
    assert saved[2]["review"]["bidding"] and "rules" not in saved[2]
    assert asyncio.run(recheck.run(accounts, pause=0)) == 0  # done once: not scanned again
