"""Responses to one of a suit and opener's rebids (base system).

Follows docs/bidding-system.md, including the partnership's "limit" NT
responses: 1NT 6-10, 2NT 11-12 balanced, 3NT 13-15 balanced.
"""
from __future__ import annotations

from ...core.cards import SUITS
from ..context import Ctx
from ..evaluation import Eval
from ..rules import Convention, Rule, level_needed, seq
from ..shows import shows

ONE_SUITS = {"1C", "1D", "1H", "1S"}
NAMES = {"S": "spades", "H": "hearts", "D": "diamonds", "C": "clubs"}


def higher(a: str, b: str) -> bool:
    """Suit a ranks above suit b."""
    return SUITS.index(a) < SUITS.index(b)


def opening_suit(ctx: Ctx) -> str:
    return ctx.since_open[0][1]


partner_opened_one = seq(ONE_SUITS, "P", opener="pd")

# --- responder's first bid -----------------------------------------------------------


def one_level_choice(ev: Eval, o: str) -> str | None:
    """Responder's 1-level new suit, or None."""
    cands = [s for s in SUITS if higher(s, o) and ev.len(s) >= 4]
    if not cands:
        return None
    longest = max(ev.len(s) for s in cands)
    if longest >= 5:
        return next(s for s in cands if ev.len(s) == longest)  # higher of equal 5+ suits
    # only four-card suits: up the line, but skip a four-card diamond suit for a major
    up = sorted(cands, key=lambda s: -SUITS.index(s))
    if "D" in up and ev.len("D") == 4 and any(m in up for m in "HS"):
        up.remove("D")
    return up[0]


def two_level_choice(ev: Eval, o: str) -> str | None:
    """Responder's 2-level new suit (lower-ranking than opener's suit)."""
    cands = [s for s in SUITS if higher(o, s) and
             ev.len(s) >= (5 if s == "H" else 4)]
    if not cands:
        return None
    longest = max(ev.len(s) for s in cands)
    best = [s for s in cands if ev.len(s) == longest]
    return best[0] if longest >= 5 else best[-1]  # 5-5: higher; 4-4: lower (up the line)


def _major_raise_value(ev: Eval, o: str) -> int:
    return ev.support_points(o)


def _fits_major(ev, ctx):
    o = opening_suit(ctx)
    return o in "HS" and ev.len(o) >= 3


def _single_raise_ok(ev, ctx, c):
    o = opening_suit(ctx)
    if c[1] != o:
        return False
    if o in "HS":
        return ev.len(o) >= 3 and 6 <= _major_raise_value(ev, o) <= 9
    need = 4 if o == "D" else 5
    return ev.len(o) >= need and 6 <= ev.hcp <= 10 and not ev.four_card_majors()


def _limit_raise_ok(ev, ctx, c):
    o = opening_suit(ctx)
    if c[1] != o:
        return False
    if o in "HS":
        return ev.len(o) >= 3 and 10 <= _major_raise_value(ev, o) <= 12
    need = 4 if o == "D" else 5
    return ev.len(o) >= need and 11 <= ev.hcp <= 12 and not ev.four_card_majors()


def _one_level_ok(ev, ctx, c):
    o = opening_suit(ctx)
    if ev.hcp < 6:
        return False
    if _fits_major(ev, ctx) and _major_raise_value(ev, o) <= 12:
        return False  # raise instead
    if ev.hcp >= 12:
        two = two_level_choice(ev, o)
        if two and ev.len(two) >= 5 and ev.len(two) > ev.len(c[1]):
            return False  # longer lower suit first with opening values
    return one_level_choice(ev, o) == c[1]


def _two_level_ok(ev, ctx, c):
    o = opening_suit(ctx)
    if ev.hcp < 11:
        return False
    if _fits_major(ev, ctx) and _major_raise_value(ev, o) <= 12:
        return False
    one = one_level_choice(ev, o)
    two = two_level_choice(ev, o)
    if two != c[1]:
        return False
    if ev.balanced and ev.hcp <= 15 and ev.len(two) < 5 and not (ev.hcp <= 12 and _jacoby_2n_on(ctx)):
        return False  # limit-style 2NT/3NT describes the hand better (2NT is Jacoby over a major)
    if one is None:
        return True
    return ev.hcp >= 12 and ev.len(two) >= 5 and ev.len(two) > ev.len(one)


