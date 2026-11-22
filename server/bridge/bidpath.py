"""Did leaving the system help or hurt? For a call that differed from the system's, the auction is bid again from that
point with the system's call, the system bidding every seat after it (the player too), and the two contracts are
compared on double-dummy scores (every card seen, so the card play doesn't muddy it).

It is an estimate: at the table the bots and the player might have bid differently after the system's call.
"""
from __future__ import annotations

from functools import lru_cache

from .bidding.conventions import make_engine
from .core.auction import Auction, Contract
from .core.board import is_vulnerable
from .core.cards import Hand
from .core.scoring import duplicate_score

MAX_CALLS = 60  # an auction never gets near this; a guard against a loop
SAME = 20  # points either way that count as no difference (an overtrick, a part score's odd trick)


@lru_cache(maxsize=16)
def _engine(conventions: tuple[str, ...] | None):
    return make_engine(set(conventions) if conventions is not None else None)


VERSION = 2  # outcomes worked out before this (1.88 to 1.91) scored rubber boards without the part score: redo them


def dd_score_ns(contract: Contract | None, dd: dict, vulnerability: str, below: dict | None = None) -> int | None:
    """The score for North-South if `contract` is played double dummy. At rubber, `below` is each side's part score
    when the board was dealt, so a contract that finishes the game gets the game bonus (core.scoring)."""
    if contract is None:
        return 0
    tricks = ((dd or {}).get("tricks") or {}).get(contract.strain, {}).get(contract.declarer)
    if tricks is None:
        return None
    side = "NS" if contract.declarer in "NS" else "EW"
    s = duplicate_score(contract, tricks, is_vulnerable(vulnerability, contract.declarer), (below or {}).get(side, 0))
    return s if contract.declarer in "NS" else -s


def outcome(engine, hands: dict[str, Hand], dealer: str, calls: list[str], index: int, system_call: str,
            dd: dict, vulnerability: str, score=None, below: dict | None = None) -> dict | None:
    """{"system_auction": the calls after the system's call, "system_contract", "system_dd_ns", "actual_dd_ns",
    "bid_after": the seats that bid again after this call at the table (so a coach can tell a result the call
    decided from one another player's bid decided)}."""
    actual = Auction(dealer, list(calls)).contract() if calls else None
    auction = Auction(dealer, list(calls[:index]))
    try:
        auction.add(system_call)
        while not auction.is_complete() and len(auction.calls) < MAX_CALLS:
            auction.add(engine.choose(hands[auction.next_to_call], auction, score, vulnerability).call)
    except Exception:  # an estimate is a bonus
        return None
    if not auction.is_complete():
        return None
    sys_c = auction.contract()
    a, s = dd_score_ns(actual, dd, vulnerability, below), dd_score_ns(sys_c, dd, vulnerability, below)
    if a is None or s is None:
        return None
    seats = Auction(dealer, list(calls))
    caller = seats.seat_of(index)
    later = sorted({seats.seat_of(i) for i in range(index + 1, len(calls))
                    if calls[i] not in ("P", "X", "XX") and seats.seat_of(i) != caller})
    return {"v": VERSION, "system_auction": list(auction.calls[index:]),
            "system_contract": sys_c.to_dict() if sys_c else None,
            "system_dd_ns": s, "actual_dd_ns": a, "bid_after": later}


def add_outcomes(rec: dict, engine=None, score=None) -> list[dict]:
    """Each off-system call of a board's review with its outcome (worked out once, then kept in the record)."""
    review = rec.get("review") or {}
    rows = review.get("bidding") or []
    todo = [b for b in rows if "index" in b and (b.get("outcome") or {}).get("v") != VERSION]
    if todo and rec.get("dd") and not (rec.get("dd") or {}).get("error"):
        conv = rec.get("conventions")
        engine = engine or _engine(tuple(sorted(conv)) if conv is not None else None)
        hands = {s: Hand.from_pbn(h) for s, h in (rec.get("hands") or {}).items()}
        if len(hands) == 4:
            for b in todo:
                b["outcome"] = outcome(engine, hands, rec.get("dealer", "N"), rec.get("calls") or [], b["index"],
                                       b["system_call"], rec["dd"], rec.get("vulnerability") or "None", score,
                                       rec.get("below_before"))
    return rows


# --- was it a good bet? -----------------------------------------------------------------------------------------
# The outcome above is for this one deal. A call can work this time and still be a poor bet (or the reverse), so the
# call is also judged the way card odds are: on LAYOUTS deals of the other three hands that fit what the caller could
# see (their own hand and the calls before theirs), both auctions bid out by the system and scored double dummy. The
# average is what the review shows. Worked out after the board at the solver's lowest urgency (Room.fill_odds).
LAYOUTS = 30
MAX_AVERAGED = 3  # calls averaged per board: each takes about 15 seconds of the solver's spare time on a half CPU


