"""Defensive signals: which spot card a defender plays when the choice doesn't cost a trick, and what partner (and
declarer) can read from it.

A table plays one method, or none (`Settings.signals`):
  standard  high encourages, and high-low shows an even number;
  upside    upside-down: low encourages, and low-high shows an even number. Suit preference is the same in both.

The situations, each only the first time the suit is played (and never in the trump suit):
  attitude    following to partner's lead: like the suit if you hold the ace, king or queen;
  preference  following to partner's lead in a suit contract when dummy has one card or none there (attitude can't
              matter), or leading a suit partner has shown out of (a ruff): a high card asks for the higher of the
              two other side suits, a low one the lower; ask for the higher one if you hold its ace or king;
  count       following to declarer's (or dummy's) lead: an even or odd number of cards in the suit;
  discard     your first discard: a card in a suit you like (holding its ace or king), or one you don't.

A card says "high" when the defender holds a lower card in that suit, and "low" when it is their lowest. Tens and
honors, and a card that was the only one in its suit, say nothing. The same tests give a signal (`pick`, among the
cards the solver finds equally good) and read one (`consistent`, in the sampler on each layout of a hidden hand), so
a bot reads exactly what a bot means. A person's cards are read the same way: playing signals is the table's
agreement. Bots from strength 3 up give and read signals (the levels that use the auction).
"""
from __future__ import annotations

from dataclasses import dataclass

from ..core.cards import SUIT_SYMBOL, SUITS, partner, rank_value, same_side
from .view import BotView

METHODS = {"standard": "Standard", "upside": "Upside-down"}
SPOTS = set("23456789")
HONORS = {"attitude": "AKQ", "discard": "AK", "preference": "AK"}


@dataclass(frozen=True)
class Signal:
    kind: str  # attitude, count, preference or discard
    suit: str  # the suit the card was played in


def _tricks_before(view: BotView, t: int, i: int) -> list[tuple[str, tuple]]:
    """The play up to the i-th card of trick t."""
    leader, cards = view.tricks[t]
    return list(view.tricks[:t]) + [(leader, cards[:i])]


def situation(tricks: list[tuple[str, tuple]], seat: str, card: str, declarer: str, trump: str,
              dummy_cards: list[str] | None) -> Signal | None:
    """What `card`, played by `seat` after `tricks` (the last one is the trick it's played to), would signal."""
    if same_side(seat, declarer):
        return None
    leader, cards = tricks[-1]
    earlier = [cs for _, cs in tricks[:-1] if cs]
    led_before = {cs[0][1][0] for cs in earlier}
    suit = card[0]
    if trump != "N" and suit == trump:
        return None  # trumps (and ruffs) aren't signals here
    if not cards:  # leading
        if trump == "N":
            return None
        mate = partner(seat)
        shown_out = any(s == mate and c[0] != cs[0][1][0] for cs in earlier for s, c in cs[1:]
                        if cs[0][1][0] == suit)
        return Signal("preference", suit) if shown_out else None
    led = cards[0][1][0]
    if suit == led:
        if led in led_before:
            return None
        if cards[0][0] == partner(seat):
            if trump != "N" and dummy_cards is not None and sum(c[0] == led for c in dummy_cards) <= 1:
                return Signal("preference", led)
            return Signal("attitude", led)
        return Signal("count", led)
    discarded = any(s == seat and c[0] != cs[0][1][0] and (trump == "N" or c[0] != trump)
                    for cs in earlier for s, c in cs)
    return None if discarded else Signal("discard", suit)


def others(suit: str, trump: str) -> tuple[str, str]:
    """For suit preference: (the higher, the lower) of the two side suits other than `suit`."""
    rest = [s for s in SUITS if s not in (suit, trump)]
    return rest[0], rest[1]


def reads_high(card: str, hand: list[str]) -> bool | None:
    """True if `card` reads as high (a lower card of the suit held with it), False if it's the lowest held, None if
    it says nothing: a ten or an honor, or the only card held in the suit."""
    if card[1] not in SPOTS:
        return None
    suit = [c for c in hand if c[0] == card[0]]
    if len(suit) < 2:
        return None
    return any(rank_value(c) < rank_value(card) for c in suit)


def truth(sig: Signal, hand: list[str], trump: str) -> bool:
    """Whether the signal should say yes (like the suit, an even number, the higher suit) with this hand."""
    if sig.kind == "count":
        return sum(c[0] == sig.suit for c in hand) % 2 == 0
    suit = others(sig.suit, trump)[0] if sig.kind == "preference" else sig.suit
    return any(c[0] == suit and c[1] in HONORS[sig.kind] for c in hand)