def _temporize_ok(ev, ctx, c):
    """13+ with support for opener's major: bid a new suit first."""
    o = opening_suit(ctx)
    if not (_fits_major(ev, ctx) and _major_raise_value(ev, o) >= 13):
        return False
    s = c[1]
    if s == o or s == "N":
        return False
    if c[0] == "1":
        return ev.len(s) >= 4 and one_level_choice(ev, o) == s
    if not higher(o, s):
        return False
    if one_level_choice(ev, o) is not None:
        return False
    # any 3+ card lower suit will do as a temporizing bid (hearts need 5); prefer the longest
    lower = [x for x in SUITS if higher(o, x) and (x != "H" or ev.len("H") >= 5)]
    best = max(lower, key=lambda x: (ev.len(x), -SUITS.index(x)), default=None)
    return best == s and ev.len(s) >= 3


def _temporize_meaning(ctx, c):
    """Partner can't tell a temporizing bid from a natural one, so this describes both:
    the 1-level bid is a real 4-card suit; at the 2 level it may be only 3 cards."""
    if c[0] == "1":
        return shows(f"New suit: 6+ HCP, 4+ {NAMES[c[1]]}, forcing", (6, 37), forcing=True,
                     **{c[1]: 4})
    n = 5 if c[1] == "H" else 3
    usually = "" if c[1] == "H" else " (usually 4+)"
    return shows(f"New suit: 11+ HCP, {n}+ {NAMES[c[1]]}{usually}, forcing", (11, 37),
                 forcing=True, **{c[1]: n})


def _jump_shift_calls(ctx):
    o = opening_suit(ctx)
    out = []
    for s in SUITS:
        if s == o:
            continue
        lvl = 2 if higher(s, o) else 3
        out.append(f"{lvl}{s}")
    return out


def _new_suit_calls(level):
    def calls(ctx):
        o = opening_suit(ctx)
        if level == 1:
            return [f"1{s}" for s in SUITS if higher(s, o)]
        return [f"2{s}" for s in SUITS if higher(o, s)]
    return calls


def _jacoby_2n_on(ctx: Ctx) -> bool:
    """2NT over partner's major is Jacoby 2NT (not a natural 11-12)."""
    return "jacoby_2nt" in ctx.engine.enabled and opening_suit(ctx) in "HS" and not ctx.passed_hand


def _nt_resp_ok(ev, ctx, c):
    o = opening_suit(ctx)
    if c == "1N":
        if not 6 <= ev.hcp <= 10:
            return False
        if _fits_major(ev, ctx) and _major_raise_value(ev, o) >= 6:
            return False
        return one_level_choice(ev, o) is None
    if not ev.balanced or (_fits_major(ev, ctx)):
        return False
    if one_level_choice(ev, o) is not None:
        return False
    if c == "2N":
        return 11 <= ev.hcp <= 12 and not _jacoby_2n_on(ctx)
    return 13 <= ev.hcp <= 15


