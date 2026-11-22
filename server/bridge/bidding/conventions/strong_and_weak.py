"""Strong 2C, weak twos and pre-empts: openings' follow-ups."""
from __future__ import annotations

from ...core.auction import is_bid
from ...core.cards import SUITS
from ..rules import Convention, Rule, U, cheapest, opening_position, seq
from ..shows import shows

NAMES = {"S": "spades", "H": "hearts", "D": "diamonds", "C": "clubs"}


def is_suit_bid(call: str) -> bool:
    return is_bid(call) and call[1] in SUITS

# --- strong 2C ---------------------------------------------------------------------


def _two_club_open(ev, ctx, c):
    return (ev.balanced and ev.hcp >= 22) or (not ev.balanced and ev.tp >= 22)


def _positive(ev):
    return ev.hcp >= 8 or (ev.aces >= 1 and ev.kings >= 1)


def _positive_suit(ev):
    five = [s for s in SUITS if ev.len(s) >= 5]
    if not five:
        return None
    return max(five, key=lambda s: (ev.len(s), -SUITS.index(s)))


def _resp_2c_ok(ev, ctx, c):
    if c == "2D":
        return not _positive(ev)
    if not _positive(ev):
        return False
    suit = _positive_suit(ev)
    if c == "2N":
        return suit is None
    return suit == c[1]


def _resp_2c_meaning(ctx, c):
    if c == "2D":
        return shows("Waiting/negative: 0-7 HCP", (0, 7), artificial=True, game_forcing=False,
                     forcing=True)
    if c == "2N":
        return shows("Positive: 8+ HCP, balanced, no 5-card suit", (8, 37), balanced=True,
                     game_forcing=True)
    return shows(f"Positive: 8+ HCP, 5+ {NAMES[c[1]]}", (8, 37), game_forcing=True, **{c[1]: 5})


def _opener_after_2d_ok(ev, ctx, c):
    if ev.balanced:
        if 22 <= ev.hcp <= 24:
            return c == "2N"
        if 25 <= ev.hcp <= 27:
            return c == "3N"
        return c == "4N" if ev.hcp >= 28 else False
    suit = max(SUITS, key=lambda s: (ev.len(s), -SUITS.index(s)))
    lvl = 2 if suit in "HS" else 3
    return c == f"{lvl}{suit}"


def _opener_after_2d_meaning(ctx, c):
    if c == "2N":
        return shows("22-24 balanced (not forcing)", (22, 24), balanced=True)
    if c == "3N":
        return shows("25-27 balanced", (25, 27), balanced=True)
    if c == "4N":
        return shows("28+ balanced, quantitative", (28, 37), balanced=True)
    return shows(f"Strong, 5+ {NAMES[c[1]]} (4 with a 4-4-4-1 hand), game forcing", (22, 37),
                 game_forcing=True, **{c[1]: 4})


def _resp_second_ok(ev, ctx, c):
    """Responder after 2C-2D-2x (x a suit): game forcing."""
    x = ctx.since_open[4][1]
    if ev.len(x) >= 3:
        return c == (f"3{x}" if x in "HS" else f"4{x}")
    five = [s for s in SUITS if ev.len(s) >= 5 and s != x]
    if five:
        return c == cheapest(ctx, five[0])
    return c == ("2N" if "2N" in ctx.legal else "3N")


def _resp_second_meaning(ctx, c):
    x = ctx.since_open[4][1]
    if c[1] == x:
        return shows(f"Support for {NAMES[x]} (3+), game forcing", game_forcing=True, **{x: 3})
    if c[1] in SUITS:
        return shows(f"Natural: 5+ {NAMES[c[1]]}, game forcing", game_forcing=True, **{c[1]: 5})
    return shows("Natural, game forcing", game_forcing=True)


def _strong_2c_interfered(ctx) -> bool:
    """I opened a strong 2C, the opponents have since bid, partner has only passed or bid 2D (waiting), and the
    last bid is theirs. 2C forces to game, so opener must not let them play it cheaply."""
    if ctx.opener_rel != "me" or ctx.since_open[:1] != ("2C",) or ctx.contract_is_ours or ctx.doubled:
        return False
    if not any(is_bid(c) for c in ctx.opp_bids):
        return False
    pd = [c for seat, c in ctx.calls[ctx.opening_index:] if seat == ctx.partner and c != "P"]
    return pd in ([], ["2D"]) and ctx.my_bids == ["2C"]


