"""Competitive bidding: overcalls, takeout doubles, advances and responding
after an opponent's overcall (docs: "Competitive bidding")."""
from __future__ import annotations

from ...core.auction import is_bid
from ...core.cards import SUITS
from ..context import Ctx
from ..evaluation import Eval
from ..rules import Convention, Rule, cheapest, level_needed
from ..shows import shows

NAMES = {"S": "spades", "H": "hearts", "D": "diamonds", "C": "clubs"}
MIN_OVERCALL = {1: 8, 2: 10, 3: 13, 4: 15}


def _our_calls_all_pass(ctx: Ctx) -> bool:
    if ctx.opening_index is None:
        return False
    after = ctx.calls[ctx.opening_index:]
    return all(c == "P" for s, c in after if s in (ctx.me, ctx.partner))


def can_enter(ctx: Ctx) -> bool:
    """Opponents opened; we have only passed since; the last bid is theirs."""
    return ctx.they_opened and _our_calls_all_pass(ctx) and not ctx.contract_is_ours \
        and ctx.doubled == 0 and int(ctx.last_bid[0]) <= 4


def their_suits(ctx: Ctx) -> list[str]:
    return ctx.opp_suits


def unbid_suits(ctx: Ctx) -> list[str]:
    return [s for s in SUITS if s not in ctx.opp_suits]


def _min_hcp(ctx: Ctx, call: str) -> int:
    return MIN_OVERCALL.get(int(call[0]), 16)


def _last_level(ctx: Ctx) -> int:
    return int(ctx.last_bid[0])


# --- direct actions ----------------------------------------------------------------


def _nt_overcall_ok(ev, ctx, c):
    lvl = _last_level(ctx)
    if c == "1N":
        return lvl == 1 and ev.balanced and 15 <= ev.hcp <= 18 and ev.stoppers(their_suits(ctx))
    # 2NT/3NT over a weak two or pre-empt: natural, strong
    return int(c[0]) == lvl + (1 if lvl >= 2 else 0) and lvl >= 2 and 16 <= ev.hcp <= 21 and \
        ev.semi_balanced and ev.stoppers(their_suits(ctx)) and c == cheapest(ctx, "N")


def _simple_overcall_ok(ev, ctx, c):
    s = c[1]
    if s in their_suits(ctx) or s == "N" or c != cheapest(ctx, s):
        return False
    lvl = int(c[0])
    if ev.len(s) < 5 or ev.hcp > 16 or ev.hcp < _min_hcp(ctx, c):
        return False
    # two honors (cheat sheet); with 11+ points one top honor (A, K or Q) is enough
    if not (ev.decent_suit(s) or (ev.tp >= 11 and ev.honors(s, 3) >= 1)):
        return False
    if lvl >= 2 and not (ev.good_suit(s) or ev.len(s) >= 6):
        return False
    if ev.balanced and ev.hcp <= 10 and not ev.good_suit(s):
        return False
    return True


def _weak_jump_ok(ev, ctx, c):
    s = c[1]
    if s in their_suits(ctx) or s == "N":
        return False
    base = cheapest(ctx, s)
    if base is None or int(c[0]) != int(base[0]) + 1:
        return False
    lvl = int(c[0])
    need = {2: 6, 3: 7}.get(lvl)
    return need is not None and 5 <= ev.hcp <= 10 and ev.len(s) == need and ev.decent_suit(s)


def _takeout_shape(ev: Eval, ctx: Ctx) -> bool:
    theirs = their_suits(ctx)
    if any(ev.len(s) > 2 for s in theirs):
        return False
    unbid = unbid_suits(ctx)
    short_unbid = [s for s in unbid if ev.len(s) < 3]
    return not short_unbid or (len(short_unbid) == 1 and short_unbid[0] in "CD" and
                               all(ev.len(m) >= 4 for m in unbid if m in "HS"))


def _takeout_ok(ev, ctx, c):
    lvl = _last_level(ctx)
    if ctx.last_bid[1] == "N":
        return False
    need = 12 if lvl == 1 else 13
    strong = ev.hcp >= 17 or (ev.hcp >= 16 and ev.shape[0] >= 6)
    return strong or (ev.hcp >= need and _takeout_shape(ev, ctx))


def _overcall_calls(ctx: Ctx, jump: int) -> list[str]:
    """Suit overcalls at the cheapest level (+jump) in suits they haven't bid."""
    out = []
    for s in SUITS:
        if s in their_suits(ctx):
            continue
        b = cheapest(ctx, s)
        if b and int(b[0]) + jump <= (3 if jump else 4):
            out.append(f"{int(b[0]) + jump}{s}")
    return out


TAKEOUT_SHOWS = shows("Takeout double: opening values (12+), short in their suit and support "
                      "for the others — or any strong hand (17+)", (11, 37), forcing=True)


def _overcall_meaning(ctx, c):
    lvl = int(c[0])
    lo = MIN_OVERCALL.get(lvl, 15)
    return shows(f"Overcall: {lo}-16 HCP, 5+ {NAMES[c[1]]} with two honors (one with 11+)", (lo, 16),
                 **{c[1]: 5})


