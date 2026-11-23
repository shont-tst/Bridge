"""My stats: how a player declares, defends and bids, worked out from the boards saved to their account, and their
level on the bots' 1 to 10 scale.

Tricks lost are counted the way the post-hand review counts them: against perfect play with all cards seen, every
card the player chose (dummy's cards count to declarer). The level compares those numbers with how each bot level
does on the same measure (bots/calibration.json, made by scripts/calibrate.py).
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from .bidding.conventions import BY_ID
from .bidpath import add_outcomes, verdict
from .core.auction import Contract
from .core.board import is_vulnerable
from .core.cards import partner
from .core.par import par as par_from_tricks
from .core.scoring import duplicate_score
from .game.second import fill_split
from .patterns import costly_cards, lead_info

CALIBRATION = Path(__file__).resolve().parent / "bots" / "calibration.json"
LEVEL_BOARDS = 40  # the level is worked out from this many recent hands
LEVEL_MIN = 20  # and shown only once there are this many


def _calibration() -> dict[int, dict]:
    try:
        levels = json.loads(CALIBRATION.read_text())["levels"]
    except (OSError, ValueError, KeyError):
        return {}
    return {int(k): v for k, v in levels.items()}


def board_facts(rec: dict) -> dict:
    """What one saved board says about the player who sat in `rec["seat"]`."""
    seat = rec.get("seat") or "S"
    c = rec.get("contract")
    ns = seat in "NS"
    mine = rec.get("score_ns", 0) * (1 if ns else -1)
    par = (rec.get("dd") or {}).get("par_score_ns")
    out = {"key": rec.get("key"), "at": rec.get("finished_at", 0), "board": rec.get("board"), "seat": seat,
           "room": rec.get("room"), "contract": c, "tricks": rec.get("declarer_tricks", 0), "score": mine,
           "par": None if par is None else par * (1 if ns else -1), "difficulty": rec.get("difficulty"),
           "partner": (rec.get("players") or {}).get(partner(seat)), "bots": rec.get("bots") or [],
           "role": None, "lost": None, "makeable": None, "made": None, "lead_cost": None,
           "off_system": [], "hints": 0, "undos": 0, "coach": 0,
           # the same without the calls and cards that came right after a hint or an AI coach question (boards from
           # before 1.88 didn't mark those, so they count as all the player's own)
           "lost_own": None, "lead_cost_own": None, "off_system_own": [], "asked": 0,
           "costly": [], "cards_by_kind": {}, "undone": 0, "bid_outcomes": [], "lead": None, "rubber": rec.get("scoring") == "rubber"}
    help_ = (rec.get("help") or {}).get(seat) or {}
    out["hints"], out["undos"] = help_.get("hints", 0), help_.get("undos", 0)
    out["coach"] = help_.get("coach", 0)  # questions to their AI assistant on their turn
    asked = [m for m in rec.get("asked") or [] if m.get("seat") == seat]
    out["asked"] = len(asked)
    asked_calls = {m["index"] for m in asked if m["kind"] == "call"}
    asked_cards = {m["index"] for m in asked if m["kind"] == "card"}
    undone = [u for u in rec.get("undone") or [] if u.get("by") == seat]
    out["undone"] = len(undone)
    # first choices taken back: cards that would have cost tricks, calls the system wouldn't have made
    out["undone_cards_costly"] = sum(1 for u in undone if u["kind"] == "card" and (u.get("lost") or 0) > 0)
    out["undone_tricks"] = sum(u.get("lost") or 0 for u in undone if u["kind"] == "card")
    out["undone_calls_off"] = sum(1 for u in undone if u["kind"] == "call" and u.get("system_call") not in (None, u["call"]))
    review = rec.get("review") or {}
    # the same deal played again with a level 10 bot in this seat, in IMPs for the player (game/second.py)
    second = ((fill_split(rec).get("review") or {}).get("second") or {}).get(seat) or {}
    out["second_imps"] = second.get("imps")
    out["second_bidding"], out["second_play"] = second.get("bidding_imps"), second.get("play_imps")
    off = [b for b in review.get("bidding") or [] if b.get("seat") == seat and not b.get("minor")]
    out["off_system"] = [b.get("convention") for b in off]
    out["off_system_own"] = [b.get("convention") for b in off if b.get("index") not in asked_calls]
    try:
        add_outcomes(rec)  # boards from before 1.88 get theirs worked out here
    except Exception:  # an estimate is a bonus
        pass
    out["bid_outcomes"] = [{"convention": b.get("convention"), "own": b.get("index") not in asked_calls,
                            **(verdict(b.get("outcome"), seat) or {"verdict": None, "points": None})} for b in off]
    # the score par is compared with. At rubber, the board's points on the pad have no game bonus until the rubber
    # ends, so the board is scored like par is: game and part-score bonuses on the board, with the part score
    # already below the line counting towards game (with 60 on, 2♥ made is a game)
    below = rec.get("below_before") or {"NS": 0, "EW": 0}
    out["below_before"] = rec.get("below_before")
    out["below_guessed"] = bool(rec.get("below_guessed"))
    if c and rec.get("scoring") == "rubber":
        d = c["declarer"]
        side = "NS" if d in "NS" else "EW"
        pts = duplicate_score(Contract(c["level"], c["strain"], d, int(c.get("doubled") or 0)),
                              rec.get("declarer_tricks", 0), is_vulnerable(rec.get("vulnerability") or "None", d),
                              below.get(side, 0))
        out["score_for_par"] = pts * (1 if same_side_ns(d) == ns else -1)
    elif not c:
        out["score_for_par"] = 0
    else:
        out["score_for_par"] = mine
    if rec.get("scoring") == "rubber":
        rp = rubber_par(rec)
        if rp:
            out["par"] = rp["score_ns"] * (1 if ns else -1)
            out["par_contracts"] = rp["contracts"]
    if not c:
        return out
    declarer = c["declarer"]
    out["role"] = "declarer" if declarer == seat else "dummy" if partner(declarer) == seat else "defender"
    play = review.get("play")
    if play and out["role"] != "dummy":
        cards = play.get("cards") or []
        out["lost"] = sum(x["lost"] for x in cards if x["by"] == seat)
        out["lost_own"] = sum(x["lost"] for i, x in enumerate(cards) if x["by"] == seat and i not in asked_cards)
        out["costly"], out["cards_by_kind"] = costly_cards(rec, seat)
        if out["role"] == "declarer":
            needed = c["level"] + 6
            out["makeable"] = play.get("dd_declarer_tricks", 0) >= needed
            out["made"] = rec.get("declarer_tricks", 0) >= needed
        elif cards and cards[0]["seat"] == seat:
            out["lead_cost"] = cards[0]["lost"] > 0
            out["lead_cost_own"] = None if 0 in asked_cards else out["lead_cost"]
            out["lead"] = lead_info(rec, seat)
    return out


def rubber_par(rec: dict) -> dict | None:
    """Par for a rubber board on the scoring it was played with: the part scores below the line count towards
    game. None without a double-dummy table."""
    tricks = (rec.get("dd") or {}).get("tricks")
    if not tricks:
        return None
    return par_from_tricks(tricks, rec.get("vulnerability") or "None", rec.get("below_before"))


def rebuild_part_scores(records: list[dict]) -> None:
    """Boards saved before 1.93 don't say what was below the line when they were dealt: replay each table's rubber
    boards in order to find out. A board whose vulnerability doesn't fit the replay (a board missing in between,
    such as one played before this player sat down) starts again from no part score, and is marked a guess."""
    from .core.auction import Contract as C
    from .core.cards import Hand
    from .core.rubber import Rubber
    by_room: dict[str, list[dict]] = {}
    for r in records:
        if r.get("scoring") == "rubber":
            by_room.setdefault(r.get("room") or "", []).append(r)
    for rows in by_room.values():
        rows.sort(key=lambda r: r.get("finished_at", 0))
        rubber = Rubber()
        for r in rows:
            if r.get("below_before") is None:
                guess = rubber.vulnerability() != (r.get("vulnerability") or "None")
                if guess:  # out of step: start again from what the vulnerability says
                    v = r.get("vulnerability") or "None"
                    rubber = Rubber(games={"NS": int(v in ("NS", "Both")), "EW": int(v in ("EW", "Both"))})
                r["below_before"] = dict(rubber.below)
                if guess:
                    r["below_guessed"] = True
            else:
                rubber.below = dict(r["below_before"])
                v = r.get("vulnerability") or "None"
                rubber.games = {"NS": int(v in ("NS", "Both")), "EW": int(v in ("EW", "Both"))}
            c = r.get("contract")
            try:
                hands = {s: Hand.from_pbn(h) for s, h in (r.get("hands") or {}).items()}
                rubber.record(r.get("board", 0), C(c["level"], c["strain"], c["declarer"], int(c.get("doubled") or 0))
                              if c else None, r.get("declarer_tricks", 0), hands)
            except Exception:  # a record we can't replay: carry on from no part score
                rubber = Rubber()


def same_side_ns(seat: str) -> bool:
    return seat in "NS"


def own_play(facts: list[dict]) -> list[dict]:
    """The facts with hint- and AI-coach-assisted calls and cards left out."""
    return [{**f, "lost": f.get("lost_own", f["lost"]), "lead_cost": f.get("lead_cost_own", f["lead_cost"]),
             "off_system": f.get("off_system_own", f["off_system"])} for f in facts]


def leave_out(facts: list[dict], hints: bool = False, undo: bool = False, coach: bool = False) -> list[dict]:
    """The facts without the boards where the player used the help they ticked (a hint, Undo, an AI coach question).
    Whole boards go, so every figure follows the same rule: par and the second table score the whole board and can't
    leave out one card."""
    return [f for f in facts if not ((hints and f.get("hints")) or (undo and f.get("undos")) or (coach and f.get("coach")))]


def _avg(xs: list[float]) -> float | None:
    return round(sum(xs) / len(xs), 2) if xs else None


def summarize(facts: list[dict]) -> dict:
    decl = [f for f in facts if f["role"] == "declarer" and f["lost"] is not None]
    dfn = [f for f in facts if f["role"] == "defender" and f["lost"] is not None]
    leads = [f for f in dfn if f["lead_cost"] is not None]
    makeable = [f for f in decl if f["makeable"]]
    vs_par = [f.get("score_for_par", f["score"]) - f["par"] for f in facts if f["par"] is not None]
    off = [conv for f in facts for conv in f["off_system"]]
    by_conv: dict[str, int] = {}
    for conv in off:
        title = BY_ID[conv].title if conv in BY_ID else "General bidding"
        by_conv[title] = by_conv.get(title, 0) + 1
    # did leaving the system pay? Only calls nobody else bid after, so the call alone decided the contract
    # (bidpath.py: both contracts scored with perfect play)
    decided = [o for f in facts for o in f.get("bid_outcomes") or []
               if o.get("verdict") and o.get("contract_set_by", "your call") == "your call"]
    n = len(facts)
    second = [f["second_imps"] for f in facts if f.get("second_imps") is not None]
    return {
        "boards": n,
        "second_imps": _avg(second), "second_boards": len(second),
        # where those IMPs came from: the bidding (both contracts with every card seen), and the play, split by
        # whether the player's side declared at their table
        "second_bidding": _avg([f["second_bidding"] for f in facts if f.get("second_bidding") is not None]),
        "second_declaring": _avg([f["second_play"] for f in facts
                                  if f.get("second_play") is not None and f["role"] in ("declarer", "dummy")]),
        "second_defending": _avg([f["second_play"] for f in facts
                                  if f.get("second_play") is not None and f["role"] == "defender"]),
        "off_system_points": _avg([o["points"] for o in decided]),
        "off_system_helped": sum(1 for o in decided if o["verdict"] == "helped"),
        "off_system_cost": sum(1 for o in decided if o["verdict"] == "hurt"),
        "off_system_same": sum(1 for o in decided if o["verdict"] == "no difference"),
        "vs_par": _avg(vs_par),
        "at_or_above_par": round(100 * sum(1 for v in vs_par if v >= 0) / len(vs_par)) if vs_par else None,
        "declared": len(decl), "made": sum(1 for f in makeable if f["made"]), "makeable": len(makeable),
        "declarer_lost": _avg([f["lost"] for f in decl]),
        "defended": len(dfn), "defender_lost": _avg([f["lost"] for f in dfn]),
        "leads": len(leads), "costly_leads": sum(1 for f in leads if f["lead_cost"]),
        "off_system_per_10": round(10 * len(off) / n, 1) if n else None,
        "off_system_by": sorted(by_conv.items(), key=lambda kv: -kv[1])[:3],
        "hints_per_board": round(sum(f["hints"] for f in facts) / n, 1) if n else None,
        "undos_per_board": round(sum(f["undos"] for f in facts) / n, 1) if n else None,
        "coach_per_board": round(sum(f.get("coach", 0) for f in facts) / n, 1) if n else None,
    }


def smoothed(curve: dict[int, float]) -> dict[int, float]:
    """The bots' tricks lost per hand by level, with a higher level never losing more than a lower one (the
    measurements are a little noisy). The level and the coach's benchmarks both read this, so they agree."""
    out, last = {}, None
    for lv in sorted(curve):
        last = curve[lv] if last is None else min(curve[lv], last)
        out[lv] = last
    return out


