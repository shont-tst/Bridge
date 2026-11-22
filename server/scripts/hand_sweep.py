"""Hand sweep: bid (and optionally play) many seeded deals with the bots and flag anything that looks wrong.

Unlike `bidding_sweep` (which scores contracts against double-dummy par), this checks each call on its own:

- crashes and runaway auctions
- illegal calls (checked here independently of `Auction.legal_calls`) and illegal cards (revokes, cards not held)
- opening bids that break the No Fear Bridge cheat sheet (1♥/1♠ without 5, 1NT/2NT outside range, weak twos, 2♣)
- 1NT responses (Stayman without a major, transfers without 5)
- a pass of a forcing call, a 2♣ auction that dies below game, a missed game with 26+ HCP
- explanations (`engine.explain`) that don't fit the bidder's own hand

Deals are random (board N uses seed N) plus targeted sets dealt by rejection sampling from the same seed.
Run from server/:
    python -m scripts.hand_sweep [RANDOM=300] [TARGETED_EACH=40] [PLAY=40] [OUT=hand_sweep.jsonl]
"""
from __future__ import annotations

import json
import os
import random
import sys
import time
import traceback
from collections import Counter, defaultdict

os.environ.setdefault("BRIDGE_SOLVER_IN_PROCESS", "1")

from bridge.bidding.conventions import make_engine  # noqa: E402
from bridge.bidding.evaluation import Eval  # noqa: E402
from bridge.bots.player import BotPlayer  # noqa: E402
from bridge.bots.view import view_for  # noqa: E402
from bridge.core.auction import Auction, bid_rank, is_bid  # noqa: E402
from bridge.core.board import dealer_for, vulnerability_for  # noqa: E402
from bridge.core.cards import SEATS, deal_random, next_seat, partner, same_side, side  # noqa: E402
from bridge.core.play import Play  # noqa: E402

ENGINE = make_engine()
MAX_CALLS = 60
GAME = {"N": 3, "S": 4, "H": 4, "D": 5, "C": 5}


# --- independent legality --------------------------------------------------------------------------------
def call_problem(calls: list[str], dealer: str, call: str) -> str | None:
    """Why `call` would be illegal after `calls` (None if it is fine). Written apart from core/auction.py."""
    me = next_seat(dealer, len(calls))
    if call == "P":
        return None
    last_i = max((i for i, c in enumerate(calls) if is_bid(c)), default=None)
    if is_bid(call):
        if last_i is not None and bid_rank(call) <= bid_rank(calls[last_i]):
            return f"insufficient bid {call} over {calls[last_i]}"
        return None
    if last_i is None:
        return f"{call} with no bid to double"
    bidder = next_seat(dealer, last_i)
    after = calls[last_i + 1:]
    if call == "X":
        if same_side(me, bidder):
            return "double of own side's bid"
        if "X" in after or "XX" in after:
            return "double of an already doubled bid"
        return None
    if call == "XX":
        if not same_side(me, bidder):
            return "redouble of the other side's bid"
        if "X" not in after or "XX" in after:
            return "redouble without a double"
        return None
    return f"unknown call {call!r}"


# --- system checks -----------------------------------------------------------------------------------------
def opening_checks(ev: Eval, call: str) -> list[str]:
    out = []
    L = ev.lengths
    if call in ("1H", "1S") and L[call[1]] < 5:
        out.append(f"opened {call} with {L[call[1]]} cards")
    if call == "1N" and not (15 <= ev.hcp <= 17 and ev.balanced):
        out.append(f"1NT with {ev.hcp} HCP, shape {ev.shape}")
    if call == "2N" and not (20 <= ev.hcp <= 21 and ev.balanced):
        out.append(f"2NT with {ev.hcp} HCP, shape {ev.shape}")
    if call == "2C" and not (ev.tp >= 22 or ev.hcp >= 22):
        out.append(f"2C with {ev.hcp} HCP / {ev.tp} TP")
    if call in ("2D", "2H", "2S") and not (5 <= ev.hcp <= 10 and L[call[1]] == 6):
        out.append(f"weak {call} with {ev.hcp} HCP, {L[call[1]]} cards")
    if call[:1] == "1" and call[1] in "CD" and max(L["S"], L["H"]) >= 5 and L[call[1]] < max(L["S"], L["H"]):
        out.append(f"opened {call} with a longer 5-card major")
    if call == "P":
        if ev.balanced and 12 <= ev.hcp and ev.hcp <= 21:
            out.append(f"passed a balanced {ev.hcp} HCP")
        elif ev.tp >= 13:
            out.append(f"passed {ev.tp} TP")
        elif ev.hcp >= 22:
            out.append(f"passed {ev.hcp} HCP")
    return out


