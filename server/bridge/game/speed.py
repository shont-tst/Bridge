"""A fixed piece of bot thinking, timed, to tell whether this device or the server thinks faster.

The app runs it on the phone (in Play locally's engine) and asks the server for its own time on the same work
(GET /api/speed). Real waits differ from deal to deal and level to level, so they can't be compared; this is the same
work everywhere: the strongest bots play the first trick, the slowest part of a board, of a set deal (about a second on the server).
"""
from __future__ import annotations

import random
import time

from ..bidding.conventions import BY_ID, make_engine
from ..bots.player import BotPlayer
from ..core.cards import SEATS
from .table import PLAYING, Table

DEALS = (1,)  # the deal's seed: the bots bid it out and play it at level 10
CARDS = 4  # the first trick, the slowest of a board


def first_trick(seed: int) -> tuple[list[str], float]:
    """The cards the level 10 bots play to the first trick of the deal from this seed, and the seconds they took."""
    engine = make_engine({c.id for c in BY_ID.values() if c.default_on})
    table = Table(engine, 1, set(SEATS), BotPlayer(engine, level=10, seed=seed), rng=random.Random(seed))
    table.bot_claims = False
    while table.phase != PLAYING:
        table.bot_step()
    cards, spent = [], 0.0
    for _ in range(CARDS):
        started = time.perf_counter()
        cards.append(table.bot_step()["card"])
        spent += time.perf_counter() - started
    return cards, spent


def bench() -> float:
    """Seconds this device spends on the bots' first trick of the set deal (bidding not counted)."""
    return round(sum(first_trick(seed)[1] for seed in DEALS), 3)
