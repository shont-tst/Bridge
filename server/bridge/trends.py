"""Patterns across many boards, for the AI coach (connector.py): the coaching overview, mistakes grouped by kind, the
list of boards with filters and paging, and every call the player made with what the system would have bid.

The overview and the mistake groups come from each board's facts (stats.board_facts), which the server keeps in memory,
so they cover every saved board without reading them again. Only the bidding list reads whole boards, a page at a time.
"""
from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

from .bidding.conventions import BY_ID
from .stats import LEVEL_BOARDS, _calibration, level_for, own_play, rating, smoothed

PACIFIC = ZoneInfo("America/Los_Angeles")
EXAMPLES = 3  # boards quoted for each group, so the AI can point at real hands


def day_start(day: str | None, end: bool = False) -> float | None:
    """"2026-11-03" -> the start (or with end, the end) of that day in Pacific time, as a timestamp."""
    if not day:
        return None
    d = dt.date.fromisoformat(str(day)[:10])
    t = dt.datetime.combine(d, dt.time.max if end else dt.time.min, PACIFIC)
    return t.timestamp()


def when(at: float) -> str:
    """"2026-11-03 9:05 PM", Pacific time."""
    t = dt.datetime.fromtimestamp(at, PACIFIC)
    return f"{t:%Y-%m-%d} {t.hour % 12 or 12}:{t:%M} {'AM' if t.hour < 12 else 'PM'}"


def in_range(facts: list[dict], since: str | None = None, until: str | None = None,
             days: int | None = None) -> list[dict]:
    import time
    lo = day_start(since)
    hi = day_start(until, end=True)
    if days and lo is None:
        lo = time.time() - days * 86400
    return [f for f in facts if (lo is None or f["at"] >= lo) and (hi is None or f["at"] <= hi)]


def filter_boards(facts: list[dict], role: str | None = None, min_level: int | None = None,
                  max_level: int | None = None, strain: str | None = None, off_system: bool | None = None,
                  with_partner: str | None = None) -> list[dict]:
    out = []
    for f in facts:
        c = f["contract"]
        if role and f["role"] != role:
            continue
        if (min_level or max_level or strain) and not c:
            continue
        if min_level and c["level"] < min_level:
            continue
        if max_level and c["level"] > max_level:
            continue
        if strain and c["strain"] != strain:
            continue
        if off_system is not None and bool(f["off_system"]) != off_system:
            continue
        if with_partner == "bot" and f["partner"]:
            continue
        if with_partner == "person" and not f["partner"]:
            continue
        out.append(f)
    return sorted(out, key=lambda f: -f["at"])


def _pct(a: int, b: int) -> int | None:
    return round(100 * a / b) if b else None


def _avg(xs: list[float], digits: int = 2) -> float | None:
    return round(sum(xs) / len(xs), digits) if xs else None


def _ref(f: dict, **more) -> dict:
    """A board, briefly, for an example: the key opens it with board_review."""
    return {"key": f["key"], "finished": when(f["at"]), "board": f["board"], **more}


def _band(c: dict) -> str:
    if c["level"] >= 6:
        return "slam"
    game = {"N": 3, "S": 4, "H": 4, "D": 5, "C": 5}[c["strain"]]
    return "game" if c["level"] >= game else "part score"


