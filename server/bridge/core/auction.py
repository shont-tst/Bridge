"""Auction: call legality, completion and the resulting contract.

Calls are strings: "P" (pass), "X" (double), "XX" (redouble) or a bid such as
"1C", "3N", "7S". Strains rank C < D < H < S < N.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .cards import next_seat, same_side

STRAINS = "CDHSN"
PASS, DOUBLE, REDOUBLE = "P", "X", "XX"


def is_bid(call: str) -> bool:
    return len(call) == 2 and call[0] in "1234567" and call[1] in STRAINS


def bid_rank(call: str) -> int:
    """Total order of bids: 1C=0 ... 7N=34."""
    return (int(call[0]) - 1) * 5 + STRAINS.index(call[1])


def all_bids() -> list[str]:
    return [f"{lvl}{s}" for lvl in range(1, 8) for s in STRAINS]


def normalize(call: str) -> str:
    c = call.strip().upper().replace("NT", "N").replace("PASS", "P")
    if c in ("D", "DBL"):
        return DOUBLE
    if c in ("R", "RDBL"):
        return REDOUBLE
    return c


@dataclass(frozen=True)
class Contract:
    level: int
    strain: str  # one of CDHSN
    declarer: str
    doubled: int = 0  # 0, 1 (X) or 2 (XX)

    def __str__(self) -> str:
        return f"{self.level}{self.strain}{'X' * self.doubled} by {self.declarer}"

    def to_dict(self) -> dict:
        return {"level": self.level, "strain": self.strain, "declarer": self.declarer,
                "doubled": self.doubled}


@dataclass
class Auction:
    dealer: str
    calls: list[str] = field(default_factory=list)

    def copy(self) -> "Auction":
        return Auction(self.dealer, list(self.calls))

    @property
    def next_to_call(self) -> str:
        return next_seat(self.dealer, len(self.calls))

    def seat_of(self, index: int) -> str:
        return next_seat(self.dealer, index)

    def with_seats(self) -> list[tuple[str, str]]:
        return [(self.seat_of(i), c) for i, c in enumerate(self.calls)]

    def last_bid_index(self) -> int | None:
        for i in range(len(self.calls) - 1, -1, -1):
            if is_bid(self.calls[i]):
                return i
        return None

    def last_bid(self) -> str | None:
        i = self.last_bid_index()
        return None if i is None else self.calls[i]

    def is_complete(self) -> bool:
        n = len(self.calls)
        if n >= 4 and all(c == PASS for c in self.calls):
            return True
        return self.last_bid_index() is not None and n >= 4 and self.calls[-3:] == [PASS] * 3

    def is_passed_out(self) -> bool:
        return self.is_complete() and self.last_bid_index() is None

    def _double_state(self) -> tuple[int, str | None]:
        """(0/1/2, seat that made the last bid) for the current last bid."""
        i = self.last_bid_index()
        if i is None:
            return 0, None
        state = 0
        for c in self.calls[i + 1:]:
            if c == DOUBLE:
                state = 1
            elif c == REDOUBLE:
                state = 2
        return state, self.seat_of(i)

    def legal_calls(self) -> list[str]:
        if self.is_complete():
            return []
        out = [PASS]
        last = self.last_bid()
        lo = 0 if last is None else bid_rank(last) + 1
        out += [b for b in all_bids() if bid_rank(b) >= lo]
        state, bidder = self._double_state()
        me = self.next_to_call
        if bidder is not None:
            if state == 0 and not same_side(me, bidder):
                out.append(DOUBLE)
            if state == 1 and same_side(me, bidder):
                out.append(REDOUBLE)
        return out

    def is_legal(self, call: str) -> bool:
        return normalize(call) in self.legal_calls()

    def add(self, call: str) -> None:
        call = normalize(call)
        if not self.is_legal(call):
            raise ValueError(f"illegal call {call!r} after {self.calls}")
        self.calls.append(call)

    def contract(self) -> Contract | None:
        """The final contract, or None if passed out / incomplete."""
        if not self.is_complete() or self.is_passed_out():
            return None
        i = self.last_bid_index()
        last = self.calls[i]
        strain = last[1]
        winner = self.seat_of(i)
        declarer = None
        for j, c in enumerate(self.calls):
            s = self.seat_of(j)
            if is_bid(c) and c[1] == strain and same_side(s, winner):
                declarer = s
                break
        state, _ = self._double_state()
        return Contract(int(last[0]), strain, declarer, state)
