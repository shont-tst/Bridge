"""Bidding with the vulnerability in mind (IMPs or rubber).

The system's rules are written for any vulnerability. `adjust` looks at who is vulnerable after the rules have
picked a call, and changes it in a few ways. Each way can be switched on or off (`Vul.use`), so how much a bot uses
depends on its level (`BotPlayer.vul_for`): see docs/bots.md.

- "game": when we are vulnerable, a game bid is worth more (500 against 300 at IMPs), so count one extra point
  when the choice is between game and stopping short.
- "lighter": when only they are vulnerable, compete 2 points lighter when they own a low contract.
- "save": when only they are vulnerable and they bid a game over our known 10-card fit, bid one more as a
  sacrifice with a weak hand (10 HCP or less) and a singleton or void.

Tried and left out (Fable review, 2026-11-12): more caution vulnerable against not (pre-empts only with a good suit,
2-level overcalls with 2 more points). It cost 94 IMPs on 3,000 deals, because pre-empting still paid.

Every change carries a `note` the Why pop-up shows.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

from ..core.auction import Auction, is_bid
from ..core.cards import SUITS
from .context import Ctx
from .evaluation import Eval
from .rules import cheapest
from .shows import readable, shows

GAME_LEVEL = {"C": 5, "D": 5, "H": 4, "S": 4, "N": 3}
ALL = frozenset({"game", "lighter", "save"})
RISKY = frozenset({"lighter", "save"})  # bots use these from level 8, the rest from level 6


@dataclass(frozen=True)
class Vul:
    vulnerability: str  # "None", "NS", "EW" or "Both"
    use: frozenset = ALL


def _exp() -> frozenset | None:
    v = os.environ.get("BRIDGE_VUL_EXP")
    return None if v is None else frozenset(x for x in v.split(",") if x)


def _is_game(call: str) -> bool:
    return is_bid(call) and GAME_LEVEL[call[1]] <= int(call[0]) <= 5


def _level(call: str) -> int:
    return int(call[0]) if is_bid(call) else 0


def adjust(engine, hand, auction: Auction, dec, vul: Vul):
    from .engine import Decision

    use = _exp() if _exp() is not None else vul.use
    ctx = Ctx(auction, engine, vul.vulnerability)
    ev = Eval(hand)
    last = ctx.last_bid

    # lighter: favorable, compete 2 points lighter against their low contract
    if "lighter" in use and ctx.favorable and dec.call == "P" and last and not ctx.contract_is_ours \
            and _level(last) <= 3:
        for d in engine.candidates(hand, auction, 2, vul=vul.vulnerability):
            c = d.call
            if c == "P":
                break
            if c == "X" or c[1] == "N" or _level(c) > 3:
                continue
            if d.meaning.artificial or d.meaning.forcing:
                continue
            return Decision(c, d.rule, d.meaning,
                            note=readable(f"Not vulnerable against vulnerable: {c} competes on a little less."))

    # game: we are vulnerable, count one extra point when the choice is game or stop
    if "game" in use and ctx.we_vul and ctx.partner_bids and not _is_game(dec.call) and \
            (dec.call == "P" or _level(dec.call) < 4) and (not last or ctx.contract_is_ours or dec.call != "P"):
        alts = engine.candidates(hand, auction, 1, vul=vul.vulnerability)
        if alts:
            a = alts[0]
            m = a.meaning
            same = dec.call == "P" or a.call[1:] == dec.call[1:] or a.call == "3N"
            if _is_game(a.call) and same and not (m.artificial or m.forcing) and \
                    (not last or _level(a.call) > _level(last)):
                return Decision(a.call, a.rule, m, note=readable(f"Vulnerable: game pays more, so {a.call}."))

    # save: favorable, they bid game over our 10-card fit, a weak hand bids one more
    if "save" in use and ctx.favorable and dec.call in ("P",) and last and not ctx.contract_is_ours \
            and _is_game(last) and last[1] != "N" and ctx.doubled == 0 and ev.hcp <= 10 and ev.shape[-1] <= 1:
        info = ctx.partner_info
        for s in SUITS:
            if s == last[1] or info.min_len(s) < 3 or ev.len(s) + info.min_len(s) < 10:
                continue
            if not any(c[1] == s for c in ctx.partner_bids) and not any(c[1] == s for c in ctx.my_bids):
                continue
            b = cheapest(ctx, s)
            if b and _level(b) == _level(last) + (0 if SUITS.index(s) < SUITS.index(last[1]) else 1) and \
                    _level(b) <= 5:
                return Decision(b, None, shows(f"Sacrifice: {b} should cost less than their game"),
                                note=readable(f"Not vulnerable against vulnerable: {b} costs less than their game."),
                                note_only=True)
    return dec
