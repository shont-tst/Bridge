"""GIB-style Monte Carlo card play: sample deals consistent with what the bot
can see, solve each double-dummy with DDS, and play the card with the best
average outcome (softened by the difficulty settings)."""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

from ..solver import solve_all_boards
from endplay.types import Deal, Denom, Player

from ..bidding.engine import BiddingEngine
from ..core.cards import RANKS, rank_value, same_side
from .difficulty import Difficulty
from . import leads, signals
from .sampler import Sampler
from .view import BotView

_DENOM = {"S": Denom.spades, "H": Denom.hearts, "D": Denom.diamonds, "C": Denom.clubs,
          "N": Denom.nt}
_PLAYER = {"N": Player.north, "E": Player.east, "S": Player.south, "W": Player.west}
_SUIT_CHAR = {Denom.spades: "S", Denom.hearts: "H", Denom.diamonds: "D", Denom.clubs: "C"}


def _card_str(card) -> str:
    rank = card.rank.name[1]  # Rank.RA -> "A", Rank.RT -> "T"
    return _SUIT_CHAR[card.suit] + rank


@dataclass
class CardChoice:
    card: str
    scores: dict[str, float]  # average utility per legal card
    samples: int
    reason: str
    made: dict[str, int] = field(default_factory=dict)  # layouts in which each card still reaches the side's goal
    layouts: dict[str, list[float]] = field(default_factory=dict)  # each card's tricks (+ goal bonus), layout by layout
    signal: dict | None = None  # what the card told partner, at a table that plays signals (signals.describe)
    lead: str | None = None  # at the opening lead, the Standard leads rule the card follows (leads.WORDS)


def _signal(view: BotView, choice: CardChoice) -> CardChoice:
    """Among the cards exactly as good as the one chosen on every layout, the one that signals (signals.pick)."""
    if not view.signals or not choice.layouts:
        return choice
    equal = [c for c in choice.layouts if choice.layouts[c] == choice.layouts[choice.card]]
    card, signal = signals.pick(view, choice.card, equal)
    choice.card, choice.signal = card, signal
    return choice


def _to_deal(view: BotView, hands: dict[str, list[str]]) -> Deal:
    """Build an endplay Deal positioned at the current point of play."""
    leader, cards = view.current_trick
    full = {s: list(h) for s, h in hands.items()}
    for seat, card in cards:  # put the current trick's cards back, then replay them
        full[seat].append(card)

    def pbn_hand(cs):
        return ".".join("".join(c[1] for c in sorted((c for c in cs if c[0] == s),
                                                      key=rank_value, reverse=True))
                        for s in "SHDC")
    pbn = "N:" + " ".join(pbn_hand(full[s]) for s in "NESW")
    deal = Deal.from_pbn(pbn)
    deal.trump = _DENOM[view.trump]
    deal.first = _PLAYER[leader]
    for _, card in cards:
        deal.play(card)
    return deal


def _need(view: BotView) -> int:
    """Tricks the side to play still needs from here to achieve its goal."""
    level = view.contract.level
    decl_side_target = level + 6
    won_decl = 0
    won_def = 0
    trump = view.trump
    for leader, cards in view.tricks:
        if len(cards) < 4:
            continue
        lead = cards[0][1][0]

        def strength(card):
            if trump != "N" and card[0] == trump:
                return 100 + rank_value(card)
            return rank_value(card) if card[0] == lead else 0
        winner = max(cards, key=lambda sc: strength(sc[1]))[0]
        if same_side(winner, view.declarer):
            won_decl += 1
        else:
            won_def += 1
    if same_side(view.seat, view.declarer):
        return decl_side_target - won_decl
    return (14 - decl_side_target) - won_def


def choose_card(view: BotView, engine: BiddingEngine | None, diff: Difficulty,
                rng: random.Random | None = None) -> CardChoice:
    choice = _choose(view, engine, diff, rng or random.Random())
    if leads.is_opening_lead(view) and view.seat == view.controller:
        choice.lead = leads.kind(view, choice.card)
    return choice