def _strong_2c_interfered_choice(ev, ctx) -> str | None:
    their = ctx.opp_suits
    if ev.semi_balanced and ev.stoppers(their):
        b = cheapest(ctx, "N")
        if b and int(b[0]) <= 3:
            return b
    for s in ev.longest_suits():
        b = cheapest(ctx, s)
        if ev.len(s) >= 5 and s not in their and b and int(b[0]) <= 5:
            return b
    return "X" if "X" in ctx.legal else None


def _strong_2c_interfered_meaning(ctx, c):
    if c == "X":
        return shows("Strong 2C opener: no clear bid, takeout (partner may pass for penalty)", (22, 37))
    if c[1] == "N":
        return shows("Strong 2C opener: balanced with a stopper in their suit", (22, 37), balanced=True)
    return shows(f"Strong 2C opener: 5+ {NAMES[c[1]]}", (22, 37), **{c[1]: 5})


STRONG_2C = [
    Rule("Strong 2C", opening_position, "2C", _two_club_open,
         shows("Strong: 22+ HCP balanced or 22+ total points; artificial, forcing", (19, 37),
               artificial=True, forcing=True),
         priority=95),
    Rule("Response to 2C", U("2C"), ["2D", "2H", "2S", "3C", "3D", "2N"], _resp_2c_ok,
         _resp_2c_meaning, priority=90),
    Rule("Opener after 2C-2D", U("2C", "2D"), ["2H", "2S", "3C", "3D", "2N", "3N", "4N"],
         _opener_after_2d_ok, _opener_after_2d_meaning, priority=90),
    Rule("Responder after 2C-2D-2x",
         lambda ctx: U("2C", "2D", is_suit_bid)(ctx),
         lambda ctx: ["2H", "2S", "2N", "3C", "3D", "3H", "3S", "3N", "4C", "4D", "4H", "4S"],
         _resp_second_ok, _resp_second_meaning, priority=90),
    Rule("Strong 2C opener over interference", _strong_2c_interfered,
         lambda ctx: [c for c in ctx.legal if c != "P"],
         lambda ev, ctx, c: c == _strong_2c_interfered_choice(ev, ctx), _strong_2c_interfered_meaning,
         priority=88),
]


# --- weak twos ---------------------------------------------------------------------

WEAK = {"2D", "2H", "2S"}
partner_weak_two = seq(WEAK, "P", opener="pd")


def _wt_resp_ok(ev, ctx, c):
    x = ctx.since_open[0][1]
    n = ev.len(x)
    strong = ev.hcp >= 15
    if c == f"4{x}" and x in "HS":
        return n >= 4 or (n >= 3 and ev.hcp >= 16)
    if c == f"3{x}":
        return n == 3 and not strong or (x == "D" and n >= 3 and not strong)
    if c == "2N":
        return strong and n < 4
    if c == "3N":
        return False
    if c == "P":
        return not strong and n < 3
    return False


WEAK_TWO = [
    Rule("Response to weak two", partner_weak_two,
         lambda ctx: ["P", f"3{ctx.since_open[0][1]}", f"4{ctx.since_open[0][1]}", "2N"],
         _wt_resp_ok,
         lambda ctx, c: (shows("Feature ask: 15+ HCP, forcing", (15, 37), forcing=True,
                               artificial=True) if c == "2N" else
                         shows("No interest", (0, 14), signoff=True) if c == "P" else
                         shows("Pre-emptive raise / game", signoff=True)),
         priority=70),
]


def _feature_ok(ev, ctx, c):
    x = ctx.since_open[0][1]
    if ev.hcp <= 7:
        return c == f"3{x}"
    if ev.honors(x, 3) >= 2:
        return c == "3N"
    feats = [s for s in SUITS if s != x and (ev.has_card(s + "A") or ev.has_card(s + "K"))]
    if feats:
        return c == f"3{feats[0]}"
    return c == f"3{x}"


