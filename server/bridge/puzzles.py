"""Your mistakes: a signed-in player's own past mistakes come back as one-decision puzzles.

A puzzle is a card the review marked Mistake (another card was clearly the better bet on the odds, game/odds.py) or a
call it tagged Cost (on average over deals like this one the system's call does better, bidpath.py), made by the
player themselves, not by a bot or a partner. The table is set up at that spot with the real cards (game/replay.py)
and the player's answer is judged with the review's own measures. Unlucky cards aren't puzzles: they were the right
bet.

Progress is kept per puzzle in the `puzzles` table (partition: the user): a wrong answer brings it back in 3 days,
a right one too until it has been right twice, and then it's done. After a wrong answer the player can remove a
puzzle they disagree with ("Don't show this again"), and it never comes back. Puzzles stay out of My stats; the AI coach sees a
summary (connector.py).
"""
from __future__ import annotations

import time

from .bidpath import add_outcomes, verdict
from .core.cards import partner
from .game.replay import COME_BACK, RETIRE

SEP = "~"  # between a board's key and the decision: "<board key>~c12" (the 13th card), "<board key>~b3" (the 4th call)


def is_mistake(c: dict) -> bool:
    """A card the review marks Mistake (as ReviewPanel's isMistake): another card was clearly the better bet."""
    o = c.get("odds")
    if not o:
        return False
    if o.get("better") is not None:
        return bool(o["better"])
    return o.get("best") != c.get("card") and (o.get("best_pct") or 0) > (o.get("played") or 0)


def spots(rec: dict, seat: str) -> list[dict]:
    """The decisions on a saved board that make puzzles for the player in `seat`: their calls tagged Cost and their
    cards marked Mistake (still charged after any the other side gave straight back), in the order they were made."""
    review = rec.get("review") or {}
    out = []
    for b in review.get("bidding") or []:
        if b.get("seat") == seat and isinstance(b.get("index"), int):
            v = verdict(b.get("outcome"), seat)
            if v and v["verdict"] == "hurt":
                out.append({"kind": "call", "index": b["index"]})
    for i, c in enumerate((review.get("play") or {}).get("cards") or []):
        if c.get("by") == seat and c.get("lost", 0) - c.get("back", 0) > 0 and is_mistake(c):
            out.append({"kind": "card", "index": i})
    return out


KINDS = ("bidding", "suit", "notrump", "leads", "defense")  # what the player can pick to practice


def kind_of(f: dict, spot: dict) -> str:
    """Which kind of mistake a spot is, for picking what to practice: a call is bidding; a card is declarer play in a
    suit or in notrump, the opening lead, or the rest of defense (in any contract)."""
    if spot["kind"] == "call":
        return "bidding"
    c, seat = f.get("contract") or {}, f.get("seat") or "S"
    if c.get("declarer") in (seat, partner(seat)):  # the player plays dummy's cards too, when a bot partner declares
        return "notrump" if c.get("strain") == "N" else "suit"
    return "leads" if spot["index"] == 0 else "defense"


def puzzle_id(key: str, spot: dict) -> str:
    return f"{key}{SEP}{'c' if spot['kind'] == 'card' else 'b'}{spot['index']}"


def parse_id(pid: str) -> tuple[str, str, int] | None:
    key, _, what = str(pid).rpartition(SEP)
    if not key or len(what) < 2 or what[0] not in "cb" or not what[1:].isdigit():
        return None
    return key, "card" if what[0] == "c" else "call", int(what[1:])