RESP = [
    Rule("Pass partner's opening", partner_opened_one, "P",
         lambda ev, ctx, c: ev.hcp < 6, shows("0-5 HCP", (0, 5)), priority=40),
    Rule("Jump shift", partner_opened_one, _jump_shift_calls,
         lambda ev, ctx, c: ev.hcp >= 19 and ev.len(c[1]) >= 5,
         lambda ctx, c: shows(f"Strong jump shift: 19+ HCP, 5+ {NAMES[c[1]]}", (19, 37),
                              game_forcing=True, **{c[1]: 5}),
         priority=75, prefer=lambda ev, ctx, c: -ev.len(c[1])),
    Rule("Single raise", partner_opened_one, lambda ctx: [f"2{opening_suit(ctx)}"], _single_raise_ok,
         lambda ctx, c: (shows(f"Raise: 6-9 points, 3+ {NAMES[c[1]]}", (5, 10), **{c[1]: 3})
                         if c[1] in "HS" else
                         shows(f"Raise: 6-10 HCP, 4+ {NAMES[c[1]]}, no 4-card major", (6, 10),
                               S=(0, 3), H=(0, 3), **{c[1]: 4})),
         priority=70),
    Rule("Limit raise", partner_opened_one, lambda ctx: [f"3{opening_suit(ctx)}"], _limit_raise_ok,
         lambda ctx, c: (shows(f"Limit raise: 10-12 points, 3+ {NAMES[c[1]]}", (9, 12),
                               **{c[1]: 3})
                         if c[1] in "HS" else
                         shows(f"Limit raise: 11-12 HCP, 4+ {NAMES[c[1]]}", (11, 12),
                               S=(0, 3), H=(0, 3), **{c[1]: 4})),
         priority=70),
    Rule("New suit, temporizing with support", partner_opened_one,
         lambda ctx: _new_suit_calls(1)(ctx) + _new_suit_calls(2)(ctx), _temporize_ok,
         _temporize_meaning, priority=69),
    Rule("New suit at the one level", partner_opened_one, _new_suit_calls(1), _one_level_ok,
         lambda ctx, c: shows(f"New suit: 6+ HCP, 4+ {NAMES[c[1]]}, forcing", (6, 37),
                              forcing=True, **{c[1]: 4}),
         priority=65),
    Rule("New suit at the two level", partner_opened_one, _new_suit_calls(2), _two_level_ok,
         lambda ctx, c: shows(f"New suit: 11+ HCP, {5 if c[1] == 'H' else 4}+ {NAMES[c[1]]}, "
                              "forcing", (11, 37), forcing=True,
                              **{c[1]: 5 if c[1] == "H" else 4}),
         priority=64),
    Rule("1NT response", partner_opened_one, "1N", _nt_resp_ok,
         shows("6-10 HCP, no 1-level suit to bid (not necessarily balanced)", (6, 10)),
         priority=50),
    Rule("2NT response", partner_opened_one, "2N", _nt_resp_ok,
         shows("11-12 HCP, balanced, invitational", (11, 12), balanced=True), priority=60),
    Rule("3NT response", partner_opened_one, "3N", _nt_resp_ok,
         shows("13-15 HCP, balanced, to play", (13, 15), balanced=True), priority=60),
]

# --- opener's rebid -----------------------------------------------------------------


def resp(ctx) -> str:
    return ctx.since_open[2]


def _tp(ev: Eval, ctx: Ctx, trump: str | None = None) -> int:
    return ev.support_points(trump) if trump else ev.tp


def lower_new_suit(ev: Eval, o: str, exclude: str = "") -> str | None:
    cands = [s for s in SUITS if higher(o, s) and s != exclude and ev.len(s) >= 4]
    return max(cands, key=lambda s: (ev.len(s), SUITS.index(s)), default=None)


def reverse_suit(ev: Eval, o: str, exclude: str = "") -> str | None:
    if ev.len(o) < 5:
        return None
    cands = [s for s in SUITS if higher(s, o) and s != exclude and ev.len(s) >= 4]
    return max(cands, key=lambda s: ev.len(s), default=None)


def _after_raise_ok(ev, ctx, c):
    o = ctx.since_open[0][1]
    r = resp(ctx)
    tp = _tp(ev, ctx, o)
    if r[0] == "2":
        if o in "HS":
            want = "P" if tp <= 15 else f"3{o}" if tp <= 18 else f"4{o}"
        else:
            want = "P" if tp <= 15 else f"3{o}" if tp <= 18 else "3N"
    else:  # limit raise
        if o in "HS":
            want = f"4{o}" if tp >= 14 else "P"
        else:
            want = "3N" if tp >= 14 else "P"
    return c == want


