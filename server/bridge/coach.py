"""Hand sheets for an AI coach: what the connector (connector.py) hands to the player's own AI assistant (Claude, ChatGPT, ...).

The AI explains; it doesn't solve. Everything a sheet says about the cards comes from the app itself: the double-dummy
review, the Mistake/Unlucky odds, the system's meaning of each call. A sheet only ever holds what the player may see:
their own finished boards, and the board they're playing as their seat sees it, only at tables that allow AI coaching
during play (everyone at the table is told, and each question asked on the player's turn is counted in the review).
"""
from __future__ import annotations

from functools import lru_cache

from . import site
from .bidding.conventions import make_engine
from .bots.signals import METHODS

from .core.auction import Auction
from .core.cards import SEATS, partner, rank_value
from .game.second import fill_split
from .stats import board_facts

SUIT = {"S": "♠", "H": "♥", "D": "♦", "C": "♣", "N": "NT"}
SEAT = {"N": "North", "E": "East", "S": "South", "W": "West"}
CALL = {"P": "Pass", "X": "Double", "XX": "Redouble"}
# The table's defensive signals, for the coach: high encourages (standard) or low encourages (upside-down)
SIGNAL_NAMES = {m: f"{name} attitude, count and suit preference" for m, name in METHODS.items()}
LEADS_NAME = ("Standard leads: top of a sequence, ace from ace-king, an ace against a suit contract rather than lead "
              "away from it, top of two cards, low from three to an honor, top of three small, fourth best from four "
              "or more")

# What the AI is told when it connects (the MCP "instructions"), so it coaches the way the app does.
INSTRUCTIONS = """You are coaching a player of {name}, a bridge app where people play with and against bots.
Use these tools to see the player's hands. Explain in plain, friendly words, as a patient bridge teacher would.

- Trust the facts in the tools. "dd" figures are double-dummy (every card seen); "odds" are how often a card works
  on the layouts that fit what the player could see. A card marked "mistake" was the worse bet at the time; one marked
  "unlucky" was as good a bet or better and the cards just lay badly. Never invent your own analysis of where the
  cards are, and never second-guess the double-dummy numbers.
- The bidding follows the No Fear Bridge cheat sheet (Standard American, 15-17 1NT, 5-card majors), plus any
  conventions listed for the table. Each call comes with what it meant in this system: explain from that.
  defensive_signals says how the table's defenders signal (none, Standard, or Upside-down). opening_leads says
  whether the table leads by Standard leads (top of a sequence, fourth best from four or more, and so on).
- Finished boards are the heart of it: help the player understand what happened and what to look for next time.
- During a board, current_board shows only what the player's seat sees, and only if their table allows AI coaching.
  Never guess at hidden cards; talk about what the auction and the visible cards suggest and how to think the decision
  through. app_hint gives the app's own suggestion and odds (it counts as a hint): use it rather than your own card
  analysis when the player wants to know what to play. Questions on the player's turn show up in their review.
- To find patterns over many boards, start with coaching_overview, then mistake_patterns and bidding_history, and
  open example boards with board_reviews. Call something a pattern only with enough examples (about 10 or more) and
  say how many it rests on; compare rates with the bot benchmarks rather than with zero; quote two or three real
  boards for each tip; and suggest one thing to work on at a time. Calls and cards marked you_asked_first came right
  after a hint or an AI coach question, so they aren't a fair sample of the player's own judgment;
  first_choices_taken_back are the honest first tries they took back with Undo.
- The second table (second_table, second_* and *_imps fields) is the same deal played again with a level 10 bot in
  the player's seat and the other seats as at their table, scored in IMPs as at a team match: plus means the player
  did better. The bidding's share scores both contracts double dummy; the play's share is the rest, split into
  declaring and defending. One board says more about the cards than the player; read the averages over many boards.
- coaching_notes holds what the player is working on. Read it at the start, check whether that area got better since
  the note's date, and add or remove a note only when the player agrees.
- Write suits as symbols (♠ ♥ ♦ ♣), not letters, and use American spelling. Keep answers short unless asked for more:
  the player may be listening by voice at the table."""