def _choose(view: BotView, engine: BiddingEngine | None, diff: Difficulty, rng: random.Random) -> CardChoice:
    # at the opening lead, the solver picks the suit and Standard leads the card in it (leads.py)
    legal = leads.candidates(view) if leads.is_opening_lead(view) else list(view.legal)
    if len(legal) == 1:
        return CardChoice(legal[0], {legal[0]: 0.0}, 0, "only card")
    if diff.blunder and rng.random() < diff.blunder:
        c = rng.choice(legal)
        return CardChoice(c, {}, 0, "blunder")

    sampler = Sampler(view, engine, rng, use_inference=diff.inference, forget=diff.forget)
    deals = sampler.sample(diff.samples)
    if len(deals) < diff.samples and diff.forget:  # what it misremembers can't be dealt: it thinks again
        deals = Sampler(view, engine, rng, use_inference=diff.inference).sample(diff.samples)
    if not deals:
        c = min(legal, key=rank_value)
        return CardChoice(c, {}, 0, "no consistent deal found")

    boards = [_to_deal(view, d) for d in deals]
    results = solve_all_boards(boards)
    need = _need(view)
    per_layout = {c: [] for c in legal}  # tricks plus the goal bonus, layout by layout
    made = {c: 0 for c in legal}
    for solved in results:
        per = {_card_str(card): tricks for card, tricks in solved}
        for c in legal:
            if c in per:
                t = per[c]
            else:  # DDS may omit cards equivalent to one it listed: use the nearest in suit
                same = [x for x in per if x[0] == c[0]]
                t = per[min(same, key=lambda x: abs(rank_value(x) - rank_value(c)))] if same \
                    else 0
            per_layout[c].append(t + (1.0 if t >= need else 0.0))
            made[c] += t >= need
    n = len(results)
    scores = {c: sum(per_layout[c]) / n for c in legal}

    if diff.temperature <= 0:
        best = max(scores.values())
        top = [c for c in legal if scores[c] >= best - 1e-9]
        card = min(top, key=lambda c: (rank_value(c), RANKS.index(c[1])))
        return _signal(view, CardChoice(card, scores, n, "best average", made, per_layout))
    options = _options(legal, per_layout, prune=rng.random() < diff.notice) if diff.group else legal
    m = max(scores[o] for o in options)
    weights = [math.exp((scores[o] - m) / diff.temperature) for o in options]
    card = rng.choices(options, weights=weights)[0]
    choice = CardChoice(card, scores, n, "softmax", made, per_layout)
    return _signal(view, choice) if diff.group else choice


def top_two_gap(choice: CardChoice) -> int | None:
    """Percentage points between how often the best card reaches the goal and how often the next real choice does
    (cards that do the same in every layout count as one), or None when there's only one real choice."""
    if not choice.samples or not choice.layouts:
        return None
    seen: dict[tuple, str] = {}
    for c in choice.layouts:
        seen.setdefault(tuple(choice.layouts[c]), c)
    pct = sorted((100 * choice.made.get(c, 0) / choice.samples for c in seen.values()), reverse=True)
    return round(pct[0] - pct[1]) if len(pct) > 1 else None


def merge(a: CardChoice, b: CardChoice, view: BotView | None = None) -> CardChoice:
    """Two runs of the strongest bot on the same position as one run over all their layouts."""
    n = a.samples + b.samples
    layouts = {c: a.layouts.get(c, []) + b.layouts.get(c, []) for c in a.scores}
    scores = {c: sum(v) / n for c, v in layouts.items()}
    made = {c: a.made.get(c, 0) + b.made.get(c, 0) for c in a.scores}
    best = max(scores.values())
    top = [c for c in scores if scores[c] >= best - 1e-9]
    card = min(top, key=lambda c: (rank_value(c), RANKS.index(c[1])))
    merged = CardChoice(card, scores, n, a.reason, made, layouts)
    merged.lead = a.lead if card == a.card else b.lead if card == b.card else None
    return _signal(view, merged) if view is not None else merged


def _options(legal: list[str], per_layout: dict[str, list[float]], prune: bool) -> list[str]:
    """The real choices a softened (lower level) bot picks among.

    Cards of one suit that do exactly the same in every layout are one choice, played with the lowest, so a hand
    with six small diamonds isn't six times as likely to discard one. With `prune`, a choice that another does at
    least as well as in every layout, and better in some, is dropped: the free ruff, the sure winner. A lower level
    still errs, but only between plans that each have something going for them. Lower levels prune only some of the time
    (`notice`), and the lowest pick card by card, so they still forget to ruff now and then."""
    groups: dict[tuple, str] = {}
    for c in sorted(legal, key=rank_value):
        groups.setdefault((c[0], tuple(per_layout[c])), c)
    options = list(groups.values())
    if not prune:
        return options

    def beats(a: str, b: str) -> bool:
        pa, pb = per_layout[a], per_layout[b]
        return all(x >= y for x, y in zip(pa, pb)) and any(x > y for x, y in zip(pa, pb))
    return [o for o in options if not any(beats(p, o) for p in options if p != o)]