DIRECT = [
    Rule("1NT overcall", can_enter, ["1N", "2N", "3N"], _nt_overcall_ok,
         lambda ctx, c: (shows("15-18 balanced with a stopper in their suit", (15, 18),
                               balanced=True) if c == "1N" else
                         shows("16-21, stoppers in their suit, to play", (16, 21))),
         priority=80),
    # only of a 1NT opening: over a 1NT response or rebid their side has shown the values (Fable review, 2026-11-12)
    Rule("Penalty double of 1NT", lambda ctx: can_enter(ctx) and ctx.last_bid == "1N" and ctx.since_open[0] == "1N",
         "X",
         lambda ev, ctx, c: ev.hcp >= 16,
         shows("Penalty: 16+ HCP, any shape", (16, 37)), priority=80),
    Rule("Strong takeout double", can_enter, "X",
         lambda ev, ctx, c: _takeout_ok(ev, ctx, c) and (ev.hcp >= 17 or ev.hcp >= 16 and
                                                         ev.shape[0] >= 6),
         TAKEOUT_SHOWS, priority=75),
    Rule("Weak jump overcall", can_enter, lambda ctx: _overcall_calls(ctx, jump=1), _weak_jump_ok,
         lambda ctx, c: shows(f"Weak jump overcall: 5-10 HCP, {6 if c[0] == '2' else 7}+ "
                              f"{NAMES[c[1]]}", (5, 10), **{c[1]: 6 if c[0] == "2" else 7}),
         priority=72),
    Rule("Simple overcall", can_enter, lambda ctx: _overcall_calls(ctx, jump=0),
         _simple_overcall_ok,
         _overcall_meaning, priority=70,
         prefer=lambda ev, ctx, c: (-ev.len(c[1]), SUITS.index(c[1]))),
    Rule("Takeout double", can_enter, "X", _takeout_ok, TAKEOUT_SHOWS, priority=66),
    Rule("Pass over their opening", can_enter, "P", lambda *a: True,
         shows("No suitable overcall or double", (0, 16)), priority=20),
]


# --- reopening in the pass-out seat --------------------------------------------------
# (1x) P (P) or (2x weak) P (P): passing ends the auction, so act on less than in the direct seat.


def _balancing(ctx: Ctx) -> bool:
    return can_enter(ctx) and len(ctx.since_open) == 3 and ctx.since_open[1:] == ("P", "P") and \
        ctx.since_open[0] in ("1C", "1D", "1H", "1S", "2D", "2H", "2S")


def _balance_choice(ev: Eval, ctx: Ctx) -> str:
    o = ctx.since_open[0]
    lvl, t = int(o[0]), o[1]
    hcp = ev.hcp
    if lvl == 1 and ev.balanced and 11 <= hcp <= 14 and ev.stopper(t):
        return "1N"
    if lvl == 2 and ev.semi_balanced and 15 <= hcp <= 18 and ev.stopper(t) and "2N" in ctx.legal:
        return "2N"
    if hcp >= 15 and (ev.len(t) <= 3 or (ev.balanced and ev.stopper(t))) and "X" in ctx.legal:
        return "X"  # any 15+ (balanced 15-18 doubles, then bids notrump; a reopening 1NT is 11-14)
    for s in ev.longest_suits():
        b = cheapest(ctx, s)
        if s == t or ev.len(s) < 5 or not b:
            continue
        need = {1: 8, 2: 10 if ev.len(s) == 5 else 8, 3: 12}.get(int(b[0]), 99)
        if need <= hcp <= 16 and (int(b[0]) < 3 or ev.len(s) >= 6):
            return b
    short = ev.len(t) <= (3 if lvl == 1 or hcp >= 13 else 2)
    if hcp >= (10 if lvl == 1 else 12) and short and "X" in ctx.legal and \
            all(ev.len(m) >= 3 for m in "HS" if m != t):
        return "X"
    return "P"


def _balance_meaning(ctx: Ctx, c: str):
    if c == "1N":
        return shows("Reopening 1NT: 11-14 balanced with a stopper", (11, 14), balanced=True)
    if c == "2N":
        return shows("Reopening 2NT: 15-18 with a stopper", (15, 18))
    if c == "X":
        return shows("Reopening double: 10+ short in their suit, or any 15+", (10, 37), forcing=True)
    return shows(f"Reopening overcall: 8-16 HCP, 5+ {NAMES[c[1]]}", (8, 16), **{c[1]: 5})


BALANCING = [
    Rule("Reopen in the pass-out seat", _balancing, lambda ctx: [c for c in ctx.legal if c != "P"],
         lambda ev, ctx, c: c == _balance_choice(ev, ctx), _balance_meaning, priority=85),
]

# --- advancing a takeout double ----------------------------------------------------


def _advancing_double(ctx: Ctx) -> bool:
    s = ctx.since_open
    if not ctx.they_opened or len(ctx.calls) < 2:
        return False
    # partner's last call was X of their bid, RHO passed, I haven't bid since the opening
    return (ctx.calls[-2] == (ctx.partner, "X") and ctx.calls[-1][1] == "P" and
            not any(is_bid(c) for c in ctx.my_calls) and
            all(c in ("P", "X") for c in ctx.partner_calls) and len(s) >= 3)


