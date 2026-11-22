"""Opening bids (base system)."""
from ...core.cards import SUITS
from ..evaluation import Eval
from ..rules import Convention, Rule, opening_position
from ..shows import shows


def can_open_one(ev: Eval) -> bool:
    if ev.balanced:
        return 12 <= ev.hcp
    return ev.tp >= 13 or (ev.tp >= 12 and ev.rule_of_20)


def one_level_suit(ev: Eval) -> str:
    """Suit to open at the one level (docs: longest; equal 5+ → higher;
    no 5-card major → longer minor, 1D with 4-4, 1C with 3-3)."""
    L = ev.lengths
    longest = max(L.values())
    if longest >= 5:
        # SUITS runs high→low, so equal lengths pick the higher-ranking suit
        return next(s for s in SUITS if L[s] == longest)
    # no 5-card suit: longer minor
    if L["D"] > L["C"]:
        return "D"
    if L["C"] > L["D"]:
        return "C"
    return "D" if L["D"] >= 4 else "C"


def _one_suit_ok(ev, ctx, call):
    return can_open_one(ev) and ev.tp <= 21 and not (ev.balanced and ev.hcp >= 20) \
        and one_level_suit(ev) == call[1]


def _weak_two_ok(ev, ctx, call):
    s = call[1]
    others = [m for m in "SH" if m != s]
    return (5 <= ev.hcp <= 10 and ev.len(s) == 6 and ev.decent_suit(s) and ev.tp < 13
            and all(ev.len(m) < 4 for m in others) and not can_open_one(ev))


def _preempt_ok(level):
    def ok(ev, ctx, call):
        s = call[1]
        n = ev.len(s)
        others = [m for m in "SH" if m != s]
        want = 7 if level == 3 else 8
        return (5 <= ev.hcp <= 10 and (n == want or (level == 4 and n >= 8)) and ev.decent_suit(s)
                and ev.tp < 13 + (n - 7) and all(ev.len(m) < 4 for m in others))
    return ok


def one_suit_meaning(ctx, call):
    s = call[1]
    if s in "HS":
        return shows(f"Opening: 12-21 points, 5+ {s}", (11, 21), light=10, **{s: 5})
    if s == "D":
        return shows("Opening: 12-21 points, 3+ diamonds (usually 4+), a 5-card major only if diamonds are longer",
                     (11, 21), light=10, D=3)
    return shows("Opening: 12-21 points, 3+ clubs, a 5-card major only if clubs are longer", (11, 21), light=10, C=3)


rules = [
    Rule("2NT opening", opening_position, "2N",
         lambda ev, ctx, c: ev.balanced and 20 <= ev.hcp <= 21,
         shows("20-21 HCP, balanced", (20, 21), balanced=True), priority=90),
    Rule("1NT opening", opening_position, "1N",
         lambda ev, ctx, c: ev.balanced and 15 <= ev.hcp <= 17,
         shows("15-17 HCP, balanced", (15, 17), balanced=True), priority=90),
    Rule("One of a suit", opening_position, ["1C", "1D", "1H", "1S"], _one_suit_ok,
         one_suit_meaning, priority=60),
    Rule("Pass (no opening)", opening_position, "P",
         lambda ev, ctx, c: True,
         shows("Not enough to open (fewer than 12-13 points)", (0, 13)), priority=1),
]

weak_two_rules = [
    Rule("Weak two", opening_position, ["2D", "2H", "2S"], _weak_two_ok,
         lambda ctx, c: shows(f"Weak two: 5-10 HCP, good 6-card {c[1]} suit", (5, 10),
                              **{c[1]: (6, 6)}),
         priority=70),
]

preempt_rules = [
    Rule("Three-level pre-empt", opening_position, ["3C", "3D", "3H", "3S"], _preempt_ok(3),
         lambda ctx, c: shows(f"Pre-empt: 5-10 HCP, good 7-card {c[1]} suit", (5, 10),
                              **{c[1]: (7, 7)}),
         priority=70),
    Rule("Four-level pre-empt", opening_position, ["4C", "4D", "4H", "4S"], _preempt_ok(4),
         lambda ctx, c: shows(f"Pre-empt: 5-10 HCP, 8+ {c[1]}", (5, 11), **{c[1]: 8}),
         priority=71),
]

OPENINGS = Convention(
    "openings", "Opening bids",
    "Five-card majors, strong 1NT (15-17), 2NT 20-21, one of a suit with 12-21.",
    rules, core=True)

WEAK_TWOS = Convention(
    "weak_twos", "Weak two bids",
    "2♦/2♥/2♠: 5-10 HCP with a good six-card suit. Partner's 2NT asks for a feature.",
    weak_two_rules)

PREEMPTS = Convention(
    "preempts", "Three- and four-level pre-empts",
    "Good seven-card suit, 5-10 HCP: open at the three level (eight cards: four level).",
    preempt_rules)
