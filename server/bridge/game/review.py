"""Post-hand review: where tricks were lost against double-dummy, and which
calls differed from what the system would have bid with the same hand."""
from __future__ import annotations

from ..solver import solve_all_boards
from endplay.types import Deal, Denom, Player

from ..bidding.engine import BiddingEngine
from ..bidding.partscore import Score
from ..core.auction import Auction, Contract
from ..core.cards import SEATS, Hand, partner, rank_value, same_side

_DENOM = {"S": Denom.spades, "H": Denom.hearts, "D": Denom.diamonds, "C": Denom.clubs,
          "N": Denom.nt}
_PLAYER = {"N": Player.north, "E": Player.east, "S": Player.south, "W": Player.west}
_SUIT_CHAR = {Denom.spades: "S", Denom.hearts: "H", Denom.diamonds: "D", Denom.clubs: "C"}


def _card_str(card) -> str:
    return _SUIT_CHAR[card.suit] + card.rank.name[1]


def _tricks_for(per: dict[str, int], card: str) -> int:
    """DDS may leave out a card equivalent to one it listed: use the nearest in suit."""
    if card in per:
        return per[card]
    same = [x for x in per if x[0] == card[0]]
    return per[min(same, key=lambda x: abs(rank_value(x) - rank_value(card)))] if same else 0


def play_review(hands: dict[str, Hand], contract: Contract,
                play: list[tuple[str, str]], human_seats: set[str] | None = None) -> dict:
    """Double-dummy cost of every card played.

    For each card, the position just before it is solved; `lost` is how many
    tricks the player's side gave up compared with the best card there. Dummy's
    cards are charged to declarer, who chose them. When a bot declares opposite a person, the person plays both
    hands (see Table.controller_of), so both hands' cards are charged to them.
    """
    pbn = "N:" + " ".join(hands[s].to_pbn() for s in SEATS)
    leader = SEATS[(SEATS.index(contract.declarer) + 1) % 4]
    positions: list[Deal] = []
    deal = Deal.from_pbn(pbn)
    deal.trump = _DENOM[contract.strain]
    deal.first = _PLAYER[leader]
    for _, card in play:
        positions.append(deal.copy())
        deal.play(card)
    solved = solve_all_boards(positions) if positions else []

    dummy = partner(contract.declarer)
    plays_both = contract.declarer
    if human_seats is not None and contract.declarer not in human_seats and dummy in human_seats:
        plays_both = dummy
    cards = []
    for i, ((seat, card), result) in enumerate(zip(play, solved)):
        per = {_card_str(c): t for c, t in result}
        best = max(per.values()) if per else 0
        got = _tricks_for(per, card)
        best_cards = sorted((c for c, t in per.items() if t == best),
                            key=lambda c: ("SHDC".index(c[0]), -rank_value(c)))
        chooser = plays_both if seat in (contract.declarer, dummy) else seat
        cards.append({
            "trick": i // 4 + 1, "seat": seat, "by": chooser, "card": card,
            "lost": best - got,
            "reach": best,  # tricks the side to play could still take, all cards seen
            "best": best_cards if best > got else [],
            "role": "declarer" if same_side(seat, contract.declarer) else "defence",
        })
    _given_back(cards, contract.declarer)
    _gave_back_later(cards, contract.declarer)
    # tricks declarer can take with best play from the opening lead on
    start = max((t for _, t in solved[0]), default=0) if solved else 0
    dd_declarer = 13 - start  # solved[0] is from the opening leader's side
    lost_by = {s: sum(c["lost"] for c in cards if c["by"] == s) for s in SEATS}
    return {"cards": cards, "dd_declarer_tricks": dd_declarer, "lost_by": lost_by}