def level_for(lost: float, curve: dict[int, float]) -> float:
    """Where `lost` tricks per hand sits on the bots' scale: between the two levels either side of it."""
    curve = smoothed(curve)
    levels = sorted(curve)
    vals = [curve[lv] for lv in levels]
    if lost >= vals[0]:
        return float(levels[0])
    for (l0, v0), (l1, v1) in zip(zip(levels, vals), zip(levels[1:], vals[1:])):
        if v1 <= lost <= v0:
            return l0 + (0 if v0 == v1 else (v0 - lost) / (v0 - v1)) * (l1 - l0)
    return float(levels[-1])


def rating(facts: list[dict]) -> dict:
    """The player's level from their most recent hands as declarer or defender."""
    played = [f for f in sorted(facts, key=lambda f: -f["at"]) if f["role"] in ("declarer", "defender")
              and f["lost"] is not None][:LEVEL_BOARDS]
    out: dict = {"hands": len(played), "needed": LEVEL_MIN, "level": None, "declaring": None, "defending": None}
    cal = _calibration()
    if len(played) < LEVEL_MIN or not cal:
        return out
    parts = []
    for role, key in (("declarer", "declaring"), ("defender", "defending")):
        mine = [f["lost"] for f in played if f["role"] == role]
        if mine:
            curve = {k: v[key] for k, v in cal.items()}
            mean = sum(mine) / len(mine)
            lv = level_for(mean, curve)
            out[key] = round(lv, 1)
            # the margin of error: tricks lost per hand, give or take two standard errors (about 95% sure), read
            # off the same curve (losing more is a lower level)
            sd = (sum((x - mean) ** 2 for x in mine) / (len(mine) - 1)) ** 0.5 if len(mine) > 1 else mean
            err = 2 * sd / len(mine) ** 0.5
            parts.append((lv, level_for(mean + err, curve), level_for(max(0.0, mean - err), curve), len(mine)))
    total = sum(p[3] for p in parts)
    out["level"], out["low"], out["high"] = (round(sum(p[i] * p[3] for p in parts) / total, 1) for i in range(3))
    return out