def overview(facts: list[dict], own_only: bool = False) -> dict:
    """Rates over a set of boards, with bot benchmarks: where the player loses tricks and points."""
    if own_only:
        facts = own_play(facts)
    n = len(facts)
    out: dict = {"boards": n}
    if not n:
        return out
    decl = [f for f in facts if f["role"] == "declarer" and f["lost"] is not None]
    dfn = [f for f in facts if f["role"] == "defender" and f["lost"] is not None]
    out["roles"] = {r: sum(1 for f in facts if f["role"] == r) for r in ("declarer", "dummy", "defender")}
    out["passed_out"] = sum(1 for f in facts if not f["contract"])

    # declaring: how often a makeable contract was made, by kind of contract
    def made_rate(rows):
        ok = [f for f in rows if f["makeable"]]
        return {"makeable": len(ok), "made": sum(1 for f in ok if f["made"]), "made_pct": _pct(sum(1 for f in ok if f["made"]), len(ok))}
    out["declaring"] = {
        "hands": len(decl), "tricks_lost_per_hand": _avg([f["lost"] for f in decl]),
        **made_rate(decl),
        "by_contract": {k: made_rate([f for f in decl if f["contract"]["strain"] == "N" and k == "notrump"
                                      or f["contract"]["strain"] != "N" and k == "suit"])
                        for k in ("notrump", "suit")},
        "by_level": {b: made_rate([f for f in decl if _band(f["contract"]) == b]) for b in ("part score", "game", "slam")},
        "went_down_when_makeable": [_ref(f, contract=_contract(f)) for f in decl if f["makeable"] and not f["made"]][:EXAMPLES],
    }
    # defending, with opening leads by what they were led from
    leads = [f["lead"] for f in dfn if f.get("lead")]
    by_kind: dict[str, dict] = {}
    for f in dfn:
        ld = f.get("lead")
        if not ld:
            continue
        row = by_kind.setdefault(ld["kind"], {"leads": 0, "costly": 0, "examples": []})
        row["leads"] += 1
        if ld["lost"]:
            row["costly"] += 1
            if len(row["examples"]) < EXAMPLES:
                row["examples"].append(_ref(f, led=ld["card"], holding=ld["holding"], against=ld["against"],
                                            tricks_lost=ld["lost"], best=ld["best"]))
    out["defending"] = {
        "hands": len(dfn), "tricks_lost_per_hand": _avg([f["lost"] for f in dfn]),
        "opening_leads": len(leads), "costly_leads": sum(1 for x in leads if x["lost"]),
        "costly_leads_pct": _pct(sum(1 for x in leads if x["lost"]), len(leads)),
        "leads_vs_notrump": _lead_rate([x for x in leads if x["against"] == "NT"]),
        "leads_vs_suit": _lead_rate([x for x in leads if x["against"] == "suit"]),
        "leads_by_kind": dict(sorted(by_kind.items(), key=lambda kv: -kv[1]["leads"])),
    }
    out["cards_by_kind"] = mistakes(facts, own_only=False, examples=0)["by_kind"]
    # bidding: how often each part of the system was left, and how those boards scored against par
    off_rows: dict[str, list] = {}
    for f in facts:
        for conv in set(f["off_system"]):
            off_rows.setdefault(BY_ID[conv].title if conv in BY_ID else "General bidding", []).append(f)
    vs = lambda rows: _avg([f.get("score_for_par", f["score"]) - f["par"] for f in rows if f["par"] is not None], 0)
    outcomes: dict[str, dict] = {}
    for f in facts:
        for o in f.get("bid_outcomes") or []:
            if own_only and not o.get("own", True):
                continue
            area = BY_ID[o["convention"]].title if o.get("convention") in BY_ID else "General bidding"
            row = outcomes.setdefault(area, {"area": area, "calls": 0, "helped": 0, "hurt": 0, "no_difference": 0,
                                             "net_points": 0, "examples_hurt": [], "examples_helped": [],
                                             "other_bids_decided": {"calls": 0, "net_points": 0, "examples": []}})
            if not o.get("verdict"):
                continue
            ex = _ref(f, points=o["points"], contract_set_by=o.get("contract_set_by"))
            if o.get("contract_set_by", "your call") != "your call":
                # someone else bid again after the call, so the result says as much about their bid as about it
                other = row["other_bids_decided"]
                other["calls"] += 1
                other["net_points"] += o["points"]
                if len(other["examples"]) < EXAMPLES:
                    other["examples"].append(ex)
                continue
            row["calls"] += 1
            row[o["verdict"].replace(" ", "_")] += 1
            row["net_points"] += o["points"]
            lst = row.get(f"examples_{o['verdict']}")
            if lst is not None and len(lst) < EXAMPLES:
                lst.append(ex)
    out["bidding"] = {
        "calls_off_system_per_10_boards": round(10 * sum(len(f["off_system"]) for f in facts) / n, 1),
        "off_system_calls_helped_or_hurt": {
            "what": ("Each call that left the system, against the system's call: the auction bid again from there "
                     "by the system for every seat, both contracts scored double dummy on the board's own scoring "
                     "(at rubber the part score counts towards game). Points are per call, from the player's side (+ "
                     "means their call did better). The counts cover only calls after which nobody else bid again, "
                     "so the call itself decided the contract; calls where partner or an opponent bid on are in "
                     "other_bids_decided, since their bid may have decided the result. An estimate, not a "
                     "certainty."),
            "by_area": sorted(outcomes.values(), key=lambda r: r["net_points"])},
        "vs_par_all_boards": vs(facts),
        "vs_par_boards_with_off_system_calls": vs([f for f in facts if f["off_system"]]),
        "vs_par_boards_on_system": vs([f for f in facts if not f["off_system"]]),
        "by_area": [{"area": k, "boards": len(v), "vs_par": vs(v)} for k, v in
                    sorted(off_rows.items(), key=lambda kv: -len(kv[1]))],
        "note": "Use bidding_history for each call with the system's call and the result.",
    }
    out["help"] = {"hints_per_board": _avg([f["hints"] for f in facts], 1),
                   "undos_per_board": _avg([f["undos"] for f in facts], 1),
                   "ai_questions_per_board": _avg([f.get("coach", 0) for f in facts], 1),
                   "first_choices_taken_back": sum(f.get("undone", 0) for f in facts),
                   "taken_back_cards_that_would_have_cost": sum(f.get("undone_cards_costly", 0) for f in facts),
                   "tricks_those_would_have_cost": sum(f.get("undone_tricks", 0) for f in facts),
                   "taken_back_calls_off_system": sum(f.get("undone_calls_off", 0) for f in facts)}
    out["level"] = {**rating(facts), "based_on": f"the player's most recent {LEVEL_BOARDS} hands as declarer or "
                                                  f"defender in this range (the tricks lost above cover every hand "
                                                  f"in the range, so the two can differ)"}
    cal = _calibration()
    curves = {role: smoothed({lv: v[role] for lv, v in cal.items()}) for role in ("declaring", "defending")}
    out["bot_benchmarks"] = {
        "what": ("Double-dummy tricks lost per hand by the app's bots at each level, on the same measure as yours, "
                 "smoothed so a higher level never loses more (the same table the level is read from)"),
        "levels": {lv: {r: round(curves[r][lv], 2) for r in curves} for lv in sorted(cal)},
        "your_range_on_this_scale": {
            r: round(level_for(v, {lv: x[r] for lv, x in cal.items()}), 1) if v is not None and cal else None
            for r, v in (("declaring", out["declaring"]["tricks_lost_per_hand"]),
                         ("defending", out["defending"]["tricks_lost_per_hand"]))}}
    return out


