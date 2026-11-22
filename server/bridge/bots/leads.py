"""Opening leads: which card of a suit the opening leader leads, and what the other three can read from it.

Every bot leads by Standard leads, against a suit contract and against no trump alike:
  a singleton;
  the ace from ace-king;
  against a suit contract, an ace rather than lead away from it (not in the trump suit);
  the top of a sequence: two touching cards, the higher a ten or better (K Q 5, J T 3);
  the top of an inside sequence: an honor above two touching cards, the higher a ten or better (K J T 4, A Q J);
  the top of two cards;
  low from three to an honor (K 7 3), and the top of three small (8 6 2);
  fourth best from four or more (K J 6 4 2: the 4).
The solver still picks the suit, but within it only this card is weighed, so the lead always follows the method.
The same rule reads a lead back (`consistent`, in the sampler on each layout of the leader's hand), so partner and
declarer read exactly what the leader meant. A person's lead is read the same way, as the table's agreement; when
no layouts fit (they led another card), the sampler drops it, as it does signals. Bots read leads from strength 3
up, the levels that use the auction. A table setting (`Settings.leads`, on by default) can switch it off: then the
solver picks any card, and nobody reads the lead. The review's odds don't read the lead.
"""
from __future__ import annotations

from ..core.cards import SUITS, rank_value
from .view import BotView

WORDS = {
    "single": "a singleton",
    "ace-king": "the ace from ace-king",
    "ace": "the ace, rather than lead away from it",
    "sequence": "top of a sequence",
    "inside": "top of an inside sequence",
    "doubleton": "top of two cards",
    "low-honor": "low from three to an honor",
    "nothing": "top of three small",
    "fourth": "fourth best",
}


def method_card(suit_cards: list[str], trump: str) -> tuple[str, str]:
    """The card Standard leads lead from these cards of one suit, and which rule picked it (a key of WORDS)."""
    cs = sorted(suit_cards, key=rank_value, reverse=True)
    r = [rank_value(c) for c in cs]
    n = len(cs)
    if n == 1:
        return cs[0], "single"
    if r[0] == 14 and r[1] == 13:
        return cs[0], "ace-king"
    if trump != "N" and cs[0][0] != trump and r[0] == 14:
        return cs[0], "ace"
    if r[0] >= 10 and r[1] == r[0] - 1:
        return cs[0], "sequence"
    if n >= 3 and r[0] >= 12 and r[1] >= 10 and r[2] == r[1] - 1:
        return cs[1], "inside"
    if n == 2:
        return cs[0], "doubleton"
    if n == 3:
        return (cs[2], "low-honor") if r[0] >= 11 else (cs[0], "nothing")
    return cs[3], "fourth"


def is_opening_lead(view: BotView) -> bool:
    """The opening lead, at a table that plays Standard leads."""
    return view.leads and not view.all_played()


def candidates(view: BotView) -> list[str]:
    """At the opening lead, the one card of each suit that Standard leads would lead."""
    hand = list(view.own_hand)
    return [method_card([c for c in hand if c[0] == s], view.trump)[0] for s in SUITS if any(c[0] == s for c in hand)]


def kind(view: BotView, card: str) -> str | None:
    """Which rule the opening lead `card` follows from the leader's own hand, or None if it isn't the method card."""
    suit = [c for c in view.own_hand if c[0] == card[0]]
    led, why = method_card(suit, view.trump)
    return why if led == card else None


def words(why: str) -> str:
    """'Standard leads: fourth best.'"""
    return f"Standard leads: {WORDS[why]}."


def shows(card: str, trump: str) -> str:
    """What everyone at the table can read from a lead by its rank alone, without the leader's hand."""
    r = rank_value(card)
    if r == 14:
        rest = "rather than lead away from it" if trump != "N" else "top of two cards"
        return f"Standard leads: the ace from ace-king, or {rest}."
    if r >= 10:
        return "Standard leads: top of a sequence, or of two cards."
    return "Standard leads: fourth best, low from three to an honor, or top of two or three small."


def opening(view: BotView) -> tuple[str, str] | None:
    """(leader, card) once the opening lead is made, at a table that plays Standard leads."""
    if not view.leads:
        return None
    _, cards = view.tricks[0]
    return cards[0] if cards else None


def consistent(view: BotView, seat: str, remaining: list[str]) -> bool:
    """Whether a layout's cards for `seat` (what it holds now) fit its opening lead, if it made it."""
    lead = opening(view)
    if lead is None or lead[0] != seat:
        return True
    card = lead[1]
    hand = remaining + view.played_by(seat)  # what it held at the start
    return method_card([c for c in hand if c[0] == card[0]], view.trump)[0] == card
