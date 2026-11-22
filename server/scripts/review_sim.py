"""Check the end-of-board review's lost-trick suggestions by simulation.

Bots bid and play random boards. For every card the review says cost a trick:
  A. swap in the review's hindsight card (and, for Mistakes, the "better bet"), let bots play out the rest,
     and compare the side's tricks with replaying the card actually played the same way;
  B. check whether the better bet actually reaches the target in the real deal.
Separately, C. calibration: at random positions, the % the odds give each legal card vs whether that card
reaches the target in the real deal (double dummy).
Run from server/:  python -m scripts.review_sim BOARDS LEVEL OUT.jsonl [FIRST_SEED]   (about 1 minute per board on 4 cores)
Then:              python -m scripts.review_sim report OUT.jsonl
"""
import json
import os
import random
import sys
from statistics import mean
from concurrent.futures import ProcessPoolExecutor

os.environ["BRIDGE_SOLVER_IN_PROCESS"] = "1"

from endplay.types import Deal  # noqa: E402

from bridge.bidding.conventions import ALL_CONVENTIONS, make_engine  # noqa: E402
from bridge.bots.card_play import _card_str, _need, _to_deal  # noqa: E402
from bridge.bots.sampler import Sampler  # noqa: E402
from bridge.game.odds import _tricks  # noqa: E402
from bridge.game.review import _DENOM, _PLAYER  # noqa: E402
from bridge.solver import solve_all_boards  # noqa: E402
from bridge.bots.card_play import choose_card  # noqa: E402
from bridge.bots.difficulty import difficulty  # noqa: E402
from bridge.bots.player import BotPlayer  # noqa: E402
from bridge.bots.view import view_for  # noqa: E402
from bridge.core.auction import Auction  # noqa: E402
from bridge.core.cards import SEATS, side  # noqa: E402
from bridge.core.play import Play  # noqa: E402
from bridge.game.odds import SAMPLES, card_odds  # noqa: E402
from bridge.game.review import play_review  # noqa: E402
from bridge.game.table import DONE, Table  # noqa: E402

PLAYOUTS = 2
FINISH_LEVEL = 8  # how well the bots play out the rest after the swap


def playout(t, play, index, card, rng, level):
    """Side-to-play's total tricks when `card` replaces play[index] and bots finish the hand."""
    p = Play.start(t.contract.declarer, t.contract.strain, t.hands)
    for _, c in play[:index]:
        p.play(c)
    seat = p.next_to_play
    p.play(card)
    diff = difficulty(level)
    auction = Auction(t.dealer, list(t.auction.calls))
    while not p.is_complete():
        s = p.next_to_play
        v = view_for(p, auction, t.contract, t.vulnerability, s)
        p.play(choose_card(v, t.engine, diff, rng).card)
    return p.tricks_won(side(seat))


def all_pcts(engine, t, calls, play, index, rng, need):
    p = Play.start(t.contract.declarer, t.contract.strain, t.hands)
    for _, card in play[:index]:
        p.play(card)
    seat = play[index][0]
    view = view_for(p, Auction(t.dealer, list(calls)), t.contract, t.vulnerability, seat)
    if len(view.legal) < 2:
        return None
    deals = Sampler(view, engine, rng).sample(SAMPLES)
    if not deals:
        return None
    made = {c: 0 for c in view.legal}
    for solved in solve_all_boards([_to_deal(view, d) for d in deals]):
        per = {_card_str(card): v for card, v in solved}
        for c in view.legal:
            made[c] += _tricks(per, c) >= need
    return {c: 100 * k / len(deals) for c, k in made.items()}


def one_board(args):
    seed, level = args
    engine = make_engine({c.id for c in ALL_CONVENTIONS if c.default_on})
    rng = random.Random(seed)
    bot = BotPlayer(engine, level, seed=rng.random())
    t = Table(engine, seed % 16 + 1, set(SEATS), bot, rng=rng)
    t.engine = engine
    while t.phase != DONE:
        t.bot_step()
    if not t.contract:
        return []
    play = t.play.played_cards()
    calls = list(t.auction.calls)
    review = play_review(t.hands, t.contract, play, set())
    cards = review["cards"]
    out = []
    final = {s: t.play.tricks_won(side(s)) for s in "NE"}
    for i, c in enumerate(cards):
        if c["lost"] <= 0:
            continue
        hind = c["best"][0]
        o = card_odds(engine, t.hands, t.dealer, t.vulnerability, calls, t.contract, play, i, rng, SAMPLES,
                      c["reach"], hind)
        if not o:
            continue
        p = Play.start(t.contract.declarer, t.contract.strain, t.hands)
        for _, x in play[:i]:
            p.play(x)
        before = p.tricks_won(side(c["seat"]))
        rec = {"seed": seed, "i": i, "seat": c["seat"], "played": c["card"], "lost": c["lost"],
               "reach": c["reach"], "before": before, "dd_best": c["best"], "final": final[side(c["seat"])[0]],
               "odds": o, "mistake": o["better"]}
        # A: bots finish after the swap, vs after the card played
        rec["bot_played"] = [playout(t, play, i, c["card"], rng, FINISH_LEVEL) for _ in range(PLAYOUTS)]
        rec["bot_hind"] = [playout(t, play, i, hind, rng, FINISH_LEVEL) for _ in range(PLAYOUTS)]
        if o["better"] and o["best"] != hind:
            rec["bot_best"] = [playout(t, play, i, o["best"], rng, FINISH_LEVEL) for _ in range(PLAYOUTS)]
        # B: does the better bet reach the target in this deal (double dummy)?
        rec["best_in_dd_best"] = o["best"] in c["best"]
        out.append(rec)
    # C: calibration at two random positions with 2+ legal cards
    for i in rng.sample(range(len(play)), min(4, len(play))):
        c = cards[i]
        p0 = Play.start(t.contract.declarer, t.contract.strain, t.hands)
        for _, x in play[:i]:
            p0.play(x)
        goal = _need(view_for(p0, Auction(t.dealer, calls), t.contract, t.vulnerability, play[i][0]))
        pcts = all_pcts(engine, t, calls, play, i, rng, goal)
        if not pcts:
            continue
        # actual DD tricks for every legal card at this position
        p = Play.start(t.contract.declarer, t.contract.strain, t.hands)
        for _, x in play[:i]:
            p.play(x)
        legal = p.legal_cards()
        pbn = "N:" + " ".join(t.hands[s].to_pbn() for s in SEATS)
        deal = Deal.from_pbn(pbn)
        deal.trump = _DENOM[t.contract.strain]
        deal.first = _PLAYER[SEATS[(SEATS.index(t.contract.declarer) + 1) % 4]]
        for _, x in play[:i]:
            deal.play(x)
        per = {_card_str(k): v for k, v in solve_all_boards([deal])[0]}
        out.append({"calib": True, "seed": seed, "i": i, "pcts": pcts, "reach": c["reach"], "goal": goal,
                    "actual": {x: per.get(x, 0) >= goal for x in legal}})
    return out