def meaning_mismatch(ev: Eval, m) -> list[str]:
    """Where the bidder's hand falls outside what its call was explained to show."""
    out = []
    lo, hi = m.hcp
    # Ranges are in points (HCP plus length or shortness), so allow some slack before flagging.
    pts = max(ev.hcp, ev.tp)
    if ev.hcp > hi + 1:
        out.append(f"HCP {ev.hcp} above shown {lo}-{hi}")
    if pts + 3 < lo:
        out.append(f"points {ev.hcp}/{ev.tp} below shown {lo}-{hi}")
    if not m.artificial:
        for s, (a, b) in m.lengths.items():
            n = ev.len(s)
            if n < a or n > b:
                out.append(f"{s} length {n} outside shown {a}-{b}")
    if m.balanced is True and not ev.semi_balanced:
        out.append(f"shown balanced but shape {ev.shape}")
    return out


def sweep_auction(hands, dealer, bot, rec):
    """Bid the deal; append flags to rec['flags']."""
    a = Auction(dealer)
    flags = rec["flags"]
    decisions = []
    while not a.is_complete():
        if len(a.calls) >= MAX_CALLS:
            flags.append({"kind": "runaway auction", "detail": f"{len(a.calls)} calls"})
            break
        seat = a.next_to_call
        try:
            dec = bot.bid(hands[seat], a)
        except Exception as e:  # noqa: BLE001
            flags.append({"kind": "crash (bid)", "detail": f"{type(e).__name__}: {e}",
                          "where": list(a.calls), "tb": traceback.format_exc()[-800:]})
            break
        prob = call_problem(a.calls, dealer, dec.call)
        if prob:
            flags.append({"kind": "illegal call", "detail": prob, "where": list(a.calls), "call": dec.call})
            break
        decisions.append((seat, dec, a.copy()))
        a.add(dec.call)
    rec["auction"] = list(a.calls)
    rec["rules"] = [d.rule.name if d.rule else None for _, d, _ in decisions]
    if not a.is_complete():
        return a

    evs = {s: Eval(hands[s]) for s in SEATS}
    opened = False
    for i, (seat, dec, before) in enumerate(decisions):
        ev = evs[seat]
        idx = len(before.calls)
        tag = {"at": idx, "seat": seat, "call": dec.call, "rule": dec.rule.name if dec.rule else None}
        if not opened:
            for p in opening_checks(ev, dec.call):
                flags.append({"kind": "opening breaks system", "detail": p, **tag})
            if is_bid(dec.call):
                opened = True
        # explanation the table shows for the call actually made
        try:
            m = ENGINE.explain(a, idx)
        except Exception as e:  # noqa: BLE001
            flags.append({"kind": "crash (explain)", "detail": f"{type(e).__name__}: {e}", **tag})
            continue
        if dec.call != "P" or m.text not in ("No agreed meaning", ""):
            mm = meaning_mismatch(ev, m)
            if mm:
                flags.append({"kind": "explanation doesn't fit hand", "detail": "; ".join(mm),
                              "text": m.text, **tag})
        # (The table's text may differ from the bot's own rule on purpose: one explanation can cover two rules
        # that partner can't tell apart. A real mismatch shows up above, as a hand outside the explanation.)
        # pass of a forcing call: partner's last call forcing and RHO passed
        if dec.call == "P":
            pidx = idx - 2
            if pidx >= 0 and before.calls[idx - 1] == "P":
                pm = ENGINE.explain(a, pidx)
                pc = before.calls[pidx]
                at_game = is_bid(pc) and int(pc[0]) >= GAME[pc[1]]
                if (pm.forcing or (pm.game_forcing and not at_game)) and is_bid(pc) and not pm.signoff:
                    flags.append({"kind": "passed a forcing bid",
                                  "detail": f"partner's {before.calls[pidx]}: {pm.text}", **tag})

    ct = a.contract()
    # 2C strong opening that died below game (2C-2D-2NT may stop)
    first = next((c for c in a.calls if is_bid(c)), None)
    if first == "2C" and ct is not None:
        op_i = next(i for i, c in enumerate(a.calls) if is_bid(c))
        op_seat = a.seat_of(op_i)
        op_m = ENGINE.explain(a, op_i)
        if op_m.artificial and same_side(ct.declarer, op_seat) and ct.level < GAME[ct.strain]:
            ours = [c for j, c in enumerate(a.calls) if same_side(a.seat_of(j), op_seat) and is_bid(c)]
            if ours[:3] != ["2C", "2D", "2N"] or len(ours) > 3:
                flags.append({"kind": "2C auction stopped below game", "detail": f"{ct}"})
    # missed game: 26+ combined HCP and the side played below game (or the other side played it undoubled cheaply)
    for sd in ("NS", "EW"):
        x, y = [s for s in SEATS if side(s) == sd]
        hcp = hands[x].hcp + hands[y].hcp
        if hcp < 26:
            continue
        fit = max(hands[x].length(s) + hands[y].length(s) for s in "SH")
        if ct is None:
            flags.append({"kind": "passed out with 26+", "detail": f"{sd} {hcp} HCP"})
        elif side(ct.declarer) == sd and ct.level < GAME[ct.strain] and not ct.doubled:
            flags.append({"kind": "missed game 26+", "detail": f"{sd} {hcp} HCP, major fit {fit}, played {ct}"})
        elif side(ct.declarer) != sd and not ct.doubled and ct.level <= 3:
            flags.append({"kind": "let them play undoubled with 26+", "detail": f"{sd} {hcp} HCP, they play {ct}"})
    return a