def _given_back(cards: list[dict], declarer: str) -> None:
    """A costly card the other side gave straight back, with a costly card of their own before this side played
    again, cost nothing in the end (for example, South's ♦2 cost a trick only if West ducked, and West
    took the ace). Both get `back`, the tricks netted out, so the review charges neither; the first also gets
    `given_back`, the card that gave it back. `lost` stays the double-dummy cost, which My stats counts."""
    for i, c in enumerate(cards):
        left = c["lost"] - c.get("back", 0)
        ours = same_side(c["seat"], declarer)
        for d in cards[i + 1:]:
            if left <= 0 or same_side(d["seat"], declarer) == ours:
                break
            gift = d["lost"] - d.get("back", 0)
            if gift > 0:
                n = min(left, gift)
                c["back"] = c.get("back", 0) + n
                d["back"] = d.get("back", 0) + n
                c["given_back"] = {"card": d["card"], "by": d["by"], "seat": d["seat"]}
                left -= n


def _gave_back_later(cards: list[dict], declarer: str) -> None:
    """A costly card still charged after `_given_back` whose trick the other side handed back a little later, by the
    end of the next trick and before this side cost another, gets `later_back` (the card, who chose it and its trick).
    Nothing is netted: the card was still the worse bet, but the review says why the result came out fine anyway
    (for example, the ♦Q finesse lost and West's ♥5 at trick 8 gave the trick back)."""
    for i, c in enumerate(cards):
        if c["lost"] - c.get("back", 0) <= 0:
            continue
        ours = same_side(c["seat"], declarer)
        for d in cards[i + 1:]:
            if d["trick"] > c["trick"] + 1:
                break
            if d["lost"] - d.get("back", 0) <= 0:
                continue
            if same_side(d["seat"], declarer) == ours:
                break
            c["later_back"] = {"card": d["card"], "by": d["by"], "seat": d["seat"], "trick": d["trick"]}
            break


def bidding_review(engine: BiddingEngine, dealer: str, calls: list[str],
                   hands: dict[str, Hand], seats: set[str], score: Score | None = None,
                   vulnerability: str | None = None) -> list[dict]:
    """Calls by `seats` that differ from the system's choice with the same hand.

    `minor` marks a sensible alternative: a bid (not a pass where the system bids, or the other way round) that the
    system itself allows with this hand, just not as its first choice. The review hides those unless asked."""
    out = []
    auction = Auction(dealer)
    for i, call in enumerate(calls):
        seat = auction.next_to_call
        if seat in seats:
            dec = engine.choose(hands[seat], auction, score, vulnerability)
            if dec.call != call:
                minor = "P" not in (call, dec.call) and engine.fits(hands[seat], auction, call)
                out.append({
                    "index": i, "seat": seat, "call": call,
                    "meaning": engine.explain_next(auction, call).text,
                    "system_call": dec.call, "minor": minor,
                    "system_meaning": dec.text,
                    "convention": dec.rule.module if dec.rule else None,
                })
        auction.add(call)
    return out


def board_review(engine: BiddingEngine, hands: dict[str, Hand], dealer: str,
                 calls: list[str], contract: Contract | None,
                 play: list[tuple[str, str]], human_seats: set[str], score: Score | None = None,
                 vulnerability: str | None = None) -> dict:
    return {
        "bidding": bidding_review(engine, dealer, calls, hands, human_seats, score, vulnerability),
        "play": play_review(hands, contract, play, human_seats) if contract and play else None,
    }


# --- for an AI coach: the choices behind the final board -------------------------------------------------------------
def take_back_note(t, asked: list[list]) -> dict | None:
    """What Undo is about to take back on table `t`: the last call or card a person made, with the position it was made
    in, so the review can still say what that first choice was worth. None for a claim, or when nothing can go."""
    humans = [i for i, (who, _, _) in enumerate(t.actions) if who not in t.bot_seats]
    if not humans:
        return None
    i = humans[-1]
    who, kind, what = t.actions[i]
    before = t.actions[:i]
    help_ = sorted({k for _, n, k in asked if n == i})
    if kind == "call":
        calls = [w for _, k, w in before if k == "call"]
        seat = Auction(t.dealer, list(calls)).next_to_call
        return {"kind": "call", "seat": seat, "by": who, "call": what, "calls_before": calls, "asked": help_}
    if kind == "card" and t.play and t.contract:
        n = sum(1 for _, k, _ in before if k == "card")
        played = t.play.played_cards()
        if n >= len(played):
            return None
        return {"kind": "card", "seat": played[n][0], "by": who, "card": what,
                "play_before": [list(x) for x in played[:n]], "contract": t.contract.to_dict(), "asked": help_}
    return None


