"""Card play: following suit, trick winners and trick counting."""
from __future__ import annotations

from dataclasses import dataclass, field

from .cards import Hand, next_seat, partner, rank_value, side


@dataclass
class Trick:
    leader: str
    cards: list[tuple[str, str]] = field(default_factory=list)  # (seat, card)

    @property
    def lead_suit(self) -> str | None:
        return self.cards[0][1][0] if self.cards else None

    def is_complete(self) -> bool:
        return len(self.cards) == 4

    def winner(self, trump: str) -> str:
        assert self.is_complete()
        lead = self.lead_suit

        def strength(card: str) -> int:
            if trump != "N" and card[0] == trump:
                return 100 + rank_value(card)
            if card[0] == lead:
                return rank_value(card)
            return 0

        return max(self.cards, key=lambda sc: strength(sc[1]))[0]

    def to_dict(self) -> dict:
        return {"leader": self.leader, "cards": [{"seat": s, "card": c} for s, c in self.cards]}


@dataclass
class Play:
    """Play of one deal. `hands` holds remaining cards and is mutated as cards are played."""
    declarer: str
    trump: str  # CDHS or N
    hands: dict[str, list[str]]
    tricks: list[Trick] = field(default_factory=list)

    @classmethod
    def start(cls, declarer: str, trump: str, hands: dict[str, Hand]) -> "Play":
        p = cls(declarer, trump, {s: list(h.cards) for s, h in hands.items()})
        p.tricks.append(Trick(next_seat(declarer)))
        return p

    @property
    def dummy(self) -> str:
        return partner(self.declarer)

    @property
    def current(self) -> Trick:
        return self.tricks[-1]

    @property
    def next_to_play(self) -> str | None:
        if self.is_complete():
            return None
        t = self.current
        return next_seat(t.leader, len(t.cards))

    def opening_lead_made(self) -> bool:
        return bool(self.tricks[0].cards)

    def is_complete(self) -> bool:
        return len(self.tricks) == 13 and self.tricks[-1].is_complete()

    def legal_cards(self, seat: str | None = None) -> list[str]:
        seat = seat or self.next_to_play
        if seat is None or seat != self.next_to_play:
            return []
        hand = self.hands[seat]
        lead = self.current.lead_suit
        if lead:
            follow = [c for c in hand if c[0] == lead]
            if follow:
                return follow
        return list(hand)

    def play(self, card: str) -> str | None:
        """Play `card` for the seat to move. Returns the trick winner if this card completed a trick."""
        seat = self.next_to_play
        if seat is None:
            raise ValueError("play is complete")
        if card not in self.legal_cards(seat):
            raise ValueError(f"illegal card {card} for {seat}")
        self.hands[seat].remove(card)
        self.current.cards.append((seat, card))
        if self.current.is_complete():
            w = self.current.winner(self.trump)
            if len(self.tricks) < 13:
                self.tricks.append(Trick(w))
            return w
        return None

    def completed_tricks(self) -> list[Trick]:
        return [t for t in self.tricks if t.is_complete()]

    def tricks_won(self, by_side: str) -> int:
        return sum(1 for t in self.completed_tricks() if side(t.winner(self.trump)) == by_side)

    def declarer_tricks(self) -> int:
        return self.tricks_won(side(self.declarer))

    def played_cards(self) -> list[tuple[str, str]]:
        return [sc for t in self.tricks for sc in t.cards]