def _lead_rate(leads: list[dict]) -> dict:
    return {"leads": len(leads), "costly": sum(1 for x in leads if x["lost"]),
            "costly_pct": _pct(sum(1 for x in leads if x["lost"]), len(leads))}


def _contract(f: dict) -> str | None:
    from .coach import contract_text
    return contract_text(f["contract"])


CHECKS = {
    "trumps_out": "led a trump when the opponents had none left",
    "threw_winner": "discarded a card that was the highest left in its suit",
    "ruffed_partners_winner": "ruffed a trick partner was already winning",
}


def mistakes(facts: list[dict], whose: str = "you", own_only: bool = False, examples: int = EXAMPLES) -> dict:
    """Costly cards grouped by role, kind of card and the counting checks, with rates where the player's own cards
    give them (costly cards of a kind out of all the cards of that kind they chose)."""
    by_role: dict[str, dict] = {}
    by_kind: dict[str, dict] = {}
    checks: dict[str, dict] = {}
    trumps = {"costly": 0, "tricks_lost": 0, "examples": []}
    for f in facts:
        if f["role"] not in ("declarer", "defender"):
            continue
        for k, cnt in (f.get("cards_by_kind") or {}).items() if whose == "you" else ():
            by_kind.setdefault(k, {"cards": 0, "costly": 0, "tricks_lost": 0, "mistake": 0, "unlucky": 0,
                                   "examples": []})["cards"] += cnt
        for x in f.get("costly") or []:
            if x["whose"] != whose or (own_only and x.get("asked")):
                continue
            ex = _ref(f, trick=x["trick"], card=x["card"], tricks_lost=x["lost"], verdict=x["verdict"],
                      better=x["best"], contract=_contract(f), **({"after": x["asked"]} if x.get("asked") else {}))
            for group, key in ((by_role, f["role"]), (by_kind, x["kind"])):
                row = group.setdefault(key, {"cards": 0, "costly": 0, "tricks_lost": 0, "mistake": 0, "unlucky": 0,
                                             "examples": []})
                row["costly"] += 1
                row["tricks_lost"] += x["lost"]
                if x["verdict"]:
                    row[x["verdict"]] += 1
                if len(row["examples"]) < examples:
                    row["examples"].append(ex)
            if x.get("trumps"):
                trumps["costly"] += 1
                trumps["tricks_lost"] += x["lost"]
                if len(trumps["examples"]) < examples:
                    trumps["examples"].append(ex)
            for c in x.get("checks") or []:
                row = checks.setdefault(c, {"what": CHECKS[c], "times": 0, "tricks_lost": 0, "examples": []})
                row["times"] += 1
                row["tricks_lost"] += x["lost"]
                if len(row["examples"]) < examples:
                    row["examples"].append(ex)
    for row in by_kind.values():
        row["costly_pct"] = _pct(row["costly"], row["cards"]) if row["cards"] else None
        if not row["cards"]:
            row.pop("cards")
    for group in (by_role, by_kind):
        for row in group.values():
            if not examples:
                row.pop("examples", None)
            if "cards" in row and group is by_role:
                row.pop("cards")
    if not examples:
        trumps.pop("examples")
        for row in checks.values():
            row.pop("examples")
    return {"by_role": by_role, "by_kind": by_kind, "cards_with_trumps": trumps, "counting_checks": checks}