def instructions() -> str:
    """INSTRUCTIONS with this site's name (BRIDGE_APP_NAME)."""
    return INSTRUCTIONS.replace("{name}", site.app_name())


def card(c: str) -> str:
    """"SA" -> "♠A", "HT" -> "♥10"."""
    return SUIT[c[0]] + ("10" if c[1] == "T" else c[1])


def call_text(c: str) -> str:
    """"1N" -> "1NT", "4H" -> "4♥", "P" -> "Pass"."""
    return CALL[c] if c in CALL else c[0] + SUIT[c[1:]]


def hand_text(pbn_or_cards) -> str:
    """A hand as "♠AK52 ♥Q10 ♦J873 ♣64", from a PBN string ("AK52.QT.J873.64") or a list of cards."""
    if isinstance(pbn_or_cards, str):
        suits = pbn_or_cards.split(".")
    else:
        suits = ["".join(c[1] for c in pbn_or_cards if c[0] == s) for s in "SHDC"]
    return " ".join(SUIT[s] + (h.replace("T", "10") or "—") for s, h in zip("SHDC", suits))


def contract_text(c: dict | None) -> str | None:
    if not c:
        return None
    x = {1: " doubled", 2: " redoubled"}.get(int(c.get("doubled") or 0), "")
    return f"{c['level']}{SUIT[c['strain']]}{x} by {SEAT[c['declarer']]}"


def _auction(dealer: str, calls: list[str], conventions: list[str] | None,
             asked: dict[int, list[str]] | None = None) -> list[dict]:
    """Each call with what it meant in the table's system, and whether the player asked for help before making it."""
    engine = _engine(tuple(sorted(conventions)) if conventions is not None else None)
    auction = Auction(dealer, list(calls))
    out = []
    for i, (seat, c) in enumerate(auction.with_seats()):
        try:
            meaning = engine.explain(auction, i).text
        except Exception:  # an explanation is a bonus
            meaning = ""
        out.append({"seat": SEAT[seat], "call": call_text(c), **({"meaning": meaning} if meaning else {}),
                    **({"you_asked_first": _asked(asked[i])} if asked and i in asked else {})})
    return out


@lru_cache(maxsize=16)
def _engine(conventions: tuple[str, ...] | None):
    return make_engine(set(conventions) if conventions is not None else None)


ASKED = {"hints": "hint", "coach": "AI coach question"}


def _asked(kinds: list[str]) -> list[str]:
    return [ASKED.get(k, k) for k in kinds]


