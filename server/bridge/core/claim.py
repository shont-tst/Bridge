"""Claims: when the side on lead is sure to take every remaining trick, in any order, however the hidden cards lie.

The rule: a claim has to win whatever order the cards are played in, as at
the club when you put your hand down and say "the rest are mine". Declarer sees dummy, so both hands count: every
combination of cards declarer and dummy could play, in any order, has to take every trick, against the strongest
cards the other side may hold. A card wins a trick when it is higher than any card the other side may still hold in
the suit led and, unless it is itself a trump higher than all of theirs, they hold no trumps to ruff it with (either of
them may be void). So high trumps in one hand take care of losers led from the other,
while a line that needs a set order (crossing to dummy, ruffing out a suit, running a long suit once the others are
gone, drawing the last trump first) isn't a claim, nor is a guess such as a two-way finesse.

A defender doesn't see partner's hand, so a defender's claim is their own cards alone, each higher than any card left
in the other three hands.

Mid-trick (the other side led, or one of them played after the claimer's partner), the claimer's side must win this
trick too, with cards it chooses now: one that beats those already played and, while one of the other side is still
to play, is sure to win as above. Every combination of play after that trick must then win the rest.
"""
from __future__ import annotations

from itertools import product

from .cards import next_seat, partner, rank_value, same_side
from .play import Play

def _others(play: Play, seats: list[str]) -> dict[str, tuple[int, ...]]:
    """Ranks the other side might hold, per suit, lowest first."""
    cards = [c for s, h in play.hands.items() if s not in seats for c in h]
    return {s: tuple(sorted(rank_value(c) for c in cards if c[0] == s)) for s in "SHDC"}


def _seats(play: Play, leader: str) -> tuple[str, str | None]:
    """The leader and the hand the claimer can see and play with them (None for a defender, who can't)."""
    if same_side(leader, play.declarer):
        return leader, partner(leader)
    return leader, None


def _sure(card: str, trump: str, pool: dict[str, tuple[int, ...]]) -> bool:
    """Whether `card` wins any trick it is led to or played on, whatever the other side holds and plays."""
    s = card[0]
    top = not pool[s] or rank_value(card) > pool[s][-1]
    return top and (trump in ("N", s) or not pool[trump])


LIMIT = 5_000  # positions looked at before giving up (no claim): plenty for real endings, and quick


def _wins(card: str, led: str, trump: str, pool: dict[str, tuple[int, ...]]) -> bool:
    """Whether `card`, played to a trick in suit `led`, beats anything the other side may play to it (any of them
    may be void in the suit and ruff)."""
    s, r = card[0], rank_value(card)
    if trump != "N" and s == trump:
        return not pool[trump] or r > pool[trump][-1]
    if s != led:
        return False
    return (not pool[s] or r > pool[s][-1]) and (trump == "N" or not pool[trump])


def _every_way(hands: dict[str, tuple[str, ...]], leader: str, trump: str,
               pool: dict[str, tuple[int, ...]]) -> bool:
    """Whether every combination of play by the claimer's hands (one, or declarer and dummy), from `leader` on lead,
    takes every remaining trick. The other side keeps its strongest cards throughout, which can only make it harder."""
    seen: dict[tuple, bool] = {}
    budget = [LIMIT]

    def strength(card: str, led: str) -> int:
        return (100 if trump != "N" and card[0] == trump else 0 if card[0] == led else -100) + rank_value(card)

    def go(hs: tuple[tuple[str, tuple[str, ...]], ...], lead_seat: str) -> bool:
        cards = dict(hs)
        if not cards[lead_seat]:
            return True
        key = (hs, lead_seat)
        if key in seen:
            return seen[key]
        budget[0] -= 1
        if budget[0] < 0:
            return False
        if all(_wins(x, x[0], trump, pool) for h in cards.values() for x in h):
            return True  # only winners left: whatever is led wins, and so does any card that beats it
        other = next((s for s in cards if s != lead_seat), None)

        def choices(seat: str, among: list[str]) -> list[str]:
            """One card of each run that plays alike: no card of the other hands' lies between them."""
            outside = [x for s, h in cards.items() if s != seat for x in h]
            picked: dict[tuple, str] = {}
            for x in among:
                below = sum(rank_value(y) < rank_value(x) for y in outside if y[0] == x[0])
                below += sum(r < rank_value(x) for r in pool[x[0]])
                picked.setdefault((x[0], below), x)
            return list(picked.values())

        ok = True
        for c in choices(lead_seat, list(cards[lead_seat])):
            led = c[0]
            follows = [None] if other is None else choices(
                other, [x for x in cards[other] if x[0] == led] or list(cards[other]))
            for f in follows:
                played = [(lead_seat, c)] + ([(other, f)] if f is not None else [])
                win_seat, win = max(played, key=lambda sc: strength(sc[1], led))
                if not _wins(win, led, trump, pool):
                    ok = False
                    break
                rest = tuple((s, tuple(x for x in h if x not in (c, f))) for s, h in hs)
                if not go(rest, win_seat):
                    ok = False
                    break
            if not ok:
                break
        seen[key] = ok
        return ok

    return go(tuple((s, tuple(sorted(h))) for s, h in sorted(hands.items())), leader)


