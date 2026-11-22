"""Duplicate bridge scoring (Laws of Duplicate Bridge, law 77)."""
from __future__ import annotations

from .auction import Contract


def trick_score(strain: str, level: int) -> int:
    """Contract trick points for `level` tricks bid (undoubled)."""
    if strain in "CD":
        return 20 * level
    if strain in "HS":
        return 30 * level
    return 40 + 30 * (level - 1)  # NT


def duplicate_score(contract: Contract | None, tricks: int, vulnerable: bool, below_before: int = 0) -> int:
    """Score from declarer's side's perspective (negative when the contract fails).

    `tricks` is the number of tricks declarer's side took (0..13). `below_before` is the part score declarer's side
    already has at rubber: a contract that takes it to 100 gets the game bonus, as it finishes a game there. With 0
    (duplicate, or a fresh game at rubber) this is plain duplicate scoring.
    """
    if contract is None:
        return 0
    level, strain, dbl = contract.level, contract.strain, contract.doubled
    needed = level + 6
    if tricks >= needed:
        mult = (1, 2, 4)[dbl]
        below = trick_score(strain, level) * mult
        score = below
        # game / part-score bonus
        if below + below_before >= 100:
            score += 500 if vulnerable else 300
        else:
            score += 50
        # slam bonuses
        if level == 6:
            score += 750 if vulnerable else 500
        elif level == 7:
            score += 1500 if vulnerable else 1000
        # insult
        if dbl == 1:
            score += 50
        elif dbl == 2:
            score += 100
        # overtricks
        over = tricks - needed
        if over:
            if dbl == 0:
                score += over * (20 if strain in "CD" else 30)
            else:
                per = (100 if not vulnerable else 200) * dbl
                score += over * per
        return score

    down = needed - tricks
    if dbl == 0:
        return -down * (100 if vulnerable else 50)
    if vulnerable:
        pen = 200 + (down - 1) * 300
    else:
        pen = 100 + min(down - 1, 2) * 200 + max(down - 3, 0) * 300
    return -pen * dbl


_IMP_TABLE = [20, 50, 90, 130, 170, 220, 270, 320, 370, 430, 500, 600, 750, 900,
              1100, 1300, 1500, 1750, 2000, 2250, 2500, 3000, 3500, 4000]


def imps(diff: int) -> int:
    """Convert a point difference to IMPs (signed)."""
    a = abs(diff)
    n = sum(1 for t in _IMP_TABLE if a >= t)
    return n if diff >= 0 else -n