WEAK_TWO += [
    Rule("Weak two: answer feature ask", U(WEAK, "2N"),
         ["3C", "3D", "3H", "3S", "3N"], _feature_ok,
         lambda ctx, c: (shows("Minimum (5-7), or no outside ace or king", (5, 10)) if c[1] == ctx.since_open[0][1] else
                         shows("Maximum with two of the top three trump honors", (8, 10))
                         if c == "3N" else
                         shows(f"Maximum with an ace or king in {NAMES[c[1]]}", (8, 10))),
         priority=70),
    Rule("Weak two: pass partner's raise",
         lambda ctx: U(WEAK, is_bid)(ctx) and ctx.since_open[2][1] == ctx.since_open[0][1],
         "P", lambda *a: True, shows("Opener does not bid again"), priority=70),
]


def _after_feature_ok(ev, ctx, c):
    x = ctx.since_open[0][1]
    reply = ctx.since_open[4]
    fit = ev.len(x) >= 3 or (ev.len(x) >= 2 and reply == "3N")
    if reply == "3N":
        return c == ("4" + x if x in "HS" and ev.len(x) >= 3 else "P")
    if fit and x in "HS":
        return c == f"4{x}"
    # a feature shows a maximum: don't pass it, unless short in partner's suit (no way to reach it)
    if (ev.hcp >= 17 or (reply[1] != x and ev.len(x) >= 2)) and "3N" in ctx.legal:
        return c == "3N"
    return c == ("P" if reply[1] == x else f"3{x}" if f"3{x}" in ctx.legal else "P")


WEAK_TWO += [
    Rule("Weak two: placing the contract", U(WEAK, "2N", is_bid),
         ["P", "3H", "3S", "3N", "4H", "4S"], _after_feature_ok,
         lambda ctx, c: shows("Placing the contract", signoff=True), priority=70),
    Rule("Weak two: accept placement",
         U(WEAK, "2N", is_bid, is_bid), "P",
         lambda *a: True, shows("Accepting"), priority=70),
]

def _preempter_rebid_ok(ev, ctx, c):
    o, r = ctx.since_open[0][1], ctx.since_open[2]
    if r[1] in (o, "N"):  # raise or 3NT: done
        return c == "P"
    if ev.len(r[1]) >= 3:
        return c == cheapest(ctx, r[1])
    return c == cheapest(ctx, o)


# --- pre-empts ---------------------------------------------------------------------

PRE = {"3C", "3D", "3H", "3S", "4C", "4D", "4H", "4S"}
partner_preempt = seq(PRE, "P", opener="pd")


def _pre_resp_ok(ev, ctx, c):
    o = ctx.since_open[0]
    x = o[1]
    n = ev.len(x)
    game = f"4{x}" if x in "HS" else f"5{x}"
    if o[0] == "4":
        return c == "P"
    if ev.hcp >= 16:
        if n >= 2:
            return c == game
        five = [s for s in SUITS if s != x and ev.len(s) >= 5]
        if five:
            return c == cheapest(ctx, five[0])
        if ev.stoppers([s for s in SUITS if s != x]):
            return c == "3N"
        return c == "P"
    if n >= 3:
        return c == f"{int(o[0]) + 1}{x}"
    return c == "P"


PREEMPT = [
    Rule("Response to pre-empt", partner_preempt, lambda ctx: ctx.legal, _pre_resp_ok,
         lambda ctx, c: (shows("No interest", (0, 15)) if c == "P" else
                         shows("Penalty") if not is_bid(c) else
                         shows("Pre-emptive raise or game", signoff=True)
                         if c[1] == ctx.since_open[0][1] else
                         shows("To play", (16, 37)) if c == "3N" else
                         shows(f"16+, 5+ {NAMES.get(c[1], '')}, forcing", (16, 37), forcing=True,
                               **({c[1]: 5} if c[1] in SUITS else {}))),
         priority=70),
    Rule("Pre-empter: pass unless forced", seq(PRE, "P", is_bid, "P", opener="me"),
         lambda ctx: ctx.legal, _preempter_rebid_ok,
         lambda ctx, c: shows("Pre-empter's rebid"), priority=70),
]

STRONG_2C_CONV = Convention("strong_2c", "Strong 2♣",
                            "2♣ is the only forcing opening: 22+ points. 2♦ is waiting.",
                            STRONG_2C)
WEAK_TWO_RESP = Convention("weak_two_responses", "Responses to weak twos",
                           "Raises are pre-emptive; 2NT asks for a feature.", WEAK_TWO, core=True)
PREEMPT_RESP = Convention("preempt_responses", "Responses to pre-empts",
                          "Raise with 3-card support; 16+ bids game or a forcing new suit.",
                          PREEMPT, core=True)
