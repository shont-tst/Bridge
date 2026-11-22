"""Sweep the bidding engine over many random deals and flag auctions that land far from double-dummy par.

Bots bid every seat (bidding is the same at every level). For each deal the double-dummy table and par are worked
out; the final contract is scored at its double-dummy tricks and compared with par in IMPs. Boards that lose a lot are
tagged (missed game, missed slam, overbid, big penalty, passed out, wrong strain) and saved with each call's rule.
Run from server/:  python -m scripts.bidding_sweep DEALS OUT.jsonl [FIRST_SEED] [all]   ("all" turns every convention on)
Then:              python -m scripts.bidding_sweep report OUT.jsonl [CATEGORY]
Before/after:      python -m scripts.bidding_sweep compare OLD.jsonl NEW.jsonl   (same seeds, e.g. after a rule change)
"""
import json
import os
import random
import sys
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor

os.environ["BRIDGE_SOLVER_IN_PROCESS"] = "1"

from bridge.bidding.conventions import ALL_CONVENTIONS, make_engine  # noqa: E402
from bridge.core.auction import Auction, Contract  # noqa: E402
from bridge.core.board import dealer_for, is_vulnerable, vulnerability_for  # noqa: E402
from bridge.core.cards import SEATS, deal_random, partner, side  # noqa: E402
from bridge.core.scoring import duplicate_score, imps  # noqa: E402
from bridge.game.analysis import dd_summary  # noqa: E402

FLAG_IMPS = 6  # a board is flagged when the side at fault loses at least this many IMPs against par
GAME = {"N": 3, "S": 4, "H": 4, "D": 5, "C": 5}
_ENGINE = None


def engine(all_on: bool):
    global _ENGINE
    if _ENGINE is None:
        _ENGINE = make_engine({c.id for c in ALL_CONVENTIONS if all_on or c.default_on})
    return _ENGINE


def best_for(dd, s: str, vul: str):
    """The best undoubled contract side `s` can make double dummy: (score, level, strain, seat), opponents silent."""
    best = (0, 0, "", "")
    for strain, by_seat in dd["tricks"].items():
        seat = max((x for x in SEATS if side(x) == s), key=lambda x: by_seat[x])
        t = by_seat[seat]
        for level in range(1, t - 5):
            sc = duplicate_score(Contract(level, strain, seat), t, is_vulnerable(vul, seat))
            if sc > best[0]:
                best = (sc, level, strain, seat)
    return best


def fit_len(hands, s: str) -> int:
    """Longest combined suit length of side `s`."""
    a, b = [x for x in SEATS if side(x) == s]
    return max(hands[a].length(x) + hands[b].length(x) for x in "SHDC")


def category(c, tricks, sc, s, hcp, fit, best_level, best_strain) -> str:
    """Why side `s` lost against par. Values-based tests keep double-dummy flukes out of the bidding categories."""
    mine = c is not None and side(c.declarer) == s
    down = mine and tricks < c.level + 6
    if c is None:
        return "passed out" if hcp >= 21 else "noise"
    if down and c.doubled and -sc >= 500:
        return "big penalty"
    if down and c.level >= 6 and hcp <= 30:
        return "overbid"
    if down and c.level >= GAME[c.strain] and c.level < 6 and hcp <= 22 and fit < 9:
        return "overbid"
    if down and tricks <= c.level + 3:
        return "overbid"
    if down and c.level >= GAME[c.strain] and best_level >= GAME.get(best_strain, 9) and hcp >= 25:
        return "wrong strain"
    if best_level >= 6 and hcp >= 33 and (not mine or c.level < 6):
        return "missed slam"
    if best_level >= GAME.get(best_strain, 9) and (hcp >= 26 or (hcp >= 24 and fit >= 9)) and \
            (not mine or c.level < GAME[c.strain]):
        return "missed game" if mine else "missed game (they played)"
    return "noise"


def sequence(calls, s: str) -> str:
    """The auction from side `s`'s view: our calls, theirs in brackets, trailing passes dropped."""
    out = [x["call"] if side(x["seat"]) == s else f"({x['call']})" for x in calls]
    while out and out[-1] in ("P", "(P)"):
        out.pop()
    while out and out[0] in ("P", "(P)"):
        out.pop(0)
    return " ".join(out)