def _advance_choice(ev: Eval, ctx: Ctx) -> str:
    theirs = their_suits(ctx)
    unbid = unbid_suits(ctx)
    stop = ev.stoppers(theirs)

    def longest(cands):
        majors = [s for s in cands if s in "HS" and ev.len(s) >= 4]
        if majors:
            return max(majors, key=lambda s: (ev.len(s), -SUITS.index(s)))
        return max(cands, key=lambda s: (ev.len(s), -SUITS.index(s)))

    best = longest(unbid) if unbid else None
    majors4 = [m for m in ev.four_card_majors() if m not in theirs]
    if ev.hcp >= 13:
        if best in ("H", "S") and ev.len(best) >= 6:
            return f"4{best}"
        if ev.balanced and stop and ev.hcp <= 15 and "3N" in ctx.legal:
            return "3N"
        cue = cheapest(ctx, theirs[0]) if theirs else None
        if cue:
            return cue
    if 11 <= ev.hcp <= 12 and stop and not majors4 and "2N" in ctx.legal:
        return "2N"
    if 9 <= ev.hcp <= 12 and best in ("H", "S") and ev.len(best) >= 4 and \
            level_needed(ctx, best) == 3:
        return f"4{best}"  # over a pre-empt: no room to jump, so bid the game
    if 9 <= ev.hcp <= 12 and best and ev.len(best) >= 4 and cheapest(ctx, best):
        b = cheapest(ctx, best)
        jump = f"{int(b[0]) + 1}{best}"
        if jump in ctx.legal and int(jump[0]) <= 3:
            return jump
    if 6 <= ev.hcp <= 10 and stop and not majors4 and "1N" in ctx.legal:
        return "1N"
    if best:
        return cheapest(ctx, best)
    return "P"


def _advance_meaning(ctx: Ctx, c: str):
    if c == "P":
        return shows("Converting to penalties (long, strong trumps)")
    if not is_bid(c):
        return shows("Penalty")
    if c[1] == "N":
        return {"1": shows("6-10 HCP with a stopper", (6, 10)),
                "2": shows("11-12 HCP with a stopper, invitational", (11, 12)),
                "3": shows("13-15 balanced with a stopper", (13, 15))}.get(
            c[0], shows("To play"))
    if c[1] in ctx.opp_suits:
        return shows("Cue bid: 13+ HCP, forcing", (13, 37), game_forcing=True, artificial=True)
    s = c[1]
    base = cheapest(ctx, s)
    if c[0] == "4" and s in "HS" and c != base:
        if base and base[0] == "3":
            return shows(f"Game: 9+ HCP, 4+ {NAMES[s]}", (9, 37), **{s: 4})
        return shows(f"Game: 13+ with 6+ {NAMES[s]}", (10, 37), **{s: 6})
    if base and int(c[0]) > int(base[0]):
        return shows(f"Jump: 9-12 HCP, 4+ {NAMES[s]}", (9, 12), **{s: 4})
    if c[0] in "345":  # forced to the 3, 4 or 5 level (over a pre-empt): there was no room to jump or bid notrump
        return shows(f"0-12 HCP, longest unbid suit ({NAMES[s]})", (0, 12), **{s: 3})
    return shows(f"0-8 HCP, longest unbid suit ({NAMES[s]})", (0, 8), **{s: 3})


ADVANCE_X = [
    Rule("Advance a takeout double", _advancing_double, lambda ctx: ctx.legal,
         lambda ev, ctx, c: c == _advance_choice(ev, ctx), _advance_meaning, priority=80),
]

# --- advancing an overcall -----------------------------------------------------------


def _partner_overcall(ctx: Ctx) -> str | None:
    """Partner's overcall (a suit bid) if the situation is: they opened, partner
    overcalled, RHO passed or bid, and I haven't bid."""
    if not ctx.they_opened or any(is_bid(c) or c == "X" for c in ctx.my_calls):
        return None
    pb = [c for c in ctx.partner_calls if c != "P"]
    if len(pb) != 1 or not is_bid(pb[0]) or pb[0][1] == "N":
        return None
    # RHO passed or doubled (a double doesn't stop me raising: P (1♥) P (P) 1♠ (X), ♠K98: 2♠)
    # a penalty double is left to the rescue rule (general.py)
    # RHO may also bid a suit at the 2 level (1♦ 1♥ 2♦: raise to 2♥ with support, Fable review)
    last = ctx.calls[-1][1]
    if not (last in ("P", "X") or (is_bid(last) and int(last[0]) <= 2)) or ctx.calls[-2][0] != ctx.partner:
        return None
    if ctx.calls[-1][1] == "X" and \
            ctx.engine.explain(ctx.auction, len(ctx.calls) - 1).text.lower().startswith("penalty"):
        return None
    return pb[0]


def _is_reopening(ctx: Ctx, oc: str) -> bool:
    """Partner's overcall was made in the pass-out seat, so it can be a king lighter."""
    for i, (s, c) in enumerate(ctx.calls):
        if s == ctx.partner and c == oc:
            return ctx.engine.explain(ctx.auction, i).text.startswith("Reopening")
    return False