def _raise_situation(ctx):
    s = ctx.since_open
    return (ctx.opener_rel == "me" and len(s) == 4 and s[0] in ONE_SUITS and s[1] == "P"
            and s[3] in ("P", "X") and len(s[2]) == 2 and s[2][1] == s[0][1] and s[2][0] in "23")


OPENER_AFTER_RAISE = Rule(
    "Opener after a raise", _raise_situation,
    ["P", "3C", "3D", "3H", "3S", "3N", "4H", "4S"], _after_raise_ok,
    lambda ctx, c: (shows("Minimum, no game interest", signoff=True) if c == "P" else
                    shows("Game try / invitation (16-18)", (16, 18), light=13) if c[0] == "3" and c != "3N"
                    else shows("To play", signoff=True)), priority=70)


def _rebid_after_new_suit_or_1n(ev: Eval, ctx: Ctx) -> str:
    """Opener's rebid after a new-suit or 1NT response. Returns the chosen call."""
    o_call = ctx.since_open[0]
    o = o_call[1]
    r = resp(ctx)
    y = r[1]
    two_level_resp = r[0] == "2" and y != "N"
    legal = set(ctx.legal)

    def ok(call):
        return call in legal

    fit = y in SUITS and (ev.len(y) >= 4 or (two_level_resp and y == "H" and ev.len(y) >= 3))
    tp_fit = ev.support_points(y) if fit else ev.tp

    if r == "1N":
        if ev.balanced:
            if ev.hcp <= 14:
                return "P"
            return "2N" if ev.hcp <= 19 else "3N"
        if ev.tp <= 15:
            if ev.len(o) >= 6:
                return f"2{o}"
            low = lower_new_suit(ev, o)
            if low:
                return f"2{low}"
            return "P"
        if ev.tp <= 18:
            if ev.len(o) >= 6:
                return f"3{o}"
            rev = reverse_suit(ev, o)
            if rev:
                return f"2{rev}"
            low = lower_new_suit(ev, o)
            return f"2{low}" if low else "2N"
        if o in "HS" and ev.len(o) >= 6:
            return f"4{o}"
        side = lower_new_suit(ev, o) or reverse_suit(ev, o)
        if side and not ev.semi_balanced:
            return f"3{side}"
        return "3N"

    if r[1] == "N":  # 2NT or 3NT response
        if r == "3N":
            return f"4{o}" if o in "HS" and ev.len(o) >= 6 else "P"
        if o in "HS" and ev.len(o) >= 6:
            return f"4{o}" if ev.tp >= 14 else f"3{o}"
        return "3N" if ev.tp >= 14 else "P"

    # new suit response: forcing
    if ev.balanced:
        if fit and y in "HS":
            if ev.hcp <= 14:
                return f"{2 if r[0] == '1' else 3}{y}"
            return f"{3 if r[0] == '1' else 4}{y}" if ev.hcp <= 18 else f"4{y}"
        if ev.hcp <= 14:
            if fit:
                return f"{int(r[0]) + 1}{y}"
            if r[0] == "1" and y != "S" and ev.len("S") >= 4 and ok("1S"):
                return "1S"
            if r[0] == "1" and y in "CD" and ev.len("H") >= 4 and ok("1H"):
                return "1H"
            return "1N" if ok("1N") else "2N"
        if ev.hcp <= 19:
            return "2N" if r[0] == "1" else "3N"
        return "3N"

    if fit:
        if tp_fit <= 15:
            return f"{int(r[0]) + 1}{y}"
        if tp_fit <= 18:
            return f"{int(r[0]) + 2}{y}" if int(r[0]) + 2 <= 4 else f"4{y}"
        return f"4{y}" if y in "HS" else ("3N" if ev.semi_balanced else f"5{y}")

    # no fit, unbalanced
    one_level = [s for s in SUITS if higher(s, y) and s != o and ev.len(s) >= 4 and ok(f"1{s}")]
    low = lower_new_suit(ev, o, exclude=y)
    rev = reverse_suit(ev, o, exclude=y)
    if ev.tp <= 15:
        if one_level:
            return f"1{one_level[-1]}"
        if low and ok(f"2{low}"):
            return f"2{low}"
        return f"2{o}" if ok(f"2{o}") else f"3{o}"
    if ev.tp <= 18:
        if rev and ok(f"2{rev}"):
            return f"2{rev}"
        if ev.len(o) >= 6:
            return f"3{o}"
        if one_level:
            return f"1{one_level[-1]}"
        if low and ok(f"2{low}"):
            return f"2{low}"
        return f"2{o}" if ok(f"2{o}") else f"3{o}"
    # 19-21: jump shift, game in own suit, or 3NT
    if o in "HS" and ev.len(o) >= 6:
        return f"4{o}"
    side = rev or low or (one_level[-1] if one_level else None)
    if side:
        lvl = level_needed(ctx, side)
        return f"{lvl + 1}{side}" if lvl < 3 else "3N"
    return "3N"