def one(args):
    seed, all_on = args
    eng = engine(all_on)
    board = seed % 16 + 1
    dealer, vul = dealer_for(board), vulnerability_for(board)
    hands = deal_random(random.Random(seed))
    auction = Auction(dealer, [])
    calls = []
    while not auction.is_complete():
        seat = auction.next_to_call
        d = eng.choose(hands[seat], auction, vul=vul)
        calls.append({"seat": seat, "call": d.call, "rule": d.rule.name if d.rule else None,
                      "module": d.rule.module if d.rule else None})
        auction.add(d.call)
    dd = dd_summary(hands, vul, dealer)
    c = auction.contract()
    hcp = {s: hands[s].hcp for s in SEATS}
    side_hcp = {"NS": hcp["N"] + hcp["S"], "EW": hcp["E"] + hcp["W"]}
    if c:
        tricks = dd["tricks"][c.strain][c.declarer]
        sc = duplicate_score(c, tricks, is_vulnerable(vul, c.declarer))
        score_ns = sc if side(c.declarer) == "NS" else -sc
    else:
        tricks, score_ns = None, 0
    par = dd["par_score_ns"]
    loss_ns = imps(score_ns - par)  # + means NS gained against par
    rec = {"seed": seed, "board": board, "dealer": dealer, "vul": vul, "all": all_on,
           "hands": {s: hands[s].to_pbn() for s in SEATS}, "hcp": hcp, "calls": calls,
           "contract": str(c) if c else "Pass", "dd_tricks": tricks, "score_ns": score_ns, "par_ns": par,
           "par": dd["par_contracts"], "imps_ns": loss_ns, "flags": []}
    for s in ("NS", "EW"):
        sign = 1 if s == "NS" else -1
        lost = -loss_ns * sign
        if lost < FLAG_IMPS:
            continue
        best_sc, best_level, best_strain, best_seat = best_for(dd, s, vul)
        rec["flags"].append({"side": s, "imps": lost, "side_hcp": side_hcp[s], "fit": fit_len(hands, s),
                             "best": f"{best_level}{best_strain} by {best_seat}" if best_level else "-",
                             "cat": category(c, tricks, sc if c else 0, s, side_hcp[s], fit_len(hands, s),
                                             best_level, best_strain),
                             "seq": sequence(calls, s)})
    return rec


def run(n, out, first, all_on):
    with ProcessPoolExecutor(4) as ex, open(out, "w") as f:
        for i, rec in enumerate(ex.map(one, [(s, all_on) for s in range(first, first + n)], chunksize=8)):
            f.write(json.dumps(rec) + "\n")
            if i % 250 == 0:
                print(i, flush=True)


def fmt_auction(r):
    return " ".join(x["call"] for x in r["calls"])


def report(path, only=None):
    recs = [json.loads(line) for line in open(path)]
    flags = [(r, f) for r in recs for f in r["flags"]]
    print(f"{len(recs)} deals, {len(flags)} flags, mean |IMPs vs par| "
          f"{sum(abs(r['imps_ns']) for r in recs) / len(recs):.2f}")
    print(Counter(f["cat"] for _, f in flags).most_common())
    by = defaultdict(list)
    for r, f in flags:
        if f["cat"] == "noise" or (only and f["cat"] != only):
            continue
        own = [x for x in r["calls"] if side(x["seat"]) == f["side"]]
        last = next((x for x in reversed(own) if x["call"] != "P"), own[-1])
        by[(f["cat"], last["module"], last["rule"])].append((r, f))
    for (cat, mod, rule), items in sorted(by.items(), key=lambda kv: -sum(f["imps"] for _, f in kv[1]))[:50]:
        print(f"\n== {cat} | last bid by {mod}: {rule}  x{len(items)}  {sum(f['imps'] for _, f in items)} IMPs")
        for r, f in items[:4]:
            print(f"  seed {r['seed']} {f['side']} dlr {r['dealer']} vul {r['vul']}  {f['seq']}  -> {r['contract']}"
                  f" ({r['dd_tricks']})  best {f['best']}  hcp {f['side_hcp']} fit {f['fit']}")
            print("     ", "  ".join(f"{s}:{r['hands'][s]}" for s in SEATS))


def compare(old_path, new_path):
    old = {r["seed"]: r for r in map(json.loads, open(old_path))}
    new = {r["seed"]: r for r in map(json.loads, open(new_path))}
    seeds = sorted(set(old) & set(new))
    changed = [s for s in seeds if [c["call"] for c in old[s]["calls"]] != [c["call"] for c in new[s]["calls"]]]
    first, gain = {}, {}
    for s in changed:  # judged for the side that made the first different call: did its score go up?
        i = next(i for i, (a, b) in enumerate(zip(old[s]["calls"], new[s]["calls"])) if a["call"] != b["call"])
        first[s] = new[s]["calls"][i]
        sign = 1 if side(first[s]["seat"]) == "NS" else -1
        gain[s] = sign * imps(new[s]["score_ns"] - old[s]["score_ns"])
    print(f"{len(seeds)} deals, {len(changed)} auctions changed: better {sum(g > 0 for g in gain.values())}, "
          f"worse {sum(g < 0 for g in gain.values())}, net {sum(gain.values()):+d} IMPs for the side that changed")
    by_rule = defaultdict(list)
    for s in changed:
        by_rule[f"{first[s]['module']}: {first[s]['rule']}"].append(gain[s])
    for rule, g in sorted(by_rule.items(), key=lambda kv: sum(kv[1])):
        print(f"  {sum(g):+5d} IMPs  x{len(g):4d}  {rule}")
    for s in sorted(changed, key=lambda s: gain[s])[:int(sys.argv[4]) if len(sys.argv) > 4 else 8]:
        o, n = old[s], new[s]
        print(f"\n  seed {s} dlr {o['dealer']} vul {o['vul']} {gain[s]:+d}: {fmt_auction(o)} -> {o['contract']} ({o['dd_tricks']})"
              f"\n      now {fmt_auction(n)} -> {n['contract']} ({n['dd_tricks']})  par {o['par']}")
        print("     ", "  ".join(f"{x}:{o['hands'][x]}" for x in SEATS))


if __name__ == "__main__":
    if sys.argv[1] == "compare":
        compare(sys.argv[2], sys.argv[3])
    elif sys.argv[1] == "report":
        report(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None)
    else:
        run(int(sys.argv[1]), sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else 1,
            len(sys.argv) > 4 and sys.argv[4] == "all")
