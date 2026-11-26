"""One-spot double-dummy sweep: how much a candidate bidding change gains in the spot where it applies.

A candidate is a class with two functions of `ctx` (the hand, auction, the system's decision, seat, vulnerability
and engine): `when(ctx)` says the spot applies, `alt(ctx)` gives the call to try instead (None keeps the system's).
Put candidates in a file of your own (see example_candidates.py) and run from server/:

    python -m scripts.bid_mining.spot FILE.py NAME DEALS [FIRST_SEED]     the first time the spot comes up on each deal
    python -m scripts.bid_mining.spot FILE.py NAME DEALS [FIRST_SEED] full   North-South use it on every call

The bots bid random deals with the default conventions. "first": at the first call where `when` holds, both the
system's call and the candidate's are bid out by the system and scored double dummy, in IMPs for the caller's side.
"full": North-South use the candidate wherever it applies against East-West on the system, in IMPs for North-South;
this catches a change that helps in one spot but makes later calls worse. Competitive spots come up on about 1% of
deals, so use 30,000 deals or more, and a second seed set before trusting a number.
"""
from __future__ import annotations

import importlib.util
import os
import random
import sys
from collections import Counter
from concurrent.futures import ProcessPoolExecutor

os.environ["BRIDGE_SOLVER_IN_PROCESS"] = "1"

from bridge.bidding.conventions import ALL_CONVENTIONS, make_engine  # noqa: E402
from bridge.bidpath import dd_score_ns  # noqa: E402
from bridge.core.auction import Auction  # noqa: E402
from bridge.core.board import dealer_for, vulnerability_for  # noqa: E402
from bridge.core.cards import deal_random  # noqa: E402
from bridge.core.scoring import imps  # noqa: E402
from bridge.game.analysis import dd_summary  # noqa: E402

E = make_engine({c.id for c in ALL_CONVENTIONS if c.default_on})


def load(path: str, name: str):
    spec = importlib.util.spec_from_file_location("candidates", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return getattr(mod, name)


def signed_imps(points: int) -> int:
    return imps(points) if points >= 0 else -imps(-points)


def deal(seed: int):
    rng = random.Random(seed)
    hands = deal_random(rng)
    board = rng.randint(1, 16)
    return hands, dealer_for(board), vulnerability_for(board)


def bid_out(hands, auction: Auction, vul, cand=None) -> Auction:
    a = auction.copy()
    while not a.is_complete() and len(a.calls) < 60:
        seat = a.next_to_call
        dec = E.choose(hands[seat], a, None, vul)
        call = dec.call
        if cand is not None and seat in "NS":
            ctx = {"hand": hands[seat], "auction": a, "dec": dec, "seat": seat, "vul": vul, "engine": E}
            if cand.when(ctx):
                alt = cand.alt(ctx)
                if alt and a.is_legal(alt):
                    call = alt
        a.add(call)
    return a


def first(args) -> tuple[int, int, int]:
    """(spot came up, call changed, IMPs for the caller's side)."""
    path, name, seed = args
    cand = load(path, name)
    hands, dealer, vul = deal(seed)
    a = Auction(dealer)
    while not a.is_complete():
        seat = a.next_to_call
        dec = E.choose(hands[seat], a, None, vul)
        ctx = {"hand": hands[seat], "auction": a, "dec": dec, "seat": seat, "vul": vul, "engine": E}
        if cand.when(ctx):
            alt = cand.alt(ctx)
            if not alt or alt == dec.call or not a.is_legal(alt):
                return 1, 0, 0
            x, y = a.copy(), a.copy()
            x.add(dec.call)
            y.add(alt)
            cx, cy = bid_out(hands, x, vul).contract(), bid_out(hands, y, vul).contract()
            if (cx and cx.to_dict()) == (cy and cy.to_dict()):
                return 1, 1, 0
            dd = dd_summary(hands, vul, dealer)
            return 1, 1, signed_imps((dd_score_ns(cy, dd, vul) - dd_score_ns(cx, dd, vul)) * (1 if seat in "NS" else -1))
        a.add(dec.call)
    return 0, 0, 0


def full(args) -> tuple[int, int, int]:
    path, name, seed = args
    cand = load(path, name)
    hands, dealer, vul = deal(seed)
    c0 = bid_out(hands, Auction(dealer), vul).contract()
    c1 = bid_out(hands, Auction(dealer), vul, cand).contract()
    if (c0 and c0.to_dict()) == (c1 and c1.to_dict()):
        return 0, 0, 0
    dd = dd_summary(hands, vul, dealer)
    return 1, 1, signed_imps(dd_score_ns(c1, dd, vul) - dd_score_ns(c0, dd, vul))


def main(argv: list[str]) -> None:
    if len(argv) < 3:
        sys.exit(__doc__)
    path, name, n = argv[0], argv[1], int(argv[2])
    seed0 = int(argv[3]) if len(argv) > 3 and argv[3].isdigit() else 1
    fn = full if "full" in argv[3:] else first
    with ProcessPoolExecutor(os.cpu_count() or 4) as ex:
        res = list(ex.map(fn, [(path, name, s) for s in range(seed0, seed0 + n)], chunksize=50))
    c = Counter()
    for spot, changed, gain in res:
        c["spot"] += spot
        c["changed"] += changed
        c["imps"] += gain
        c["better"] += gain > 0
        c["worse"] += gain < 0
    print(f"{name} ({fn.__name__}): {n} deals from seed {seed0}, spot came up {c['spot']}, changed {c['changed']}, "
          f"{c['imps']:+d} IMPs (better {c['better']}, worse {c['worse']}), {c['imps'] / max(c['changed'], 1):+.2f} per change")


if __name__ == "__main__":
    main(sys.argv[1:])
