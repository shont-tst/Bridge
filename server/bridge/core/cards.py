"""Cards, suits, seats and hands.

Cards are short strings like "SA", "HT", "C2" (suit letter + rank char) so they
serialize trivially to JSON and read naturally in tests.
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Iterable

SUITS = "SHDC"  # rank order, highest first
RANKS = "23456789TJQKA"
SEATS = "NESW"
SUIT_SYMBOL = {"S": "♠", "H": "♥", "D": "♦", "C": "♣", "N": "NT"}
HCP_VALUE = {"A": 4, "K": 3, "Q": 2, "J": 1}


def rank_value(card: str) -> int:
    """2..14"""
    return RANKS.index(card[1]) + 2


def suit_of(card: str) -> str:
    return card[0]


def full_deck() -> list[str]:
    return [s + r for s in SUITS for r in RANKS]


def sort_cards(cards: Iterable[str]) -> list[str]:
    return sorted(cards, key=lambda c: (SUITS.index(c[0]), -rank_value(c)))


def next_seat(seat: str, n: int = 1) -> str:
    return SEATS[(SEATS.index(seat) + n) % 4]


def partner(seat: str) -> str:
    return next_seat(seat, 2)


def side(seat: str) -> str:
    return "NS" if seat in "NS" else "EW"


def same_side(a: str, b: str) -> bool:
    return side(a) == side(b)


@dataclass(frozen=True)
class Hand:
    cards: tuple[str, ...]

    @staticmethod
    def of(cards: Iterable[str]) -> "Hand":
        return Hand(tuple(sort_cards(cards)))

    @staticmethod
    def from_pbn(text: str) -> "Hand":
        """'AKQ2.T98.765.432' (S.H.D.C)"""
        parts = text.split(".")
        assert len(parts) == 4, text
        return Hand.of(s + r for s, p in zip(SUITS, parts) for r in p.upper().replace("10", "T"))

    def suit(self, s: str) -> list[str]:
        return [c for c in self.cards if c[0] == s]

    def length(self, s: str) -> int:
        return sum(1 for c in self.cards if c[0] == s)

    def lengths(self) -> dict[str, int]:
        return {s: self.length(s) for s in SUITS}

    @property
    def hcp(self) -> int:
        return sum(HCP_VALUE.get(c[1], 0) for c in self.cards)

    def suit_hcp(self, s: str) -> int:
        return sum(HCP_VALUE.get(c[1], 0) for c in self.cards if c[0] == s)

    def has(self, card: str) -> bool:
        return card in self.cards

    def to_pbn(self) -> str:
        return ".".join("".join(c[1] for c in self.suit(s)) for s in SUITS)

    def __len__(self) -> int:
        return len(self.cards)


def deal_random(rng: random.Random | None = None) -> dict[str, Hand]:
    rng = rng or random.Random()
    deck = full_deck()
    rng.shuffle(deck)
    return {seat: Hand.of(deck[i * 13:(i + 1) * 13]) for i, seat in enumerate(SEATS)}


def hands_from_pbn(pbn: str) -> dict[str, Hand]:
    """'N:AKQ.. ... ... ...' with the first hand belonging to the named seat."""
    first, rest = pbn.split(":")
    out = {}
    for i, h in enumerate(rest.split()):
        out[next_seat(first, i)] = Hand.from_pbn(h)
    return out