def asked_marks(actions: list[tuple[str, str, str]], asked: list[list]) -> list[dict]:
    """Which of the board's final calls and cards came right after the player asked for a hint or their AI coach:
    [{"kind": "call" or "card", "index": its place in the auction or the play, "seat": who asked, "asked": [...]}]."""
    out: dict[int, dict] = {}
    counts = {"call": 0, "card": 0, "claim": 0}
    places = []
    for _, kind, _ in actions:
        places.append((kind, counts[kind]))
        counts[kind] += 1
    for seat, n, what in asked:
        if n < len(places) and places[n][0] in ("call", "card"):
            row = out.setdefault(n, {"kind": places[n][0], "index": places[n][1], "seat": seat, "asked": []})
            if what not in row["asked"]:
                row["asked"].append(what)
    return [out[n] for n in sorted(out)]


def undone_review(engine: BiddingEngine, t, undone: list[dict]) -> list[dict]:
    """The calls and cards people took back with Undo on this board: a call with the system's choice for that hand.
    `then` is what they chose instead, when the board went on from the same position. What each card was worth is
    filled in later by solve_undone, with the review's odds, so it never holds up a bot or a hint."""
    out = []
    final_calls = list(t.auction.calls)
    final_play = [list(x) for x in t.play.played_cards()] if t.play else []
    for u in undone:
        row = {k: u[k] for k in ("kind", "seat", "by", "asked")}
        if u["kind"] == "call":
            before = list(u["calls_before"])
            row["call"], row["calls_before"] = u["call"], before
            try:
                dec = engine.choose(t.hands[u["seat"]], Auction(t.dealer, before), t.score, t.vulnerability)
                row["system_call"] = dec.call
                row["system_meaning"] = dec.text
                row["meaning"] = engine.explain_next(Auction(t.dealer, before), u["call"]).text
            except Exception:  # a meaning is a bonus
                pass
            if final_calls[:len(before)] == before and len(final_calls) > len(before):
                row["then"] = final_calls[len(before)]
        else:
            before = u["play_before"]
            row["card"], row["trick"], row["contract"] = u["card"], len(before) // 4 + 1, u["contract"]
            row["play_before"] = before
            if final_play[:len(before)] == before and len(final_play) > len(before):
                row["then"] = final_play[len(before)][1]
        out.append(row)
    return out


def solve_undone(hands: dict[str, Hand], rows: list[dict]) -> None:
    """Each card taken back gets its double-dummy cost from the position it was played in (`lost`, `best`)."""
    cards = [r for r in rows if r["kind"] == "card" and "lost" not in r]
    positions = []
    for row in cards:
        c = row["contract"]
        leader = SEATS[(SEATS.index(c["declarer"]) + 1) % 4]
        deal = Deal.from_pbn("N:" + " ".join(hands[s].to_pbn() for s in SEATS))
        deal.trump = _DENOM[c["strain"]]
        deal.first = _PLAYER[leader]
        for _, card in row["play_before"]:
            deal.play(card)
        positions.append(deal)
    try:
        solved = solve_all_boards(positions) if positions else []
    except Exception:  # the cost is a bonus
        solved = []
    for row, result in zip(cards, solved):
        per = {_card_str(c): n for c, n in result}
        best = max(per.values()) if per else 0
        row["lost"] = best - _tricks_for(per, row["card"])
        row["best"] = sorted((c for c, n in per.items() if n == best),
                             key=lambda c: ("SHDC".index(c[0]), -rank_value(c))) if row["lost"] else []