def report(paths):
    recs = [json.loads(line) for p in paths for line in open(p)]
    flag = [r for r in recs if not r.get("calib")]
    cal = [r for r in recs if r.get("calib")]
    mis = [r for r in flag if r["mistake"]]
    unl = [r for r in flag if not r["mistake"]]
    print(f"boards {len({r['seed'] for r in recs})}, flagged cards {len(flag)}: Mistake {len(mis)}, Unlucky {len(unl)}")


    def gain(r, key):
        return mean(r[key]) - mean(r["bot_played"])


    for name, rs in (("all", flag), ("Mistake", mis), ("Unlucky", unl)):
        if not rs:
            continue
        g = [gain(r, "bot_hind") for r in rs]
        print(f"\n{name}: hindsight card, bots finish: avg gain {mean(g):+.2f} tricks (review claims {mean(r['lost'] for r in rs):.2f})")
        print(f"  gained >=1/2 trick: {sum(x >= 0.5 for x in g) / len(g):.0%}, no change: {sum(abs(x) < 0.5 for x in g) / len(g):.0%},"
              f" worse: {sum(x <= -0.5 for x in g) / len(g):.0%}")
        reached = [mean(x >= r["before"] + r["reach"] for x in r["bot_hind"]) for r in rs]
        print(f"  bots reach the review's trick total with the hindsight card: {mean(reached):.0%};"
              f" with the card played: {mean(mean(x >= r['before'] + r['reach'] for x in r['bot_played']) for r in rs):.0%}")

    if mis:
        b = [r for r in mis]
        gb = [gain(r, "bot_best" if "bot_best" in r else "bot_hind") for r in b]
        print(f"\nMistake 'better bet' card, bots finish: avg gain {mean(gb):+.2f}; gained {sum(x >= .5 for x in gb) / len(gb):.0%},"
              f" worse {sum(x <= -.5 for x in gb) / len(gb):.0%}")
        print(f"  better bet also DD-best in this deal: {mean(r['best_in_dd_best'] for r in b):.0%};"
              f" claimed avg {mean(r['odds']['best_pct'] for r in b):.0f}% vs played {mean(r['odds']['played'] for r in b):.0f}%")
        odd = [r for r in b if r["odds"]["best"] != r["odds"]["hindsight"] and r["best_in_dd_best"]]
        print(f"  wording: 'X would have worked this time, but the better bet was Y' while Y also worked: {len(odd)} of {len(b)}")
    un_hi = [r for r in unl if r["odds"]["played"] - (r["odds"]["hindsight_pct"] or 0) >= 10]
    print(f"\nUnlucky where the card played was the clearly better bet: {len(un_hi)} of {len(unl)}")
    lowpct = [r for r in unl if r["odds"]["played"] < 20]
    print(f"Unlucky with played% < 20 (everything looked bad): {len(lowpct)}")

    # calibration
    bins = {}
    for r in cal:
        vals = set(r["pcts"].values())
        if vals <= {0.0, 100.0} and len(vals) == 1:
            continue
        for c, p in r["pcts"].items():
            k = min(9, int(p // 10))
            bins.setdefault(k, []).append(r["actual"][c])
    print("\nCalibration (cards at random positions where the cards differ):")
    for k in sorted(bins):
        v = bins[k]
        print(f"  odds {k * 10:3d}-{k * 10 + 9 if k < 9 else 100}%: actually reached {mean(v):.0%}  (n={len(v)})")


if __name__ == "__main__":
    if sys.argv[1] == "report":
        report(sys.argv[2:])
        sys.exit()
    n, level, path = int(sys.argv[1]), int(sys.argv[2]), sys.argv[3]
    start = int(sys.argv[4]) if len(sys.argv) > 4 else 0
    with ProcessPoolExecutor(4) as pool, open(path, "a") as f:
        for recs in pool.map(one_board, [(start + k, level) for k in range(n)]):
            for r in recs:
                f.write(json.dumps(r) + "\n")
            f.flush()
