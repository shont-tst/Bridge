"""The second table for boards saved before it existed (game/second.py), worked out once in the background.

After a start, every saved board without a second table gets one, oldest player first, a board at a time at the
solver's lowest urgency with a pause between boards, so tables in play aren't held up. A board done is saved with it
(`review.second`), so a restart carries on where it stopped, and once every board has one, a config row
(`second_backfill`) skips the scan. A board that can't be replayed is saved with an empty one, so it isn't tried again.
Old boards are replayed with today's bots, at the strength the table had then.
"""
from __future__ import annotations

import asyncio
import logging
import random

from .bidding.conventions import make_engine
from .bidding.partscore import Score
from .core.auction import Contract
from .core.cards import SEATS, Hand
from .game.second import fill_split, second_table
from .stats import board_facts, rebuild_part_scores

log = logging.getLogger("bridge.backfill")
DONE = ("config", "cfg", "second_backfill")
PAUSE = 2.0  # seconds between boards


def needs(rec: dict) -> bool:
    review = rec.get("review")
    return (isinstance(review, dict) and "second" not in review and "error" not in review and bool(rec.get("hands"))
            and not rec.get("tutorial") and rec.get("seat") in SEATS)


def replay(rec: dict) -> dict:
    """The second table for one saved board, from what the record kept."""
    seat = rec["seat"]
    engine = make_engine(set(rec["conventions"]) if "conventions" in rec else None)
    hands = {s: Hand.from_pbn(h) for s, h in rec["hands"].items()}
    vul = rec.get("vulnerability") or "None"
    below = rec.get("below_before") if rec.get("scoring") == "rubber" else None
    score = Score.from_rubber(below, vul) if below is not None else None
    c = rec.get("contract")
    contract = Contract(c["level"], c["strain"], c["declarer"], int(c.get("doubled") or 0)) if c else None
    people = set(SEATS) - set(rec.get("bots") or [])
    return second_table(engine, hands, rec.get("dealer") or "N", vul, score, seat, people | {seat},
                        int(rec.get("difficulty") or 6), rec.get("signals"), rec.get("leads", True), below, contract,
                        int(rec.get("declarer_tricks") or 0),
                        random.Random(f"{rec.get('finished_at')}-{rec.get('room')}-{rec.get('board')}-{seat}"))


async def run(accounts, pause: float = PAUSE) -> int:
    """Fill in every saved board's second table. Returns how many boards it did."""
    store = accounts.store
    if await asyncio.to_thread(store.get, *DONE):
        return 0
    loop = asyncio.get_running_loop()
    done = 0
    for user in await asyncio.to_thread(accounts.all_users):
        uid = user["id"]
        records = await asyncio.to_thread(accounts.boards, uid)
        rebuild_part_scores(records)  # boards saved before 1.93 didn't keep the rubber's part score
        for rec in reversed(records):  # oldest first
            if not needs(rec):
                continue
            key = rec.pop("key")
            try:
                out = await loop.run_in_executor(None, replay, rec)
                rec["review"]["second"] = {rec["seat"]: out}
                fill_split(rec)
            except Exception as exc:  # not again: an empty one says it was tried
                log.warning("could not play the second table for %s %s: %s", uid, key, exc)
                rec["review"]["second"] = {}
            await asyncio.to_thread(accounts.update_board, uid, key, rec)
            done += 1
            await asyncio.sleep(pause)
    await asyncio.to_thread(store.put, *DONE, {"boards": done})
    log.info("second tables worked out for %d saved boards", done)
    return done
