"""Signals sweep: do bot defenders do better when the table plays signals?

Each deal is bid by the engine and played out by four bots of one strength level, once with no signals and once
with each method, from the same seed. Declarer's bots read the defenders' signals too, as at a real table. Prints the
defenders' average tricks for each, how many signals were given, and deals where the result changed.
Run from server/:
    python -m scripts.signals_sweep [DEALS=100] [LEVEL=8] [PROCESSES=4]
"""
from __future__ import annotations

import os
import random
import sys
from multiprocessing import Pool

os.environ.setdefault("BRIDGE_SOLVER_IN_PROCESS", "1")

from bridge.bidding.conventions import make_engine  # noqa: E402
from bridge.bots.player import BotPlayer  # noqa: E402
from bridge.bots.view import view_for  # noqa: E402
from bridge.core.auction import Auction  # noqa: E402
from bridge.core.board import vulnerability_for  # noqa: E402
from bridge.core.cards import SEATS, deal_random, same_side  # noqa: E402
from bridge.core.play import Play  # noqa: E402

METHODS = (None, "standard", "upside")
ARMS = METHODS + ("off again",)  # no signals with other random choices: how much results move by chance alone


def one(args):
    seed, level = args
    engine = make_engine()
    hands = deal_random(random.Random(seed))
    a = Auction(SEATS[seed % 4])
    while not a.is_complete():
        a.add(engine.choose(hands[a.next_to_call], a).call)
    ct = a.contract()
    if ct is None:
        return None
    out = {}
    for arm in ARMS:
        method = None if arm == "off again" else arm
        bot = BotPlayer(engine, level, seed=seed + (10**6 if arm == "off again" else 0))
        p = Play.start(ct.declarer, ct.strain, hands)
        given = 0
        while not p.is_complete():
            seat = p.next_to_play
            choice = bot.play(view_for(p, a, ct, vulnerability_for(seed), seat, method))
            given += choice.signal is not None
            p.play(choice.card)
        defense = sum(1 for t in p.tricks if not same_side(t.winner(p.trump), ct.declarer))
        out[arm] = (defense, given)
    return seed, str(ct.level) + ct.strain + " by " + ct.declarer, out


def main():
    deals = int(sys.argv[1]) if len(sys.argv) > 1 else 100
    level = int(sys.argv[2]) if len(sys.argv) > 2 else 8
    procs = int(sys.argv[3]) if len(sys.argv) > 3 else 4
    with Pool(procs) as pool:
        rows = [r for r in pool.map(one, [(s, level) for s in range(1, deals + 1)]) if r]
    print(f"{len(rows)} played deals, bots at level {level}")
    for m in ARMS:
        tricks = sum(r[2][m][0] for r in rows) / len(rows)
        sig = sum(r[2][m][1] for r in rows) / len(rows)
        print(f"  {m or 'off':9} defenders' tricks {tricks:.3f}   signals given per deal {sig:.1f}")
    for m in ARMS[1:]:
        better = sum(r[2][m][0] > r[2][None][0] for r in rows)
        worse = sum(r[2][m][0] < r[2][None][0] for r in rows)
        print(f"  {m}: defense better on {better} deals, worse on {worse}")


if __name__ == "__main__":
    main()
