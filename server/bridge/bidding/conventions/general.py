"""General bidding judgment for auctions no specific rule covers.

Uses what partner has shown (HCP range, suit lengths) plus my hand to find a
fit, estimate combined strength and place the contract: game with 25+, invite
when game is possible, compete by the Law of Total Tricks, double when the
opponents have overreached. Always on; lowest priority.
"""
from __future__ import annotations

from ...core.auction import is_bid
from ...core.cards import SUITS
from ..context import Ctx
from ..evaluation import Eval
from ..rules import Convention, Rule, cheapest
from ..shows import shows

NAMES = {"S": "spades", "H": "hearts", "D": "diamonds", "C": "clubs"}
GAME_LEVEL = {"C": 5, "D": 5, "H": 4, "S": 4, "N": 3}
INVITE_MARGIN = 2  # an invitation needs game within reach without partner's top 2 points


def best_fit(ev: Eval, ctx: Ctx) -> tuple[str, int] | None:
    """(suit, combined length) of our best known 8+ card fit."""
    info = ctx.partner_info
    fits = []
    for s in SUITS:
        total = ev.len(s) + info.min_len(s)
        if total >= 8 and info.min_len(s) >= 2 and ev.len(s) >= 2:
            fits.append((s, total))
    if not fits:
        return None
    return max(fits, key=lambda f: (f[0] in "HS", f[1], -SUITS.index(f[0])))


def my_value(ev: Eval, fit: str | None) -> int:
    if fit:
        return max(ev.tp, ev.support_points(fit))
    return ev.tp


def partner_range(ctx: Ctx) -> tuple[int, int]:
    lo, hi = ctx.partner_info.hcp
    return lo, min(hi, lo + 6)


def _partner_bid_nt_over_them(ctx: Ctx) -> bool:
    """Partner bid notrump after the opponents showed a suit: partner holds the stopper."""
    first_opp = next((i for i, (seat, c) in enumerate(ctx.calls)
                      if seat in (ctx.lho, ctx.rho) and is_bid(c) and c[1] in SUITS), None)
    return first_opp is not None and any(seat == ctx.partner and is_bid(c) and c[1] == "N"
                                         for seat, c in ctx.calls[first_opp:])


def _game_strain(ev: Eval, ctx: Ctx, fit, combined: int) -> str | None:
    if fit and fit[0] in "HS":
        return fit[0]
    stop = ev.stoppers(ctx.opp_suits) if ctx.opp_suits else True
    stop = stop or _partner_bid_nt_over_them(ctx)
    if not fit:  # a long major (or, with their suit unguarded, a long minor) plays better than notrump
        long = max(SUITS, key=lambda s: (ev.len(s), s in "HS"))
        if long in "HS" and (ev.len(long) >= 7 or (ev.len(long) >= 6 and ev.good_suit(long))) or \
                (not stop and ev.len(long) >= 6 and ev.good_suit(long)):
            return long
    if fit and (combined >= 29 or not stop or ev.shape[-1] <= 1):
        return fit[0]
    # no fit and their suit unguarded: don't invite in notrump (with game values, still bid it)
    return "N" if stop or combined >= 25 else None


def _forced_bid(ev: Eval, ctx: Ctx, fit) -> str:
    """Some sensible non-pass bid when the auction is forcing."""
    if fit:
        b = cheapest(ctx, fit[0])
        if b:
            return b
    pb = [c[1] for c in ctx.partner_bids if c[1] in SUITS]
    for s in ev.longest_suits():
        if ev.len(s) >= 5 and s not in ctx.opp_suits and s not in pb:
            b = cheapest(ctx, s)
            if b and int(b[0]) <= 4:
                return b
    if ev.stoppers(ctx.opp_suits) or not ctx.opp_suits:
        b = cheapest(ctx, "N")
        if b and int(b[0]) <= 3:
            return b
    if pb:
        best = max(pb, key=lambda s: ev.len(s))
        b = cheapest(ctx, best)
        if b:
            return b
    for s in ev.longest_suits():
        b = cheapest(ctx, s)
        if b:
            return b
    return "P"