def _is_weak_jump(ctx: Ctx, oc: str) -> bool:
    for i, (s, c) in enumerate(ctx.calls):
        if s == ctx.partner and c == oc:
            return ctx.engine.explain(ctx.auction, i).hcp[1] <= 10
    return False


def _advance_overcall_choice(ev: Eval, ctx: Ctx) -> str:
    oc = _partner_overcall(ctx)
    y = oc[1]
    theirs = their_suits(ctx)
    stop = ev.stoppers(theirs)
    weak_jump = _is_weak_jump(ctx, oc)
    support = ev.len(y) >= (3 if y in "HS" or weak_jump else 4)
    assumed = 6 if weak_jump else 5
    if support:
        sp = ev.support_points(y)
        if _is_reopening(ctx, oc):
            sp -= 3  # partner borrowed a king to reopen
        if weak_jump:
            if sp >= 11:
                return f"4{y}" if y in "HS" else ("3N" if stop else f"5{y}")
            if sp >= 6:
                return cheapest(ctx, y)
            return "P"
        if sp >= 10 and theirs:
            cue = cheapest(ctx, theirs[0])
            if cue and int(cue[0]) <= 3:
                return cue
            game = f"{4 if y in 'HS' else 5}{y}"  # too high to cue bid: bid the game
            return game if game in ctx.legal else "P"  # partner is already in game
        total = ev.len(y) + assumed
        # by the Law of Total Tricks, but one level lower when they raised over the overcall: partner may have
        # bid on a minimum, and they compete too (tested: +52 IMPs over 5,000 deals)
        target = min(total - 6, 4) if not is_bid(ctx.calls[-1][1]) else min(total - 7, 4)
        if (ev.hcp >= 5 or ev.len(y) >= 4) and cheapest(ctx, y):
            want = f"{max(target, int(cheapest(ctx, y)[0]))}{y}"
            if want in ctx.legal:
                return want
        return "P"
    if weak_jump:
        return "3N" if ev.hcp >= 13 and stop else "P"
    if ev.hcp < 9:
        return "P"
    five = [s for s in SUITS if s != y and s not in theirs and ev.len(s) >= 5 and ev.good_suit(s)]
    if five:
        b = cheapest(ctx, five[0])
        if b and int(b[0]) <= 3:
            return b
    if stop:
        total = ev.hcp + MIN_OVERCALL.get(int(oc[0]), 15)  # partner's overcall can be this light
        if ev.hcp >= 15 or total >= 25:
            return "3N"
        if ev.hcp >= 13 or total >= 21:
            return "2N" if "2N" in ctx.legal else "3N" if total >= 23 else "P"
        if "1N" in ctx.legal and ev.hcp <= 12:
            return "1N"
    return "P"


def _advance_overcall_meaning(ctx: Ctx, c: str):
    oc = _partner_overcall(ctx)
    y = oc[1]
    if c == "P":
        return shows("No fit or not enough to bid", (0, 12))
    if not is_bid(c):
        return shows("Penalty")
    if c[1] == y:
        return shows(f"Raise: support for {NAMES[y]}", (5, 12), **{y: 3})
    if c[1] in ctx.opp_suits:
        return shows(f"Cue bid: 10+ with support for {NAMES[y]}", (10, 37), forcing=True,
                     artificial=True, **{y: 3})
    if c[1] == "N":
        if int(oc[0]) == 1:
            return {"1": shows("9-12 with a stopper", (9, 12)),
                    "2": shows("13-14 with a stopper", (13, 14)),
                    "3": shows("15+ with a stopper, to play", (13, 37))}[c[0]]
        # over a two- or three-level overcall: count on partner's extra strength
        lo = 21 - MIN_OVERCALL.get(int(oc[0]), 15)
        return shows("Invitational, with a stopper", (lo, 14)) if c[0] == "2" else \
            shows("Game values with a stopper, to play", (lo + 2, 37))
    return shows(f"9+ HCP, good 5+ {NAMES[c[1]]}, not forcing", (9, 37), **{c[1]: 5})


def _overcaller_after_cue(ctx: Ctx) -> bool:
    if not ctx.they_opened or len(ctx.calls) < 2 or ctx.calls[-1][1] != "P":
        return False
    pc = ctx.partner_calls
    mine = [c for c in ctx.my_calls if c != "P"]
    return (len(mine) == 1 and is_bid(mine[0]) and mine[0][1] != "N" and pc and is_bid(pc[-1])
            and pc[-1][1] in ctx.opp_suits and ctx.calls[-2][0] == ctx.partner)


def _overcaller_after_cue_ok(ev, ctx, c):
    y = [x for x in ctx.my_calls if x != "P"][0][1]
    if ev.hcp >= 13:
        want = f"4{y}" if y in "HS" else ("3N" if "3N" in ctx.legal else f"5{y}")
        if want in ctx.legal:
            return c == want
    return c == cheapest(ctx, y)


ADVANCE_OC = [
    Rule("Advance an overcall", lambda ctx: _partner_overcall(ctx) is not None,
         lambda ctx: ctx.legal, lambda ev, ctx, c: c == _advance_overcall_choice(ev, ctx),
         _advance_overcall_meaning, priority=78),
    Rule("Overcaller after a cue bid", _overcaller_after_cue, lambda ctx: ctx.legal,
         _overcaller_after_cue_ok,
         lambda ctx, c: shows("Maximum: game" if c == "3N" or c != cheapest(ctx, c[-1]) else
                              "Minimum overcall"), priority=78),
]

