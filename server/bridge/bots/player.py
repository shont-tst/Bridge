"""A bot seat: bids with the rule engine, plays with Monte Carlo + DDS."""
from __future__ import annotations

import random
from dataclasses import replace

from ..bidding.engine import BiddingEngine, Decision
from ..bidding.partscore import Score
from ..bidding.vul import ALL, RISKY, Vul
from ..core.auction import Auction
from ..core.cards import Hand
from .card_play import CardChoice, choose_card
from .difficulty import Difficulty, difficulty
from .view import BotView


SCORE_FROM = 6  # bot levels that bid with the rubber part score
COMPETE_FROM = 8  # ... and also compete lighter against the other side's cheap game
VUL_FROM = 6  # bot levels that bid with the vulnerability in mind (bidding/vul.py): the safe changes ...
VUL_RISKY_FROM = 8  # ... and also the riskier ones (lighter and sacrifices at favorable)


class BotPlayer:
    def __init__(self, engine: BiddingEngine, level: int = 6, seed: int | None = None):
        self.engine = engine
        self.diff: Difficulty = difficulty(level)
        self.rng = random.Random(seed)

    def set_level(self, level: int) -> None:
        self.diff = difficulty(level)

    def score_for(self, score: Score | None) -> Score | None:
        """How much of the rubber score this bot's level uses: none below level 6, stopping at game from 6,
        and competing lighter against a cheap game from 8 (see bidding/partscore.py)."""
        if score is None or self.diff.level < SCORE_FROM:
            return None
        return score if self.diff.level >= COMPETE_FROM else replace(score, compete=False)

    def vul_for(self, vulnerability: str | None) -> Vul | None:
        """How much of the vulnerability this bot's level uses: none below level 6, the safe changes from 6, and all
        of them from 8 (see bidding/vul.py)."""
        if vulnerability is None or self.diff.level < VUL_FROM:
            return None
        return Vul(vulnerability, ALL if self.diff.level >= VUL_RISKY_FROM else ALL - RISKY)

    def bid(self, hand: Hand, auction: Auction, score: Score | None = None,
            vulnerability: str | None = None) -> Decision:
        # The bidder sees only its own hand, the auction, who is vulnerable and (at rubber) the score.
        return self.engine.choose(hand, auction, self.score_for(score), self.vul_for(vulnerability))

    def play(self, view: BotView) -> CardChoice:
        return choose_card(view, self.engine, self.diff, self.rng)