def _new_suit_or_nt_situation(ctx):
    s = ctx.since_open
    # a double by the next player doesn't change opener's rebid (1H P 1S X: raise to 2S)
    return (ctx.opener_rel == "me" and len(s) == 4 and s[0] in ONE_SUITS and s[1] == "P"
            and s[3] in ("P", "X") and s[2] != "P" and s[2][1] != s[0][1] and s[2][1] in "CDHSN"
            and len(s[2]) == 2)


def _rebid_meaning(ctx: Ctx, c: str) -> "shows":
    o = ctx.since_open[0][1]
    r = resp(ctx)
    y = r[1]
    if c == "P":
        return shows("Minimum, nothing more to say", (11, 15), signoff=True, light=10)
    lvl, s = int(c[0]), c[1]
    if s == "N":
        if c == "1N":
            return shows("12-14 balanced", (12, 14), balanced=True)
        if c == "2N" and r[0] == "1" and y != "N":
            return shows("18-19 balanced", (18, 19), balanced=True)
        if c == "2N" and r == "1N":
            return shows("18-19 balanced, invitational", (18, 19), balanced=True)
        if c == "2N":
            return shows("12-14 balanced", (12, 14), balanced=True)
        return shows("To play", (12, 21))
    if s == y:
        jump = lvl - int(r[0])
        if (s in "HS" and lvl >= 4) or lvl >= 5:
            if r[0] == "2":  # partner's 2-level response already promised 11+
                return shows(f"Raise to game: 15+, support for {NAMES[s]}", (15, 21),
                             **{s: 3 if s == "H" else 4})
            return shows(f"Raise to game: 19-21, 4+ {NAMES[s]}", (17, 21), light=16, **{s: 4})
        n = 3 if r == "2H" else 4  # a 2H response promises 5, so opener raises with 3 (see the fit test above)
        if jump == 1:
            return shows(f"Raise: 13-15, {n}+ {NAMES[s]}", (12, 15), light=10, **{s: n})
        return shows(f"Jump raise: 16-18, {n}+ {NAMES[s]}", (16, 18), light=14, **{s: n})
    if s == o:
        if (s in "HS" and lvl >= 4) or lvl >= 5:
            return shows(f"Game: 19-21 with long {NAMES[s]}", (17, 21), light=16, **{s: 6})
        if lvl > level_needed(ctx, s):
            return shows(f"Jump rebid: 16-18, 6+ {NAMES[s]}", (15, 18), light=14, **{s: 6})
        return shows(f"Rebid: minimum, usually 6 {NAMES[s]}", (12, 15), light=10, **{s: 5})
    if higher(s, o) and lvl == 2:
        return shows(f"Reverse: 16+, 4+ {NAMES[s]}, longer {NAMES[o]}", (16, 21), light=15, forcing=True,
                     **{s: 4, o: 5})
    # new suit
    cheapest_level = int(r[0]) if y != "N" and higher(s, y) else int(r[0]) + 1
    if lvl > cheapest_level:
        return shows(f"Jump shift: 19-21, 4+ {NAMES[s]}", (19, 21), game_forcing=True, **{s: 4})
    return shows(f"New suit: 4+ {NAMES[s]}", (12, 18), light=10, **{s: 4})