def general_choice(ev: Eval, ctx: Ctx) -> str:
    legal = set(ctx.legal)
    fit = best_fit(ev, ctx)
    trump = fit[0] if fit else None
    mine = my_value(ev, trump)
    plo, phi = partner_range(ctx)
    lo, hi = mine + plo, mine + phi
    partner_has_bid = bool(ctx.partner_bids)
    last = ctx.last_bid

    # --- opponents own the contract: compete or double ---
    if last and not ctx.contract_is_ours:
        lvl, strain = int(last[0]), last[1]
        if "X" in legal and strain in SUITS and lvl >= 2 and ev.len(strain) >= 4 and \
                ev.honors(strain) >= 2 and lo >= 20 and not (fit and fit[0] == strain):
            return "X"
        if "X" in legal and lvl >= 4 and lo >= 26 and not fit:
            return "X"
        if fit and partner_has_bid:
            b = cheapest(ctx, fit[0])
            game = f"{GAME_LEVEL[fit[0]]}{fit[0]}"
            if lo >= 25 and game in legal:
                return game
            # by the Law of Total Tricks: as high as the fit's length less 6. With fewer than 17 together, only to
            # the 3 level and with 6+ HCP (players who competed here beat the bots: +470 to +626 IMPs per 30,000)
            if b and int(b[0]) <= fit[1] - 6 and (lo >= 17 or (ev.hcp >= 6 and int(b[0]) <= 3 and not ctx.doubled)):
                return b
        again = _rebid_long_suit(ev, ctx)
        if again:
            return again
        if ctx.partner_forcing:
            return _forced_bid(ev, ctx, fit)
        if "X" in legal and _double_their_game(ev, ctx, lvl, strain):
            return "X"  # only where the system would pass: that's where it was tested
        return "P"

    if not partner_has_bid:
        return "P"

    # --- our auction: place the contract ---
    current = int(last[0]) if last else 0
    if ctx.last_bidder == ctx.partner and last == "3N" and lo < 33:
        pull = _pull_3nt(ev, ctx, legal)  # a long major I have bid plays better than notrump (Fable review)
        if pull:
            return pull
    if ctx.last_bidder == ctx.partner and _is_game(last) and lo < 33:
        return "P"  # partner chose a game: respect it
    strain = _game_strain(ev, ctx, fit, lo)
    game = f"{GAME_LEVEL[strain]}{strain}" if strain else None  # None: nowhere safe for game
    if strain and lo >= 33:
        slam = f"6{strain}"
        if slam in legal:
            return slam
    if strain and lo >= 25:
        if game not in legal and strain == "N" and fit:  # past 3NT already: game in the fit
            game = f"{GAME_LEVEL[fit[0]]}{fit[0]}"
        if game in legal:
            return game
        if current >= GAME_LEVEL.get(last[1], 3) or current >= 4:
            return "P"  # already in game
    elif strain and hi - INVITE_MARGIN >= 25 and not ctx.doubled and not (ctx.partner_forcing and strain == "N"):
        # doubled: never bid on just to invite. Over partner's forcing new suit, no notrump invitation (opener with
        # 12-14 doesn't jump to 2NT: Fable review); and partner's range has to reach game without the top of it.
        invite = f"{GAME_LEVEL[strain] - 1}{strain}" if strain != "N" else "2N"
        if invite in legal and current < int(invite[0]):
            if int(invite[0]) - current < 3:
                return invite
            b = cheapest(ctx, strain)  # a double jump (1D 1H 1S P 4D) isn't an invitation: rebid the suit
            if b and int(b[0]) <= current + 1:
                return b
        if not is_bid(invite) or current >= int(invite[0]):
            # partner invited (or we are already at the invite level): accept with a maximum
            my_lo, my_hi = ctx.my_info.hcp
            if my_hi > 30:
                my_hi = my_lo + 6
            flat = 1 if ev.shape == [4, 3, 3, 3] and strain != "N" and ev.len(strain) == 4 else 0  # 4-3-3-3 with 4 trumps: no ruffs
            if ev.hcp - flat >= (my_lo + my_hi + 1) / 2 and game in legal:
                return game
    if ctx.partner_forcing or (ctx.game_forcing and current < 4 and last not in ("3N",)):
        if ctx.game_forcing and lo >= 23 and game and game in legal and current >= 3:
            return game
        return _forced_bid(ev, ctx, fit)
    # not forcing, no game: correct to our fit if partner's suit is not it
    if fit and last and last[1] != fit[0] and int((cheapest(ctx, fit[0]) or "9")[0]) <= 2 \
            and ctx.last_bidder == ctx.partner:
        return cheapest(ctx, fit[0])
    return "P"


def _double_their_game(ev: Eval, ctx: Ctx, lvl: int, strain: str) -> bool:
    """They bid a game (below slam) and partner has shown values: double with 3½ quick tricks. Players who doubled
    here beat the bots; tested on 100,000 deals (+1,195 IMPs), with the whole auction (+361 over 50,000) and on re-dealt
    layouts (right on 76 of 77). Without partner's values, or with 3 quick tricks, it lost on too many layouts."""
    return GAME_LEVEL[strain] <= lvl < 6 and not ctx.doubled and ctx.partner_info.hcp[0] >= 6 \
        and ev.quick_tricks() >= 3.5


def _rebid_long_suit(ev: Eval, ctx: Ctx) -> str | None:
    """They bid over us: bid my own long suit again, a 7-card one up to the 4 level or a 6-card one at the 2 level,
    with 6+ HCP, unless my first bid was a pre-empt (that already said it all). Players who did this beat the bots:
    +1,595 IMPs over 30,000 deals."""
    if ev.hcp < 6 or ctx.doubled or ctx.last_bid == "3N":
        return None  # a double of theirs stands, and bidding on over their 3NT lost on re-dealt layouts
    for i, (seat, c) in enumerate(ctx.calls):
        if seat != ctx.me or not is_bid(c):
            continue
        s = c[1]
        m = ctx.engine.explain(ctx.auction, i)
        if s not in SUITS or s in ctx.opp_suits or m.artificial or m.hcp[1] <= 11:
            return None  # first bid notrump, in their suit, artificial, or weak
        b = cheapest(ctx, s)
        if b and ((ev.len(s) >= 7 and int(b[0]) <= 4) or (ev.len(s) >= 6 and int(b[0]) <= 2)):
            return b
        return None
    return None


