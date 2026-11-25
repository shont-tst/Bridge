"""Playing a deal again: the same cards, from the start or from a point in the play, with bots in the other seats.

A replay is described by a `spec`: the deal (hands, dealer, vulnerability, the part scores at rubber), the calls and
cards made at the table, the seat the player sat in, and `from`, how many of those calls and cards are made for the
player before they take over (0 plays the whole deal again). The review's "Play on from here" and "Play this deal
again" send one, and Your mistakes (puzzles.py) builds one for each puzzle with the board's facts the answer needs
in `puzzle`. A replay never goes into My stats.

Judging a puzzle's answer (`judge_card`, `judge_call`) uses the review's own measures: a card is right when it isn't
clearly worse on the odds than the best card there (the review's Mistake line, `odds.MARGIN`), and a call is right
when it is the system's call.
"""
from __future__ import annotations

import random

from endplay.types import Deal

from ..bidding.engine import BiddingEngine
from ..bidding.partscore import Score
from ..bots.card_play import _card_str
from ..bots.player import BotPlayer
from ..core.auction import Auction
from ..core.cards import SEATS, Hand, side
from ..solver import solve_all_boards
from .odds import MARGIN, SAMPLES, card_odds
from .table import BIDDING, PLAYING, Table

VULS = ("None", "NS", "EW", "Both")
RETIRE = 2  # Your mistakes: right this many times and a puzzle is done
COME_BACK = 3 * 24 * 3600  # and after an answer, it comes back this many seconds later


def check(spec: dict) -> dict:
    """A spec from the app, checked and tidied: raises ValueError for anything that isn't a real deal, or calls and
    cards that couldn't have been made."""
    if not isinstance(spec, dict):
        raise ValueError("that isn't a deal")
    hands = spec.get("hands")
    if not isinstance(hands, dict) or set(hands) != set(SEATS):
        raise ValueError("a deal has four hands")
    parsed = {s: Hand.from_pbn(str(hands[s])) for s in SEATS}
    cards = [c for h in parsed.values() for c in h.cards]
    if any(len(h.cards) != 13 for h in parsed.values()) or len(set(cards)) != 52:
        raise ValueError("a deal has four hands of 13 different cards")
    dealer, vul, seat = spec.get("dealer"), spec.get("vulnerability"), spec.get("seat")
    if dealer not in tuple(SEATS) or vul not in VULS or seat not in tuple(SEATS):  # (SEATS is a string)
        raise ValueError("dealer, vulnerability and seat, please")
    calls = spec.get("calls") or []
    play = spec.get("play") or []
    if not isinstance(calls, list) or not isinstance(play, list) or len(calls) > 400 or len(play) > 52:
        raise ValueError("calls and play, please")
    below = spec.get("below")
    if below is not None and not (isinstance(below, dict) and all(isinstance(below.get(k), int) for k in ("NS", "EW"))):
        below = None
    out = {
        "board": int(spec.get("board") or 1), "dealer": dealer, "vulnerability": vul, "seat": seat,
        "hands": {s: parsed[s].to_pbn() for s in SEATS},
        "calls": [str(c) for c in calls], "play": [[str(s), str(c)] for s, c in play],
        "from": max(0, min(int(spec.get("from") or 0), len(calls) + len(play))),
        "below": below,
    }
    for k in ("conventions", "difficulty", "signals", "leads", "puzzle"):
        if spec.get(k) is not None:
            out[k] = spec[k]
    return out


def build(spec: dict, engine: BiddingEngine, bot_seats: set[str], bot: BotPlayer, rng: random.Random,
          signals: str | None, leads: bool) -> Table:
    """The table at the spec's starting point: its first `from` calls and cards made as they were at the table, and
    fixed, so Undo can't take them back."""
    hands = {s: Hand.from_pbn(h) for s, h in spec["hands"].items()}
    vul = spec["vulnerability"]
    score = Score.from_rubber(spec["below"], vul) if spec.get("below") else None
    t = Table(engine, spec["board"], bot_seats, bot, rng=rng, hands=hands, dealer=spec["dealer"], vulnerability=vul,
              score=score, signals=signals, leads=leads)
    steps = [("call", c) for c in spec["calls"]] + [("card", c) for _, c in spec["play"]]
    for kind, what in steps[:spec["from"]]:
        if kind == "call":
            t.make_call(t.auction.next_to_call, what)
        else:
            if t.phase != PLAYING:
                raise ValueError("those cards don't follow that auction")
            t.play_card(t.controller_to_act(), what)
    t.fixed = len(t.actions)
    return t