def sweep_play(hands, a, vul, bot, rec):
    ct = a.contract()
    if ct is None:
        return
    original = {s: set(hands[s].cards) for s in SEATS}
    play = Play.start(ct.declarer, ct.strain, {s: hands[s] for s in SEATS})
    played: set[str] = set()
    held = {s: set(original[s]) for s in SEATS}
    n = 0
    while not play.is_complete():
        n += 1
        if n > 60:
            rec["flags"].append({"kind": "runaway play", "detail": f"{n} cards"})
            return
        seat = play.next_to_play
        try:
            v = view_for(play, a, ct, vul, seat)
            card = bot.play(v).card
        except Exception as e:  # noqa: BLE001
            rec["flags"].append({"kind": "crash (play)", "detail": f"{type(e).__name__}: {e}",
                                 "tb": traceback.format_exc()[-800:]})
            return
        trick = play.current
        if card not in held[seat]:
            rec["flags"].append({"kind": "illegal card", "detail": f"{seat} played {card} not held"})
            return
        lead = trick.cards[0][1][0] if trick.cards else None
        if lead and card[0] != lead and any(c[0] == lead for c in held[seat]):
            rec["flags"].append({"kind": "revoke", "detail": f"{seat} played {card} on a {lead} lead"})
            return
        held[seat].discard(card)
        played.add(card)
        play.play(card)
    total = play.tricks_won("NS") + play.tricks_won("EW")
    if total != 13 or len(played) != 52:
        rec["flags"].append({"kind": "trick count", "detail": f"{total} tricks, {len(played)} cards"})
    rec["tricks"] = play.declarer_tricks()
    rec["contract"] = str(ct)


# --- targeted deals ----------------------------------------------------------------------------------------
def _bal(h):
    return Eval(h).balanced


def _major5(h):
    return max(h.length("S"), h.length("H")) >= 5


