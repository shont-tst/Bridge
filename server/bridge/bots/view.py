"""What a bot is allowed to know when choosing a card.

The bot's decision functions take only a BotView. `view_for` is the single
place that reads from the full game state, and it copies out exactly what the
deciding seat could see at a real table: its own cards, dummy once the
opening lead has been made, the auction and every card already played.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..core.auction import Auction, Contract
from ..core.cards import partner
from ..core.play import Play


@dataclass(frozen=True)
class BotView:
    seat: str                       # whose card is being played (may be dummy)
    controller: str                 # who decides (declarer when playing dummy's card)
    dealer: str
    vulnerability: str
    calls: tuple[str, ...]
    contract: Contract
    own_hand: tuple[str, ...]       # controller's remaining cards
    dummy: str
    dummy_hand: tuple[str, ...] | None  # dummy's remaining cards once visible
    tricks: tuple[tuple[str, tuple[tuple[str, str], ...]], ...]  # (leader, ((seat, card), ...))
    legal: tuple[str, ...]
    signals: str | None = None      # the table's defensive signals ("standard" or "upside"), or none (signals.py)
    leads: bool = True              # the table leads by Standard leads (leads.py)

    @property
    def declarer(self) -> str:
        return self.contract.declarer

    @property
    def trump(self) -> str:
        return self.contract.strain

    def auction(self) -> Auction:
        return Auction(self.dealer, list(self.calls))

    def played_by(self, seat: str) -> list[str]:
        return [c for _, cards in self.tricks for s, c in cards if s == seat]

    def all_played(self) -> list[str]:
        return [c for _, cards in self.tricks for _, c in cards]

    @property
    def current_trick(self) -> tuple[str, tuple[tuple[str, str], ...]]:
        return self.tricks[-1]


def view_for(play: Play, auction: Auction, contract: Contract, vulnerability: str,
             seat_to_play: str, signals: str | None = None, leads: bool = True) -> BotView:
    declarer = contract.declarer
    dummy = partner(declarer)
    controller = declarer if seat_to_play == dummy else seat_to_play
    dummy_visible = play.opening_lead_made()
    return BotView(
        seat=seat_to_play,
        controller=controller,
        dealer=auction.dealer,
        vulnerability=vulnerability,
        calls=tuple(auction.calls),
        contract=contract,
        own_hand=tuple(play.hands[controller]),
        dummy=dummy,
        dummy_hand=tuple(play.hands[dummy]) if dummy_visible and controller != dummy else None,
        tricks=tuple((t.leader, tuple(t.cards)) for t in play.tricks),
        legal=tuple(play.legal_cards(seat_to_play)),
        signals=signals,
        leads=leads,
    )
