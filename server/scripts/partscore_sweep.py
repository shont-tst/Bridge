"""Measure how much knowing the rubber score helps the bots' bidding (bidding/partscore.py).

Each deal gets a random rubber score (part scores below the line, who is vulnerable). The bots bid it twice: once
blind to the score, as at duplicate, and once knowing it. Where the auctions differ, both contracts are scored at
their double-dummy tricks the way the score values them: a contract that finishes a game earns the game bonus (300
not vulnerable, 500 vulnerable), any other made contract its trick points plus 50, as in Chicago. The side whose call
first changed gains or loses the difference in IMPs.
Run from server/:  python -m scripts.partscore_sweep DEALS [FIRST_SEED] [SHOW]
"""
import os
import random
import sys
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor

os.environ["BRIDGE_SOLVER_IN_PROCESS"] = "1"

from bridge.bidding.conventions import ALL_CONVENTIONS, make_engine  # noqa: E402
from bridge.bidding.partscore import Score  # noqa: E402
from bridge.core.auction import Auction, Contract  # noqa: E402
from bridge.core.board import is_vulnerable  # noqa: E402
from bridge.core.cards import SEATS, deal_random, side  # noqa: E402
from bridge.core.scoring import duplicate_score, imps, trick_score  # noqa: E402
from bridge.game.analysis import dd_summary  # noqa: E402

PART = [20, 30, 40, 40, 60, 60, 70, 80, 90]
_ENGINE = None


def engine():
    global _ENGINE
    if _ENGINE is None:
        _ENGINE = make_engine({c.id for c in ALL_CONVENTIONS if c.default_on})
    return _ENGINE


def random_score(rng: random.Random) -> Score:
    while True:
        ns = rng.choice(PART) if rng.random() < 0.5 else 0
        ew = rng.choice(PART) if rng.random() < 0.5 else 0
        if ns or ew:
            return Score(ns, ew, rng.choice(["None", "NS", "EW", "Both"]))


def value(c: Contract | None, tricks: int, score: Score) -> int:
    """The board's worth for N-S under this score."""
    if c is None:
        return 0
    vul = is_vulnerable(score.vulnerability, c.declarer)
    s = duplicate_score(c, tricks, vul)
    if tricks >= c.level + 6:
        below = trick_score(c.strain, c.level) * (1, 2, 4)[c.doubled]
        was_game = below >= 100
        now_game = below + score.below(c.declarer) >= 100
        if now_game and not was_game:
            s += (500 if vul else 300) - 50
    return s if side(c.declarer) == "NS" else -s


def bid(hands, dealer, score):
    eng = engine()
    a = Auction(dealer, [])
    calls = []
    while not a.is_complete():
        seat = a.next_to_call
        d = eng.choose(hands[seat], a, score)
        calls.append((seat, d.call, d.rule.name if d.rule else None, d.note))
        a.add(d.call)
    return calls, a.contract()


def one(seed):
    rng = random.Random(seed)
    hands = deal_random(rng)
    dealer = rng.choice(SEATS)
    score = random_score(rng)
    old_calls, old_c = bid(hands, dealer, None)
    new_calls, new_c = bid(hands, dealer, score)
    if [c[1] for c in old_calls] == [c[1] for c in new_calls]:
        return None
    dd = dd_summary(hands, score.vulnerability, dealer)
    t_old = dd["tricks"][old_c.strain][old_c.declarer] if old_c else 0
    t_new = dd["tricks"][new_c.strain][new_c.declarer] if new_c else 0
    i = next(i for i, (a, b) in enumerate(zip(old_calls, new_calls)) if a[1] != b[1])
    who = new_calls[i]
    sign = 1 if side(who[0]) == "NS" else -1
    gain = sign * imps(value(new_c, t_new, score) - value(old_c, t_old, score))
    note = who[3] or ""
    kind = "compete" if "competing" in note else "cheaper" if "no need" in note else "stop" if note else "knock-on"
    return {"seed": seed, "gain": gain, "kind": kind, "score": score.to_dict(), "dealer": dealer,
            "old": " ".join(c[1] for c in old_calls), "new": " ".join(c[1] for c in new_calls),
            "old_c": f"{old_c} ({t_old})" if old_c else "Pass", "new_c": f"{new_c} ({t_new})" if new_c else "Pass",
            "hands": "  ".join(f"{s}:{hands[s].to_pbn()}" for s in SEATS), "who": who[0]}


def main(n, first, show):
    with ProcessPoolExecutor(4) as ex:
        recs = [r for r in ex.map(one, range(first, first + n), chunksize=16) if r]
    by = defaultdict(list)
    for r in recs:
        by[r["kind"]].append(r["gain"])
    print(f"{n} deals, {len(recs)} auctions changed: better {sum(r['gain'] > 0 for r in recs)}, "
          f"worse {sum(r['gain'] < 0 for r in recs)}, net {sum(r['gain'] for r in recs):+d} IMPs")
    for k, g in sorted(by.items()):
        print(f"  {k:9s} x{len(g):4d}  net {sum(g):+5d}  better {sum(x > 0 for x in g)} worse {sum(x < 0 for x in g)}")
    for r in sorted(recs, key=lambda r: r["gain"])[:show]:
        print(f"\nseed {r['seed']} {r['kind']} {r['gain']:+d} score {r['score']} dlr {r['dealer']} changed by {r['who']}"
              f"\n  old {r['old']} -> {r['old_c']}\n  new {r['new']} -> {r['new_c']}\n  {r['hands']}")


if __name__ == "__main__":
    main(int(sys.argv[1]), int(sys.argv[2]) if len(sys.argv) > 2 else 1, int(sys.argv[3]) if len(sys.argv) > 3 else 6)
