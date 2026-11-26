"""Saved boards checked again against today's bidding rules, once after each change of the rules, in the background.

A board's review keeps, for each call a person made off the system, the system's call and what leaving it gained or
cost (game/review.py, bidpath.py). Those were the rules on the day the board was played, so after the rules change an
old review could name a system call today's bots no longer make, and Your mistakes could count it as the right answer.
Bump RULES whenever a change alters which call the system makes. After a start, every saved board whose `rules` is
older is checked: the people's calls are compared with today's system again; a row whose system call is unchanged
keeps its worked-out figures, a changed or new row has them worked out again, and a call the system now makes drops
out. The calls, play and score are never touched. Each board is saved with `rules` set, so a restart carries on where
it stopped; a config row (`rules_recheck`) holding RULES skips the scan once every board is done.
"""
from __future__ import annotations

import asyncio
import logging
import random

from .bidding.conventions import make_engine
from .bidding.partscore import Score
from .bidpath import add_averages, add_outcomes
from .core.cards import SEATS, Hand
from .game.review import bidding_review
from .load import timings

log = logging.getLogger("bridge.recheck")
RULES = 1  # 2.72: compete in a known fit, bid a long suit again, double their game (bidding/conventions/general.py)
DONE = ("config", "cfg", "rules_recheck")
PAUSE = 1.0  # seconds between boards that changed


def needs(rec: dict) -> bool:
    review = rec.get("review")
    return (isinstance(review, dict) and "error" not in review and (rec.get("rules") or 0) < RULES
            and bool(rec.get("hands")) and bool(rec.get("calls")) and not rec.get("tutorial"))


def recheck(rec: dict, rng: random.Random | None = None) -> bool:
    """Bring one board's bidding review up to today's rules (in place). True if any row changed."""
    rec["rules"] = RULES
    engine = make_engine(set(rec["conventions"]) if "conventions" in rec else None)
    hands = {s: Hand.from_pbn(h) for s, h in rec["hands"].items()}
    vul = rec.get("vulnerability") or "None"
    below = rec.get("below_before") if rec.get("scoring") == "rubber" else None
    score = Score.from_rubber(below, vul) if below is not None else None
    people = set(SEATS) - set(rec.get("bots") or [])
    review = rec["review"]
    old = {(b.get("index"), b.get("system_call")): b for b in review.get("bidding") or []}
    new = []
    for b in bidding_review(engine, rec.get("dealer") or "N", list(rec["calls"]), hands, people, score, vul):
        kept = old.get((b["index"], b["system_call"]))
        new.append(kept if kept is not None else b)
    if [id(b) for b in new] == [id(b) for b in review.get("bidding") or []]:
        return False
    review["bidding"] = new
    add_outcomes(rec, engine, score)
    add_averages(review, engine, hands, rec.get("dealer") or "N", list(rec["calls"]), vul, score, below,
                 rng or random.Random(f"{rec.get('finished_at')}-{rec.get('room')}-{rec.get('board')}"))
    return True


async def run(accounts, pause: float = PAUSE) -> int:
    """Check every saved board against today's rules. Returns how many boards changed."""
    store = accounts.store
    if ((await asyncio.to_thread(store.get, *DONE)) or {}).get("rules", 0) >= RULES:
        return 0
    with timings.working("Checking saved boards against new bidding rules"):  # for the Admin page's Load tab
        loop = asyncio.get_running_loop()
        changed = 0
        for user in await asyncio.to_thread(accounts.all_users):
            uid = user["id"]
            for rec in await asyncio.to_thread(accounts.boards, uid):
                if not needs(rec):
                    continue
                key = rec.pop("key")
                try:
                    if await loop.run_in_executor(None, recheck, rec):
                        changed += 1
                        await asyncio.sleep(pause)
                except Exception as exc:  # not again: the board keeps the review it had
                    log.warning("could not check %s %s against today's rules: %s", uid, key, exc)
                    rec["rules"] = RULES
                await asyncio.to_thread(accounts.update_board, uid, key, rec)
        await asyncio.to_thread(store.put, *DONE, {"rules": RULES, "changed": changed})
        log.info("saved boards checked against bidding rules %d: %d changed", RULES, changed)
        return changed
