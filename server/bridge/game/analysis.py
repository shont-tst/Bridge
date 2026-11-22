"""Double-dummy summary for a finished board (shown after the hand)."""
from __future__ import annotations

from endplay.types import Deal, Player, Vul

from ..core.cards import SEATS, Hand
from ..solver import dd_table_and_par

_ROWS = "SHDCN"  # endplay DDTable row order
_VUL = {"None": Vul.none, "NS": Vul.ns, "EW": Vul.ew, "Both": Vul.both}
_PLAYER = {"N": Player.north, "E": Player.east, "S": Player.south, "W": Player.west}


def dd_summary(hands: dict[str, Hand], vulnerability: str, dealer: str) -> dict:
    pbn = "N:" + " ".join(hands[s].to_pbn() for s in SEATS)
    deal = Deal.from_pbn(pbn)
    table, par_score, par_contracts = dd_table_and_par(deal, _VUL[vulnerability], _PLAYER[dealer])
    tricks = {strain: {seat: table[r][c] for c, seat in enumerate(SEATS)}
              for r, strain in enumerate(_ROWS)}
    return {
        "tricks": tricks,  # tricks[strain][declarer]
        "par_score_ns": par_score,
        "par_contracts": par_contracts,
    }
