"""What a call shows: HCP range, suit lengths and flags.

The same description serves three purposes: explaining a call to the players,
letting the bidder reason about partner's hand, and constraining the deals the
card-play bot samples.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, replace

from ..core.cards import SUITS

MAX_HCP = 37


@dataclass(frozen=True)
class Shows:
    text: str = ""
    hcp: tuple[int, int] = (0, MAX_HCP)
    lengths: dict[str, tuple[int, int]] = field(default_factory=dict)
    balanced: bool | None = None
    forcing: bool = False          # partner may not pass (one round)
    game_forcing: bool = False     # partnership must reach game
    artificial: bool = False       # says nothing about the named strain
    signoff: bool = False          # partner should pass
    # Fewest HCP that can make this call when long-suit points count (an opening on 13 total points, or 12 with the
    # Rule of 20, can hold 10 HCP). Only the card-play bots' picture of the hand uses it (sampler.py); the bidding
    # still counts on `hcp`, as partner would. None: the same as hcp[0].
    light: int | None = None

    def length(self, suit: str) -> tuple[int, int]:
        return self.lengths.get(suit, (0, 13))

    def with_(self, **kw) -> "Shows":
        return replace(self, **kw)

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "hcp": list(self.hcp),
            "lengths": {s: list(v) for s, v in self.lengths.items()},
            "balanced": self.balanced,
            "forcing": self.forcing,
            "game_forcing": self.game_forcing,
            "artificial": self.artificial,
        }


UNKNOWN = Shows("No agreed meaning")


def shows(text: str, hcp=(0, MAX_HCP), balanced=None, forcing=False, game_forcing=False,
          artificial=False, signoff=False, light=None, **suit_lengths) -> Shows:
    """Convenience constructor: shows("...", (12, 21), S=(5, 13))."""
    lengths = {}
    for s, v in suit_lengths.items():
        lengths[s] = (v, 13) if isinstance(v, int) else tuple(v)
    return Shows(readable(text), tuple(hcp), lengths, balanced, forcing, game_forcing, artificial, signoff, light)


_SYMBOL = {"S": "♠", "H": "♥", "D": "♦", "C": "♣", "N": "NT"}
_PLURAL = {"S": "spades", "H": "hearts", "D": "diamonds", "C": "clubs"}
_SINGULAR = {"S": "spade", "H": "heart", "D": "diamond", "C": "club"}


def readable(text: str) -> str:
    """Meanings are often built from suit letters ("5+ H", "4S"); show them the way players read them ("5+ hearts",
    "4♥"), so the app can color the suits."""
    text = re.sub(r"\b([1-7])([SHDCN])\b", lambda m: m[1] + _SYMBOL[m[2]], text)
    text = re.sub(r"\b([SHDC]) suit\b", lambda m: f"{_SINGULAR[m[1]]} suit", text)
    return re.sub(r"(?<![\w-])([SHDC])\b(?!-)", lambda m: _PLURAL[m[1]], text)


@dataclass
class HandInference:
    """Aggregated knowledge about one seat's hand from all its calls."""
    hcp: tuple[int, int] = (0, MAX_HCP)
    lengths: dict[str, tuple[int, int]] = field(default_factory=lambda: {s: (0, 13) for s in SUITS})
    balanced: bool | None = None
    fewest: int = 0  # fewest HCP the hand can hold, counting light calls made on long-suit points (Shows.light)

    def add(self, s: Shows) -> None:
        lo, hi = max(self.hcp[0], s.hcp[0]), min(self.hcp[1], s.hcp[1])
        if lo <= hi:  # ignore contradictory information (misbids happen)
            self.hcp = (lo, hi)
        few = max(self.fewest, s.hcp[0] if s.light is None else min(s.light, s.hcp[0]))
        if few <= self.hcp[1]:
            self.fewest = few
        for suit, (a, b) in s.lengths.items():
            cur = self.lengths[suit]
            lo, hi = max(cur[0], a), min(cur[1], b)
            if lo <= hi:
                self.lengths[suit] = (lo, hi)
        if s.balanced is not None:
            self.balanced = s.balanced

    def min_len(self, suit: str) -> int:
        return self.lengths[suit][0]

    def max_len(self, suit: str) -> int:
        return self.lengths[suit][1]

    @property
    def mid_hcp(self) -> int:
        return (self.hcp[0] + min(self.hcp[1], self.hcp[0] + 6)) // 2

    def to_dict(self) -> dict:
        return {"hcp": list(self.hcp), "lengths": {k: list(v) for k, v in self.lengths.items()},
                "balanced": self.balanced}