# --- responder after an opponent's overcall ---------------------------------------------


def _responding_after_overcall(ctx: Ctx) -> bool:
    s = ctx.since_open
    return (ctx.opener_rel == "pd" and len(s) == 2 and s[0] in ("1C", "1D", "1H", "1S")
            and s[1] != "P" and not ctx.my_bids)


def _resp_interference_choice(ev: Eval, ctx: Ctx) -> str:
    o = ctx.since_open[0][1]
    theirs = their_suits(ctx)
    their_call = ctx.since_open[1]
    if o in "HS" and ev.len(o) >= 3:
        sp = ev.support_points(o)
        if 6 <= sp <= 9:
            return cheapest(ctx, o)
        if 10 <= sp <= 12:
            b = cheapest(ctx, o)
            j = f"{int(b[0]) + 1}{o}" if b else None
            return j if j in ctx.legal and int(j[0]) <= 3 else f"4{o}"
        if sp >= 13:
            return f"4{o}"
    if _negative_on(ctx):
        if _negative_double_ok(ev, ctx):
            return "X"
    elif is_bid(their_call) and their_call[1] in SUITS and ev.len(their_call[1]) >= 4 and \
            ev.hcp >= 10 and \
            ev.honors(their_call[1]) >= 2 and "X" in ctx.legal:
        return "X"
    if their_call == "X":
        if ev.hcp >= 10:
            return "XX"
    for s in ev.longest_suits():
        if s in theirs or s == o:
            continue
        b = cheapest(ctx, s)
        if b is None:
            continue
        lvl = int(b[0])
        if lvl == 1 and ev.len(s) >= 4 and ev.hcp >= 6:
            return b
        if lvl == 2 and ev.len(s) >= 5 and ev.hcp >= 10:
            return b
        if lvl == 3 and ev.len(s) >= 5 and ev.hcp >= 12:
            return b
    if ev.len(o) >= (4 if o in "CD" else 3) and 6 <= ev.hcp <= 10:
        b = cheapest(ctx, o)
        if b and int(b[0]) <= 2:
            return b
    if ev.stoppers(theirs):
        if 8 <= ev.hcp <= 10 and "1N" in ctx.legal:
            return "1N"
        if 11 <= ev.hcp <= 12 and "2N" in ctx.legal:
            return "2N"
        if ev.hcp >= 13:
            return "3N"
    if ev.hcp >= 13 and is_bid(their_call) and their_call[1] in SUITS:
        cue = cheapest(ctx, their_call[1])  # game values but no natural bid: cue bid
        if cue:
            return cue
    return "P"


# --- negative doubles ----------------------------------------------------------------------


def _negative_on(ctx: Ctx) -> bool:
    """Negative doubles are on, and their overcall is a suit at the one or two level."""
    their_call = ctx.since_open[1]
    return ("negative_doubles" in ctx.engine.enabled and is_bid(their_call) and their_call[1] in SUITS
            and int(their_call[0]) <= 2 and "X" in ctx.legal)


def _negative_suits(ctx: Ctx) -> str:
    """What a negative double promises: the unbid majors, or both minors when the majors are taken."""
    o, theirs = ctx.since_open[0][1], ctx.since_open[1][1]
    majors = "".join(m for m in "SH" if m not in (o, theirs))
    return majors or "".join(m for m in "DC" if m not in (o, theirs))


def _negative_double_ok(ev: Eval, ctx: Ctx) -> bool:
    lvl = int(ctx.since_open[1][0])
    if ev.hcp < (6 if lvl == 1 else 8):
        return False
    promised = _negative_suits(ctx)
    if promised in ("SH", "DC"):
        return all(ev.len(x) >= 4 for x in promised)
    x = promised[0]
    if ev.len(x) == 4:
        return True
    if ev.len(x) >= 5:  # a five-card suit is bid if we're strong enough to bid it
        b = cheapest(ctx, x)
        return b is None or (b[0] == "2" and ev.hcp < 10)
    return False


def _negative_meaning(ctx: Ctx, c: str):
    promised = _negative_suits(ctx)
    lvl = int(ctx.since_open[1][0])
    named = " and ".join(NAMES[x] for x in promised)
    each = "4 " if len(promised) == 1 else "4+ in each of "
    return shows(f"Negative double: {each}{named}, {6 if lvl == 1 else 8}+ HCP", (6 if lvl == 1 else 8, 37),
                 forcing=True, **{x: 4 for x in promised})


def _after_negative_double(ctx: Ctx) -> bool:
    s = ctx.since_open
    return (ctx.opener_rel == "me" and len(s) == 4 and s[0] in ("1C", "1D", "1H", "1S")
            and is_bid(s[1]) and s[1][1] in SUITS and int(s[1][0]) <= 2 and s[2] == "X" and s[3] == "P")