def claim_line(play: Play) -> tuple[str, str | None] | None:
    """At the start of a trick: the leader's card, and their partner's when the claimer plays it too (declarer's side),
    that begin a sure line to every remaining trick. None when no such claim is certain."""
    if play.is_complete() or play.current.cards:
        return None
    leader, other = _seats(play, play.next_to_play)
    seen = [leader] if other is None else [leader, other]
    if not _every_way({s: tuple(play.hands[s]) for s in seen}, leader, play.trump, _others(play, seen)):
        return None
    # every way wins, so any line will do: top cards first (trumps first), partner following as low as it may
    lead = min(play.hands[leader], key=lambda c: (c[0] != play.trump, -rank_value(c), c))
    if other is None:
        return lead, None
    legal = [x for x in play.hands[other] if x[0] == lead[0]] or list(play.hands[other])
    return lead, min(legal, key=lambda x: (play.trump != "N" and x[0] == play.trump and x[0] != lead[0],
                                           rank_value(x), x))


def trick_plan(play: Play) -> dict[str, str] | None:
    """Mid-trick: the cards the claimer's side plays to finish this trick (by seat) so that it surely wins it and then
    has a sure line to every trick after. None when there's no such plan, or at the start of a trick."""
    t = play.current
    if play.is_complete() or not t.cards:
        return None
    actor = play.next_to_play
    leader, other = _seats(play, actor)
    seen = [leader] if other is None else [leader, other]
    pool = _others(play, seen)
    led = t.lead_suit
    to_play = [next_seat(t.leader, i) for i in range(len(t.cards), 4)]
    ours = [s for s in to_play if s in seen]  # the other side's cards here are unknown
    opponents_left = any(s not in seen for s in to_play)

    def legal(seat: str) -> list[str]:
        hand = play.hands[seat]
        return [c for c in hand if c[0] == led] or list(hand)

    def strength(card: str) -> int:
        return (100 if play.trump != "N" and card[0] == play.trump else 0 if card[0] == led else -100) + rank_value(card)

    for cards in product(*(legal(s) for s in ours)):
        mine = dict(zip(ours, cards))
        best = max(t.cards + list(mine.items()), key=lambda sc: strength(sc[1]))
        if best[0] not in mine:  # a defender can't count on partner, and declarer must take it with a card played now
            continue
        w = best[1]
        if strength(w) < 0 or (opponents_left and not _sure(w, play.trump, pool)):
            continue
        rest = {s: tuple(sorted(c for c in play.hands[s] if c != mine.get(s))) for s in seen}
        if _every_way(rest, best[0], play.trump, pool):
            return mine
    return None


def can_claim(play: Play) -> bool:
    if play.is_complete():
        return False
    if play.current.cards:
        return trick_plan(play) is not None
    return claim_line(play) is not None


def lowest(play: Play) -> str:
    """The card the other side plays during a claim: the lowest it may, a non-trump if it can discard one."""
    legal = play.legal_cards()
    return min(legal, key=lambda c: (play.trump != "N" and c[0] == play.trump and c[0] != play.current.lead_suit,
                                     rank_value(c), c))


def play_claim(play: Play) -> None:
    """Play out the rest of the hand along the claim's line; the other side plays its lowest cards."""
    if play.current.cards:
        plan = trick_plan(play)
        if plan is None:
            raise ValueError("the rest of the tricks aren't certain")
        while play.current.cards and not play.is_complete():
            seat = play.next_to_play
            play.play(plan[seat] if seat in plan else lowest(play))
    while not play.is_complete():
        line = claim_line(play)
        if line is None:
            raise ValueError("the rest of the tricks aren't certain")
        lead, follow = line
        leader = play.next_to_play
        for i in range(4):
            seat = play.next_to_play
            if i == 0:
                play.play(lead)
            elif follow is not None and seat == partner(leader):
                play.play(follow)
            else:
                play.play(lowest(play))