def flipped(sig: Signal, method: str) -> bool:
    """Upside-down turns attitude and count around (low says yes); suit preference is the same in both."""
    return method == "upside" and sig.kind != "preference"


def dummy_cards(view: BotView) -> list[str] | None:
    if view.dummy_hand is None:
        return None
    return list(view.dummy_hand) + view.played_by(view.dummy)


def pick(view: BotView, card: str, equal: list[str]) -> tuple[str, dict | None]:
    """Out of `equal` (cards the solver found exactly as good as `card` on every layout), the card that tells partner
    the truth by the table's method, with what it says. A defender with no choice that could tell the truth plays
    `card` as chosen."""
    method = view.signals
    if not method or view.seat != view.controller:
        return card, None
    hand = list(view.own_hand)
    tricks = list(view.tricks)
    found: list[tuple[str, Signal, bool, bool]] = []
    lead = not view.current_trick[1]
    for c in equal:
        if lead and c[0] != card[0]:
            continue  # a signal doesn't change the suit led
        sig = situation(tricks, view.seat, c, view.declarer, view.trump, dummy_cards(view))
        if sig is None:
            continue
        high = reads_high(c, hand)
        if high is None:
            continue
        yes = truth(sig, hand, view.trump)
        if high == (yes != flipped(sig, method)):
            found.append((c, sig, high, yes))
    if not found:
        return card, None
    if found[0][1].kind == "discard":  # a card in a suit you like if you can, otherwise one you don't
        found = [f for f in found if f[3]] or found
    suit = card[0] if any(f[0][0] == card[0] for f in found) else found[0][0][0]
    found = [f for f in found if f[0][0] == suit]
    c, sig, high, yes = (max if found[0][2] else min)(found, key=lambda f: rank_value(f[0]))
    return c, describe(sig, high, yes, method, view.trump)


def describe(sig: Signal, high: bool, yes: bool, method: str, trump: str) -> dict:
    asked = others(sig.suit, trump)[0 if yes else 1] if sig.kind == "preference" else None
    return {"kind": sig.kind, "suit": sig.suit, "high": high, "yes": yes, "method": method, "asks": asked}


def words(signal: dict, you: bool = False) -> str:
    """'Standard signals: a high card says it likes ♥.' (or 'you like ♥' for a hint)."""
    sym = SUIT_SYMBOL[signal["suit"]]
    who, likes, has, wants = ("you", "you like", "you have", "you want") if you else \
        ("it", "it likes", "it has", "it wants")
    kind, yes = signal["kind"], signal["yes"]
    if kind in ("attitude", "discard"):
        what = f"{likes} {sym}" if yes else f"{who} don't like {sym}" if you else f"it doesn't like {sym}"
    elif kind == "count":
        what = f"{has} an {'even' if yes else 'odd'} number of {sym}"
    else:
        what = f"{wants} {SUIT_SYMBOL[signal['asks']]} next"
    return f"{METHODS[signal['method']]} signals: a {'high' if signal['high'] else 'low'} card says {what}."


@dataclass(frozen=True)
class Seen:
    """A signal a hidden defender gave: the card, in trick t, and what it was about."""
    seat: str
    trick: int
    card: str
    sig: Signal


def seen(view: BotView) -> list[Seen]:
    """Every card a hidden defender played that may have been a signal."""
    if not view.signals:
        return []
    visible = {view.controller} | ({view.dummy} if view.dummy_hand is not None else set())
    out = []
    dummy = dummy_cards(view)
    for t, (_, cards) in enumerate(view.tricks):
        for i, (seat, c) in enumerate(cards):
            if seat in visible or c[1] not in SPOTS:
                continue
            sig = situation(_tricks_before(view, t, i), seat, c, view.declarer, view.trump, dummy)
            if sig:
                out.append(Seen(seat, t, c, sig))
    return out


def consistent(view: BotView, signals: list[Seen], seat: str, remaining: list[str]) -> bool:
    """Whether a layout's cards for `seat` (what it holds now) fit the signals it gave, by the table's method."""
    method = view.signals
    for s in signals:
        if s.seat != seat:
            continue
        later = [c for _, cards in view.tricks[s.trick:] for p, c in cards if p == seat]
        hand = remaining + later  # what it held when it played the card
        high = reads_high(s.card, hand)
        if high is None:
            continue
        if (high != flipped(s.sig, method)) != truth(s.sig, hand, view.trump):
            return False
    return True
