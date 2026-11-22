"""The auction from one seat's point of view, as seen by bidding rules."""
from __future__ import annotations

from functools import cached_property
from typing import TYPE_CHECKING

from ..core.auction import PASS, Auction, is_bid
from ..core.board import is_vulnerable
from ..core.cards import next_seat, partner, same_side

if TYPE_CHECKING:
    from .engine import BiddingEngine
    from .shows import HandInference

REL = {0: "me", 1: "lho", 2: "pd", 3: "rho"}


class Ctx:
    """Context for the seat about to call after `auction.calls`."""

    def __init__(self, auction: Auction, engine: "BiddingEngine", vul: str | None = None):
        self.auction = auction
        self.engine = engine
        self.vul = vul  # who is vulnerable ("None", "NS", "EW", "Both"), or None when the bidder isn't told (vul.py)
        self.me = auction.next_to_call
        self.partner = partner(self.me)
        self.lho = next_seat(self.me)
        self.rho = next_seat(self.me, 3)
        self.calls = auction.with_seats()

    # --- who's who -------------------------------------------------------------
    @property
    def we_vul(self) -> bool:
        return self.vul is not None and is_vulnerable(self.vul, self.me)

    @property
    def they_vul(self) -> bool:
        return self.vul is not None and is_vulnerable(self.vul, self.lho)

    @property
    def unfavorable(self) -> bool:
        """We are vulnerable and they are not: going down costs us the most."""
        return self.we_vul and not self.they_vul

    @property
    def favorable(self) -> bool:
        """They are vulnerable and we are not."""
        return self.vul is not None and self.they_vul and not self.we_vul

    def rel(self, seat: str) -> str:
        return REL[("NESW".index(seat) - "NESW".index(self.me)) % 4]

    @cached_property
    def opening_index(self) -> int | None:
        for i, (_, c) in enumerate(self.calls):
            if is_bid(c):
                return i
        return None

    @cached_property
    def opener(self) -> str | None:
        """Seat that opened the bidding."""
        return None if self.opening_index is None else self.calls[self.opening_index][0]

    @cached_property
    def opener_rel(self) -> str | None:
        return None if self.opener is None else self.rel(self.opener)

    @property
    def we_opened(self) -> bool:
        return self.opener is not None and same_side(self.opener, self.me)

    @property
    def they_opened(self) -> bool:
        return self.opener is not None and not same_side(self.opener, self.me)

    @cached_property
    def since_open(self) -> tuple[str, ...]:
        """All calls from the opening bid on (empty if nobody has bid)."""
        if self.opening_index is None:
            return ()
        return tuple(c for _, c in self.calls[self.opening_index:])

    def calls_by(self, seat: str) -> list[str]:
        return [c for s, c in self.calls if s == seat]

    @cached_property
    def my_calls(self) -> list[str]:
        return self.calls_by(self.me)

    @cached_property
    def partner_calls(self) -> list[str]:
        return self.calls_by(self.partner)

    @cached_property
    def partner_bids(self) -> list[str]:
        return [c for c in self.partner_calls if is_bid(c)]

    @cached_property
    def my_bids(self) -> list[str]:
        return [c for c in self.my_calls if is_bid(c)]

    @cached_property
    def opp_bids(self) -> list[str]:
        return [c for s, c in self.calls if not same_side(s, self.me) and is_bid(c)]

    @cached_property
    def opp_suits(self) -> list[str]:
        """Natural-ish suits bid by the opponents (first bids only)."""
        out = []
        for c in self.opp_bids:
            if c[1] != "N" and c[1] not in out:
                out.append(c[1])
        return out

    @cached_property
    def uncontested(self) -> bool:
        return all(c == PASS for s, c in self.calls if not same_side(s, self.me))

    @cached_property
    def passed_hand(self) -> bool:
        """I passed before anyone opened."""
        before = self.calls if self.opening_index is None else self.calls[:self.opening_index]
        return any(s == self.me for s, _ in before)

    @property
    def legal(self) -> list[str]:
        return self.auction.legal_calls()

    @property
    def last_bid(self) -> str | None:
        return self.auction.last_bid()

    @cached_property
    def last_bidder(self) -> str | None:
        i = self.auction.last_bid_index()
        return None if i is None else self.auction.seat_of(i)

    @property
    def contract_is_ours(self) -> bool:
        return self.last_bidder is not None and same_side(self.last_bidder, self.me)

    @cached_property
    def doubled(self) -> int:
        st, _ = self.auction._double_state()
        return st

    # --- inference ---------------------------------------------------------------
    @cached_property
    def partner_info(self) -> "HandInference":
        return self.engine.infer(self.auction, self.partner)

    @cached_property
    def my_info(self) -> "HandInference":
        return self.engine.infer(self.auction, self.me)

    def partner_last_meaning(self):
        """Shows for partner's most recent call (None if partner hasn't called)."""
        for i in range(len(self.calls) - 1, -1, -1):
            if self.calls[i][0] == self.partner:
                return self.engine.explain(self.auction, i)
        return None

    @cached_property
    def partner_forcing(self) -> bool:
        """Partner's last call forces me to bid (and RHO didn't bid in between)."""
        m = self.partner_last_meaning()
        if m is None:
            return False
        rho_call = self.calls[-1][1] if self.calls else PASS
        if m.game_forcing:
            return True
        return m.forcing and rho_call == PASS

    @cached_property
    def game_forcing(self) -> bool:
        """Either of us has made a game-forcing call."""
        for i, (s, _) in enumerate(self.calls):
            if same_side(s, self.me) and self.engine.explain(self.auction, i).game_forcing:
                return True
        return False

    def __repr__(self) -> str:
        return f"Ctx(me={self.me}, calls={self.auction.calls})"