def _pull_3nt(ev: Eval, ctx: Ctx, legal: set) -> str | None:
    """Partner's 3NT, but I have bid a 7-card major, or a good 6-card one with a singleton or void: play it in 4."""
    for m in "SH":
        if not any(b[1] == m for b in ctx.my_bids):
            continue
        n = ev.len(m)
        if (n >= 7 or (n == 6 and ev.good_suit(m) and ev.shape[-1] <= 1)) and f"4{m}" in legal:
            return f"4{m}"
    return None


def _is_game(call: str | None) -> bool:
    return bool(call) and is_bid(call) and int(call[0]) >= GAME_LEVEL[call[1]]


def general_meaning(ctx: Ctx, c: str):
    if c == "P":
        if ctx.calls and ctx.calls[-1] == (ctx.rho, "X") and ctx.we_opened and ctx.contract_is_ours:
            return shows("Nothing to add over the double yet")  # opener waits
        return shows("No reason to bid further")
    if c == "X":
        return shows("Penalty double: they have overreached")
    if c == "XX":
        return shows("Redouble: confident it makes")
    s = c[1]
    lvl = int(c[0])
    if s == "N":
        return shows("Natural: to play (or invitational) in notrump")
    partner_suits = {b[1] for b in ctx.partner_bids}
    if s in partner_suits:
        # A raise here comes from best_fit: enough cards for 8 together with what partner has shown
        # (2 opposite a 6-card suit, 4 opposite a 4-card suit). With an artificial bid of partner's, the old 3 / 2.
        pmin = ctx.partner_info.min_len(s)
        if lvl >= GAME_LEVEL[s]:
            return shows(f"To play in {NAMES[s]} game", **{s: max(2, 8 - pmin) if pmin >= 3 else 2})
        need = max(2, 8 - pmin) if pmin >= 3 else 3
        if ctx.partner_forcing and c == cheapest(ctx, s):
            need = min(need, 3)  # may be a forced preference (_forced_bid), not a fit
        return shows(f"Support for partner's {NAMES[s]} ({need}+)", **{s: need})
    if s in {b[1] for b in ctx.my_bids}:
        return shows(f"Rebidding {NAMES[s]}: extra length", **{s: 5})
    return shows(f"Natural: {NAMES[s]}", **{s: 4})


def _partner_signed_off(ctx: Ctx) -> bool:
    if not ctx.calls or ctx.calls[-1][1] != "P":
        return False
    m = ctx.partner_last_meaning()
    return m is not None and m.signoff and ctx.contract_is_ours


def _penalty_double_of_partner(ctx: Ctx) -> str | None:
    """Partner's suit bid (at the 1 or 2 level) that the opponents doubled for penalty, if I am next to speak
    for our side; None otherwise."""
    if ctx.doubled != 1 or ctx.last_bidder != ctx.partner or not ctx.contract_is_ours:
        return None
    last = ctx.last_bid
    if last[1] not in SUITS or int(last[0]) > 2 or "X" in ctx.my_calls[-1:]:
        return None
    i = max(i for i, (_, c) in enumerate(ctx.calls) if c == "X")
    if ctx.calls[i][0] == ctx.partner or len(ctx.calls) - i > 3:
        return None
    m = ctx.engine.explain(ctx.auction, i)
    return last if m.text.lower().startswith("penalty") else None


def _rescue_suit(ev: Eval, ctx: Ctx) -> str | None:
    last = _penalty_double_of_partner(ctx)
    if last is None or ev.len(last[1]) > 1 or ev.hcp > 10:
        return None
    for s in ev.longest_suits():
        b = cheapest(ctx, s)
        if ev.len(s) >= 5 and s != last[1] and s not in ctx.opp_suits and b and int(b[0]) <= 2:
            return b
    return None


def _rescue_meaning(ctx: Ctx, c: str):
    p = ctx.last_bid[1]
    return shows(f"Rescue: little or nothing in {NAMES[p]}, 5+ {NAMES[c[1]]}; to play", (0, 10), signoff=True,
                 **{c[1]: 5})


GENERAL = Convention(
    "general", "General bidding judgment",
    "Finds fits and places the contract when no specific rule applies.",
    [
        Rule("Respect partner's sign-off", _partner_signed_off, "P", lambda *a: True,
             shows("Accepting partner's sign-off"), priority=95),
        Rule("Rescue from a penalty double", lambda ctx: _penalty_double_of_partner(ctx) is not None,
             lambda ctx: [b for s in SUITS if (b := cheapest(ctx, s))],
             lambda ev, ctx, c: c == _rescue_suit(ev, ctx), _rescue_meaning, priority=70),
        Rule("General judgment", lambda ctx: True, lambda ctx: ctx.legal,
             lambda ev, ctx, c: c == general_choice(ev, ctx), general_meaning, priority=5),
    ],
    core=True)
