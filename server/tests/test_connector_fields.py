"""Every field the AI connector returns is either plain from its name or explained in its tool's description, so the
player's AI reads the numbers the way the app means them. A new field fails here until it's described: add it to the
tool's field guide in connector.py (STATS_FIELDS, BOARD_SECOND_FIELDS, or a new one), or, if its name alone says what
it is, to PLAIN below."""
import random
import re

from bridge.bidding.conventions import ALL_CONVENTIONS, make_engine
from bridge.coach import board_sheet
from bridge.connector import TOOLS
from bridge.core.auction import Contract
from bridge.core.cards import SEATS, deal_random
from bridge.game.second import add_split, second_table
from bridge.stats import board_facts, stats_from_facts

ENGINE = make_engine({c.id for c in ALL_CONVENTIONS if c.default_on})

# Fields whose name says what they are, checked by a person. Keys that are values (seats, suits, calls, kinds of
# card, levels) aren't fields and are skipped.
PLAIN = {
    "board", "you", "your_partner", "players", "bot_level", "dealer", "vulnerable", "scoring", "conventions_on",
    "defensive_signals", "opening_leads", "hands", "auction", "seat", "call", "meaning", "meant", "contract", "result",
    "claimed_by", "your_score", "play", "trick", "cards", "led_by", "won_by", "double_dummy",
    "tricks_each_strain_by_declarer", "par_score_for_you", "par_contracts", "review", "calls_off_system", "by_you",
    "system_call", "system_meaning", "small_difference", "costly_cards", "chosen_by", "card", "dd_tricks_lost",
    "dd_best", "verdict", "odds", "card_played_works", "best_bet", "best_bet_works", "layouts",
    "would_have_worked_this_time", "dd_tricks_for_declarer", "dd_tricks_lost_by_seat", "note", "you_used", "hints",
    "undos", "ai_coach_questions", "first_choices_taken_back", "call_number", "first_choice", "same_as_system",
    "then_chose", "dd_tricks_it_would_have_lost", "in_contract", "you_asked_first", "part_scores_when_dealt",
    "opponents", "your_score_for_par", "scoring_note", "key", "finished", "role", "declarer_tricks", "par_for_you",
    "partner", "dd_tricks_lost_by_you", "total", "boards", "next_cursor", "error",
    # coaching_overview, mistake_patterns, bidding_history, coaching_notes
    "ai_questions_per_board", "calls_off_system_per_10_boards", "area", "based_on", "bidding", "bot_benchmarks", "by_area", "by_contract", "by_level",
    "calls", "cards_by_kind", "contract_set_by", "costly", "costly_leads", "costly_leads_pct", "costly_pct",
    "declaring", "defending", "examples", "examples_helped", "examples_hurt", "from", "help", "helped",
    "hints_per_board", "hurt", "lead", "leads", "leads_by_kind", "leads_vs_notrump", "leads_vs_suit", "level",
    "levels", "made", "made_pct", "makeable", "mistake", "needed", "net_points", "no_difference",
    "off_system_calls_helped_or_hurt", "other_bids_decided", "passed_out", "points", "roles",
    "taken_back_calls_off_system", "taken_back_cards_that_would_have_cost", "to", "tricks_lost",
    "tricks_lost_per_hand", "tricks_those_would_have_cost", "undos_per_board", "unlucky", "vs_par",
    "vs_par_all_boards", "vs_par_boards_on_system", "vs_par_boards_with_off_system_calls",
    "went_down_when_makeable", "what", "working_on", "your_range_on_this_scale", "by_kind", "by_role",
    "cards_with_trumps", "counting_checks", "against_system", "auction_before", "boards_matching",
    "dd_tricks_in_contract", "final_contract", "system_area", "system_auction_from_here", "system_contract",
    "your_call", "your_hand", "notes", "id", "at", "added",
    "times", "trumps_out", "threw_winner", "ruffed_partners_winner",
    # current_board and app_hint
    "hands_you_can_see", "cards_left", "phase", "to_act", "your_turn", "current_trick", "last_trick", "tricks_won",
    "suggested_call", "suggested_card", "playing_for", "calls_you_may_make", "cards_you_may_play", "equally_good",
    "one_trick_more",
}
VALUES = {"declarer", "defender", "dummy", "game", "slam", "suit", "notrump", "follow", "discard", "ruff", "other",
          "later lead", "opening lead", "part score", "NT",
          # the kinds of opening lead (patterns.py), whichever this deal happened to have
          "singleton", "trump lead", "underled an ace", "from ace-king", "top of a sequence", "from a doubleton",
          "top of nothing", "fourth best", "low from an honor"}


def keys(data, out=None) -> set[str]:
    out = set() if out is None else out
    if isinstance(data, dict):
        for k, v in data.items():
            out.add(k)
            keys(v, out)
    elif isinstance(data, list):
        for v in data:
            keys(v, out)
    return out


def undescribed(tool: str, data) -> set[str]:
    """The fields in `data` (a tool's answer) that its description doesn't name and aren't plain from their name."""
    desc = next(t["description"] for t in TOOLS if t["name"] == tool)
    return {k for k in keys(data) if k not in PLAIN and k not in VALUES and not k[:1].isupper() and not k[:1].isdigit()
            and k not in "♠♥♦♣" and not re.search(rf"\b{re.escape(k)}\b", desc)}


def _board_with_second_table() -> dict:
    hands = deal_random(random.Random(8))
    mine = Contract(1, "N", "S")
    dd = {"tricks": {s: {d: 7 for d in SEATS} for s in "SHDCN"}, "par_score_ns": 90}
    rec = {"room": "TEST", "board": 1, "seat": "S", "finished_at": 1000.0, "dealer": "N", "vulnerability": "None",
           "hands": {s: hands[s].to_pbn() for s in SEATS}, "contract": mine.to_dict(), "declarer_tricks": 7,
           "score_ns": 90, "difficulty": 4, "bots": ["N", "E", "W"], "scoring": "duplicate", "dd": dd,
           "review": {"bidding": [], "play": None}}
    out = second_table(ENGINE, hands, "N", "None", None, "S", {"S"}, 4, None, True, None, mine, 7, random.Random(1))
    rec["review"]["second"] = {"S": add_split(out, mine, dd, "None", None)}
    return rec


def test_the_second_table_is_in_the_board_review_and_described():
    rec = _board_with_second_table()
    sheet = board_sheet(rec)
    s = sheet["second_table"]
    raw = rec["review"]["second"]["S"]
    assert s["imps_for_you"] == raw["imps"] and s["bidding_imps"] + s["play_imps"] == raw["imps"]
    assert s["bot_level_in_your_seat"] == 10 and s["your_score_at_duplicate"] == 90
    assert s["their_auction"] and all("call" in a for a in s["their_auction"])
    for tool in ("last_board_review", "board_review", "board_reviews"):
        assert not undescribed(tool, sheet)
    # no second table yet: the field is left out rather than shown empty
    assert "second_table" not in board_sheet({**rec, "review": {"bidding": [], "play": None, "second_pending": True}})


def test_every_my_stats_field_is_described():
    facts = [board_facts(_board_with_second_table())]
    stats = stats_from_facts(facts, days=None)
    assert stats["now"]["second_boards"] == 1 and stats["now"]["second_imps"] is not None
    assert not undescribed("my_stats", stats)
    assert not undescribed("my_stats", stats_from_facts([], days=30))
    # the level's whole answer, once there are enough hands to work it out
    assert not undescribed("my_stats", {"level": {"level": 5, "low": 4, "high": 6, "declaring": 5, "defending": 5,
                                                  "hands": 40, "needed": 20}})
