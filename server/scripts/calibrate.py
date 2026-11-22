"""Measure how many tricks each bot level loses, so a player's card play can be placed on the same 1 to 10 scale.

Four bots of one level bid and play random deals. Every card is checked against double-dummy (as in the post-hand
review), and the tricks given away are averaged per hand: as declarer (dummy's cards count to declarer), and per
defender. Writes bridge/bots/calibration.json. Run from server/:  python -m scripts.calibrate [deals per level]
"""
from __future__ import annotations

import json
import os
import random
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

os.environ["BRIDGE_SOLVER_IN_PROCESS"] = "1"  # each of this script's own worker processes calls DDS directly

from bridge.bidding.conventions import ALL_CONVENTIONS, make_engine  # noqa: E402
from bridge.bots.player import BotPlayer
from bridge.core.cards import SEATS, partner
from bridge.game.review import play_review
from bridge.game.table import DONE, Table

OUT = Path(__file__).resolve().parents[1] / "bridge" / "bots" / "calibration.json"
# the same numbers for the app's "How bot strength works" table (tests/test_stats.py checks the two agree)
WEB = Path(__file__).resolve().parents[2] / "web" / "src" / "botLevels.json"


def web_table(levels: dict) -> dict:
    """Tricks lost per hand by level as the app shows them: smoothed like the player's level, to two places."""
    from bridge.stats import smoothed
    dec = smoothed({int(k): v["declaring"] for k, v in levels.items()})
    dfn = smoothed({int(k): v["defending"] for k, v in levels.items()})
    return {str(lv): {"declaring": round(dec[lv], 2), "defending": round(dfn[lv], 2)} for lv in sorted(dec)}


def one_level(args: tuple[int, int]) -> dict:
    level, deals = args
    engine = make_engine({c.id for c in ALL_CONVENTIONS if c.default_on})
    rng = random.Random(1000 + level)
    declaring, defending = [], []
    for n in range(deals):
        bot = BotPlayer(engine, level, seed=rng.random())
        t = Table(engine, n + 1, set(SEATS), bot, rng=rng)
        while t.phase != DONE:
            t.bot_step()
        if not t.contract:
            continue
        r = play_review(t.hands, t.contract, t.play.played_cards())
        d = t.contract.declarer
        declaring.append(r["lost_by"][d] + r["lost_by"][partner(d)])
        defenders = [s for s in SEATS if s not in (d, partner(d))]
        defending += [r["lost_by"][s] for s in defenders]
    return {"level": level, "declaring": sum(declaring) / max(1, len(declaring)),
            "defending": sum(defending) / max(1, len(defending)), "hands": len(declaring)}


def main() -> None:
    deals = int(sys.argv[1]) if len(sys.argv) > 1 else 150
    start = time.time()
    with ProcessPoolExecutor() as pool:
        rows = list(pool.map(one_level, [(lv, deals) for lv in range(1, 11)]))
    table = {str(r["level"]): {"declaring": round(r["declaring"], 3), "defending": round(r["defending"], 3),
                               "hands": r["hands"]} for r in rows}
    OUT.write_text(json.dumps({"deals_per_level": deals, "levels": table}, indent=1) + "\n")
    WEB.write_text(json.dumps(web_table(table), indent=1) + "\n")
    print(json.dumps(table, indent=1), f"\n{time.time() - start:.0f}s")


if __name__ == "__main__":
    main()