def _opener_after_negative_choice(ev: Eval, ctx: Ctx) -> str:
    o, theirs = ctx.since_open[0][1], ctx.since_open[1][1]
    tp = ev.tp

    def at(strain: str, extra: int) -> str | None:
        b = cheapest(ctx, strain)
        if b is None:
            return None
        c = f"{min(int(b[0]) + extra, 4 if strain in 'HS' else 5)}{strain}"
        return c if c in ctx.legal else b

    for x in _negative_suits(ctx):
        if ev.len(x) >= 4:
            extra = 0 if tp <= 15 else 1 if tp <= 18 else 2
            return at(x, extra)
    if ev.len(o) >= 6:
        return at(o, 0 if tp <= 15 else 1)
    if ev.stoppers([theirs]) and ev.semi_balanced:
        b = cheapest(ctx, "N")
        if b == "1N" or (b == "2N" and ev.hcp >= 15):
            return b if ev.hcp <= 18 or b == "2N" else "3N"
    for x in ev.longest_suits():
        if x not in (o, theirs) and ev.len(x) >= 4:
            b = cheapest(ctx, x)
            if b and int(b[0]) <= 2:
                return b
    return cheapest(ctx, o) or "P"


def _opener_after_negative_meaning(ctx: Ctx, c: str):
    o = ctx.since_open[0][1]
    if c == "P":
        return shows("Penalty: long, strong trumps in their suit")
    if c[1] == "N":
        return shows("Balanced with a stopper in their suit", (12, 18), balanced=True)
    if c[1] == o:
        return shows(f"Rebid: 6+ {NAMES[o]}", (12, 18), light=10, **{o: 6})
    b = cheapest(ctx, c[1])
    jump = int(c[0]) - int(b[0]) if b else 0
    rng = (12, 15) if jump <= 0 else (16, 18) if jump == 1 else (19, 21)
    return shows(f"{'Jump: ' if jump > 0 else ''}4+ {NAMES[c[1]]}, {rng[0]}-{rng[1]}", rng, light=rng[0] - 2, **{c[1]: 4})


NEGATIVE_RULES = [
    Rule("Negative double", lambda ctx: _responding_after_overcall(ctx) and _negative_on(ctx), "X",
         lambda ev, ctx, c: _resp_interference_choice(ev, ctx) == "X", _negative_meaning, priority=61),
    Rule("Opener after a negative double", _after_negative_double, lambda ctx: ctx.legal,
         lambda ev, ctx, c: c == _opener_after_negative_choice(ev, ctx), _opener_after_negative_meaning,
         priority=80),
]

NEGATIVE_DOUBLES = Convention(
    "negative_doubles", "Negative doubles",
    "After partner opens and the next player overcalls a suit (up to 2♠), double shows the "
    "unbid major(s) and 6+ points, not a penalty.", NEGATIVE_RULES,
    default_on=False)  # not on the No Fear cheat sheet, so off unless the players choose it


def _resp_interference_meaning(ctx: Ctx, c: str):
    o = ctx.since_open[0][1]
    if c == "P":
        return shows("Nothing suitable to bid", (0, 12))
    if c == "X":
        return shows("Penalty double: 10+ with length in their suit", (10, 37))
    if c == "XX":
        return shows("Redouble: 10+ HCP", (10, 37))
    if c[1] == o:
        # a single raise is 6-9 (6-10 in a minor), a jump 10-12, game 10+ (Fable review: opener read the limit
        # raise as anything from 6 to 15 and passed it with game values)
        b = cheapest(ctx, o)
        if c == b:
            return shows(f"Raise of partner's {NAMES[o]}: 6-9 points", (6, 10), **{o: 3})
        if b and int(c[0]) == int(b[0]) + 1 and int(c[0]) <= 3:
            return shows(f"Jump raise of partner's {NAMES[o]}: 10-12 points", (10, 12), **{o: 3})
        return shows(f"Raise of partner's {NAMES[o]} to game", (10, 15), **{o: 3})
    if c[1] == "N":
        return shows("Natural with a stopper", {"1": (8, 10), "2": (11, 12)}.get(c[0], (13, 18)))
    if c[1] in their_suits(ctx):
        return shows("Cue bid: 13+ HCP, game forcing, asks partner to describe", (13, 37),
                     game_forcing=True, artificial=True)
    lvl = int(c[0])
    return shows(f"New suit: 5+ {NAMES[c[1]]}" if lvl >= 2 else f"New suit: 4+ {NAMES[c[1]]}",
                 (10 if lvl >= 2 else 6, 37), forcing=True, **{c[1]: 5 if lvl >= 2 else 4})


def _opener_competes(ctx: Ctx) -> bool:
    """I opened one of a suit, they have bid since, partner has only passed."""
    return (ctx.opener_rel == "me" and ctx.since_open[0] in ("1C", "1D", "1H", "1S")
            and not ctx.partner_bids and not ctx.contract_is_ours and bool(ctx.opp_bids)
            and len(ctx.my_bids) == 1 and "X" not in ctx.my_calls and ctx.doubled == 0)


