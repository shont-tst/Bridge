"""Finds the deals for Learn to play steps 4 and 5, checked with the double-dummy solver, and writes them to
web/src/tutorial/deals.json. Run from server/:  python -m scripts.tutorial_deals

Each lesson has a test on the four hands and a contract. A deal is kept only when the solver agrees it teaches the
idea: as declarer (step 4) the contract makes exactly, with too few sure winners to make it without the lesson's
technique; on defense (step 5) the contract can just be beaten. tests/test_tutorial_deals.py checks the file again.
"""
from __future__ import annotations

import json
import random
from pathlib import Path

from endplay.dds import calc_dd_table, solve_board
from endplay.types import Deal, Denom, Player

RANKS = "23456789TJQKA"
SEATS = "NESW"
DENOM = {"S": Denom.spades, "H": Denom.hearts, "D": Denom.diamonds, "C": Denom.clubs, "N": Denom.nt}
PLAYER = {"N": Player.north, "E": Player.east, "S": Player.south, "W": Player.west}
OUT = Path(__file__).resolve().parents[2] / "web" / "src" / "tutorial" / "deals.json"
PER_LESSON = 4


def rank(c: str) -> int:
    return RANKS.index(c[1])


def suit(cards, s):
    return [c for c in cards if c[0] == s]


def hcp(cards) -> int:
    return sum(max(0, rank(c) - 8) for c in cards)


def deal(rng: random.Random) -> dict[str, list[str]]:
    deck = [s + r for s in "SHDC" for r in RANKS]
    rng.shuffle(deck)
    return {p: deck[i * 13:(i + 1) * 13] for i, p in enumerate(SEATS)}


def to_endplay(h: dict[str, list[str]]) -> Deal:
    pbn = lambda cards: ".".join("".join(sorted((c[1] for c in cards if c[0] == s), key=lambda r: -RANKS.index(r)))
                                 for s in "SHDC")
    return Deal("N:" + " ".join(pbn(h[p]) for p in SEATS))


def dd(h, trump: str, declarer: str) -> int:
    return calc_dd_table(to_endplay(h))[DENOM[trump], PLAYER[declarer]]


def lead_tricks(h, trump: str, leader: str) -> dict[str, int]:
    """Tricks the leader's side takes after each possible opening lead."""
    d = to_endplay(h)
    d.trump, d.first = DENOM[trump], PLAYER[leader]
    return {f"{'SHDC'[c.suit.value]}{str(c)[-1]}": n for c, n in solve_board(d)}


def top_tricks(a, b) -> int:
    total = 0
    for s in "SHDC":
        both = {rank(c) for c in suit(a, s) + suit(b, s)}
        n, r = 0, 12
        while r in both:
            n, r = n + 1, r - 1
        total += min(n, max(len(suit(a, s)), len(suit(b, s))))
    return total


def balanced(cards) -> bool:
    lens = sorted(len(suit(cards, s)) for s in "SHDC")
    return lens[0] >= 2 and lens.count(2) <= 1 and lens[3] <= 5


def fit(a, b) -> str:
    """The pair's longest suit with 8+ cards (a major on a tie), else N."""
    fits = sorted(((len(suit(a, s)) + len(suit(b, s)), s in "HS", s) for s in "SHDC"), reverse=True)
    return fits[0][2] if fits[0][0] >= 8 else "N"


def needed(trump: str, pts: int) -> int:
    return 7 if pts < 25 else 9 if trump == "N" else 10 if trump in "HS" else 11


def finesse_suit(h):
    """A suit where South holds A-Q (no K, J), North has 2+ small cards, and East holds the K: lead toward A-Q."""
    for s in "SHDC":
        ss, nn = [c[1] for c in suit(h["S"], s)], [c[1] for c in suit(h["N"], s)]
        if "A" in ss and "Q" in ss and "K" not in ss and "J" not in ss and len(nn) >= 2 and not set(nn) & set("KQJT") \
                and s + "K" in h["E"]:
            return s
    return None


def long_suit(h, trump):
    """A side suit North and South can set up: 8+ cards together, 5+ in one hand, missing an honor, the rest 3-2."""
    for s in "SHDC":
        if s == trump:
            continue
        n, ss = suit(h["N"], s), suit(h["S"], s)
        opp = suit(h["E"], s) + suit(h["W"], s)
        if len(n) + len(ss) >= 8 and max(len(n), len(ss)) >= 5 and sorted([len(suit(h["E"], s)), len(suit(h["W"], s))]) == [2, 3] \
                and any(c[1] in "KQ" for c in opp) and not any(c[1] == "A" for c in opp):
            return s
    return None


def ruff_suit(h, trump):
    """A side suit where dummy (North) has 0-1 cards and South has 2+ losers, with dummy holding 3+ trumps."""
    if trump == "N" or len(suit(h["N"], trump)) < 3:
        return None
    for s in "SHDC":
        if s != trump and len(suit(h["N"], s)) <= 1 and len(suit(h["S"], s)) >= 3 and not any(c[1] in "AK" for c in suit(h["S"], s)):
            return s
    return None


