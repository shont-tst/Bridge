"""Board numbering: dealer and vulnerability follow the standard 16-board cycle."""
from __future__ import annotations

from .cards import SEATS

_VUL_CYCLE = [
    "None", "NS", "EW", "Both",
    "NS", "EW", "Both", "None",
    "EW", "Both", "None", "NS",
    "Both", "None", "NS", "EW",
]


def dealer_for(board: int) -> str:
    return SEATS[(board - 1) % 4]


def vulnerability_for(board: int) -> str:
    return _VUL_CYCLE[(board - 1) % 16]


def is_vulnerable(vul: str, seat: str) -> bool:
    return vul == "Both" or (vul != "None" and seat in vul)