def _opener_compete_choice(ev: Eval, ctx: Ctx) -> str:
    o = ctx.since_open[0][1]
    theirs = their_suits(ctx)
    lvl = _last_level(ctx)
    if ev.hcp >= 16 and all(ev.len(s) <= 2 for s in theirs) and "X" in ctx.legal and lvl <= 3:
        return "X"
    if ev.len(o) >= 6:
        b = cheapest(ctx, o)
        if b and (int(b[0]) <= 2 or (int(b[0]) == 3 and ev.tp >= 15)):
            return b
    for s in ev.longest_suits():
        if s != o and s not in theirs and ev.len(s) >= 5 and ev.tp >= 15:
            b = cheapest(ctx, s)
            if b and int(b[0]) <= 3:
                return b
    if ev.hcp >= 18 and "X" in ctx.legal:
        return "X"
    return "P"


def _opener_compete_meaning(ctx: Ctx, c: str):
    o = ctx.since_open[0][1]
    if c == "P":
        return shows("Nothing more to add", (11, 17), light=10)
    if c == "X":
        return shows("Competitive double: 16+ with support for the unbid suits", (16, 37),
                     forcing=True)
    if c[1] == o:
        return shows(f"Rebid: 6+ {NAMES[o]}", (12, 18), light=10, **{o: 6})
    return shows(f"New suit: 5+ {NAMES.get(c[1], '')}, extra values", (15, 21),
                 **({c[1]: 5} if c[1] in SUITS else {}))


def _doubler_again(ctx: Ctx) -> bool:
    """I made a takeout double, partner has not bid, they still own the contract."""
    return (ctx.they_opened and "X" in ctx.my_calls and not ctx.my_bids and
            not ctx.partner_bids and not ctx.contract_is_ours and ctx.doubled == 0)


def _doubler_again_choice(ev: Eval, ctx: Ctx) -> str:
    if ev.hcp < 17 and not (ev.hcp >= 16 and ev.shape[0] >= 6):  # 16+ with a 6-card suit: double, then bid it
        return "P"
    theirs = their_suits(ctx)
    for s in ev.longest_suits():
        if s not in theirs and ev.len(s) >= 5:
            b = cheapest(ctx, s)
            if b and int(b[0]) <= 3:
                return b
    if ev.semi_balanced and ev.stoppers(theirs):
        b = cheapest(ctx, "N")
        if b and int(b[0]) <= 2:
            return b
    if "X" in ctx.legal and _takeout_shape(ev, ctx):
        return "X"
    return "P"


def _doubler_again_meaning(ctx: Ctx, c: str):
    if c == "P":
        return shows("Nothing extra to show", (11, 37))
    if c == "X":
        return shows("Second takeout double: strong, still short in their suits", (17, 37))
    if c[1] == "N":
        return shows("Strong balanced hand with a stopper (19+ if 1NT was skipped)", (17, 21))
    return shows(f"Strong hand (17+) with 5+ {NAMES[c[1]]}", (17, 37), **{c[1]: 5})


GAME_LEVEL = {"C": 5, "D": 5, "H": 4, "S": 4, "N": 3}


def _opener_rebid_over_them(ctx: Ctx) -> bool:
    """I opened one of a suit, partner has bid once, they bid over it; my second call."""
    return (ctx.opener_rel == "me" and ctx.since_open[0] in ("1C", "1D", "1H", "1S")
            and len(ctx.partner_bids) == 1 and len(ctx.my_bids) == 1 and not ctx.contract_is_ours
            and ctx.last_bidder == ctx.rho and ctx.doubled == 0 and "X" not in ctx.my_calls
            and ctx.partner_bids[0][1] != ctx.since_open[0][1])


def _partner_fit(ev: Eval, ctx: Ctx) -> str | None:
    p = ctx.partner_bids[0][1]
    if p in SUITS and p not in their_suits(ctx) and ev.len(p) + ctx.partner_info.min_len(p) >= 8:
        return p
    return None


def _raise(ctx: Ctx, suit: str, pts: int, extra: int, game_from: int) -> str | None:
    """Cheapest raise, a jump with extras, game with plenty (None when the raise would be too high)."""
    b = cheapest(ctx, suit)
    if b is None:
        return None
    game = f"{GAME_LEVEL[suit]}{suit}"
    if pts >= game_from and game in ctx.legal:
        return game
    lvl = int(b[0])
    if pts >= extra and lvl + 1 < GAME_LEVEL[suit] and lvl + 1 <= 3:
        return f"{lvl + 1}{suit}"
    if lvl <= 2 or (lvl == 3 and pts >= 15):
        return b
    return None


def _opener_rebid_over_them_choice(ev: Eval, ctx: Ctx) -> str:
    o = ctx.since_open[0][1]
    theirs = their_suits(ctx)
    fit = _partner_fit(ev, ctx)
    if fit:
        pts = ev.support_points(fit)
        b = _raise(ctx, fit, pts, 16, 19 if fit in "HS" else 99)
        if b:
            return b
    if ev.len(o) >= 6:
        b = _raise(ctx, o, ev.tp, 17, 99)
        if b:
            return b
    if ev.balanced and ev.stoppers(theirs):
        b = cheapest(ctx, "N")
        if b and (b[0] == "1" and ev.hcp <= 14 or b[0] == "2" and 18 <= ev.hcp <= 19):
            return b
        if ev.hcp >= 18 and "3N" in ctx.legal:
            return "3N"
    for s in ev.longest_suits():
        b = cheapest(ctx, s)
        if s in theirs or s in (o, ctx.partner_bids[0][1]) or not b:
            continue
        if (b[0] == "1" and ev.len(s) >= 4) or (b[0] == "2" and ev.len(s) >= 5 and ev.tp >= 15):
            return b
    return "P"


