"""Hand valuation as described in docs/bidding-system.md."""
from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property

from ..core.cards import SUITS, Hand, rank_value

MAJORS = "SH"
MINORS = "DC"


@dataclass(frozen=True)
class Eval:
    hand: Hand
    bonus: int = 0  # extra points to count, for bidding a little lighter (a part score at rubber, partscore.py)

    @cached_property
    def hcp(self) -> int:
        return self.hand.hcp + self.bonus

    @cached_property
    def lengths(self) -> dict[str, int]:
        return self.hand.lengths()

    def len(self, suit: str) -> int:
        return self.lengths[suit]

    @cached_property
    def shape(self) -> list[int]:
        return sorted(self.lengths.values(), reverse=True)

    @cached_property
    def long_points(self) -> int:
        return sum(max(0, n - 4) for n in self.lengths.values())

    @cached_property
    def tp(self) -> int:
        """Total points with long-suit points (the default valuation)."""
        return self.hcp + self.long_points

    def short_points(self, trump: str) -> int:
        pts = 0
        for s, n in self.lengths.items():
            if s == trump:
                continue
            pts += {0: 5, 1: 3, 2: 1}.get(n, 0)
        return pts

    def support_points(self, trump: str) -> int:
        """HCP + short-suit points, used when raising partner's suit."""
        if trump == "N":
            return self.tp
        return self.hcp + self.short_points(trump)

    @cached_property
    def balanced(self) -> bool:
        """4-3-3-3, 4-4-3-2 or 5-3-3-2."""
        return self.shape in ([4, 3, 3, 3], [4, 4, 3, 2], [5, 3, 3, 2])

    @cached_property
    def semi_balanced(self) -> bool:
        return self.balanced or self.shape in ([5, 4, 2, 2], [6, 3, 2, 2])

    @cached_property
    def rule_of_20(self) -> bool:
        return self.hcp + self.shape[0] + self.shape[1] >= 20

    def honors(self, suit: str, top: int = 5) -> int:
        """Number of honors among the top `top` ranks (A K Q J T) held in `suit`."""
        top_ranks = "AKQJT"[:top]
        return sum(1 for c in self.hand.suit(suit) if c[1] in top_ranks)

    def good_suit(self, suit: str) -> bool:
        """Two of the top three honors, or three of the top five."""
        return self.honors(suit, 3) >= 2 or self.honors(suit, 5) >= 3

    def decent_suit(self, suit: str) -> bool:
        """Two honors (counting the ten) — the overcall/weak-two minimum."""
        return self.honors(suit, 5) >= 2

    def stopper(self, suit: str) -> bool:
        cards = self.hand.suit(suit)
        ranks = {c[1] for c in cards}
        n = len(cards)
        return "A" in ranks or ("K" in ranks and n >= 2) or ("Q" in ranks and n >= 3) or \
            ("J" in ranks and n >= 4)

    def stoppers(self, suits) -> bool:
        return all(self.stopper(s) for s in suits)

    @cached_property
    def aces(self) -> int:
        return sum(1 for c in self.hand.cards if c[1] == "A")

    @cached_property
    def kings(self) -> int:
        return sum(1 for c in self.hand.cards if c[1] == "K")

    def has_card(self, card: str) -> bool:
        return self.hand.has(card)

    def longest_suits(self) -> list[str]:
        """Suits ordered by length, ties broken by higher rank first."""
        return sorted(SUITS, key=lambda s: (-self.lengths[s], SUITS.index(s)))

    def top_cards(self, suit: str) -> list[int]:
        return sorted((rank_value(c) for c in self.hand.suit(suit)), reverse=True)

    def four_card_majors(self) -> list[str]:
        return [s for s in MAJORS if self.lengths[s] >= 4]