def trend(facts: list[dict], days: int) -> list[dict]:
    """Score against par, averaged per day, oldest first, for the line on My stats."""
    by_day: dict[str, list[int]] = {}
    for f in facts:
        if f["par"] is not None:
            day = time.strftime("%Y-%m-%d", time.localtime(f["at"]))
            by_day.setdefault(day, []).append(f.get("score_for_par", f["score"]) - f["par"])
    return [{"day": d, "vs_par": round(sum(v) / len(v)), "boards": len(v)} for d, v in sorted(by_day.items())][-days:]


def my_stats(records: list[dict], days: int | None = 30) -> dict:
    return stats_from_facts([board_facts(r) for r in records], days)


def stats_from_facts(facts: list[dict], days: int | None = 30, hints: bool = False, undo: bool = False,
                     coach: bool = False) -> dict:
    """My stats over the last `days` (None: all time), without the boards where the player used the help they ticked
    (leave_out). How much help they used is always counted over every board, and `all_boards` says how many there
    were before. The level excludes them too (one rule for the page); with few boards left it reads less surely."""
    now = time.time()
    if days:
        recent = [f for f in facts if f["at"] >= now - days * 86400]
        before = [f for f in facts if now - 2 * days * 86400 <= f["at"] < now - days * 86400]
    else:
        recent, before = facts, []
    last_difficulty = next((f["difficulty"] for f in sorted(facts, key=lambda f: -f["at"]) if f["difficulty"]), None)
    pick = lambda rows: leave_out(rows, hints, undo, coach)  # noqa: E731
    now_ = summarize(pick(recent))
    used = summarize(recent)
    now_.update({k: used[k] for k in ("hints_per_board", "undos_per_board", "coach_per_board")}, all_boards=len(recent))
    return {"days": days, "now": now_, "before": summarize(pick(before)) if before else None,
            "trend": trend(pick(recent), days or 3650), "level": rating(pick(facts)), "bots": last_difficulty,
            "left_out": [k for k, on in (("hints", hints), ("undo", undo), ("coach", coach)) if on]}


def history(records: list[dict]) -> list[dict]:
    """The hand history list: one line per board, newest first."""
    return history_from_facts([board_facts(r) for r in records])


def history_from_facts(facts: list[dict], role: str | None = None, limit: int | None = None) -> list[dict]:
    """The same from facts, optionally only boards played in one role ("declarer", "defender"), newest `limit`."""
    rows = [{k: f[k] for k in ("key", "at", "board", "seat", "room", "contract", "tricks", "score", "par",
                               "partner", "role", "bots")} for f in facts if not role or f["role"] == role]
    rows.sort(key=lambda x: -x["at"])
    return rows[:limit] if limit else rows
