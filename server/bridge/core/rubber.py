"""Rubber bridge scoring (Laws of Contract Bridge, law 72 onward).

Each board's points go "below the line" (the tricks bid and made, which count towards game) or "above the line"
(overtricks, bonuses, penalties, honors). 100 points below the line wins a game and starts a new one; the first side
to win two games wins the rubber, with a bonus of 700 (two games to none) or 500 (two games to one). A side that has
won a game is vulnerable.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .auction import Contract
from .cards import Hand, same_side
from .scoring import duplicate_score, trick_score

SIDES = ("NS", "EW")


def side_of(seat: str) -> str:
    return "NS" if same_side(seat, "N") else "EW"


def honors(hands: dict[str, Hand], strain: str) -> tuple[str, int, str] | None:
    """(seat, points, description) for honors held in one hand: 4 of the 5 trump honors 100, all 5 150;
    in no trumps, all four aces 150. Honors score whoever holds them, whether the contract makes or not."""
    for seat, hand in hands.items():
        if strain == "N":
            if sum(1 for c in hand.cards if c[1] == "A") == 4:
                return seat, 150, "four aces"
        else:
            n = sum(1 for c in hand.cards if c[0] == strain and c[1] in "AKQJT")
            if n == 5:
                return seat, 150, "five honors"
            if n == 4:
                return seat, 100, "four honors"
    return None


@dataclass
class Line:
    board: int
    side: str  # NS or EW
    where: str  # "below" or "above"
    points: int
    what: str

    def to_dict(self) -> dict:
        return dict(self.__dict__)


@dataclass
class Rubber:
    number: int = 1
    games: dict[str, int] = field(default_factory=lambda: {"NS": 0, "EW": 0})
    below: dict[str, int] = field(default_factory=lambda: {"NS": 0, "EW": 0})  # this game's part-scores
    lines: list[Line] = field(default_factory=list)  # this rubber's entries, in order
    game_ends: list[int] = field(default_factory=list)  # a game ended after lines[:i]
    finished: list[dict] = field(default_factory=list)  # earlier rubbers' totals

    def vulnerability(self) -> str:
        ns, ew = self.games["NS"] > 0, self.games["EW"] > 0
        return "Both" if ns and ew else "NS" if ns else "EW" if ew else "None"

    def totals(self) -> dict[str, int]:
        return {s: sum(l.points for l in self.lines if l.side == s) for s in SIDES}

    def record(self, board: int, contract: Contract | None, tricks: int, hands: dict[str, Hand]) -> int:
        """Score one board into the rubber. Returns the board's points for N–S minus those for E–W."""
        if contract is None:
            return 0
        start = len(self.lines)
        decl = side_of(contract.declarer)
        defs = "EW" if decl == "NS" else "NS"
        vul = self.games[decl] > 0
        level, strain, dbl = contract.level, contract.strain, contract.doubled
        needed = level + 6
        name = f"{level}{strain}{'X' * dbl}"
        if tricks >= needed:
            self._add(board, decl, "below", trick_score(strain, level) * (1, 2, 4)[dbl], name)
            over = tricks - needed
            if over:
                per = (20 if strain in "CD" else 30) if dbl == 0 else (200 if vul else 100) * dbl
                self._add(board, decl, "above", over * per, f"{over} overtrick{'s' if over > 1 else ''}")
            if dbl:
                self._add(board, decl, "above", 50 * dbl, "doubled, made" if dbl == 1 else "redoubled, made")
            if level == 6:
                self._add(board, decl, "above", 750 if vul else 500, "small slam")
            elif level == 7:
                self._add(board, decl, "above", 1500 if vul else 1000, "grand slam")
        else:
            # undertrick penalties are the same as at duplicate
            down = needed - tricks
            self._add(board, defs, "above", -duplicate_score(contract, tricks, vul), f"{name} down {down}")
        h = honors(hands, strain)
        if h:
            self._add(board, side_of(h[0]), "above", h[1], h[2])

        made = self.lines[start:]
        for s in SIDES:
            self.below[s] += sum(l.points for l in made if l.side == s and l.where == "below")
        for s in SIDES:
            if self.below[s] >= 100:
                self.games[s] += 1
                self.below = {"NS": 0, "EW": 0}
                self.game_ends.append(len(self.lines))
                if self.games[s] == 2:
                    other = "EW" if s == "NS" else "NS"
                    self._add(board, s, "above", 500 if self.games[other] else 700, "rubber")
                    made = self.lines[start:]
                    self._close(board)
                break
        return sum(l.points for l in made if l.side == "NS") - sum(l.points for l in made if l.side == "EW")

    def _add(self, board: int, side: str, where: str, points: int, what: str) -> None:
        self.lines.append(Line(board, side, where, points, what))

    def _close(self, board: int) -> None:
        # the whole pad is kept, so the end of the rubber can be shown with its score
        t = self.totals()
        self.finished.append({"number": self.number, "NS": t["NS"], "EW": t["EW"],
                              "winner": "NS" if t["NS"] >= t["EW"] else "EW", "board": board,
                              "games": dict(self.games), "lines": [l.to_dict() for l in self.lines],
                              "game_ends": list(self.game_ends)})
        self.number += 1
        self.games = {"NS": 0, "EW": 0}
        self.below = {"NS": 0, "EW": 0}
        self.lines = []
        self.game_ends = []

    def to_dict(self) -> dict:
        return {"number": self.number, "games": dict(self.games), "below": dict(self.below),
                "vulnerability": self.vulnerability(), "lines": [l.to_dict() for l in self.lines],
                "game_ends": list(self.game_ends), "totals": self.totals(), "finished": list(self.finished)}