def sequence(cards):
    """South's suit headed by three touching honors (K-Q-J, Q-J-10) without the card above, as (suit, top card)."""
    for s in "SHDC":
        rs = {c[1] for c in suit(cards, s)}
        for top, a, b, above in (("K", "Q", "J", "A"), ("Q", "J", "T", "K")):
            if top in rs and a in rs and b in rs and above not in rs:
                return s, s + top
    return None


# --- the lessons -------------------------------------------------------------------------------------------------
def declarer_lesson(test, trump_of, top_gap):
    """South declares; the contract makes exactly; sure winners fall short by `top_gap` (a range)."""
    def check(h):
        if hcp(h["S"]) <= hcp(h["N"]) or hcp(h["N"]) + hcp(h["S"]) < 21:
            return None
        trump = trump_of(h)
        if trump is None:
            return None
        need = needed(trump, hcp(h["N"]) + hcp(h["S"]))
        gap = need - top_tricks(h["S"], h["N"])
        if gap not in top_gap or not test(h, trump):
            return None
        if dd(h, trump, "S") != need:
            return None
        return {"declarer": "S", "trump": trump, "needed": need}
    return check


def defense_lesson(test, declarer):
    """East or West declares; the side's best contract, which good defense beats by one trick."""
    def check(h):
        d, dummy = declarer, "W" if declarer == "E" else "E"
        if hcp(h[d]) <= hcp(h[dummy]) or hcp(h["E"]) + hcp(h["W"]) < 22:
            return None
        trump = fit(h[d], h[dummy])
        need = needed(trump, hcp(h["E"]) + hcp(h["W"]))
        if not test(h, trump) or dd(h, trump, d) != need - 1:
            return None
        return {"declarer": d, "trump": trump, "needed": need}
    return check


def top_of_sequence(h, trump):
    seq = sequence(h["S"])
    if not seq or seq[0] == trump:
        return False
    # South leads (East declares): the top of the sequence beats it, a low card from another suit doesn't
    tricks = lead_tricks(h, trump, "S")
    beat = 13 - needed(trump, hcp(h["E"]) + hcp(h["W"])) + 1
    return tricks.get(seq[1], 0) >= beat and min(tricks.values()) < beat


def second_hand(h, trump):
    # South holds K-x-x or Q-x-x behind declarer's suits, and East (declarer, with dummy West) will lead through it
    return any(len(suit(h["S"], s)) == 3 and {c[1] for c in suit(h["S"], s)} & {"K", "Q"} and s != trump for s in "SHDC")


def third_hand(h, trump):
    # North leads (West declares) from a suit where South holds an honor to play third hand high
    return any(len(suit(h["N"], s)) >= 4 and {c[1] for c in suit(h["S"], s)} & {"A", "K", "Q"} and s != trump for s in "SHDC")


LESSONS = {
    "4.1": declarer_lesson(lambda h, t: t == "N" and balanced(h["S"]), lambda h: fit(h["S"], h["N"]) if fit(h["S"], h["N"]) == "N" else None, range(0, 1)),
    "4.2": declarer_lesson(lambda h, t: long_suit(h, t) is not None, lambda h: "N" if fit(h["S"], h["N"]) in "DCN" else None, range(1, 3)),
    "4.3": declarer_lesson(lambda h, t: finesse_suit(h) is not None, lambda h: fit(h["S"], h["N"]), range(1, 2)),
    "4.4": declarer_lesson(lambda h, t: ruff_suit(h, t) is not None, lambda h: fit(h["S"], h["N"]) if fit(h["S"], h["N"]) in "HS" else None, range(1, 3)),
    "4.5": declarer_lesson(lambda h, t: True, lambda h: fit(h["S"], h["N"]), range(2, 4)),
    "5.1": defense_lesson(top_of_sequence, "E"),
    "5.2": defense_lesson(second_hand, "E"),
    "5.3": defense_lesson(third_hand, "W"),
    "5.4": defense_lesson(third_hand, "W"),
}


def main(seed: int = 2026, only: list[str] | None = None) -> None:
    rng = random.Random(seed)
    out: dict[str, list] = json.loads(OUT.read_text()) if only and OUT.exists() else {}
    for key, check in LESSONS.items():
        if only and key not in only:
            continue
        found = []
        tries = 0
        while len(found) < PER_LESSON and tries < 400_000:
            tries += 1
            h = deal(rng)
            got = check(h)
            if got:
                found.append({"hands": {p: " ".join(sorted(h[p])) for p in SEATS}, **got})
        print(key, len(found), "deals after", tries, "tries")
        out[key] = found
    OUT.write_text(json.dumps(out, indent=1) + "\n")
    print("wrote", OUT)


if __name__ == "__main__":
    import sys
    main(only=sys.argv[1:] or None)
