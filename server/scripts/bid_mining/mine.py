"""Mine players' saved boards for calls that left the bidding system, grouped by the spot where the system would call.

Each call is re-checked with today's engine: a spot the system now gets right is skipped, and when today's system call
differs from the one the review saved, the comparison is worked out again. A call's worth is its average over 30
re-dealt layouts that fit what the caller saw (bidpath.average_outcome), so one lucky deal doesn't decide it.

Run from server/:
    python -m scripts.bid_mining.mine BACKUP OUT.json [--since YYYY-MM-DD]
BACKUP is a backup file (backups.py makes them weekly), or "latest" to read the newest one from the blob container
whose read-only SAS URL is in BRIDGE_BACKUPS_SAS_URL. --since keeps boards finished on or after that day (Pacific).
Then the report: python -m scripts.bid_mining.mine report OUT.json [MIN_CALLS]
"""
from __future__ import annotations

import datetime as dt
import gzip
import json
import os
import random
import re
import sys
import urllib.request
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor

os.environ["BRIDGE_SOLVER_IN_PROCESS"] = "1"

from bridge.bidding.conventions import make_engine  # noqa: E402
from bridge.bidpath import add_outcomes, average_outcome, verdict  # noqa: E402
from bridge.core.auction import Auction  # noqa: E402
from bridge.core.cards import Hand  # noqa: E402

PACIFIC = dt.timezone(dt.timedelta(hours=-8))
_ENGINES: dict = {}


def engine(conventions):
    key = tuple(sorted(conventions or []))
    if key not in _ENGINES:
        _ENGINES[key] = make_engine(set(key))
    return _ENGINES[key]


def latest_backup() -> bytes:
    url = os.environ["BRIDGE_BACKUPS_SAS_URL"]
    base, sas = url.split("?", 1)
    listing = urllib.request.urlopen(f"{base}?restype=container&comp=list&{sas}", timeout=60).read().decode()
    name = sorted(re.findall(r"<Name>(backup-[^<]+)</Name>", listing))[-1]
    print("reading", name, file=sys.stderr)
    return urllib.request.urlopen(f"{base}/{name}?{sas}", timeout=300).read()


def boards(raw: bytes, since: dt.date | None) -> list[tuple[str, dict]]:
    doc = json.loads(gzip.decompress(raw))
    out = []
    for row in doc["tables"].get("boards", []):
        rec = row["data"] if isinstance(row["data"], dict) else json.loads(row["data"])
        at = rec.get("finished_at")
        if since and at and dt.datetime.fromtimestamp(at, PACIFIC).date() < since:
            continue
        rec.setdefault("key", row["rk"])
        out.append((row["pk"], rec))
    return out


def calls_of(item) -> list[dict]:
    """The board's off-system calls that today's system still makes differently, each with its average worth."""
    user, rec = item
    seat = rec.get("seat") or "S"
    if rec.get("tutorial") or not rec.get("hands") or not rec.get("calls"):
        return []
    e = engine(rec.get("conventions"))
    try:
        add_outcomes(rec, e)
    except Exception:
        pass
    hands = {s: Hand.from_pbn(h) for s, h in rec["hands"].items()}
    asked = {m["index"] for m in rec.get("asked") or [] if m.get("seat") == seat and m.get("kind") == "call"}
    out = []
    for b in (rec.get("review") or {}).get("bidding") or []:
        if b.get("seat") != seat or "index" not in b or not b.get("outcome"):
            continue
        i = b["index"]
        try:
            dec = e.choose(hands[seat], Auction(rec["dealer"], list(rec["calls"][:i])), None, rec.get("vulnerability"))
        except Exception:
            continue
        if dec.call == b["call"]:
            continue  # today's system makes the player's call
        o = b["outcome"]
        if dec.call != b["system_call"] or "avg" not in o:
            o = {**o, "avg": average_outcome(e, hands, rec["dealer"], rec["calls"], i, dec.call,
                                             rec.get("vulnerability"), None, rec.get("below_before"), random.Random(i))}
        v = verdict(o, seat) if o.get("avg") else None
        out.append({"user": user, "key": rec.get("key"), "seat": seat, "hand": rec["hands"][seat],
                    "dealer": rec["dealer"], "vul": rec.get("vulnerability"), "before": rec["calls"][:i],
                    "call": b["call"], "meaning": b.get("meaning"), "system_call": dec.call,
                    "system_meaning": dec.text, "rule": dec.rule.name if dec.rule else None,
                    "asked_first": i in asked, "points": v["points"] if v else None, "avg": o.get("avg")})
    return out


def kind(row) -> str:
    def k(c):
        return "pass" if c == "P" else "double" if c in ("X", "XX") else "bid"
    return f"system {k(row['system_call'])}, player {k(row['call'])}"


def report(rows: list[dict], min_calls: int = 3) -> None:
    groups = defaultdict(list)
    for r in rows:
        groups[(r["rule"], kind(r))].append(r)
    print(f"{len(rows)} calls today's system still makes differently, {len({r['user'] for r in rows})} players")
    print("Spots where players' calls beat the system (average points per call over re-dealt layouts):")
    for (rule, k), g in sorted(groups.items(), key=lambda kv: -sum(r["points"] or 0 for r in kv[1])):
        pts = [r["points"] for r in g if r["points"] is not None]
        if len(g) < min_calls or not pts or sum(pts) <= 0:
            continue
        print(f"\n  {rule} ({k}): {len(g)} calls by {len({r['user'] for r in g})} players, "
              f"{sum(pts) / len(pts):+.0f} per call, helped {sum(p > 20 for p in pts)}, hurt {sum(p < -20 for p in pts)}")
        for r in sorted(g, key=lambda r: -(r["points"] or 0)):
            print(f"    {r['points']:+5} {r['hand']}  dealer {r['dealer']}: {' '.join(r['before']) or '(opens)'}  "
                  f"-> {r['call']} [{r['meaning']}]; system {r['system_call']}{'  (after a hint)' if r['asked_first'] else ''}")


def main(argv: list[str]) -> None:
    if argv and argv[0] == "report":
        report(json.load(open(argv[1])), int(argv[2]) if len(argv) > 2 else 3)
        return
    if len(argv) < 2:
        sys.exit(__doc__)
    since = dt.date.fromisoformat(argv[argv.index("--since") + 1]) if "--since" in argv else None
    raw = latest_backup() if argv[0] == "latest" else open(argv[0], "rb").read()
    items = boards(raw, since)
    print(f"{len(items)} boards from {len({u for u, _ in items})} players", file=sys.stderr)
    with ProcessPoolExecutor(os.cpu_count() or 4) as ex:
        rows = [r for rs in ex.map(calls_of, items, chunksize=4) for r in rs]
    json.dump(rows, open(argv[1], "w"))
    report(rows)


if __name__ == "__main__":
    main(sys.argv[1:])
