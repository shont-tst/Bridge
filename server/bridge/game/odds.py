"""Odds for the review: how often a card would have worked, judged only on what the player could see.

The double-dummy review knows where every card is. Here, at the moment a card was played, we deal many layouts of the
hidden cards that fit the auction and the play so far (the same sampler the bots use), solve each one, and count how
often each legal card still lets the player's side reach its target: the tricks it could have taken with all cards
seen (or, without that, making or beating the contract).
"""
from __future__ import annotations

import random

from endplay.types import Deal

from ..solver import solve_all_boards

from ..bidding.engine import BiddingEngine
from ..bots.card_play import _card_str, _need, _to_deal
from ..bots.sampler import Sampler
from ..bots.view import view_for
from ..core.auction import Auction, Contract
from ..core.cards import SEATS, Hand, rank_value, same_side, side
from ..core.play import Play

SAMPLES = 100
MORE = 200  # extra layouts when it's a close call: the best card within 2 x MARGIN of the one played
MAX_CARDS = 16  # cards worked out per board, people's first, so the review comes back in a few seconds
MARGIN = 10  # percentage points: a smaller gap between two cards may be sampling noise


def _tricks(per: dict[str, int], card: str) -> int:
    if card in per:
        return per[card]
    same = [x for x in per if x[0] == card[0]]  # DDS may leave out an equivalent card
    return per[min(same, key=lambda x: abs(rank_value(x) - rank_value(card)))] if same else 0


def best_card(pct: dict[str, int], played: str) -> tuple[str, bool]:
    """The best card on the odds, and whether it was clearly better than the one played."""
    best = max(pct, key=lambda c: (pct[c], c == played, -rank_value(c)))
    return best, best != played and pct[best] >= pct[played] + MARGIN


def card_odds(engine: BiddingEngine | None, hands: dict[str, Hand], dealer: str, vulnerability: str,
              calls: list[str], contract: Contract, play: list[tuple[str, str]], index: int,
              rng: random.Random, samples: int = SAMPLES, reach: int | None = None,
              hindsight: str | list[str] | None = None) -> dict | None:
    """For the card play[index]: how often the card played, and the best card on the odds, reach the target.

    The target is `reach` more tricks for the player's side: the review passes the most the side could still take with
    all cards seen, so the odds are for the trick the card lost. Without it, the target is the side's goal: making
    the contract for declarer's side, beating it for the defense. `hindsight` is the card, or cards, that were best with
    all cards seen; the one of them with the best odds comes back with its odds, so when the better bet would also
    have worked this time, the review names that card and doesn't set it against another."""
    p = Play.start(contract.declarer, contract.strain, hands)
    for _, card in play[:index]:
        p.play(card)
    seat, played = play[index]
    view = view_for(p, Auction(dealer, list(calls)), contract, vulnerability, seat, leads=False)  # the lead isn't read
    if len(view.legal) < 2:
        return None
    need = _need(view) if reach is None else reach
    made = {c: 0 for c in view.legal}
    n = 0

    def count(more: int) -> int:
        deals = Sampler(view, engine, rng).sample(more)
        for solved in solve_all_boards([_to_deal(view, d) for d in deals]) if deals else []:
            per = {_card_str(card): t for card, t in solved}
            for c in view.legal:
                made[c] += _tricks(per, c) >= need
        return len(deals)

    n += count(samples)
    if not n:
        return None
    pct = {c: round(100 * k / n) for c, k in made.items()}
    if 0 < max(pct.values()) - pct[played] < 2 * MARGIN:  # close to the line between Mistake and not: look again
        n += count(MORE)
        pct = {c: round(100 * k / n) for c, k in made.items()}
    best, better = best_card(pct, played)
    worked = [c for c in ([hindsight] if isinstance(hindsight, str) else hindsight or []) if c in pct]
    hindsight = max(worked, key=lambda c: (pct[c], c == best)) if worked else None
    return {"goal": "make" if same_side(seat, contract.declarer) else "beat", "samples": n,
            "tricks": p.tricks_won(side(seat)) + need if reach is not None else None,
            "played": pct[played], "best": best, "best_pct": pct[best], "better": better,
            "hindsight": hindsight, "hindsight_pct": pct[hindsight] if hindsight else None}


def odds_ahead(engine: BiddingEngine | None, hands: dict[str, Hand], dealer: str, vulnerability: str,
               calls: list[str], contract: Contract, play: list[tuple[str, str]], rng: random.Random) -> dict:
    """The review's odds for the last card in `play`, worked out while the board is still going, so the review has
    them when the board ends (odds should be ready, not worked out after). The position before the
    card is solved double dummy, just as the review does; only a card that cost a trick gets odds, the same ones
    `add_odds` would work out. Returns {"lost": tricks it cost, "odds": card_odds or None}."""
    from .review import _DENOM, _PLAYER, _tricks_for
    deal = Deal.from_pbn("N:" + " ".join(hands[s].to_pbn() for s in SEATS))
    deal.trump = _DENOM[contract.strain]
    deal.first = _PLAYER[SEATS[(SEATS.index(contract.declarer) + 1) % 4]]
    for _, card in play[:-1]:
        deal.play(card)
    solved = solve_all_boards([deal])
    per = {_card_str(c): t for c, t in solved[0]} if solved else {}
    best = max(per.values()) if per else 0
    lost = best - _tricks_for(per, play[-1][1])
    if lost <= 0:
        return {"lost": lost, "odds": None}
    best_cards = sorted((c for c, t in per.items() if t == best), key=lambda c: ("SHDC".index(c[0]), -rank_value(c)))
    return {"lost": lost, "odds": card_odds(engine, hands, dealer, vulnerability, calls, contract, play,
                                            len(play) - 1, rng, SAMPLES, best, best_cards)}


def add_odds(review: dict, engine: BiddingEngine | None, hands: dict[str, Hand], dealer: str,
             vulnerability: str, calls: list[str], contract: Contract, play: list[tuple[str, str]],
             people: set[str], rng: random.Random, run=lambda fn, *args: fn(*args), ready: dict | None = None) -> None:
    """Fill in `odds` on the cards that cost a trick double dummy, people's first and then the bots': how often each
    card would have taken the tricks the side could have had. The review lists a card only when its odds show a
    better choice: losing a trick to an unlucky layout is not a mistake.
    `ready` holds odds already worked out during the board (`odds_ahead`), by the card's place in the play; only the
    rest are worked out now. Each card goes through `run` on its own, so other work can use the solver between cards."""
    cards = (review.get("play") or {}).get("cards") or []
    costly = [i for i, c in enumerate(cards) if c["lost"] > 0]
    todo = sorted(costly, key=lambda i: cards[i]["by"] not in people)[:MAX_CARDS]
    ready = ready or {}
    for i in todo:
        if i in ready and ready[i]["lost"] == cards[i]["lost"]:
            odds = ready[i]["odds"]
        else:
            odds = run(card_odds, engine, hands, dealer, vulnerability, calls, contract, play, i, rng, SAMPLES,
                       cards[i].get("reach"), cards[i].get("best"))
        if odds:
            cards[i]["odds"] = odds