OPENER_REBID = Rule(
    "Opener's rebid", _new_suit_or_nt_situation,
    lambda ctx: ctx.legal,
    lambda ev, ctx, c: c == _rebid_after_new_suit_or_1n(ev, ctx),
    _rebid_meaning, priority=60)

REBIDS = [OPENER_AFTER_RAISE, OPENER_REBID]

# --- Jacoby 2NT ----------------------------------------------------------------------------

J2N_CALLS = ["3C", "3D", "3H", "3S", "3N", "4H", "4S"]


def _jacoby_2n_ok(ev, ctx, c):
    o = opening_suit(ctx)
    return ev.len(o) >= 4 and ev.support_points(o) >= 13


def _after_j2n(ctx: Ctx) -> bool:
    s = ctx.since_open
    return (ctx.opener_rel == "me" and len(s) == 4 and s[0] in ("1H", "1S") and s[1] == "P"
            and s[2] == "2N" and s[3] == "P")


def _j2n_rebid_choice(ev: Eval, ctx: Ctx) -> str:
    o = ctx.since_open[0][1]
    short = [x for x in SUITS if x != o and ev.len(x) <= 1]
    if short:
        x = min(short, key=lambda x: (ev.len(x), SUITS.index(x)))
        return f"3{x}" if f"3{x}" != f"3{o}" else f"4{o}"
    tp = ev.tp
    if tp >= 18:
        return f"3{o}"
    if tp >= 15:
        return "3N"
    return f"4{o}"


def _j2n_rebid_meaning(ctx: Ctx, c: str):
    o = ctx.since_open[0][1]
    if c == f"3{o}":
        return shows("Strong (18+), no shortness: slam interest", (17, 21), game_forcing=True, **{o: 5})
    if c == "3N":
        return shows("15-17, no singleton or void", (15, 17), game_forcing=True, **{o: 5})
    if c == f"4{o}":
        return shows("Minimum (12-14), no singleton or void", (11, 14), signoff=True, **{o: 5})
    if c[0] == "3" and c[1] in SUITS:
        return shows(f"Singleton or void in {NAMES[c[1]]}", (11, 21), game_forcing=True,
                     **{o: 5, c[1]: (0, 1)})
    return shows("To play", (11, 21))


JACOBY_2NT_RULES = [
    Rule("Jacoby 2NT",
         lambda ctx: partner_opened_one(ctx) and opening_suit(ctx) in "HS" and not ctx.passed_hand,
         "2N", _jacoby_2n_ok,
         lambda ctx, c: shows(f"Jacoby 2NT: 4+ {NAMES[opening_suit(ctx)]}, 13+ points, game forcing",
                              (11, 37), game_forcing=True, artificial=True,
                              **{opening_suit(ctx): 4}),
         priority=72),
    Rule("Opener after Jacoby 2NT", _after_j2n, J2N_CALLS,
         lambda ev, ctx, c: c == _j2n_rebid_choice(ev, ctx), _j2n_rebid_meaning, priority=80),
]

SUIT_RESPONSES = Convention(
    "suit_responses", "Responses to one of a suit",
    "Raises, new suits (forcing), and limit-style NT responses (1NT 6-10, 2NT 11-12, "
    "3NT 13-15).", RESP, core=True)

JACOBY_2NT = Convention(
    "jacoby_2nt", "Jacoby 2NT",
    "Over partner's 1♥ or 1♠, 2NT shows four-card support and 13+ points, forcing to game. "
    "Opener then shows a singleton or void, or how strong the hand is.", JACOBY_2NT_RULES,
    default_on=False)  # not on the No Fear cheat sheet, so off unless the players choose it

OPENER_REBIDS = Convention(
    "opener_rebids", "Opener's rebids",
    "Opener describes 12-14 / 15-18 / 19-21 on the second bid.", REBIDS, core=True)