def _tricks(play: list, trump: str | None, asked: dict[int, list[str]] | None = None) -> list[dict]:
    """The play, trick by trick: who led, each card by seat, who won it, and which cards came after a hint or an AI
    coach question."""
    out = []
    for i in range(0, len(play), 4):
        trick = play[i:i + 4]
        row = {"trick": i // 4 + 1, "led_by": SEAT[trick[0][0]], "cards": [f"{SEAT[s]} {card(c)}" for s, c in trick]}
        helped = [f"{SEAT[s]} {card(c)} (after a {' and '.join(_asked(asked[i + j]))})"
                  for j, (s, c) in enumerate(trick) if asked and i + j in asked]
        if helped:
            row["you_asked_first"] = helped
        if len(trick) == 4:
            led = trick[0][1][0]
            win = max(trick, key=lambda sc: (sc[1][0] == trump, sc[1][0] == led, rank_value(sc[1])))
            row["won_by"] = SEAT[win[0]]
        out.append(row)
    return out


def _review(review: dict | None, seat: str, asked_calls: dict | None = None,
            asked_cards: dict | None = None) -> dict | None:
    """The app's review, cut to what a coach needs: costly calls and cards, each with the app's verdict."""
    if not review or review.get("error"):
        return None
    calls = [{"seat": SEAT[b["seat"]], "by_you": b["seat"] == seat, "call": call_text(b["call"]), "meant": b.get("meaning"),
              "system_call": call_text(b["system_call"]), "system_meaning": b.get("system_meaning"),
              "small_difference": bool(b.get("minor")),
              **({"you_asked_first": _asked(asked_calls[b["index"]])}
                 if asked_calls and b.get("seat") == seat and b.get("index") in asked_calls else {})}
             for b in review.get("bidding") or []]
    play = review.get("play") or {}
    cards = []
    for i, c in enumerate(play.get("cards") or []):
        if c.get("lost", 0) <= 0:
            continue
        row = {"trick": c["trick"], "seat": SEAT[c["seat"]], "chosen_by": SEAT[c["by"]],
               "by_you": c["by"] == seat, "card": card(c["card"]),
               "dd_tricks_lost": c["lost"], "dd_best": [card(x) for x in c.get("best") or []]}
        if asked_cards and i in asked_cards and c["by"] == seat:
            row["you_asked_first"] = _asked(asked_cards[i])
        o = c.get("odds")
        if o:
            mistake = o.get("better", o.get("best") != c["card"] and o.get("best_pct", 0) > o.get("played", 0))
            row["verdict"] = "mistake" if mistake else "unlucky"
            row["odds"] = {"card_played_works": f"{o['played']}%", "best_bet": card(o["best"]),
                           "best_bet_works": f"{o['best_pct']}%", "layouts": o.get("samples")}
            if o.get("hindsight"):
                row["odds"]["would_have_worked_this_time"] = f"{card(o['hindsight'])} ({o['hindsight_pct']}%)"
        cards.append(row)
    out = {"calls_off_system": calls, "costly_cards": cards}
    if play:
        out["dd_tricks_for_declarer"] = play.get("dd_declarer_tricks")
        out["dd_tricks_lost_by_seat"] = {SEAT[s]: n for s, n in (play.get("lost_by") or {}).items() if n}
    if review.get("odds_pending"):
        out["note"] = "The odds were still being worked out when this board was saved."
    return out


def _dd(dd: dict | None, seat: str) -> dict | None:
    if not dd or dd.get("error"):
        return None
    sign = 1 if seat in "NS" else -1
    return {"tricks_each_strain_by_declarer": {SUIT[s]: {SEAT[d]: n for d, n in row.items()}
                                               for s, row in (dd.get("tricks") or {}).items()},
            "par_score_for_you": None if dd.get("par_score_ns") is None else dd["par_score_ns"] * sign,
            "par_contracts": dd.get("par_contracts")}


def _undone(rec: dict, seat: str) -> list[dict]:
    """The player's first choices that they took back with Undo: what each was worth, and what they chose instead."""
    out = []
    for u in rec.get("undone") or []:
        if u.get("by") != seat:
            continue
        if u["kind"] == "call":
            row = {"call_number": len(u.get("calls_before") or []) + 1, "first_choice": call_text(u["call"]),
                   "meant": u.get("meaning")}
            if u.get("system_call"):
                row["system_call"] = call_text(u["system_call"])
                row["system_meaning"] = u.get("system_meaning")
                row["same_as_system"] = u["system_call"] == u["call"]
            if u.get("then"):
                row["then_chose"] = call_text(u["then"])
        else:
            row = {"trick": u.get("trick"), "seat": SEAT[u["seat"]], "first_choice": card(u["card"])}
            if u.get("lost") is not None:
                row["dd_tricks_it_would_have_lost"] = u["lost"]
                row["dd_best"] = [card(x) for x in u.get("best") or []]
            if u.get("then"):
                row["then_chose"] = card(u["then"])
            if u.get("contract") and u["contract"] != rec.get("contract"):
                row["in_contract"] = contract_text(u["contract"])
        if u.get("asked"):
            row["you_asked_first"] = _asked(u["asked"])
        out.append(row)
    return out


def _second(rec: dict, seat: str) -> dict | None:
    """The same deal at the second table (game/second.py), for the player in `seat`: what the level 10 bot in their
    seat reached and how the two results compare in IMPs (connector.BOARD_SECOND_FIELDS says what each field means)."""
    out = ((fill_split(rec).get("review") or {}).get("second") or {}).get(seat)
    if not isinstance(out, dict) or out.get("imps") is None:
        return None
    c = out.get("contract")
    calls = [a["call"] for a in out.get("auction") or []]
    sheet = {"bot_level_in_your_seat": out.get("level"), "other_bots_level": out.get("others"),
             "their_auction": _auction(rec.get("dealer", "N"), calls, rec.get("conventions")),
             "their_contract": contract_text(c) or "Passed out",
             "their_result": f"made {out.get('tricks', 0)} tricks" if c else None,
             "their_score_for_you": out.get("score"), "your_score_at_duplicate": out.get("table_score"),
             "imps_for_you": out["imps"]}
    if out.get("bidding_imps") is not None:
        sheet["bidding_imps"], sheet["play_imps"] = out["bidding_imps"], out.get("play_imps")
    return sheet


def board_sheet(rec: dict, seat: str | None = None) -> dict:
    """A finished board (a saved record, or one in a room's history) as the player in `seat` would review it."""
    seat = seat or rec.get("seat") or "S"
    c = rec.get("contract")
    need = c["level"] + 6 if c else None
    made = rec.get("declarer_tricks", 0)
    players = rec.get("players") or {}
    sign = 1 if seat in "NS" else -1
    help_ = (rec.get("help") or {}).get(seat) or {}
    asked = [m for m in rec.get("asked") or [] if m.get("seat") == seat]
    asked_calls = {m["index"]: m["asked"] for m in asked if m["kind"] == "call"}
    asked_cards = {m["index"]: m["asked"] for m in asked if m["kind"] == "card"}
    out = {
        "board": rec.get("board"),
        "you": SEAT[seat],
        "your_partner": players.get(partner(seat)) or "a bot",
        "players": {SEAT[s]: players.get(s) or "bot" for s in SEATS},
        "bot_level": rec.get("difficulty"),
        "dealer": SEAT.get(rec.get("dealer"), rec.get("dealer")),
        "vulnerable": rec.get("vulnerability"),
        "scoring": rec.get("scoring"),
        "conventions_on": rec.get("conventions"),
        "defensive_signals": SIGNAL_NAMES.get(rec.get("signals"), "none"),
        "opening_leads": LEADS_NAME if rec.get("leads") else "none",
        "hands": {SEAT[s]: hand_text(h) for s, h in (rec.get("hands") or {}).items()},
        "auction": _auction(rec.get("dealer", "N"), rec.get("calls") or [], rec.get("conventions"), asked_calls),
        "contract": contract_text(c) or "Passed out",
        "result": None if not c else (f"made {made} tricks: " + (
            f"made{' +' + str(made - need) if made > need else ''}" if made >= need else f"down {need - made}")),
        "claimed_by": SEAT.get(rec.get("claimed")) if rec.get("claimed") else None,
        "your_score": rec.get("score_ns", 0) * sign,
        "play": _tricks(rec.get("play") or [], c["strain"] if c else None, asked_cards),
        "double_dummy": _dd(rec.get("dd"), seat),
        "review": _review(rec.get("review"), seat, asked_calls, asked_cards),
        "you_used": {"hints": help_.get("hints", 0), "undos": help_.get("undos", 0),
                     "ai_coach_questions": help_.get("coach", 0)},
    }
    second = _second(rec, seat)
    if second:
        out["second_table"] = second
    undone = _undone(rec, seat)
    if undone:
        out["first_choices_taken_back"] = undone
    if rec.get("scoring") == "rubber":
        f = board_facts({**rec, "seat": seat})
        below = rec.get("below_before") or {}
        out["part_scores_when_dealt"] = {"you": below.get("NS" if seat in "NS" else "EW", 0),
                                         "opponents": below.get("EW" if seat in "NS" else "NS", 0),
                                         **({"note": "worked out by replaying the rubber; a board may be missing, so "
                                                     "this is a best guess"} if rec.get("below_guessed") else {})}
        out["your_score_for_par"] = f.get("score_for_par")
        if out["double_dummy"] and f.get("par") is not None:
            out["double_dummy"]["par_score_for_you"] = f["par"]
            out["double_dummy"]["par_contracts"] = f.get("par_contracts")
        out["scoring_note"] = ("Rubber scoring. your_score is this board's points on the pad, with no game bonus until "
                               "the rubber ends. Par and your_score_for_par score the board the same way as each "
                               "other: game and part-score bonuses on the board, with the part score already below "
                               "the line counting towards game (with 60 on, 2♥ made is a game).")
    return out


def table_sheet(state: dict) -> dict:
    """A board in progress, from Room.state_for(seat): only what that seat can see."""
    t = state["table"]
    settings = state.get("settings") or {}
    out = {
        "board": t["board"], "you": SEAT.get(state.get("you")), "dealer": SEAT[t["dealer"]],
        "vulnerable": t["vulnerability"], "phase": t["phase"],
        "players": {SEAT[s]: (state.get("players") or {}).get(s) or "bot" for s in SEATS},
        "bot_level": settings.get("difficulty"), "conventions_on": settings.get("conventions"),
        "defensive_signals": SIGNAL_NAMES.get(settings.get("signals"), "none"),
        "opening_leads": LEADS_NAME if settings.get("leads", True) else "none",
        "hands_you_can_see": {SEAT[s]: hand_text(h) for s, h in (t.get("hands") or {}).items() if h},
        "cards_left": {SEAT[s]: n for s, n in (t.get("counts") or {}).items()},
        "auction": [{"seat": SEAT[a["seat"]], "call": call_text(a["call"]),
                     **({"meaning": a["meaning"]["text"]} if (a.get("meaning") or {}).get("text") else {})}
                    for a in t.get("auction") or []],
        "to_act": SEAT.get(t.get("turn")),
        "your_turn": bool(t.get("your_turn")),
    }
    if t.get("contract"):
        out["contract"] = contract_text(t["contract"])
        out["dummy"] = SEAT.get(t.get("dummy"))
        out["tricks_won"] = t.get("tricks_won")
        trick = (t.get("trick") or {}).get("cards") or []
        out["current_trick"] = [f"{SEAT[x['seat']]} {card(x['card'])}" for x in trick]
        last = t.get("last_trick")
        if last:
            out["last_trick"] = {"cards": [f"{SEAT[x['seat']]} {card(x['card'])}" for x in last.get("cards") or []],
                                 "won_by": SEAT.get(last.get("winner"))}
    if t.get("legal_calls"):
        out["calls_you_may_make"] = {call_text(c): (m or {}).get("text") for c, m in
                                     (t.get("call_meanings") or {}).items()}
    if t.get("legal_cards"):
        out["cards_you_may_play"] = [card(c) for c in t["legal_cards"]]
    return out


def hint_sheet(hint: dict) -> dict:
    """The app's own Hint (Table.hint / card_hint), in the same words as the rest of the sheets."""
    if hint.get("phase") == "bidding":
        return {"suggested_call": call_text(hint["call"]), "meaning": hint.get("text")}
    out = {"suggested_card": card(hint["card"]), "playing_for": SEAT.get(hint.get("seat"))}
    if hint.get("equal"):
        out["equally_good"] = [card(c) for c in hint["equal"]]
    goal = "makes" if hint.get("goal") == "make" else "beats"
    if hint.get("odds"):
        out["odds"] = [f"{card(o['card'])} {goal} the contract on {o['pct']}% of {hint.get('samples')} layouts"
                       for o in hint["odds"]]
    if hint.get("extra"):  # making is about equal, so the hint went by one trick more
        out["one_trick_more"] = [f"{card(o['card'])} takes {hint['extra']['label'].lower()} on {o['pct']}% of layouts"
                                 if hint["extra"]["label"][0].isdigit() else
                                 f"{card(o['card'])} sets it two down on {o['pct']}% of layouts"
                                 for o in hint["extra"]["odds"]]
    return out