def _opener_rebid_over_them_meaning(ctx: Ctx, c: str):
    o = ctx.since_open[0][1]
    p = ctx.partner_bids[0][1]
    if c == "P":
        return shows("Nothing more to add (usually a minimum)", (11, 37), light=10)
    if c[1] == "N":
        return shows("Balanced with a stopper in their suit", {"1": (12, 14), "2": (18, 19)}.get(c[0], (18, 21)),
                     balanced=True)
    s, lvl = c[1], int(c[0])
    jump = lvl > int((cheapest(ctx, s) or c)[0])
    game = lvl >= GAME_LEVEL[s]
    rng = (19, 21) if game else (16, 18) if jump else (15, 18) if lvl == 3 else (12, 15)
    if s == p:
        return shows(f"Support for {NAMES[s]}", rng, **{s: 3 if ctx.partner_info.min_len(s) >= 5 else 4})
    if s == o:
        return shows(f"Rebid: 6+ {NAMES[s]}", rng, light=rng[0] - 2, **{s: 6})
    return shows(f"New suit: {4 if lvl == 1 else 5}+ {NAMES[s]}", (12, 18), light=10, **{s: 4 if lvl == 1 else 5})


def _doubler_after_advance(ctx: Ctx) -> bool:
    """I made a takeout double, partner answered with a bid, they bid again: my second call."""
    return (ctx.they_opened and "X" in ctx.my_calls and not ctx.my_bids and len(ctx.partner_bids) == 1
            and not ctx.contract_is_ours and ctx.last_bidder == ctx.rho and ctx.doubled == 0)


def _doubler_after_advance_choice(ev: Eval, ctx: Ctx) -> str:
    p = ctx.partner_bids[0][1]
    theirs = their_suits(ctx)
    if p in SUITS and p not in theirs and ev.len(p) >= 4:
        pts = ev.support_points(p)
        if pts >= 17:
            b = _raise(ctx, p, pts, 17, 22 if p in "HS" else 99)
            if b:
                return b
        b = cheapest(ctx, p)
        if b and b[0] == "2" and pts >= 14:  # compete for the part score
            return b
    if ev.hcp < 17 and not (ev.hcp >= 16 and ev.shape[0] >= 6):
        return "P"
    for s in ev.longest_suits():
        b = cheapest(ctx, s)
        if s not in theirs and s != p and ev.len(s) >= 5 and b and int(b[0]) <= 3:
            return b
    if ev.semi_balanced and ev.stoppers(theirs):
        b = cheapest(ctx, "N")
        if b and int(b[0]) <= 3:
            return b
    return "P"


def _doubler_after_advance_meaning(ctx: Ctx, c: str):
    p = ctx.partner_bids[0][1]
    if c == "P":
        return shows("Nothing extra to show", (11, 37))
    if c[1] == "N":
        return shows("Strong balanced hand with a stopper", (18, 21))
    s, lvl = c[1], int(c[0])
    if s == p:
        jump = lvl > int((cheapest(ctx, s) or c)[0])
        rng = (22, 37) if lvl >= GAME_LEVEL[s] else (17, 21) if jump else (14, 21)
        return shows(f"Support for {NAMES[s]}", rng, **{s: 4})
    return shows(f"Strong hand (17+) with 5+ {NAMES[s]}", (17, 37), **{s: 5})


RESP_INTERFERENCE = [
    Rule("Doubler acts again", _doubler_again, lambda ctx: ctx.legal,
         lambda ev, ctx, c: c == _doubler_again_choice(ev, ctx), _doubler_again_meaning,
         priority=55),
    Rule("Doubler after partner's answer", _doubler_after_advance, lambda ctx: ctx.legal,
         lambda ev, ctx, c: c == _doubler_after_advance_choice(ev, ctx), _doubler_after_advance_meaning,
         priority=55),
    Rule("Opener's rebid over their bid", _opener_rebid_over_them, lambda ctx: ctx.legal,
         lambda ev, ctx, c: c == _opener_rebid_over_them_choice(ev, ctx), _opener_rebid_over_them_meaning,
         priority=55),
    Rule("Opener competes", _opener_competes, lambda ctx: ctx.legal,
         lambda ev, ctx, c: c == _opener_compete_choice(ev, ctx), _opener_compete_meaning,
         priority=55),
    Rule("Respond after their overcall", _responding_after_overcall, lambda ctx: ctx.legal,
         lambda ev, ctx, c: c == _resp_interference_choice(ev, ctx),
         _resp_interference_meaning, priority=60),
]

COMPETITIVE = Convention(
    "competitive", "Overcalls and takeout doubles",
    "Simple and weak jump overcalls, 1NT overcall (15-18), takeout doubles, penalty double "
    "of 1NT, and how to advance them.",
    DIRECT + BALANCING + ADVANCE_X + ADVANCE_OC + RESP_INTERFERENCE, core=True)
