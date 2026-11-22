"""Blackwood 4NT (aces) with the 5NT king ask."""
from __future__ import annotations

from ...core.auction import is_bid
from ...core.cards import SUITS
from ..context import Ctx
from ..rules import Convention, Rule
from ..shows import shows
from .general import best_fit, my_value, partner_range

ACE_STEPS = ["C", "D", "H", "S"]  # 0/4, 1, 2, 3


def _rule_name_of_last_call_by(ctx: Ctx, seat: str) -> tuple[str | None, str | None]:
    for i in range(len(ctx.calls) - 1, -1, -1):
        s, c = ctx.calls[i]
        if s == seat:
            r = ctx.engine.explain_rule(ctx.auction, i)
            return c, (r.name if r else None)
    return None, None


def _suit_shown(ctx: Ctx) -> bool:
    """Someone on our side has shown a real suit (otherwise 4NT is quantitative)."""
    return any(ctx.partner_info.min_len(s) >= 4 or ctx.my_info.min_len(s) >= 5 for s in SUITS)


def _blackwood_situation(ctx: Ctx) -> bool:
    if "4N" not in ctx.legal or not ctx.partner_bids:
        return False
    if "4N" in ctx.my_bids or "4N" in ctx.partner_bids:
        return False
    return _suit_shown(ctx)


def _blackwood_ok(ev, ctx, c):
    fit = best_fit(ev, ctx)
    if not fit:
        return False
    plo, phi = partner_range(ctx)
    void = min(ev.lengths.values()) == 0
    mine = my_value(ev, fit[0])
    if void:
        return False
    # slam sure on partner's minimum, or likely (middle of a limited range) with two aces of my own
    limited = ctx.partner_info.hcp[1] - plo <= 4
    return (mine + plo >= 33 and ev.aces >= 1) or (limited and mine + (plo + phi) / 2 >= 31 and ev.aces >= 2)


def _asked(name: str, call: str):
    def check(ctx: Ctx) -> bool:
        c, rule = _rule_name_of_last_call_by(ctx, ctx.partner)
        return rule == name and c == call and ctx.calls[-1][1] == "P"
    return check


def _response_calls(level: int):
    return [f"{level}{s}" for s in ACE_STEPS]


def _count_ok(attr: str, level: int):
    def ok(ev, ctx, c):
        n = getattr(ev, attr) % 4
        return c == f"{level}{ACE_STEPS[n]}"
    return ok


def _my_ask_answered(name: str):
    def check(ctx: Ctx) -> bool:
        call, rule = _rule_name_of_last_call_by(ctx, ctx.me)
        if rule != name or ctx.calls[-1][1] != "P":
            return False
        pc, prule = _rule_name_of_last_call_by(ctx, ctx.partner)
        return prule is not None and prule.startswith("Blackwood response")
    return check


def _partner_count(ctx: Ctx, mine: int) -> int:
    pc, _ = _rule_name_of_last_call_by(ctx, ctx.partner)
    n = ACE_STEPS.index(pc[1])
    if n == 0 and mine == 0:
        return 4
    return n


def _trump(ev, ctx) -> str:
    fit = best_fit(ev, ctx)
    return fit[0] if fit else "N"


def _after_aces_ok(ev, ctx, c):
    trump = _trump(ev, ctx)
    total = ev.aces + _partner_count(ctx, ev.aces)
    plo, _ = partner_range(ctx)
    combined = my_value(ev, trump if trump != "N" else None) + plo
    legal = ctx.legal
    if total <= 2:
        want = f"5{trump}"
        if want not in legal and ctx.last_bid == want:
            return c == "P"  # partner's answer is our trump suit at the 5 level: stop there (Fable review)
        return c == (want if want in legal else f"6{trump}")
    if total == 4 and combined >= 35:
        return c == "5N"
    return c == f"6{trump}"


def _after_kings_ok(ev, ctx, c):
    trump = _trump(ev, ctx)
    kings = ev.kings + _partner_count(ctx, ev.kings)
    plo, _ = partner_range(ctx)
    combined = my_value(ev, trump if trump != "N" else None) + plo
    want = f"7{trump}" if kings == 4 and combined >= 35 else f"6{trump}"
    if want not in ctx.legal:
        want = "6N" if "6N" in ctx.legal else f"7{trump}"
    return c == want


BLACKWOOD = Convention(
    "blackwood", "Blackwood",
    "4NT asks for aces: 5♣=0/4, 5♦=1, 5♥=2, 5♠=3. 5NT then asks for kings.",
    [
        Rule("Blackwood 4NT", _blackwood_situation, "4N", _blackwood_ok,
             shows("Blackwood: how many aces?", artificial=True, forcing=True), priority=88),
        Rule("Blackwood response (aces)", _asked("Blackwood 4NT", "4N"), _response_calls(5),
             _count_ok("aces", 5),
             lambda ctx, c: shows({"C": "0 or 4 aces", "D": "1 ace", "H": "2 aces",
                                   "S": "3 aces"}[c[1]], artificial=True), priority=90),
        Rule("Blackwood: place the contract", _my_ask_answered("Blackwood 4NT"),
             lambda ctx: [c for c in ctx.legal if is_bid(c)] + ["P"], _after_aces_ok,
             lambda ctx, c: (shows("King ask: all aces held, grand slam interest",
                                   artificial=True, forcing=True) if c == "5N" else
                             shows("Sign-off: an ace too few for slam", signoff=True) if c == "P" else
                             shows("Sign-off", signoff=True)), priority=90),
        Rule("Blackwood response (kings)", _asked("Blackwood: place the contract", "5N"),
             _response_calls(6), _count_ok("kings", 6),
             lambda ctx, c: shows({"C": "0 or 4 kings", "D": "1 king", "H": "2 kings",
                                   "S": "3 kings"}[c[1]], artificial=True), priority=90),
        Rule("Blackwood: after kings", _my_ask_answered("Blackwood: place the contract"),
             lambda ctx: [c for c in ctx.legal if is_bid(c)], _after_kings_ok,
             lambda ctx, c: shows("Sign-off", signoff=True), priority=90),
    ])