# --- Your mistakes: the answer to a puzzle -------------------------------------------------------------------------
def card_facts(engine: BiddingEngine, spec: dict, rng: random.Random) -> dict:
    """What judging any card at a card puzzle's spot needs, worked out while the player thinks: each legal card's %
    (the review's odds, kept with boards from now on, worked out again for older ones) and the tricks each would
    take as the cards lay. The odds go for the same target the review used (`reach`)."""
    p = spec["puzzle"]
    i = p["index"]
    hands = {s: Hand.from_pbn(h) for s, h in spec["hands"].items()}
    play = [tuple(x) for x in spec["play"]]
    auction = Auction(spec["dealer"], list(spec["calls"]))
    contract = auction.contract()
    odds = p.get("odds") or {}
    if not odds.get("all"):
        odds = card_odds(engine, hands, spec["dealer"], spec["vulnerability"], list(spec["calls"]), contract, play, i,
                         rng, SAMPLES, p.get("reach"), p.get("best")) or odds
    from .review import _DENOM, _PLAYER
    deal = Deal.from_pbn("N:" + " ".join(hands[s].to_pbn() for s in SEATS))
    deal.trump = _DENOM[contract.strain]
    deal.first = _PLAYER[SEATS[(SEATS.index(contract.declarer) + 1) % 4]]
    for _, card in play[:i]:
        deal.play(card)
    solved = solve_all_boards([deal])
    per = {_card_str(c): n for c, n in solved[0]} if solved else {}
    from ..core.play import Play
    pl = Play.start(contract.declarer, contract.strain, hands)
    for _, card in play[:i]:
        pl.play(card)
    won = pl.tricks_won(side(play[i][0]))
    legal = pl.legal_cards()
    from .review import _tricks_for
    return {"all": dict(odds.get("all") or {}), "tricks": odds.get("tricks"), "goal": odds.get("goal"),
            "dd": {c: won + _tricks_for(per, c) for c in legal} if per else {}}


def judge_card(spec: dict, facts: dict, card: str) -> dict:
    """The answer to a card puzzle: right unless the card is clearly worse on the odds than the best card there."""
    p = spec["puzzle"]
    pct = facts.get("all") or {}
    original = p["card"]
    best = max(pct, key=lambda c: (pct[c], c == card)) if pct else (p.get("odds") or {}).get("best", original)
    if pct and card in pct:
        right = pct[card] + MARGIN > pct[best]
    else:  # no odds to go on: the card that was best with all cards seen
        right = card in (p.get("best") or [])
    shown = card if right else best
    return {"kind": "card", "card": card, "right": right, "better": shown, "original": original,
            "seat": spec["play"][p["index"]][0], "trick": p["index"] // 4 + 1,
            "pct": {c: pct[c] for c in {card, best, original} if c in pct},
            "tricks": facts.get("tricks"), "goal": facts.get("goal"),
            "dd": {c: facts["dd"][c] for c in {card, best, original} if c in (facts.get("dd") or {})}}


def judge_call(engine: BiddingEngine, spec: dict, call: str) -> dict:
    """The answer to a bidding puzzle: right when it's the system's call."""
    p = spec["puzzle"]
    calls = spec["calls"][:p["index"]]
    auction = Auction(spec["dealer"], list(calls))
    if call not in auction.legal_calls():
        raise ValueError("that call isn't allowed now")
    try:
        meaning = engine.explain_next(auction, call).text
    except Exception:
        meaning = None
    return {"kind": "call", "call": call, "right": call == p["system_call"], "meaning": meaning,
            "system_call": p["system_call"], "system_meaning": p.get("system_meaning"),
            "original": p["call"], "original_meaning": p.get("meaning"), "cost": p.get("cost"),
            "average": p.get("average", False)}


def at_spot(t: Table, spec: dict) -> bool:
    """Whether the table is at the puzzle's spot, waiting for the player's answer."""
    p = spec.get("puzzle")
    if not p or len(t.actions) != spec["from"]:
        return False
    return t.phase == (BIDDING if p["kind"] == "call" else PLAYING)
