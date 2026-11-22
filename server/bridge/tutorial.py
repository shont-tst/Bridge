"""Hints for Learn to play's full deals (steps 4 and 5), from the double-dummy solver.

The tutorial plays in the app with no server table, so its Hint sends the position here: the cards each seat has
left, trumps, and the trick so far. The answer is how many tricks each legal card takes with all hands known. Only
the hint uses this; the tutorial's bots stay simple on purpose.
"""
from __future__ import annotations

from endplay.types import Deal, Denom, Player

from . import solver
from .core.cards import rank_value

SEATS = "NESW"
_CARDS = {s + r for s in "SHDC" for r in "23456789TJQKA"}
_DENOM = {"S": Denom.spades, "H": Denom.hearts, "D": Denom.diamonds, "C": Denom.clubs, "N": Denom.nt}
_PLAYER = {"N": Player.north, "E": Player.east, "S": Player.south, "W": Player.west}
_SUIT = "SHDC"


def _position(body: dict) -> tuple[dict[str, list[str]], str, str, list[tuple[str, str]]]:
    """The checked position, or ValueError: four hands that fit together, a trump, the leader and the trick."""
    hands, trump, leader, trick = body.get("hands"), body.get("trump"), body.get("leader"), body.get("trick") or []
    if not isinstance(hands, dict) or set(hands) != set(SEATS) or trump not in _DENOM or leader not in SEATS:
        raise ValueError("bad position")
    if not isinstance(trick, list) or len(trick) > 3:
        raise ValueError("bad trick")
    full = {s: list(hands[s]) for s in SEATS}
    seat, played = leader, []
    for card in trick:
        played.append((seat, card))
        full[seat] = full[seat] + [card]
        seat = SEATS[(SEATS.index(seat) + 1) % 4]
    cards = [c for s in SEATS for c in full[s]]
    if any(not isinstance(c, str) or c not in _CARDS for c in cards) or len(set(cards)) != len(cards):
        raise ValueError("bad cards")
    if len({len(full[s]) for s in SEATS}) != 1 or not full["N"]:
        raise ValueError("hands differ in length")
    if played:  # following suit, so the solver gets a position that can happen
        led = played[0][1][0]
        for s, c in played[1:]:
            if c[0] != led and any(x[0] == led for x in hands[s]):
                raise ValueError("didn't follow suit")
    return {s: full[s] for s in SEATS}, trump, leader, played


def card_tricks(body: dict) -> dict[str, int]:
    """Tricks the side to play takes after each of its legal cards, with all hands known."""
    full, trump, leader, played = _position(body)

    def pbn(cs):
        return ".".join("".join(c[1] for c in sorted((c for c in cs if c[0] == s), key=rank_value, reverse=True))
                        for s in _SUIT)
    deal = Deal.from_pbn("N:" + " ".join(pbn(full[s]) for s in SEATS))
    deal.trump = _DENOM[trump]
    deal.first = _PLAYER[leader]
    for _, c in played:
        deal.play(c)
    with solver.job(solver.Job(solver.HINT)):
        solved = solver.solve_all_boards([deal])[0]
    return {_SUIT[card.suit.value] + card.rank.name[1]: tricks for card, tricks in solved}


# --- step 6: bidding hands at a real table -----------------------------------------------------------------------
# Each hand South bids teaches one opening (or a raise); board n of the tutorial table deals hand (n - 1) % 5.
BIDDING_HANDS = 5


def bidding_deal(engine, board: int, rng):
    """(hands, dealer) for step 6's hand on tutorial board `board`."""
    from .bidding.lessons import _hand_where, practice_deal
    from .core.auction import Auction
    from .core.cards import SEATS, Hand, full_deck

    lesson = (board - 1) % BIDDING_HANDS
    if lesson == 4:  # raise partner's major: North opens, South raises
        return practice_deal(engine, "major_raises", rng, budget=1.5)
    tests = [
        lambda h, call: call == "P" and 6 <= h.hcp <= 10,
        lambda h, call: call in ("1H", "1S"),
        lambda h, call: call in ("1C", "1D"),
        lambda h, call: call == "1N",
    ]
    from .bidding.evaluation import Eval
    south = _hand_where(rng, lambda h: tests[lesson](Eval(h), engine.choose(h, Auction("S")).call), exclude=())
    rest = [c for c in full_deck() if c not in south.cards]
    rng.shuffle(rest)
    hands = {"S": south}
    for i, s in enumerate(s for s in SEATS if s != "S"):
        hands[s] = Hand.of(rest[i * 13:(i + 1) * 13])
    return hands, "S"
