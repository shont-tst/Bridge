"""Sample full deals consistent with a BotView.

Constraints, strictest first:
  1. cards already seen (own hand, dummy, played cards) and voids shown in play;
  2. what each hidden hand's calls showed in the auction (HCP and suit-length
     ranges, from the bidding engine's own rule descriptions);
  3. what a hidden opening leader's lead said, by Standard leads (leads.py), and,
     at a table that plays signals, what each hidden defender's signals said (signals.py).
If the auction constraints can't be met in reasonable time (e.g. someone
misbid), they are relaxed step by step and finally dropped; the lead and signals go first.
"""
from __future__ import annotations

import random

from ..bidding.engine import BiddingEngine
from ..bidding.shows import HandInference
from ..core.cards import HCP_VALUE, SEATS, SUITS, full_deck
from . import leads, signals
from .view import BotView


def shown_voids(view: BotView) -> dict[str, set[str]]:
    voids: dict[str, set[str]] = {s: set() for s in SEATS}
    for _, cards in view.tricks:
        if not cards:
            continue
        led = cards[0][1][0]
        for seat, card in cards[1:]:
            if card[0] != led:
                voids[seat].add(led)
    return voids


def _fits(cards: list[str], inf: HandInference, slack_hcp: int, slack_len: int) -> bool:
    hcp = sum(HCP_VALUE.get(c[1], 0) for c in cards)
    if not (min(inf.fewest, inf.hcp[0]) - slack_hcp <= hcp <= inf.hcp[1] + slack_hcp):
        return False
    for s in SUITS:
        n = sum(1 for c in cards if c[0] == s)
        lo, hi = inf.lengths[s]
        if not (lo - slack_len <= n <= hi + slack_len):
            return False
    if inf.balanced and slack_len == 0:
        lens = sorted((sum(1 for c in cards if c[0] == s) for s in SUITS), reverse=True)
        if lens not in ([4, 3, 3, 3], [4, 4, 3, 2], [5, 3, 3, 2]):
            return False
    return True


SPOTS = "23456789"  # the small cards a player loses track of; tens and honors are remembered


def _recalls(view: BotView, what: str, forget: float) -> bool:
    """Whether the player deciding still remembers this (a card played, or a seat showing out). The answer is fixed
    for the board, so a bot that has lost track of a card stays wrong about it, as a person would."""
    board = "".join(c for _, c in view.tricks[0][1])  # the first trick names the board
    return random.Random(f"{view.controller}|{board}|{what}").random() >= forget


def misremembered(view: BotView, unknown: list[str], voids: dict[str, set[str]], forget: float,
                  rng: random.Random) -> tuple[list[str], dict[str, set[str]]]:
    """The unseen cards and shown voids as a player who has lost track of the side suits pictures them
    (what a club player gets wrong is keeping track of the non-trump suits, not a free ruff).

    Only earlier tricks, only suits other than trumps, and only small cards (2 to 9):
      - a small card that was played is thought to be still out, and a small unseen card to have gone instead (from
        the same suit: "is my 9 good yet?"; or from another side suit: the count of both suits is then off by one);
      - a hidden hand that showed out of a side suit is thought to perhaps still hold it.
    Trumps, tens and honors, and the trick in progress are always remembered. The number of unseen cards stays right,
    so the layouts can still be dealt and solved."""
    side = [s for s in SUITS if s != view.trump]
    visible = {view.controller} | ({view.dummy} if view.dummy_hand is not None else set())
    hidden = [s for s in SEATS if s not in visible]
    voids = {seat: {s for s in suits if s not in side or _recalls(view, f"void{seat}{s}", forget)}
             for seat, suits in voids.items()}
    pool, unseen = list(unknown), set(unknown)
    for _, cards in view.tricks[:-1]:
        for _, card in cards:
            if card[0] not in side or card[1] not in SPOTS or _recalls(view, card, forget):
                continue
            if all(card[0] in voids[seat] for seat in hidden):
                continue  # nobody could hold it: even a hazy player knows it has gone
            swaps = [c for c in pool if c in unseen and c[0] in side and c[1] in SPOTS]
            if not swaps:
                continue
            same = [c for c in swaps if c[0] == card[0]]
            # half the time it's only the rank that blurs; otherwise the suit too, and the count goes wrong
            gone = rng.choice(same if same and _recalls(view, f"suit{card}", 0.5) else swaps)
            pool[pool.index(gone)] = card
    return pool, voids