def _deal_others(seat: str, own: Hand, infer: dict, rng, n: int) -> list[dict[str, Hand]]:
    """Up to n deals of the other three hands that fit what their calls showed, loosening that step by step if it
    can't be met (a misbid), as the card-play sampler does."""
    from .bots.sampler import _fits
    from .core.cards import SEATS, full_deck
    others = sorted((s for s in SEATS if s != seat), key=lambda s: infer[s].hcp[1] - infer[s].hcp[0])
    unknown = [c for c in full_deck() if c not in own.cards]
    out: list[dict[str, Hand]] = []
    for slack in [(0, 0), (2, 1), (4, 2), None]:
        tries = 0
        while len(out) < n and tries < 40 * n:
            tries += 1
            pool, deal = unknown[:], {}
            for i, s in enumerate(others):
                for _ in range(1 if i == 2 else 40):
                    cards = pool[:] if i == 2 else rng.sample(pool, 13)
                    if slack is None or _fits(cards, infer[s], *slack):
                        break
                else:
                    break
                if i == 2 and slack is not None and not _fits(cards, infer[s], *slack):
                    break
                deal[s] = Hand.of(cards)
                pool = [c for c in pool if c not in set(cards)]
            if len(deal) == 3:
                out.append(deal)
        if len(out) >= n:
            break
    return out


def _bid_out(engine, hands: dict[str, Hand], auction: Auction, score,
             vulnerability: str | None = None) -> Contract | None | bool:
    """The contract the system reaches from here (None: passed out), or False if it doesn't finish."""
    a = auction.copy()
    while not a.is_complete() and len(a.calls) < MAX_CALLS:
        a.add(engine.choose(hands[a.next_to_call], a, score, vulnerability).call)
    return a.contract() if a.is_complete() else False


def average_outcome(engine, hands: dict[str, Hand], dealer: str, calls: list[str], index: int, system_call: str,
                    vulnerability: str, score=None, below: dict | None = None, rng=None,
                    n: int = LAYOUTS) -> dict | None:
    """The caller's call against the system's, averaged over deals that fit what the caller could see:
    {"points_ns": average difference for North-South (call minus system), "deals", "helped", "hurt"}."""
    import random
    from .game.analysis import dd_summary
    rng = rng or random.Random()
    before = Auction(dealer, list(calls[:index]))
    seat = before.next_to_call
    infer = {s: engine.infer(before, s) for s in "NESW" if s != seat}
    diffs = []
    for others in _deal_others(seat, hands[seat], infer, rng, n):
        deal = {seat: hands[seat], **others}
        mine, theirs = before.copy(), before.copy()
        mine.add(calls[index])
        theirs.add(system_call)
        a, s = _bid_out(engine, deal, mine, score, vulnerability), _bid_out(engine, deal, theirs, score, vulnerability)
        if a is False or s is False:
            continue
        if (a.to_dict() if a else None) == (s.to_dict() if s else None):
            diffs.append(0)  # the same contract either way: nothing to solve
            continue
        dd = dd_summary(deal, vulnerability, dealer)
        sa, ss = dd_score_ns(a, dd, vulnerability, below), dd_score_ns(s, dd, vulnerability, below)
        if sa is not None and ss is not None:
            diffs.append(sa - ss)
    if not diffs:
        return None
    sign = 1 if seat in "NS" else -1
    return {"points_ns": round(sum(diffs) / len(diffs)), "deals": len(diffs),
            "helped": sum(1 for d in diffs if d * sign > SAME), "hurt": sum(1 for d in diffs if d * sign < -SAME)}


def add_averages(review: dict, engine, hands: dict[str, Hand], dealer: str, calls: list[str], vulnerability: str,
                 score=None, below: dict | None = None, rng=None, ready: dict | None = None) -> None:
    """Each off-system call that has an outcome for this deal gets its average over LAYOUTS deals (`avg`). `ready`
    holds averages already worked out while the hand was played (Room._odds_ahead), by (index, system call)."""
    ready = ready or {}
    for b in [b for b in (review or {}).get("bidding") or [] if b.get("outcome") and "index" in b][:MAX_AVERAGED]:
        o = b["outcome"]
        if "avg" not in o:
            key = (b["index"], b["system_call"])
            o["avg"] = ready[key] if key in ready else average_outcome(
                engine, hands, dealer, calls, b["index"], b["system_call"], vulnerability, score, below, rng)


def verdict(o: dict | None, seat: str) -> dict | None:
    """From the player's side: how many points their call gained (+) or lost (-) against the system's call, on
    average over deals like this one when that's been worked out (boards from 2.5 on), else on this deal."""
    if not o:
        return None
    sign = 1 if seat in "NS" else -1
    avg = o.get("avg")
    diff = (avg["points_ns"] if avg else o["actual_dd_ns"] - o["system_dd_ns"]) * sign
    later = o.get("bid_after") or []
    mate = {"N": "S", "S": "N", "E": "W", "W": "E"}[seat]
    who = ("your call" if not later else "partner bid on" if later == [mate]
           else "opponents bid on" if mate not in later else "both sides bid on")
    return {"points": diff, "verdict": "helped" if diff > SAME else "hurt" if diff < -SAME else "no difference",
            "contract_set_by": who}
