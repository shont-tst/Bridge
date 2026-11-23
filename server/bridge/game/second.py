"""The second table: the same deal played again with the strongest bot in a person's seat, scored against the
person's own result in IMPs, as at a team match.

The other three seats stay as they were at the person's table: each bot at the table's strength. A seat another
person played gets a bot at the table's strength too, since people can't be replayed. Dummy's cards are played as
at the table (`Table.controller_of`): when a bot partner declared opposite the person, the person played both hands,
so here the level 10 bot does. Bots claim as soon as the rest is certain, to save the solver's time; that never
changes the result.

One deal is a small sample, and a bot below level 10 picks with some randomness, so a single board's IMPs say more
about the cards than the player. Averaged over many boards (My stats) it measures the player against a fixed yardstick.
It runs after the board at the solver's lowest urgency (`Room._second_tables`), and on a phone in the helper.
"""
from __future__ import annotations

import random

from ..bidding.engine import BiddingEngine
from ..bidding.partscore import Score
from ..bidpath import dd_score_ns
from ..bots.player import BotPlayer
from ..bots.view import view_for
from ..core.auction import Auction, Contract
from ..core.board import is_vulnerable
from ..core.cards import SEATS, Hand, partner, same_side
from ..core.claim import can_claim, play_claim
from ..core.play import Play
from ..core.scoring import duplicate_score, imps
from .table import auction_shown

YARDSTICK = 10  # the bot that sits in the person's seat


def side_score(contract: Contract | None, tricks: int, vulnerability: str, seat: str, below: dict | None) -> int:
    """What a contract scored for `seat`'s side, at duplicate (with the rubber part score already below the line, so
    a 2♥ that finishes a game counts as one)."""
    if contract is None:
        return 0
    side = "NS" if contract.declarer in "NS" else "EW"
    s = duplicate_score(contract, tricks, is_vulnerable(vulnerability, contract.declarer), (below or {}).get(side, 0))
    return s if same_side(contract.declarer, seat) else -s


def _controller(seat: str, contract: Contract, people: set[str]) -> str:
    """Who plays `seat`'s cards, by the table's rule: declarer plays dummy, except that a person opposite a bot
    declarer plays both hands."""
    declarer, dummy = contract.declarer, partner(contract.declarer)
    if seat in (declarer, dummy):
        return dummy if declarer not in people and dummy in people else declarer
    return seat


def second_table(engine: BiddingEngine, hands: dict[str, Hand], dealer: str, vulnerability: str,
                 score: Score | None, seat: str, people: set[str], level: int, signals: str | None, leads: bool,
                 below: dict | None, contract: Contract | None, tricks: int, rng: random.Random) -> dict:
    """Play the deal again with a level 10 bot in `seat` and the table's bots (`level`) everywhere else, and score
    the person's result (`contract` making `tricks`) against it. `people` are the seats people played."""
    bots = {s: BotPlayer(engine, YARDSTICK if s == seat else level, seed=rng.randrange(2 ** 31)) for s in SEATS}
    auction = Auction(dealer)
    while not auction.is_complete():
        s = auction.next_to_call
        auction.add(bots[s].bid(hands[s], auction, score, vulnerability).call)
    theirs = auction.contract()
    # the auction as the review shows it: each call with what it meant in the system
    shown = auction_shown(engine, dealer, auction.calls)
    out = {"seat": seat, "level": YARDSTICK, "others": level, "auction": shown,
           "contract": theirs.to_dict() if theirs else None, "tricks": 0, "play": []}
    if theirs:
        play = Play.start(theirs.declarer, theirs.strain, hands)
        while not play.is_complete():
            if can_claim(play):
                out["claimed"] = 13 - len(play.completed_tricks())  # the tricks left when it was claimed
                play_claim(play)
                break
            s = play.next_to_play
            view = view_for(play, auction, theirs, vulnerability, s, signals, leads)
            # whoever holds the cards at the table plays them: the person's seat plays dummy for a bot partner who
            # declared, so the level 10 bot does here
            bot = bots[_controller(s, theirs, people)]
            play.play(bot.play(view).card)
        out["tricks"] = play.declarer_tricks()
        out["play"] = [[s, c] for s, c in play.played_cards()]
    out["score"] = side_score(theirs, out["tricks"], vulnerability, seat, below)
    out["table_score"] = side_score(contract, tricks, vulnerability, seat, below)
    out["imps"] = imps(out["table_score"] - out["score"])
    return out


def add_split(out: dict, contract: Contract | None, dd: dict | None, vulnerability: str, below: dict | None) -> dict:
    """Split the second table's IMPs into the bidding's share and the play's. The bidding's share compares the two
    contracts as if both were played with every card seen (double dummy), so the card play doesn't muddy it; the play
    is the rest. Left out when the deal's double-dummy table wasn't kept."""
    c = out.get("contract")
    theirs = Contract(c["level"], c["strain"], c["declarer"], int(c.get("doubled") or 0)) if c else None
    mine, other = dd_score_ns(contract, dd or {}, vulnerability, below), dd_score_ns(theirs, dd or {}, vulnerability, below)
    if mine is None or other is None or out.get("imps") is None:
        return out
    sign = 1 if out.get("seat", "N") in "NS" else -1
    out["bidding_imps"] = imps(sign * (mine - other))
    out["play_imps"] = out["imps"] - out["bidding_imps"]
    return out


def fill_split(rec: dict) -> dict:
    """`add_split` for a saved board whose second table was played before the split was kept."""
    seconds = (rec.get("review") or {}).get("second") or {}
    c = rec.get("contract")
    contract = Contract(c["level"], c["strain"], c["declarer"], int(c.get("doubled") or 0)) if c else None
    below = rec.get("below_before") if rec.get("scoring") == "rubber" else None
    for out in seconds.values():
        if isinstance(out, dict) and out and "bidding_imps" not in out:
            add_split(out, contract, rec.get("dd"), rec.get("vulnerability") or "None", below)
    return rec