class Sampler:
    def __init__(self, view: BotView, engine: BiddingEngine | None, rng: random.Random,
                 use_inference: bool = True, forget: float = 0.0):
        self.view = view
        self.rng = rng
        known = set(view.own_hand) | set(view.all_played())
        if view.dummy_hand is not None:
            known |= set(view.dummy_hand)
        self.unknown = [c for c in full_deck() if c not in known]
        visible = {view.controller}
        if view.dummy_hand is not None:
            visible.add(view.dummy)
        self.hidden = [s for s in SEATS if s not in visible]
        self.need = {s: 13 - len(view.played_by(s)) for s in self.hidden}
        assert sum(self.need.values()) == len(self.unknown), "card accounting mismatch"
        self.voids = shown_voids(view)
        if forget > 0 and len(view.tricks) > 1:
            self.unknown, self.voids = misremembered(view, self.unknown, self.voids, forget, rng)
        self.played = {s: view.played_by(s) for s in SEATS}
        self.inference: dict[str, HandInference] = {}
        if engine is not None and use_inference:
            auction = view.auction()
            for s in self.hidden:
                self.inference[s] = engine.infer(auction, s)
        self.signals = signals.seen(view) if use_inference else []
        lead = leads.opening(view)
        self.leader = lead[0] if use_inference and lead and lead[0] in self.hidden else None

    def _order(self) -> list[str]:
        """Most constrained hidden seat first; the last seat takes what is left."""
        def width(seat):
            inf = self.inference.get(seat)
            return 99 if inf is None else inf.hcp[1] - inf.hcp[0]
        return sorted(self.hidden, key=width)

    def _fits_signals(self, seat: str, hand: list[str], use: bool) -> bool:
        if not use:
            return True
        if seat == self.leader and not leads.consistent(self.view, seat, hand):
            return False
        return not self.signals or signals.consistent(self.view, self.signals, seat, hand)

    def _deal_once(self, slack_hcp, slack_len, seat_tries: int = 40, use_signals: bool = False):
        """One deal of the unknown cards, drawing seat by seat with per-seat rejection."""
        pool = self.unknown[:]
        out: dict[str, list[str]] = {}
        order = self._order()
        for i, seat in enumerate(order):
            n = self.need[seat]
            eligible = [c for c in pool if c[0] not in self.voids[seat]]
            if len(eligible) < n:
                return None
            last = i == len(order) - 1
            for _ in range(1 if last else seat_tries):
                hand = pool[:] if last else self.rng.sample(eligible, n)
                if last and any(c[0] in self.voids[seat] for c in hand):
                    return None
                inf = self.inference.get(seat)
                if (slack_hcp is None or inf is None or _fits(hand + self.played[seat], inf, slack_hcp, slack_len)) \
                        and self._fits_signals(seat, hand, use_signals):
                    break
            else:
                return None
            if last and slack_hcp is not None and self.inference.get(seat) is not None and \
                    not _fits(hand + self.played[seat], self.inference[seat], slack_hcp, slack_len):
                return None
            if last and not self._fits_signals(seat, hand, use_signals):
                return None
            out[seat] = hand
            taken = set(hand)
            pool = [c for c in pool if c not in taken]
        return out

    def sample(self, n: int, max_tries: int = 400) -> list[dict[str, list[str]]]:
        """Return n deals: {seat: remaining cards} for every seat."""
        out = []
        steps = [(0, 0, True), (2, 1, True), (4, 2, True)] if self.signals or self.leader else []
        for slack_hcp, slack_len, use_signals in steps + [(0, 0, False), (2, 1, False), (4, 2, False),
                                                          (None, None, False)]:
            tries = 0
            while len(out) < n and tries < max_tries:
                tries += 1
                hands = self._deal_once(slack_hcp, slack_len, use_signals=use_signals)
                if hands is not None:
                    out.append(self._complete(hands))
            if len(out) >= n:
                break
        return out

    def _complete(self, hidden: dict[str, list[str]]) -> dict[str, list[str]]:
        full = {s: list(cards) for s, cards in hidden.items()}
        full[self.view.controller] = list(self.view.own_hand)
        if self.view.dummy_hand is not None:
            full[self.view.dummy] = list(self.view.dummy_hand)
        return full
