"""What kind of card each costly card was, for an AI coach looking for patterns across many boards (the connector's
mistake_patterns tool).

Every card a player chose is sorted by what it did in its trick: the opening lead, a later lead, following suit, a
ruff or a discard, and whether trumps were involved. A few simple counting checks flag a costly card that suggests the
player lost track of the cards:

- "trumps_out": declarer's side led a trump when the opponents had none left.
- "threw_winner": a discard of the highest card left in its suit (a sure winner).
- "ruffed_partners_winner": a ruff of a trick partner was already winning.

All of it comes from the saved board (hands, play and the app's double-dummy review): nothing is guessed.
"""
from __future__ import annotations

from .core.cards import SEATS, partner, rank_value, same_side

KINDS = ("opening lead", "lead", "follow", "ruff", "discard")


def _hands(rec: dict) -> dict[str, set[str]]:
    out = {}
    for s in SEATS:
        pbn = (rec.get("hands") or {}).get(s) or ""
        cards = set()
        for suit, ranks in zip("SHDC", pbn.split(".") if pbn else []):
            cards |= {suit + r for r in ranks}
        out[s] = cards
    return out


def _winning(trick: list, trump: str | None) -> str:
    """The seat winning a (possibly unfinished) trick so far."""
    led = trick[0][1][0]
    return max(trick, key=lambda sc: (sc[1][0] == trump, sc[1][0] == led, rank_value(sc[1])))[0]


def card_kinds(rec: dict) -> list[dict]:
    """For each card played on a saved board: {"kind", "trumps", "checks"}, in play order."""
    c = rec.get("contract")
    play = [tuple(x) for x in rec.get("play") or []]
    if not c or not play:
        return []
    trump = None if c["strain"] == "N" else c["strain"]
    left = _hands(rec)
    out = []
    for i, (seat, card) in enumerate(play):
        start = i - i % 4
        trick = play[start:i]
        suit = card[0]
        checks = []
        if not trick:
            kind = "opening lead" if i == 0 else "lead"
            opps = [s for s in SEATS if not same_side(s, c["declarer"])]
            if (trump and suit == trump and same_side(seat, c["declarer"])
                    and not any(x[0] == trump for s in opps for x in left[s])):
                checks.append("trumps_out")
        elif suit == trick[0][1][0]:
            kind = "follow"
        elif trump and suit == trump:
            kind = "ruff"
            if _winning(trick, trump) == partner(seat) and len(trick) >= 2:
                checks.append("ruffed_partners_winner")
        else:
            kind = "discard"
            higher = [x for s in SEATS for x in left[s] if x[0] == suit and rank_value(x) > rank_value(card)]
            if not higher:
                checks.append("threw_winner")
        out.append({"kind": kind, "trumps": bool(trump) and (suit == trump or (bool(trick) and trick[0][1][0] == trump)),
                    "checks": checks})
        left[seat].discard(card)
    return out


def costly_cards(rec: dict, seat: str) -> tuple[list[dict], dict[str, int]]:
    """The costly cards chosen by the player in `seat` or their bot partner, each sorted by kind, and how many cards
    of each kind the player chose on the board (so a coach can give rates, not just counts)."""
    review = (rec.get("review") or {}).get("play") or {}
    cards = review.get("cards") or []
    kinds = card_kinds(rec)
    if not cards or len(kinds) != len(cards):
        return [], {}
    bots = set(rec.get("bots") or [])
    asked = {m["index"]: m["asked"] for m in rec.get("asked") or [] if m.get("kind") == "card"}
    mine: dict[str, int] = {}
    out = []
    for i, (x, k) in enumerate(zip(cards, kinds)):
        if x["by"] == seat:
            mine[k["kind"]] = mine.get(k["kind"], 0) + 1
        whose = "you" if x["by"] == seat else "bot partner" if x["by"] == partner(seat) and x["by"] in bots else None
        if not whose or x.get("lost", 0) <= 0:
            continue
        o = x.get("odds")
        verdict = None
        if o:
            verdict = "mistake" if o.get("better", o.get("best") != x["card"] and o.get("best_pct", 0) > o.get("played", 0)) \
                else "unlucky"
        out.append({"trick": x["trick"], "card": x["card"], "whose": whose, "lost": x["lost"], "verdict": verdict,
                    "best": x.get("best") or [], **k, "asked": asked.get(i, [])})
    return out, mine


def _rank(r: str) -> int:
    return "23456789TJQKA".index(r)


def lead_info(rec: dict, seat: str) -> dict | None:
    """The opening lead, when the player in `seat` made it: what it was led from, and what it cost."""
    c = rec.get("contract")
    play = rec.get("play") or []
    if not c or not play or play[0][0] != seat:
        return None
    card = play[0][1]
    suit = card[0]
    pbn = (rec.get("hands") or {}).get(seat) or ""
    holding = dict(zip("SHDC", pbn.split("."))).get(suit, "")
    ranks = sorted(holding, key=_rank, reverse=True)
    r = card[1]
    n = len(ranks)
    trump = None if c["strain"] == "N" else c["strain"]
    if n == 1:
        kind = "singleton"
    elif trump and suit == trump:
        kind = "trump lead"
    elif "A" in ranks and r != "A" and trump:
        kind = "underled an ace"
    elif n >= 2 and ranks[0] == "A" and ranks[1] == "K" and r in "AK":
        kind = "from ace-king"
    elif ranks.index(r) == 0 and n >= 2 and _rank(ranks[0]) - _rank(ranks[1]) == 1 and _rank(r) >= _rank("T"):
        kind = "top of a sequence"
    elif n == 2:
        kind = "from a doubleton"
    elif ranks.index(r) == 0 and _rank(r) < _rank("T"):
        kind = "top of nothing"
    elif n >= 4 and ranks.index(r) == 3:
        kind = "fourth best"
    elif ranks.index(r) == n - 1 and any(_rank(x) >= _rank("J") for x in ranks):
        kind = "low from an honor"
    else:
        kind = "other"
    cards = ((rec.get("review") or {}).get("play") or {}).get("cards") or []
    lost = cards[0]["lost"] if cards else None
    return {"card": card, "holding": suit + "".join(ranks), "kind": kind, "against": "NT" if not trump else "suit",
            "lost": lost, "best": (cards[0].get("best") or []) if cards else []}
