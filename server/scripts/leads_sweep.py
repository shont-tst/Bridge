"""Opening leads sweep: do bot defenders do better when the table plays Standard leads?

Each deal is bid by the engine and played out by four bots of one strength level, once with Opening leads off (the
solver picks any card) and once on (Standard leads, read by partner and declarer), from the same seed. Prints the
defenders' average tricks for each, and on how many deals the result changed.
Run from server/:
    python -m scripts.leads_sweep [DEALS=100] [LEVEL=8] [PROCESSES=4]
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

ARMS = ("off", "on", "off again")  # off again: other random choices, to show how much results move by chance alone


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
        bot = BotPlayer(engine, level, seed=seed + (10**6 if arm == "off again" else 0))
        p = Play.start(ct.declarer, ct.strain, hands)
        while not p.is_complete():
            seat = p.next_to_play
            choice = bot.play(view_for(p, a, ct, vulnerability_for(seed), seat, leads=arm == "on"))
            p.play(choice.card)
        defense = sum(1 for t in p.tricks if not same_side(t.winner(p.trump), ct.declarer))
        out[arm] = (defense, p.tricks[0].cards[0][1])
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
        print(f"  {m:9} defenders' tricks {tricks:.3f}")
    for m in ARMS[1:]:
        better = sum(r[2][m][0] > r[2]["off"][0] for r in rows)
        worse = sum(r[2][m][0] < r[2]["off"][0] for r in rows)
        led = sum(r[2][m][1] != r[2]["off"][1] for r in rows)
        print(f"  {m}: defense better on {better} deals, worse on {worse}; another opening lead on {led}")


if __name__ == "__main__":
    main()
