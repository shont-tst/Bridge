"""Notrump openings (and 1NT overcalls) — natural responses, Stayman, Jacoby
transfers, the 2S minor transfer and Gerber.

All structures are keyed off an "NT anchor": partner's (or my) 1NT/2NT opening,
the 2C-2D-2NT rebid, or a 1NT overcall. Thresholds come from the docs:
1NT: 8-9 invite, 10-15 game, 16-17 quantitative 4NT; 2NT: 4-11 game, 12 → 4NT.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..context import Ctx
from ..evaluation import Eval
from ..rules import Convention, Rule, cheapest, seq
from ..shows import shows


@dataclass(frozen=True)
class NTState:
    lo: int
    hi: int
    level: int  # 1 or 2
    ours: tuple[str, ...]  # our calls after the anchor
    i_am_nt: bool  # I made the NT bid
    inv: int | None  # responder HCP for an invite
    game: int
    quant: int
    slam: int


ANCHORS = {
    # key -> (lo, hi, level, inv, game, quant, slam)
    "1N": (15, 17, 1, 8, 10, 16, 18),
    "1N-overcall": (15, 18, 1, 8, 10, 16, 18),
    "2N": (20, 21, 2, None, 4, 12, 13),
    "2C2D2N": (22, 24, 2, None, 2, 9, 10),
}


def nt_state(ctx: Ctx, contested: bool = False) -> NTState | None:
    """The NT auction from my side's view. Opponents must have passed throughout
    unless `contested`, which lets them bid or double after our first response."""
    s = ctx.since_open
    if not s:
        return None
    anchor_key, idx = None, None
    if ctx.we_opened and s[0] in ("1N", "2N"):
        anchor_key, idx = s[0], 0
    elif ctx.we_opened and s[:5] == ("2C", "P", "2D", "P", "2N"):
        anchor_key, idx = "2C2D2N", 4
    elif ctx.they_opened and len(s) >= 2 and s[1] == "1N" and s[0][0] == "1":
        anchor_key, idx = "1N-overcall", 1
    if anchor_key is None:
        return None
    # the opening side before the anchor must be undisturbed
    if anchor_key in ("1N", "2N", "2C2D2N") and any(c != "P" for c in s[1:idx:2]):
        return None
    after = s[idx + 1:]
    if len(after) % 2 == 0:  # not our turn in the NT auction
        return None
    opp_calls, ours = after[0::2], after[1::2]
    if any(c != "P" for c in (opp_calls[:1] if contested else opp_calls)):
        return None
    lo, hi, level, inv, game, quant, slam = ANCHORS[anchor_key]
    return NTState(lo, hi, level, tuple(ours), len(ours) % 2 == 1, inv, game, quant, slam)


def nt(ours: tuple[str, ...] | None = None, level: int | None = None, nt_bidder=None,
       test=None):
    """Situation: NT anchor with our subsequent calls == ours (and test(state))."""
    def check(ctx: Ctx) -> bool:
        st = nt_state(ctx)
        if st is None:
            return False
        if ours is not None and st.ours != ours:
            return False
        if level is not None and st.level != level:
            return False
        if nt_bidder is not None and st.i_am_nt != nt_bidder:
            return False
        return test is None or bool(st.ours and test(st))
    return check


def st(ctx: Ctx) -> NTState:
    return nt_state(ctx)


def is_max(ev: Eval, ctx: Ctx) -> bool:
    return ev.hcp >= st(ctx).hi


def major_lengths(ev: Eval) -> tuple[int, int]:
    return ev.len("S"), ev.len("H")


def _five_four_majors(ev: Eval) -> bool:
    return sorted(major_lengths(ev)) == [4, 5]


R: list[Rule] = []          # natural (core)
STAYMAN: list[Rule] = []
JACOBY: list[Rule] = []
MINOR_T: list[Rule] = []
GERBER: list[Rule] = []

# --- natural responses --------------------------------------------------------------


def _resp_pass(ev, ctx, c):
    s = st(ctx)
    return ev.hcp < (s.inv if s.inv else s.game)


def _pass_meaning(ctx, c):
    s = st(ctx)
    top = (s.inv if s.inv else s.game) - 1
    return shows(f"Not enough for game opposite {s.lo}-{s.hi}", (0, top))


R += [
    Rule("Pass partner's NT", nt((), nt_bidder=False), "P", _resp_pass, _pass_meaning, priority=40),
    Rule("2NT invite", nt((), level=1, nt_bidder=False), "2N",
         lambda ev, ctx, c: st(ctx).inv <= ev.hcp < st(ctx).game,
         lambda ctx, c: shows("Invitational: 8-9 HCP, no 4-card major", (8, 9)), priority=60),
    Rule("3NT to play", nt((), nt_bidder=False), "3N",
         lambda ev, ctx, c: st(ctx).game <= ev.hcp < st(ctx).quant,
         lambda ctx, c: shows(f"To play: {st(ctx).game}-{st(ctx).quant - 1} HCP",
                              (st(ctx).game, st(ctx).quant - 1)), priority=60),
    Rule("Quantitative 4NT", nt((), nt_bidder=False), "4N",
         lambda ev, ctx, c: st(ctx).quant <= ev.hcp < st(ctx).slam and ev.semi_balanced,
         lambda ctx, c: shows(f"Quantitative: {st(ctx).quant}-{st(ctx).slam - 1} HCP, "
                              "invites 6NT", (st(ctx).quant, st(ctx).slam - 1)), priority=60),
    Rule("6NT", nt((), nt_bidder=False), "6N",
         lambda ev, ctx, c: st(ctx).slam <= ev.hcp < st(ctx).slam + 4,
         lambda ctx, c: shows("To play", (st(ctx).slam, st(ctx).slam + 3)), priority=59),
    Rule("7NT", nt((), nt_bidder=False), "7N",
         lambda ev, ctx, c: ev.hcp >= st(ctx).slam + 4,
         lambda ctx, c: shows("To play", (st(ctx).slam + 4, 37)), priority=59),
    # natural major bids when transfers are off
    Rule("Weak 2-level takeout", nt((), level=1, nt_bidder=False), ["2D", "2H", "2S"],
         lambda ev, ctx, c: ev.hcp < st(ctx).inv and ev.len(c[1]) >= 5,
         lambda ctx, c: shows(f"Weak, 5+ {c[1]}, to play", (0, 7), signoff=True, **{c[1]: 5}),
         priority=55, prefer=lambda ev, ctx, c: -ev.len(c[1]), only_if_off=("jacoby",)),
    Rule("Forcing 3-level major", nt((), nt_bidder=False), ["3H", "3S"],
         lambda ev, ctx, c: ev.hcp >= st(ctx).game and ev.len(c[1]) >= 5,
         lambda ctx, c: shows(f"Game forcing, 5+ {c[1]}", (st(ctx).game, 37), game_forcing=True,
                              **{c[1]: 5}),
         priority=65, prefer=lambda ev, ctx, c: -ev.len(c[1]), only_if_off=("jacoby",)),
    # opener's rebids
    Rule("Accept invitation", nt(("2N",), nt_bidder=True), "3N",
         lambda ev, ctx, c: is_max(ev, ctx), shows("Maximum, accepting", (17, 18)), priority=60),
    Rule("Decline invitation", nt(("2N",), nt_bidder=True), "P", lambda *a: True,
         shows("Minimum, declining", (15, 16)), priority=40),
    Rule("Accept quantitative", nt(("4N",), nt_bidder=True), "6N",
         lambda ev, ctx, c: is_max(ev, ctx), shows("Maximum, accepting slam"), priority=60),
    Rule("Decline quantitative", nt(("4N",), nt_bidder=True), "P", lambda *a: True,
         shows("Minimum, declining slam"), priority=40),
    Rule("Pass partner's signoff",
         nt(nt_bidder=True, test=lambda s: s.ours[-1] in ("3N", "6N", "7N", "4H", "4S")), "P",
         lambda *a: True, shows("Accepting partner's decision"), priority=30),
    Rule("Pass weak takeout",
         nt(nt_bidder=True, test=lambda s: len(s.ours) == 1 and s.ours[0] in ("2D", "2H", "2S")),
         "P", lambda *a: True, shows("Accepting partner's signoff"), priority=30,
         only_if_off=("jacoby",)),
    Rule("Choose game after 3M",
         nt(nt_bidder=True, test=lambda s: len(s.ours) == 1 and s.ours[0] in ("3H", "3S")),
         ["4H", "4S", "3N"],
         lambda ev, ctx, c: (c[1] == st(ctx).ours[-1][1] and ev.len(c[1]) >= 3) or
         (c == "3N" and ev.len(st(ctx).ours[-1][1]) < 3),
         lambda ctx, c: shows("Choosing game"), priority=60, only_if_off=("jacoby",)),
]

# --- Stayman -------------------------------------------------------------------------


def _stayman_ok(ev, ctx, c):
    s = st(ctx)
    sp, he = major_lengths(ev)
    has4 = 4 in (sp, he)
    if s.level == 1:
        if ev.hcp >= s.inv and has4 and max(sp, he) <= 5:
            return True
        return ev.hcp < s.inv and _five_four_majors(ev)
    return ev.hcp >= s.game and has4 and max(sp, he) <= 5


def _stayman_call(ctx):
    return ["2C"] if st(ctx).level == 1 else ["3C"]


STAYMAN += [
    Rule("Stayman", nt((), nt_bidder=False), _stayman_call, _stayman_ok,
         shows("Stayman: asks for a 4-card major", forcing=True, artificial=True), priority=79),
]


def _stayman_reply(ev, ctx, c):
    if c[1] == "H":
        return ev.len("H") >= 4
    if c[1] == "S":
        return ev.len("S") >= 4 and ev.len("H") < 4
    return ev.len("H") < 4 and ev.len("S") < 4


def _reply_calls(ctx):
    lvl = 2 if st(ctx).level == 1 else 3
    return [f"{lvl}D", f"{lvl}H", f"{lvl}S"]


def _reply_meaning(ctx, c):
    if c[1] == "D":
        return shows("No 4-card major", S=(0, 3), H=(0, 3), artificial=True)
    if c[1] == "H":
        return shows("4+ hearts (may also have 4 spades)", H=4)
    return shows("4+ spades, fewer than 4 hearts", S=4, H=(0, 3))


STAYMAN += [
    Rule("Stayman reply", nt(("2C",), nt_bidder=True), _reply_calls, _stayman_reply,
         _reply_meaning, priority=80),
    Rule("Stayman reply", nt(("3C",), nt_bidder=True), _reply_calls, _stayman_reply,
         _reply_meaning, priority=80),
]


def _after_reply(ctx):
    s = st(ctx)
    return s is not None and not s.i_am_nt and len(s.ours) == 2 and s.ours[0] in ("2C", "3C")


def _resp_after_reply_calls(ctx):
    return ["P", "2H", "2S", "2N", "3H", "3S", "3N", "4H", "4S"]


def _resp_after_reply_ok(ev, ctx, c):
    s = st(ctx)
    reply = s.ours[1]
    rs = reply[1]
    fit = rs in "HS" and ev.len(rs) >= 4
    weak = s.inv is not None and ev.hcp < s.inv
    if s.level == 1:
        if weak:  # garbage Stayman
            if rs == "D":
                return c in ("2H", "2S") and ev.len(c[1]) >= 5
            return c == "P"
        if fit:
            if ev.hcp < s.game:
                return c == f"3{rs}"
            return c == f"4{rs}"
        if rs == "D" and ev.hcp >= s.game and max(major_lengths(ev)) >= 5:
            m = "S" if ev.len("S") >= 5 else "H"
            return c == f"3{m}"
        if ev.hcp < s.game:
            return c == "2N"
        return c == "3N"
    # 2NT level
    if fit:
        return c == f"4{rs}"
    return c == "3N"


def _resp_after_reply_meaning(ctx, c):
    s = st(ctx)
    rs = s.ours[1][1]
    if c == "P":
        return shows("Weak, happy here", (0, 7), signoff=True)
    if c in ("2H", "2S"):
        return shows(f"Weak with 5 {c[1]} and 4 in the other major, to play", (0, 7),
                     signoff=True, **{c[1]: 5})
    if c == "2N":
        return shows("Invitational, 8-9 HCP; no fit for the major shown", (8, 9))
    if c == "3N":
        return shows("To play; no fit for the major shown", (s.game, s.quant - 1))
    if c[1] == rs:
        if c[0] == "3":
            return shows(f"Invitational raise, 4 {rs}", (8, 9), **{rs: 4})
        return shows(f"Game, 4 {rs}", (s.game, 37), signoff=True, **{rs: 4})
    return shows(f"Game forcing, 5 {c[1]}", (s.game, 37), game_forcing=True, **{c[1]: 5})


STAYMAN += [
    Rule("Responder after Stayman reply", _after_reply, _resp_after_reply_calls,
         _resp_after_reply_ok, _resp_after_reply_meaning, priority=78),
]


def _opener_after_stayman(ctx):
    s = st(ctx)
    return s is not None and s.i_am_nt and len(s.ours) == 3 and s.ours[0] in ("2C", "3C")


def _opener_after_stayman_ok(ev, ctx, c):
    s = st(ctx)
    _, reply, cont = s.ours
    four_s = ev.len("S") >= 4 and reply[1] == "H"
    mx = is_max(ev, ctx)
    if cont == "2N":
        if four_s:
            return c == ("4S" if mx else "3S")
        return c == ("3N" if mx else "P")
    if cont == "3N":
        return c == ("4S" if four_s else "P")
    if cont[0] == "3" and cont[1] == reply[1]:  # invitational raise
        return c == (f"4{reply[1]}" if mx else "P")
    if cont[0] == "3" and cont[1] in "HS":  # 5-card major, forcing
        return c == (f"4{cont[1]}" if ev.len(cont[1]) >= 3 else "3N")
    return c == "P"


STAYMAN += [
    Rule("Opener's last word after Stayman", _opener_after_stayman,
         ["P", "3S", "3N", "4H", "4S"], _opener_after_stayman_ok,
         lambda ctx, c: shows("Opener's rebid after Stayman"), priority=78),
]

# --- Stayman after the opponents interfere ---------------------------------------------
# 1NT-2C-(2D): opener still answers if the major can be shown cheaply; Pass says
# "no major to show"; Double is for penalty (length and two top honors in their
# suit). Over a double of 2C opener replies as usual.


def _contested_stayman(ctx, n_ours: int):
    s = nt_state(ctx, contested=True)
    if s is None or len(s.ours) != n_ours or s.ours[0] not in ("2C", "3C"):
        return None
    opp = ctx.since_open[1 - 2 * n_ours::2]  # their calls since our Stayman bid
    return s if any(c != "P" for c in opp) else None


def _their_call(ctx) -> str:
    """Their call right after our Stayman bid."""
    i = len(ctx.since_open) - 2 * len(st_c(ctx).ours) + 1
    return ctx.since_open[i]


def st_c(ctx) -> NTState:
    return nt_state(ctx, contested=True)


def _stayman_reply_calls_contested(ctx):
    s = st_c(ctx)
    lvl = 2 if s.level == 1 else 3
    their = _their_call(ctx)
    if their == "X":
        return [f"{lvl}D", f"{lvl}H", f"{lvl}S", "XX"]
    calls = ["P", "X"]
    for m in "HS":
        b = cheapest(ctx, m)
        if b and int(b[0]) <= lvl + 1:
            calls.append(b)
    return calls


def _major_to_show(ev, ctx) -> str | None:
    their = _their_call(ctx)
    for m in "HS":
        if ev.len(m) >= 4 and their[-1] != m:
            return m
    return None


def _stayman_reply_contested_ok(ev, ctx, c):
    s = st_c(ctx)
    lvl = 2 if s.level == 1 else 3
    their = _their_call(ctx)
    if their == "X":
        if c == "XX":
            return ev.len("C") >= 4 and ev.honors("C", 3) >= 2
        return _stayman_reply(ev, ctx, c)
    m = _major_to_show(ev, ctx)
    if m:
        b = cheapest(ctx, m)
        # one level higher than usual only with a maximum
        if int(b[0]) > lvl and ev.hcp < s.hi:
            m = None
        elif c[1:] == m:
            return True
    t = their[1]
    penalty = t in "CDHS" and ev.len(t) >= 4 and ev.honors(t, 3) >= 2
    if c == "X":
        return m is None and penalty
    return c == "P" and m is None and not penalty


def _denied_majors(ctx) -> dict:
    """Majors opener could have shown at the usual level, so Pass/Double deny them."""
    lvl = 2 if st_c(ctx).level == 1 else 3
    their = _their_call(ctx)
    return {m: (0, 3) for m in "HS"
            if their[-1] != m and (cheapest(ctx, m) or "9")[0] <= str(lvl)}


def _reply_contested_meaning(ctx, c):
    if c == "P":
        return shows("No 4-card major I can show", **_denied_majors(ctx))
    if c == "X":
        t = _their_call(ctx)[1]
        return shows(f"Penalty: 4+ {_NAMES[t]} with two top honors, no 4-card major",
                     **{**_denied_majors(ctx), t: 4})
    if c == "XX":
        return shows("Good clubs; happy to play 2C redoubled", C=4)
    if _their_call(ctx) == "X":
        return _reply_meaning(ctx, c)
    if c[1] == "H":
        return shows("4+ hearts (answering Stayman)", H=4)
    return shows("4+ spades (answering Stayman)", S=4)


_NAMES = {"S": "spades", "H": "hearts", "D": "diamonds", "C": "clubs"}


def _after_contested_reply_ok(ev, ctx, c):
    s = st_c(ctx)
    reply = s.ours[1]
    theirs = [x[1] for x in ctx.opp_bids if x[1] in "CDHS"]
    weak = s.inv is not None and ev.hcp < s.inv
    rs = reply[1] if reply[0].isdigit() else None
    if rs in ("H", "S") and ev.len(rs) >= 4:  # fit
        if weak:
            return c == "P"
        if ev.hcp >= s.game:
            return c == f"4{rs}"
        raise_ = cheapest(ctx, rs)
        return c == (raise_ if raise_ and int(raise_[0]) <= 3 else "P")
    if reply == "X":  # opener doubled them for penalty
        return c == "P"
    if weak:
        five = [m for m in "SH" if ev.len(m) >= 5 and m not in theirs]
        b = cheapest(ctx, five[0]) if five else None
        return c == (b if b and int(b[0]) <= 2 else "P")
    five = [m for m in "SH" if ev.len(m) >= 5 and m not in theirs]
    if ev.hcp >= s.game or (five and rs is None and ev.tp >= s.game):  # a 5-card major's length counts too
        if five and rs is None and f"3{five[0]}" in ctx.legal:  # 2M would be the weak sign-off: jump
            return c == f"3{five[0]}"
        return c == ("3N" if "3N" in ctx.legal else "P")
    # invitational
    if ev.stoppers(theirs) and "2N" in ctx.legal:
        return c == "2N"
    return c == "P"


def _after_contested_reply_meaning(ctx, c):
    s = st_c(ctx)
    if c == "P":
        return shows("Nothing more to say", (0, s.game - 1))
    if c == "2N":
        return shows("Invitational, 8-9 HCP, stopper in their suit", (8, 9))
    if c == "3N":
        return shows("To play", (s.game, s.quant - 1))
    if c[1] in "HS" and c[0] == "4":
        return shows(f"Game, 4 {_NAMES[c[1]]}", (s.game, 37), signoff=True, **{c[1]: 4})
    if c[1] == s.ours[1][-1]:
        return shows(f"Invitational raise, 4 {_NAMES[c[1]]}", (8, 9), **{c[1]: 4})
    if c[0] == "2":
        return shows(f"Weak with 5 {_NAMES[c[1]]}, to play", (0, 7), signoff=True, **{c[1]: 5})
    return shows(f"Game forcing, 5 {_NAMES[c[1]]}", (s.game, 37), game_forcing=True,
                 **{c[1]: 5})


STAYMAN += [
    Rule("Stayman reply after interference", lambda ctx: _contested_stayman(ctx, 1) is not None
         and st_c(ctx).i_am_nt, _stayman_reply_calls_contested, _stayman_reply_contested_ok,
         _reply_contested_meaning, priority=80),
    Rule("Responder after contested Stayman",
         lambda ctx: _contested_stayman(ctx, 2) is not None and not st_c(ctx).i_am_nt,
         lambda ctx: ctx.legal, _after_contested_reply_ok, _after_contested_reply_meaning,
         priority=78),
]

# --- Jacoby transfers -------------------------------------------------------------


def _transfer_target(ev: Eval) -> str | None:
    sp, he = major_lengths(ev)
    if max(sp, he) < 5:
        return None
    if _five_four_majors(ev):
        return None  # Stayman first
    if sp >= he:
        return "S"
    return "H"


def _transfer_calls(ctx):
    return ["2D", "2H"] if st(ctx).level == 1 else ["3D", "3H"]


def _transfer_ok(ev, ctx, c):
    target = {"D": "H", "H": "S"}[c[1]]
    return _transfer_target(ev) == target


JACOBY += [
    Rule("Jacoby transfer", nt((), nt_bidder=False), _transfer_calls, _transfer_ok,
         lambda ctx, c: shows(f"Transfer: 5+ {'hearts' if c[1] == 'D' else 'spades'}",
                              artificial=True, forcing=True,
                              **{"H" if c[1] == "D" else "S": 5}),
         priority=80),
]


def _complete_calls(ctx):
    t = st(ctx).ours[0]
    return [f"{t[0]}{'H' if t[1] == 'D' else 'S'}"]


def _is_transfer_start(ctx, i_am_nt):
    s = st(ctx)
    return (s is not None and len(s.ours) >= 1 and s.i_am_nt == i_am_nt and
            s.ours[0] in (("2D", "2H") if s.level == 1 else ("3D", "3H")))


def _target(ctx) -> str:
    return "H" if st(ctx).ours[0][1] == "D" else "S"


JACOBY += [
    Rule("Complete transfer after a double", seq("1N", "P", {"2D", "2H"}, "X", opener="me"),
         lambda ctx: ["2H" if ctx.since_open[2] == "2D" else "2S"], lambda *a: True,
         lambda ctx, c: shows("Completing the transfer after their double (says nothing about length)"),
         priority=80),
    Rule("Complete transfer",
         lambda ctx: _is_transfer_start(ctx, True) and len(st(ctx).ours) == 1,
         _complete_calls, lambda *a: True,
         lambda ctx, c: shows("Completing the transfer (says nothing about length)"),
         priority=80),
]


def _after_completion_ok(ev, ctx, c):
    s = st(ctx)
    m = _target(ctx)
    n = ev.len(m)
    if s.inv is not None and ev.hcp < s.inv or s.inv is None and ev.hcp < s.game:
        return c == "P"
    if s.inv is not None and ev.hcp < s.game:
        return c == (f"3{m}" if n >= 6 else "2N")
    return c == (f"4{m}" if n >= 6 else "3N")


def _after_completion_meaning(ctx, c):
    s = st(ctx)
    m = _target(ctx)
    if c == "P":
        return shows("Weak, to play", (0, (s.inv or s.game) - 1), signoff=True)
    if c == "2N":
        return shows(f"Invitational, exactly 5 {m}", (8, 9), **{m: (5, 5)})
    if c == f"3{m}":
        return shows(f"Invitational, 6+ {m}", (8, 9), **{m: 6})
    if c == "3N":
        return shows(f"Game values, exactly 5 {m}: choose 3NT or 4{m}", (s.game, 37),
                     **{m: (5, 5)})
    return shows(f"Game, 6+ {m}", (s.game, 37), signoff=True, **{m: 6})


JACOBY += [
    Rule("Responder after transfer",
         lambda ctx: _is_transfer_start(ctx, False) and len(st(ctx).ours) == 2,
         lambda ctx: ["P", "2N", f"3{_target(ctx)}", "3N", f"4{_target(ctx)}"],
         _after_completion_ok, _after_completion_meaning, priority=80),
]


def _opener_after_transfer_ok(ev, ctx, c):
    s = st(ctx)
    m = _target(ctx)
    cont = s.ours[2]
    n = ev.len(m)
    mx = is_max(ev, ctx)
    if cont == "2N":
        if n >= 3:
            return c == (f"4{m}" if mx else f"3{m}")
        return c == ("3N" if mx else "P")
    if cont == f"3{m}":
        return c == (f"4{m}" if mx else "P")
    if cont == "3N":
        return c == (f"4{m}" if n >= 3 else "P")
    return c == "P"


def _opener_after_transfer_meaning(ctx, c):
    m = _target(ctx)
    s = st(ctx)
    if c == "P":
        return shows("Declining", (s.lo, s.hi - 1), signoff=True)
    if c == f"3{m}":
        return shows(f"Minimum with 3+ {m}: declining, to play", (s.lo, s.hi - 1),
                     signoff=True, **{m: 3})
    if c == "3N":
        return shows(f"Maximum with only 2 {m}", (s.hi, s.hi + 1), signoff=True, **{m: (2, 2)})
    return shows(f"Game with 3+ {m}", signoff=True, **{m: 3})


JACOBY += [
    Rule("Opener after transfer continuation",
         lambda ctx: _is_transfer_start(ctx, True) and len(st(ctx).ours) == 3,
         lambda ctx: ["P", f"3{_target(ctx)}", "3N", f"4{_target(ctx)}"],
         _opener_after_transfer_ok, _opener_after_transfer_meaning, priority=80),
]

# --- 2S minor transfer -------------------------------------------------------------

MINOR_T += [
    Rule("Minor-suit transfer", nt((), level=1, nt_bidder=False), "2S",
         lambda ev, ctx, c: ev.hcp < 8 and max(ev.len("C"), ev.len("D")) >= 6 and
         max(major_lengths(ev)) < 5,
         shows("Weak with a 6+ card minor: asks opener to bid 3C", (0, 7), artificial=True,
               forcing=True),
         priority=75),
    Rule("Complete minor transfer", nt(("2S",), level=1, nt_bidder=True), "3C",
         lambda *a: True, shows("Forced", artificial=True), priority=80),
    Rule("Pass or correct to diamonds", nt(("2S", "3C"), level=1, nt_bidder=False), ["P", "3D"],
         lambda ev, ctx, c: (c == "3D") == (ev.len("D") > ev.len("C")),
         lambda ctx, c: shows("To play" + (" in diamonds" if c == "3D" else " in clubs"),
                              signoff=True, **({"D": 6} if c == "3D" else {"C": 6})),
         priority=80),
    Rule("Pass minor signoff", nt(("2S", "3C", "3D"), level=1, nt_bidder=True), "P",
         lambda *a: True, shows("Accepting signoff"), priority=80),
]

# --- Gerber --------------------------------------------------------------------------

GERBER_RESP = {0: "4D", 4: "4D", 1: "4H", 2: "4S", 3: "4N"}

GERBER += [
    Rule("Gerber", nt((), nt_bidder=False), "4C",
         lambda ev, ctx, c: ev.hcp >= st(ctx).slam,
         shows("Gerber: asks for aces", artificial=True, forcing=True), priority=85),
    Rule("Gerber response", nt(("4C",), nt_bidder=True), ["4D", "4H", "4S", "4N"],
         lambda ev, ctx, c: GERBER_RESP[ev.aces] == c,
         lambda ctx, c: shows({"4D": "0 or 4 aces", "4H": "1 ace", "4S": "2 aces",
                               "4N": "3 aces"}[c], artificial=True),
         priority=85),
]


def _gerber_total(ev, ctx) -> int:
    resp = st(ctx).ours[1]
    p = {"4D": 0, "4H": 1, "4S": 2, "4N": 3}[resp]
    if resp == "4D" and ev.aces == 0:
        p = 4
    return ev.aces + p


def _gerber_follow_ok(ev, ctx, c):
    s = st(ctx)
    total = _gerber_total(ev, ctx)
    combined = ev.hcp + s.lo
    if total <= 2:
        return c == ("4N" if "4N" in ctx.legal else "5N")
    if total == 4 and combined >= 37:
        return c == "7N"
    return c == "6N"


GERBER += [
    Rule("Gerber follow-up",
         nt(nt_bidder=False, test=lambda s: len(s.ours) == 2 and s.ours[0] == "4C"),
         ["4N", "5N", "6N", "7N"], _gerber_follow_ok,
         lambda ctx, c: shows("Sign-off after Gerber", signoff=True), priority=85),
    Rule("Pass after Gerber sign-off",
         nt(nt_bidder=True, test=lambda s: len(s.ours) == 3 and s.ours[0] == "4C"), "P",
         lambda *a: True, shows("Accepting"), priority=85),
]


# --- partner's 1NT and they overcall a suit ------------------------------------------------
# Natural and simple: 2M competes, 3M (5+) is game forcing, 3NT/2NT need a stopper, double is for penalty.


def _nt_overcalled(ctx: Ctx) -> bool:
    s = ctx.since_open
    return ctx.opener_rel == "pd" and len(s) == 2 and s[0] == "1N" and \
        s[1][0].isdigit() and s[1][1] in "CDHS"


def _over_their_overcall_choice(ev: Eval, ctx: Ctx) -> str:
    t = ctx.since_open[1][1]
    stop = ev.stopper(t)
    majors = sorted((m for m in "SH" if m != t and ev.len(m) >= 5), key=lambda m: -ev.len(m))
    if majors:
        m = majors[0]
        b = cheapest(ctx, m)
        if ev.hcp >= 10 or (ev.hcp >= 8 and ev.len(m) >= 6):
            if ev.len(m) >= 6 and f"4{m}" in ctx.legal:
                return f"4{m}"
            if f"3{m}" in ctx.legal and b and b[0] <= "3":
                return f"3{m}"
        elif b and b[0] == "2":
            return b
    if 10 <= ev.hcp <= 15 and stop and "3N" in ctx.legal:
        return "3N"
    if 8 <= ev.hcp <= 15 and "3N" in ctx.legal and \
            any(m != t and ev.len(m) >= 6 and ev.honors(m, 3) == 3 for m in "CD"):
        return "3N"  # a running minor (A-K-Q and 6+): seven tricks opposite 1NT
    if 8 <= ev.hcp <= 9 and stop and "2N" in ctx.legal:
        return "2N"
    if ev.hcp >= 8 and ev.len(t) >= 4 and ev.honors(t, 5) >= 2 and "X" in ctx.legal:
        return "X"
    return "P"


def _over_their_overcall_meaning(ctx: Ctx, c: str):
    t = ctx.since_open[1][1]
    if c == "P":
        return shows("Nothing suitable to bid", (0, 12))
    if c == "X":
        return shows(f"Penalty: length and honors in {_NAMES[t]}", (8, 37), **{t: 4})
    if c == "2N":
        return shows("Invitational, stopper in their suit", (8, 9))
    if c == "3N":
        return shows("To play: a stopper in their suit, or a long running minor", (8, 15))
    m = c[1]
    if c[0] == "4":
        return shows(f"To play, 6+ {_NAMES[m]}", (8, 15), signoff=True, **{m: 6})
    if c[0] == "3":
        return shows(f"Game forcing, 5+ {_NAMES[m]}", (10, 15), game_forcing=True, **{m: 5})
    return shows(f"Competing, 5+ {_NAMES[m]}, to play", (0, 9), signoff=True, **{m: 5})


R += [
    Rule("Answer 1NT after their overcall", _nt_overcalled, lambda ctx: ctx.legal,
         lambda ev, ctx, c: c == _over_their_overcall_choice(ev, ctx), _over_their_overcall_meaning,
         priority=60),
]


NOTRUMP = Convention("notrump", "Notrump responses",
                     "Natural responses to 1NT/2NT: 2NT invites, 3NT to play, 4NT quantitative.",
                     R, core=True)
STAYMAN_CONV = Convention("stayman", "Stayman",
                          "2♣ (3♣ over 2NT) asks opener for a four-card major.", STAYMAN)
JACOBY_CONV = Convention("jacoby", "Jacoby transfers",
                         "2♦ shows hearts, 2♥ shows spades (3♦/3♥ over 2NT); opener completes.",
                         JACOBY)
MINOR_T_CONV = Convention("minor_transfer", "2♠ minor-suit transfer",
                          "Over 1NT, 2♠ forces 3♣; responder passes or bids 3♦ (weak, 6+ minor).",
                          MINOR_T)
for r in MINOR_T:
    r.needs = ("jacoby",)
GERBER_CONV = Convention("gerber", "Gerber",
                         "4♣ over 1NT/2NT asks for aces: 4♦=0/4, 4♥=1, 4♠=2, 4NT=3.", GERBER)
