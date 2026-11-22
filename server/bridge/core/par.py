"""Par from a double-dummy table, on any game scoring: the score both sides reach when each bids its best contract
and the other side sacrifices whenever going down doubled costs less than letting them make it.

The par score DDS gives is duplicate only. At rubber a side with a part score finishes its game with a lower
contract (with 60 below the line, 2♥ is game), so par there is worked out here, on the same scoring as the board
(core.scoring.duplicate_score with `below_before`).
"""
from __future__ import annotations

from .auction import Contract
from .board import is_vulnerable
from .scoring import duplicate_score

STRAINS = "CDHSN"  # in bidding order
SYMBOL = {"C": "♣", "D": "♦", "H": "♥", "S": "♠", "N": "NT"}  # names as DDS gives them: "4♥S+1", "5♦Ex-2"


def _rank(level: int, strain: str) -> int:
    return (level - 1) * 5 + STRAINS.index(strain)


def par(tricks: dict[str, dict[str, int]], vulnerability: str, below: dict[str, int] | None = None) -> dict:
    """{"score_ns", "contracts": ["2♥S+1", "5♦Ex-2", ...]} from tricks[strain][seat], named as DDS names them.

    Each side's options are every contract it could play: made ones score plus, failing ones are doubled sacrifices.
    The bidding goes on while the side that is losing can bid a higher contract that does better for it."""
    below = below or {"NS": 0, "EW": 0}
    options: dict[str, list[tuple[int, int, str]]] = {"NS": [], "EW": []}  # side -> (rank, score for side, name)
    for side in ("NS", "EW"):
        for strain in STRAINS:
            for seat in side:
                t = (tricks.get(strain) or {}).get(seat)
                if t is None:
                    continue
                vul = is_vulnerable(vulnerability, seat)
                for level in range(1, 8):
                    made = t >= level + 6
                    c = Contract(level, strain, seat, 0 if made else 1)
                    sc = duplicate_score(c, t, vul, below.get(side, 0))
                    over = t - (level + 6)
                    options[side].append((_rank(level, strain), sc, f"{level}{SYMBOL[strain]}{seat}"
                                          f"{'' if made else 'x'}{'=' if over == 0 else f'{over:+d}'}"))
    # nobody has bid (0). The side that can do best opens with its best contract; then, in turn, a side that is
    # losing outbids when a higher contract (made, or a doubled sacrifice) does better for it than the current one.
    cur_rank, cur_ns, cur = -1, 0, []
    best_of = {side: max((o[1] for o in options[side]), default=0) for side in options}
    side = "NS" if best_of["NS"] >= best_of["EW"] else "EW"
    passes = 0
    for _ in range(80):
        sign = 1 if side == "NS" else -1
        higher = [o for o in options[side] if o[0] > cur_rank]
        best = max((o[1] for o in higher), default=None)
        if best is not None and best > cur_ns * sign:
            low = min(o[0] for o in higher if o[1] == best)  # the lowest contract that gets there
            cur_rank, cur_ns = low, best * sign
            cur = sorted(o[2] for o in higher if o[1] == best and o[0] == low)
            passes = 0
        else:
            passes += 1
            if passes == 2:
                break
        side = "EW" if side == "NS" else "NS"
    return {"score_ns": cur_ns, "contracts": cur}
