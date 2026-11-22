"""Convention registry. Order matters only for ties in rule priority."""
from ..engine import BiddingEngine
from ..rules import Convention
from .competitive import COMPETITIVE, NEGATIVE_DOUBLES
from .general import GENERAL
from .notrump import GERBER_CONV, JACOBY_CONV, MINOR_T_CONV, NOTRUMP, STAYMAN_CONV
from .openings import OPENINGS, PREEMPTS, WEAK_TWOS
from .slam import BLACKWOOD
from .strong_and_weak import PREEMPT_RESP, STRONG_2C_CONV, WEAK_TWO_RESP
from .suits import JACOBY_2NT, OPENER_REBIDS, SUIT_RESPONSES

ALL_CONVENTIONS: list[Convention] = [
    OPENINGS, STRONG_2C_CONV, WEAK_TWOS, PREEMPTS,
    NOTRUMP, STAYMAN_CONV, JACOBY_CONV, MINOR_T_CONV, GERBER_CONV,
    SUIT_RESPONSES, JACOBY_2NT, OPENER_REBIDS, WEAK_TWO_RESP, PREEMPT_RESP,
    COMPETITIVE, NEGATIVE_DOUBLES, BLACKWOOD, GENERAL,
]

BY_ID = {c.id: c for c in ALL_CONVENTIONS}


def make_engine(enabled: set[str] | None = None) -> BiddingEngine:
    return BiddingEngine(ALL_CONVENTIONS, enabled)


def convention_list() -> list[dict]:
    from ..lessons import LESSONS
    return [{**c.summary(), "lesson": c.id in LESSONS} for c in ALL_CONVENTIONS]


def requirements(conv: str) -> set[str]:
    """`conv` plus the conventions its rules need (e.g. minor transfers need Jacoby)."""
    out = {conv}
    for r in BY_ID[conv].rules:
        out.update(r.needs)
    return out