class Puzzles:
    def __init__(self, store, accounts):
        self.store = store
        self.accounts = accounts

    def _progress(self, user_id: str) -> dict[str, dict]:
        return dict(self.store.query("puzzles", user_id))

    def queue(self, user_id: str, now: float | None = None, kinds: set[str] | None = None) -> list[str]:
        """The puzzles waiting now, in order: new ones from the newest board down, then the ones coming back (soonest
        due first), so a session doesn't open on the same puzzles again and again. `kinds`: only those (KINDS)."""
        return [pid for pid, _ in self._waiting(user_id, now) if kinds is None or _ in kinds]

    def _waiting(self, user_id: str, now: float | None = None) -> list[tuple[str, str]]:
        """(puzzle id, kind) for every puzzle waiting now, in queue order."""
        now = time.time() if now is None else now
        progress = self._progress(user_id)
        back, new = [], []
        for f in sorted(self.accounts.facts(user_id), key=lambda f: -(f.get("at") or 0)):
            for spot in f.get("puzzles") or []:
                pid = (puzzle_id(f["key"], spot), kind_of(f, spot))
                p = progress.get(pid[0])
                if p is None:
                    new.append(pid)
                elif p.get("right", 0) < RETIRE and not p.get("removed") and p.get("due", 0) <= now:
                    back.append((p.get("due", 0), pid))
        return new + [pid for _, pid in sorted(back)]

    def summary(self, user_id: str) -> dict:
        """For the home screen and the AI coach: how many are waiting, and how the player has done with them."""
        progress = self._progress(user_id)
        waiting = self._waiting(user_id)
        return {"waiting": len(waiting), "kinds": {k: sum(1 for _, x in waiting if x == k) for k in KINDS},
                "tried": len(progress),
                "right": sum(p.get("right", 0) for p in progress.values()),
                "wrong": sum(p.get("wrong", 0) for p in progress.values()),
                "done": sum(1 for p in progress.values() if p.get("right", 0) >= RETIRE and not p.get("removed")),
                "removed": sum(1 for p in progress.values() if p.get("removed"))}

    def spec(self, user_id: str, pid: str) -> dict | None:
        """The replay spec for one puzzle (game/replay.py): the board's deal, calls and cards, the spot to start
        from, and in `puzzle` what judging the answer needs. None if the board or the decision is gone."""
        parsed = parse_id(pid)
        if not parsed:
            return None
        key, kind, index = parsed
        rec = self.accounts.board(user_id, key)
        if not rec or not rec.get("hands"):
            return None
        seat = rec.get("seat") or "S"
        try:
            add_outcomes(rec)  # boards from before 1.88 work theirs out when read, as My stats does
        except Exception:
            pass
        if {"kind": kind, "index": index} not in spots(rec, seat):
            return None
        review = rec.get("review") or {}
        calls = list(rec.get("calls") or [])
        p = (self._progress(user_id).get(pid) or {})
        puzzle = {"id": pid, "key": key, "kind": kind, "index": index, "right": p.get("right", 0)}
        if kind == "card":
            c = review["play"]["cards"][index]
            puzzle.update(card=c["card"], odds=c.get("odds"), reach=c.get("reach"), best=c.get("best"))
            start = len(calls) + index
        else:
            b = next(b for b in review["bidding"] if b.get("index") == index)
            v = verdict(b.get("outcome"), seat) or {}
            puzzle.update(call=b["call"], meaning=b.get("meaning"), system_call=b["system_call"],
                          system_meaning=b.get("system_meaning"),
                          cost=-v["points"] if v.get("points") is not None else None,
                          average=bool((b.get("outcome") or {}).get("avg")))
            start = index
        return {"board": rec.get("board") or 1, "dealer": rec["dealer"], "vulnerability": rec["vulnerability"],
                "hands": rec["hands"], "calls": calls, "play": rec.get("play") or [], "seat": seat, "from": start,
                "below": rec.get("below_before") if rec.get("scoring") == "rubber" else None,
                "conventions": rec.get("conventions"), "difficulty": rec.get("difficulty"),
                "signals": rec.get("signals"), "leads": rec.get("leads"), "puzzle": puzzle}

    def mark(self, user_id: str, pid: str, right: bool | None, now: float | None = None) -> None:
        """An answer: it comes back in 3 days, unless that was its second right answer. None: the player removed it
        (they disagree it was a mistake), and it never comes back."""
        now = time.time() if now is None else now
        p = self.store.get("puzzles", user_id, pid) or {"right": 0, "wrong": 0}
        if right is None:
            p["removed"] = now
            self.store.put("puzzles", user_id, pid, p)
            return
        p["right" if right else "wrong"] = p.get("right" if right else "wrong", 0) + 1
        p["due"], p["last"], p["last_right"] = now + COME_BACK, now, bool(right)
        self.store.put("puzzles", user_id, pid, p)
