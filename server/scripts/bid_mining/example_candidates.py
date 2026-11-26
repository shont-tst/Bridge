"""Example candidates for spot.py. A spot sweep gives the "first" number; check a winner with "full" too, then
with re-dealt layouts (bidpath.average_outcome) before changing the rules."""
from bridge.core.cards import partner, side


def _cheapest(a, suit):
    for lvl in range(1, 8):
        if a.is_legal(f"{lvl}{suit}"):
            return f"{lvl}{suit}"
    return None


def _they_bid_last(a, seat) -> bool:
    i = a.last_bid_index()
    return i is not None and side(a.seat_of(i)) != side(seat)


def _raise_fit(ctx):
    """System passes after they bid: raise our known 8-card fit by the Law of Total Tricks, to the 3 level."""
    a, seat, hand = ctx["auction"], ctx["seat"], ctx["hand"]
    if ctx["dec"].call != "P" or not _they_bid_last(a, seat) or hand.hcp < 6:
        return None
    shown = ctx["engine"].infer(a, partner(seat))
    ours = {c[1] for s, c in a.with_seats() if s in (seat, partner(seat)) and c[0].isdigit() and c[1] in "SHDC"}
    for suit in sorted(ours, key=lambda s: -(hand.length(s) + shown.min_len(s))):
        fit, call = hand.length(suit) + shown.min_len(suit), _cheapest(a, suit)
        if call and fit >= 8 and int(call[0]) <= min(3, fit - 6):
            return call
    return None


class RaiseFit:
    when = staticmethod(lambda ctx: _raise_fit(ctx) is not None)
    alt = staticmethod(_raise_fit)
