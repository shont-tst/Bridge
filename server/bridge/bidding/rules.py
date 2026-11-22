"""Rule and Convention types plus helpers for describing auction situations.

A rule says: in this situation (a predicate on the auction), these calls are
available; a hand qualifies for a call if `hand(ev, ctx, call)` holds; making
the call shows `shows`. Each convention is just a named list of rules, so a
convention can be switched on or off without touching the engine.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

from ..core.auction import is_bid
from .context import Ctx
from .evaluation import Eval
from .shows import Shows

Situation = Callable[[Ctx], bool]
HandTest = Callable[[Eval, Ctx, str], bool]


@dataclass
class Rule:
    name: str
    when: Situation
    calls: Any  # str | Iterable[str] | Callable[[Ctx], Iterable[str]]
    hand: HandTest
    shows: Shows | Callable[[Ctx, str], Shows]
    priority: int = 50
    prefer: Callable[[Eval, Ctx, str], Any] | None = None
    only_if_off: tuple[str, ...] = ()  # active only when these conventions are disabled
    needs: tuple[str, ...] = ()  # active only when these conventions are enabled
    module: str = ""

    def candidate_calls(self, ctx: Ctx) -> list[str]:
        c = self.calls
        if isinstance(c, str):
            out = [c]
        elif callable(c):
            out = list(c(ctx))
        else:
            out = list(c)
        legal = set(ctx.legal)
        return [x for x in out if x in legal]

    def meaning(self, ctx: Ctx, call: str) -> Shows:
        return self.shows(ctx, call) if callable(self.shows) else self.shows


@dataclass
class Convention:
    id: str
    title: str
    description: str
    rules: list[Rule] = field(default_factory=list)
    default_on: bool = True
    core: bool = False  # part of the base system; cannot be switched off

    def __post_init__(self):
        for r in self.rules:
            r.module = self.id

    def summary(self) -> dict:
        return {"id": self.id, "title": self.title, "description": self.description,
                "default_on": self.default_on, "core": self.core}


# --- situation helpers -----------------------------------------------------------

ANY = object()


def _item_matches(item, call: str) -> bool:
    if item is ANY:
        return True
    if isinstance(item, str):
        return item == call
    if isinstance(item, (set, frozenset, tuple, list)):
        return call in item
    return bool(item(call))


def seq(*pattern, opener: str | None = None) -> Situation:
    """Calls since the opening bid match `pattern` exactly (items may be strings,
    sets of strings, predicates or ANY); optionally require who opened ('me',
    'pd', 'lho', 'rho')."""
    def check(ctx: Ctx) -> bool:
        if opener is not None and ctx.opener_rel != opener:
            return False
        s = ctx.since_open
        return len(s) == len(pattern) and all(_item_matches(p, c) for p, c in zip(pattern, s))
    return check


def U(*ours) -> Situation:
    """Uncontested auction where our side's calls (from the opening bid on) are
    exactly `ours`; opponents only passed. Whoever made ours[0] opened."""
    pattern = []
    for c in ours:
        pattern += [c, "P"]  # each of our calls is followed by an opponent's pass
    who = "pd" if len(ours) % 2 == 1 else "me"
    return seq(*pattern, opener=who)


def opening_position(ctx: Ctx) -> bool:
    return ctx.opening_index is None


def all_of(*sits: Situation) -> Situation:
    return lambda ctx: all(s(ctx) for s in sits)


def any_of(*sits: Situation) -> Situation:
    return lambda ctx: any(s(ctx) for s in sits)


# --- call helpers ----------------------------------------------------------------

def bid(level: int, strain: str) -> str:
    return f"{level}{strain}"


def cheapest(ctx: Ctx, strain: str) -> str | None:
    """Cheapest legal bid in `strain`."""
    for lvl in range(1, 8):
        b = bid(lvl, strain)
        if b in ctx.legal:
            return b
    return None


def level_needed(ctx: Ctx, strain: str) -> int:
    b = cheapest(ctx, strain)
    return 8 if b is None else int(b[0])


def suit_calls(level: int, suits: Iterable[str] = "CDHS") -> list[str]:
    return [bid(level, s) for s in suits]


def strain_of(call: str) -> str | None:
    return call[1] if is_bid(call) else None


def legal_bids(ctx: Ctx) -> list[str]:
    return [c for c in ctx.legal if is_bid(c)]


def fixed(call: str) -> Callable[[Ctx], list[str]]:
    return lambda ctx: [call]


always: HandTest = lambda ev, ctx, call: True