TARGETS = {
    # dealer is always N
    "1NT opening": lambda h: 15 <= h["N"].hcp <= 17 and _bal(h["N"]),
    "1NT + Stayman": lambda h: 15 <= h["N"].hcp <= 17 and _bal(h["N"]) and h["S"].hcp >= 8
    and max(h["S"].length("S"), h["S"].length("H")) == 4,
    "1NT + transfer": lambda h: 15 <= h["N"].hcp <= 17 and _bal(h["N"]) and _major5(h["S"]),
    "2NT opening": lambda h: 20 <= h["N"].hcp <= 21 and _bal(h["N"]),
    "major opening + raise": lambda h: 12 <= h["N"].hcp <= 18 and _major5(h["N"]) and 6 <= h["S"].hcp
    and h["S"].length(max("SH", key=h["N"].length)) >= 3,
    "2C strong": lambda h: h["N"].hcp >= 22,
    "weak two": lambda h: 5 <= h["N"].hcp <= 10 and any(h["N"].length(s) == 6 for s in "DHS"),
    "preempt": lambda h: 5 <= h["N"].hcp <= 10 and any(h["N"].length(s) >= 7 for s in "SHDC"),
    "overcall": lambda h: 12 <= h["N"].hcp <= 16 and 8 <= h["E"].hcp <= 16
    and any(h["E"].length(s) >= 5 for s in "SHDC"),
    "takeout double": lambda h: 12 <= h["N"].hcp <= 15 and h["E"].hcp >= 12
    and min(h["E"].lengths().values()) <= 1,
    "competitive": lambda h: 17 <= h["N"].hcp + h["S"].hcp <= 23 and
    max(h["N"].length(s) + h["S"].length(s) for s in "SHDC") >= 8 and
    max(h["E"].length(s) + h["W"].length(s) for s in "SHDC") >= 8,
    "game values with fit": lambda h: h["N"].hcp + h["S"].hcp >= 26 and
    max(h["N"].length(s) + h["S"].length(s) for s in "SH") >= 8,
}


def deal_target(pred, seed):
    rng = random.Random(seed)
    for _ in range(200000):
        h = deal_random(rng)
        if pred(h):
            return h
    return None


def run(n_random=300, n_target=40, n_play=40, out="hand_sweep.jsonl"):
    bot = BotPlayer(ENGINE, level=2, seed=7)
    recs = []
    jobs = [("random", b, dealer_for(b), vulnerability_for(b), None) for b in range(1, n_random + 1)]
    for ti, name in enumerate(TARGETS):
        for k in range(n_target):
            jobs.append((name, 10000 * (ti + 1) + k, "N", "None", TARGETS[name]))
    t0 = time.time()
    played = 0
    for kind, seed, dealer, vul, pred in jobs:
        hands = deal_random(random.Random(seed)) if pred is None else deal_target(pred, seed)
        if hands is None:
            continue
        rec = {"set": kind, "seed": seed, "dealer": dealer, "vul": vul,
               "hands": {s: hands[s].to_pbn() for s in SEATS}, "flags": []}
        t = time.time()
        a = sweep_auction(hands, dealer, bot, rec)
        if time.time() - t > 10:
            rec["flags"].append({"kind": "slow auction", "detail": f"{time.time() - t:.1f}s"})
        if played < n_play and kind == "random" and a.is_complete() and a.contract() is not None:
            played += 1
            sweep_play(hands, a, vul, bot, rec)
        recs.append(rec)
    with open(out, "w") as f:
        for r in recs:
            f.write(json.dumps(r) + "\n")
    report(recs)
    print(f"\n{len(recs)} deals, {played} played, {time.time() - t0:.0f}s -> {out}")


def report(recs, show=2):
    by = defaultdict(list)
    for r in recs:
        for fl in r["flags"]:
            key = (fl["kind"], fl.get("rule"))
            by[key].append((r, fl))
    kinds = Counter(k for k, _ in by)
    print("flags by kind:", dict(kinds))
    for (kind, rule), items in sorted(by.items(), key=lambda kv: -len(kv[1])):
        print(f"\n== {kind} [{rule}] x{len(items)}")
        for r, fl in items[:show]:
            print(f"  {r['set']} seed {r['seed']} dealer {r['dealer']}: {' '.join(r['auction'])}")
            print(f"    {fl.get('seat', '')} {fl.get('call', '')}: {fl['detail']}  {fl.get('text', '')}")
            print("    " + "  ".join(f"{s}:{r['hands'][s]}" for s in SEATS))


if __name__ == "__main__":
    args = sys.argv[1:]
    if args and args[0] == "report":
        recs = [json.loads(x) for x in open(args[1])]
        report(recs, int(args[2]) if len(args) > 2 else 2)
    else:
        nums = [int(x) for x in args[:3]]
        run(*nums, *(args[3:4]))