def bidding_rows(rec: dict, only_off_system: bool = True) -> list[dict]:
    """Each call the player made on a saved board: their hand, the auction before it, what it meant, the system's
    call, whether they asked first, and how the board turned out."""
    from .bidpath import add_outcomes, verdict
    from .coach import SEAT, call_text, contract_text, hand_text
    add_outcomes(rec)
    seat = rec.get("seat") or "S"
    review = rec.get("review") or {}
    off = {b["index"]: b for b in review.get("bidding") or [] if b.get("seat") == seat and "index" in b}
    asked = {m["index"]: m["asked"] for m in rec.get("asked") or [] if m.get("seat") == seat and m["kind"] == "call"}
    calls = rec.get("calls") or []
    dealer = rec.get("dealer", "N")
    seats = "NESW"
    out = []
    for i, call in enumerate(calls):
        s = seats[(seats.index(dealer) + i) % 4]
        if s != seat or (only_off_system and i not in off):
            continue
        b = off.get(i)
        row = {"call_number": i + 1,
               "auction_before": [f"{SEAT[seats[(seats.index(dealer) + j) % 4]]} {call_text(c)}"
                                  for j, c in enumerate(calls[:i])],
               "your_call": call_text(call)}
        if b:
            v = verdict(b.get("outcome"), seat)
            if v:
                o = b["outcome"]
                row["against_system"] = {**v, "system_auction_from_here": [call_text(x) for x in o["system_auction"]],
                                         "system_contract": contract_text(o["system_contract"]) or "Passed out"}
            row.update({"meant": b.get("meaning"), "system_call": call_text(b["system_call"]),
                        "system_meaning": b.get("system_meaning"), "small_difference": bool(b.get("minor")),
                        "system_area": BY_ID[b["convention"]].title if b.get("convention") in BY_ID else "General bidding"})
        else:
            row["system_call"] = "same"
        if i in asked:
            row["after"] = asked[i]
        out.append(row)
    if not out:
        return []
    ns = seat in "NS"
    par = (rec.get("dd") or {}).get("par_score_ns")
    par_contracts = (rec.get("dd") or {}).get("par_contracts")
    if rec.get("scoring") == "rubber":
        from .stats import rubber_par
        rp = rubber_par(rec)
        if rp:
            par, par_contracts = rp["score_ns"], rp["contracts"]
    c = rec.get("contract")
    dd = (rec.get("dd") or {}).get("tricks") or {}
    board = {"key": rec.get("key"), "finished": when(rec.get("finished_at", 0)), "board": rec.get("board"),
             "you": SEAT[seat], "dealer": SEAT.get(dealer), "vulnerable": rec.get("vulnerability"),
             "your_hand": hand_text((rec.get("hands") or {}).get(seat, "...")),
             "final_contract": contract_text(c) or "Passed out",
             "declarer_tricks": rec.get("declarer_tricks") if c else None,
             "your_score": rec.get("score_ns", 0) * (1 if ns else -1),
             "dd_tricks_in_contract": (dd.get(c["strain"]) or {}).get(c["declarer"]) if c else None,
             "par_for_you": None if par is None else par * (1 if ns else -1),
             "par_contracts": par_contracts,
             "calls": out}
    return [board]
