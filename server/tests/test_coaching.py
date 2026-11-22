"""What the AI coach sees across many boards: first choices taken back with Undo, which plays came after a hint, the
kinds of costly cards, opening leads, and par on the same scoring as the score."""
import os

os.environ["BRIDGE_BOT_DELAY"] = "0"

import pytest  # noqa: E402

from bridge.coach import board_sheet  # noqa: E402
from bridge.game.room import Room  # noqa: E402
from bridge.game.table import DONE, PLAYING, Table  # noqa: E402
from bridge.patterns import card_kinds, lead_info  # noqa: E402
from bridge.stats import board_facts  # noqa: E402
from bridge.trends import bidding_rows, filter_boards, mistakes, overview  # noqa: E402


@pytest.fixture(autouse=True)
def tmp_data(tmp_path, monkeypatch):
    monkeypatch.setenv("BRIDGE_DATA_DIR", str(tmp_path))


def _bid_1nt_by_south(t: Table):
    while t.auction.next_to_call != "S":
        t.make_call(t.auction.next_to_call, "P")
    t.make_call("S", "1N")
    for _ in range(3):
        t.make_call(t.auction.next_to_call, "P")


def _room():
    room = Room("COCH", seed=3)
    room.join("Ann", user="ann")
    room.join("Bob", user="bob")
    room.new_board()
    return room


def test_first_choice_and_hints_are_kept_for_the_review():
    room = _room()
    t: Table = room.table
    _bid_1nt_by_south(t)
    t.play_card("W", t.play.legal_cards()[0])
    room._count("S", "hints")  # South asks before dummy's card
    first = t.play.legal_cards()[0]
    t.play_card("S", first)
    room.undo()
    assert room.undone and room.undone[0]["card"] == first and room.undone[0]["asked"] == ["hints"]
    # back at the same decision: the hint they saw still counts for the card they choose now
    second = t.play.legal_cards()[-1]
    t.play_card("S", second)
    while t.phase == PLAYING:
        t.play_card(t.controller_to_act(), t.play.legal_cards()[0])
    assert t.phase == DONE
    room.record_result()
    rec = room.history[-1]
    u = rec["undone"][0]
    assert u["kind"] == "card" and u["card"] == first and u["trick"] == 1 and "lost" not in u
    room.fill_odds(t, t.result.review)  # worked out with the odds, at the solver's lowest urgency
    assert "lost" in u
    assert u["then"] == second
    assert {"kind": "card", "index": 1, "seat": "S", "asked": ["hints"]} in rec["asked"]
    assert t.result.asked == rec["asked"]  # on the result too, for the review's "After a hint" (#153)

    saved = dict(room.finished[0][1])
    sheet = board_sheet(saved)
    assert sheet["first_choices_taken_back"][0]["first_choice"]
    assert "you_asked_first" in sheet["play"][0]
    f = board_facts({**saved, "key": "k"})
    assert f["undone"] == 1 and f["asked"] == 1


def test_board_saved_again_once_odds_are_in():
    room = _room()
    t = room.table
    _bid_1nt_by_south(t)
    while t.phase == PLAYING:
        t.play_card(t.controller_to_act(), t.play.legal_cards()[0])
    room.record_result()
    first = list(room.finished)
    room.finished.clear()  # saved
    assert first and first[0][1]["review"]["odds_pending"]
    room.fill_odds(t, t.result.review)
    assert [u for u, _ in room.finished] == [u for u, _ in first]
    assert room.finished[0][1]["review"]["odds_pending"] is False


def _tricks(ns_hearts: int, ew_spades: int = 4) -> dict:
    """A double-dummy table where N-S take `ns_hearts` in hearts and E-W `ew_spades` in spades, little else."""
    t = {s: {d: 3 for d in "NESW"} for s in "CDHSN"}
    t["H"] = {"N": ns_hearts, "S": ns_hearts, "E": 13 - ns_hearts, "W": 13 - ns_hearts}
    t["S"] = {"E": ew_spades, "W": ew_spades, "N": 13 - ew_spades, "S": 13 - ew_spades}
    return t


def test_rubber_board_compared_with_par_on_the_same_scoring():
    rec = {"seat": "S", "scoring": "rubber", "vulnerability": "None", "declarer_tricks": 10, "score_ns": 120,
           "contract": {"level": 4, "strain": "H", "declarer": "S", "doubled": 0},
           "dd": {"par_score_ns": 420, "tricks": _tricks(10)}, "finished_at": 1}
    f = board_facts(rec)
    assert f["score"] == 120 and f["score_for_par"] == 420 and f["par"] == 420
    assert board_sheet(rec)["your_score_for_par"] == 420


def test_a_part_score_counts_towards_game():
    """With 60 below the line, 2♥ making 9 tricks is game: it scores like 4♥, and par is game in hearts too."""
    from bridge.core.par import par
    from bridge.core.scoring import duplicate_score
    from bridge.core.auction import Contract
    assert duplicate_score(Contract(2, "H", "S"), 9, False, 60) == 390  # 60 + an overtrick 30 + game 300
    assert duplicate_score(Contract(2, "H", "S"), 8, False, 60) == 360
    assert duplicate_score(Contract(2, "H", "S"), 8, False, 0) == 110
    tricks = _tricks(9)
    assert par(tricks, "None")["score_ns"] == 140  # a part score, in a fresh game
    with60 = par(tricks, "None", {"NS": 60, "EW": 0})
    assert with60["score_ns"] == 390 and "2♥S+1" in with60["contracts"]
    rec = {"seat": "S", "scoring": "rubber", "vulnerability": "None", "declarer_tricks": 9, "score_ns": 90,
           "contract": {"level": 2, "strain": "H", "declarer": "S", "doubled": 0}, "below_before": {"NS": 60, "EW": 0},
           "dd": {"par_score_ns": 140, "tricks": tricks}, "finished_at": 1}
    f = board_facts(rec)
    assert f["score_for_par"] == f["par"]  # stopping in 2♥ was exactly right


def test_part_scores_rebuilt_by_replaying_the_rubber():
    from bridge.stats import rebuild_part_scores
    hands = {s: "AKQJ.T98.765.432" for s in "NESW"}
    b1 = {"room": "R", "scoring": "rubber", "vulnerability": "None", "finished_at": 1, "board": 1, "hands": hands,
          "contract": {"level": 2, "strain": "H", "declarer": "N", "doubled": 0}, "declarer_tricks": 8}
    b2 = {**b1, "finished_at": 2, "board": 2, "contract": {"level": 1, "strain": "S", "declarer": "E", "doubled": 0},
          "declarer_tricks": 7}
    b3 = {**b1, "finished_at": 3, "board": 3, "vulnerability": "NS"}  # a board missing in between: NS won a game
    rebuild_part_scores([b3, b2, b1])
    assert b1["below_before"] == {"NS": 0, "EW": 0} and not b1.get("below_guessed")
    assert b2["below_before"] == {"NS": 60, "EW": 0}
    assert b3["below_before"] == {"NS": 0, "EW": 0} and b3["below_guessed"]


def test_kinds_of_cards_and_counting_checks():
    hands = {"N": "AKQ.AKQ.AKQ.AKQJ", "E": "JT9.JT9.JT9.T987", "S": "876.876.876.6543", "W": "5432.5432.5432."}
    play = [["E", "SJ"], ["S", "S6"], ["W", "S2"], ["N", "SA"],
            ["N", "CA"], ["E", "C7"], ["S", "C3"], ["W", "H2"]]
    rec = {"contract": {"level": 3, "strain": "C", "declarer": "N", "doubled": 0}, "hands": hands, "play": play}
    kinds = [k["kind"] for k in card_kinds(rec)]
    assert kinds == ["opening lead", "follow", "follow", "follow", "lead", "follow", "follow", "discard"]
    assert card_kinds(rec)[4]["trumps"] is True  # a trump lead
    ld = lead_info({**rec, "play": play}, "E")
    assert ld["kind"] == "top of a sequence" and ld["against"] == "suit" and ld["holding"] == "SJT9"


def test_threw_a_winner_and_trumps_out():
    hands = {"N": "A.AK..", "E": "K.QJ..", "S": ".T9.A.", "W": "Q..K.2"}
    rec = {"contract": {"level": 1, "strain": "H", "declarer": "S", "doubled": 0}, "hands": hands,
           "play": [["W", "SQ"], ["N", "SA"], ["E", "SK"], ["S", "DA"]]}
    k = card_kinds(rec)
    assert k[3]["kind"] == "discard"
    # South's ♦A was the highest diamond left: throwing it is a sure winner gone
    assert "threw_winner" in k[3]["checks"]


def _fact(key, at, role="defender", lead_lost=0, off=(), costly=(), contract=None):
    return {"key": key, "at": at, "board": 1, "seat": "S", "role": role, "contract": contract or
            {"level": 4, "strain": "S", "declarer": "W" if role == "defender" else "S", "doubled": 0},
            "tricks": 10, "score": -420, "score_for_par": -420, "par": -420, "lost": 1, "lost_own": 0,
            "makeable": True, "made": False, "lead_cost": bool(lead_lost), "lead_cost_own": bool(lead_lost),
            "off_system": list(off), "off_system_own": list(off), "hints": 1, "undos": 0, "coach": 0,
            "partner": None, "difficulty": 5, "costly": list(costly), "cards_by_kind": {"opening lead": 1, "follow": 5},
            "lead": {"card": "SK", "holding": "SKQ3", "kind": "top of a sequence", "against": "suit",
                     "lost": lead_lost, "best": []}, "undone": 0}


def test_overview_and_patterns():
    costly = [{"trick": 1, "card": "SK", "whose": "you", "lost": 1, "verdict": "mistake", "best": ["HA"],
               "kind": "opening lead", "trumps": False, "checks": [], "asked": []}]
    facts = [_fact(f"k{i}", 1000 + i, lead_lost=1 if i % 2 else 0, costly=costly if i % 2 else (),
                   off=("stayman",) if i == 0 else ()) for i in range(6)]
    ov = overview(facts)
    assert ov["boards"] == 6 and ov["defending"]["opening_leads"] == 6 and ov["defending"]["costly_leads"] == 3
    assert ov["defending"]["leads_by_kind"]["top of a sequence"]["costly"] == 3
    assert ov["bot_benchmarks"]["levels"]
    m = mistakes(facts)
    assert m["by_kind"]["opening lead"]["costly"] == 3 and m["by_kind"]["opening lead"]["costly_pct"] == 50
    assert len(m["by_kind"]["opening lead"]["examples"]) == 3
    assert [f["key"] for f in filter_boards(facts, off_system=True)] == ["k0"]


def test_bidding_rows_show_every_call_or_only_off_system():
    rec = {"seat": "S", "dealer": "S", "calls": ["1N", "P", "2C", "P", "2H", "P", "P", "P"],
           "hands": {"S": "AK2.KQ32.QJ3.K54"}, "contract": {"level": 2, "strain": "H", "declarer": "S", "doubled": 0},
           "declarer_tricks": 8, "score_ns": 110, "dd": {"par_score_ns": 140, "tricks": {"H": {"S": 9}}},
           "review": {"bidding": [{"index": 4, "seat": "S", "call": "2H", "system_call": "2D", "minor": False,
                                   "meaning": "4 hearts", "system_meaning": "no major", "convention": None}]},
           "asked": [{"kind": "call", "index": 0, "seat": "S", "asked": ["hints"]}], "finished_at": 1, "key": "k"}
    only = bidding_rows(rec)
    assert len(only) == 1 and [c["your_call"] for c in only[0]["calls"]] == ["2♥"]
    assert only[0]["calls"][0]["system_call"] == "2♦" and only[0]["dd_tricks_in_contract"] == 9
    every = bidding_rows(rec, only_off_system=False)[0]["calls"]
    assert [c["your_call"] for c in every] == ["1NT", "2♥"] and every[0]["after"] == ["hints"]


def test_helped_or_hurt_says_who_set_the_contract():
    from bridge.bidpath import verdict
    base = {"system_auction": [], "system_contract": None, "system_dd_ns": 100, "actual_dd_ns": 400}
    assert verdict({**base, "bid_after": []}, "S") == {"points": 300, "verdict": "helped", "contract_set_by": "your call"}
    assert verdict({**base, "bid_after": ["N"]}, "S")["contract_set_by"] == "partner bid on"
    assert verdict({**base, "bid_after": ["E"]}, "S")["contract_set_by"] == "opponents bid on"
    assert verdict({**base, "bid_after": ["E", "N"]}, "S")["contract_set_by"] == "both sides bid on"
    assert verdict({**base, "bid_after": []}, "E")["verdict"] == "hurt"


def test_outcome_notes_later_bidders_and_part_score():
    from bridge.bidding.conventions import make_engine
    from bridge.bidpath import outcome
    from bridge.core.cards import Hand
    hands = {"N": Hand.from_pbn("AK2.KQ32.QJ3.K54"), "E": Hand.from_pbn("QJ9.A65.K87.QJ32"),
             "S": Hand.from_pbn("T8.JT987.A65.A76"), "W": Hand.from_pbn("76543.4.T942.T98")}
    dd = {"tricks": _tricks(10)}
    calls = ["1N", "P", "2D", "P", "2H", "P", "4H", "P", "P", "P"]  # South's 2♦ transfer, then 4♥
    o = outcome(make_engine(None), hands, "N", calls, 2, "2D", dd, "None")
    assert o and o["bid_after"] == ["N"]
    with60 = outcome(make_engine(None), hands, "N", calls, 2, "2D", dd, "None", below={"NS": 60, "EW": 0})
    assert with60["actual_dd_ns"] == o["actual_dd_ns"]  # 4♥ is game either way


def test_a_call_is_judged_on_average_over_deals_like_this_one():
    import random
    from bridge.bidding.conventions import make_engine
    from bridge.bidpath import average_outcome, verdict
    from bridge.core.cards import Hand
    hands = {"N": Hand.from_pbn("AK2.KQ32.QJ3.K54"), "E": Hand.from_pbn("QJ9.A65.K87.QJ32"),
             "S": Hand.from_pbn("T8.JT987.A65.A76"), "W": Hand.from_pbn("76543.4.T942.T98")}
    calls = ["1N", "P", "2D", "P", "2H", "P", "4H", "P", "P", "P"]
    # South jumps to 4♥ over the system's transfer: judged on deals of the other hands that fit North's 1NT
    played = ["1N", "P", "4H", "P", "P", "P"]
    avg = average_outcome(make_engine(None), hands, "N", played, 2, "2D", "None", rng=random.Random(3), n=4)
    assert avg and 1 <= avg["deals"] <= 4 and avg["helped"] + avg["hurt"] <= avg["deals"]
    o = {"system_auction": calls[2:], "system_contract": None, "system_dd_ns": 420, "actual_dd_ns": 420,
         "bid_after": [], "avg": {"points_ns": -100, "deals": 30, "helped": 2, "hurt": 20}}
    assert verdict(o, "S")["verdict"] == "hurt" and verdict(o, "S")["points"] == -100  # the average wins
    assert verdict({**o, "avg": None}, "S")["verdict"] == "no difference"  # boards from before: this deal


def test_the_same_contract_either_way_needs_no_solving(monkeypatch):
    import random
    from bridge import bidpath
    from bridge.bidding.conventions import make_engine
    from bridge.core.cards import Hand
    import bridge.game.analysis as analysis
    monkeypatch.setattr(analysis, "dd_summary", lambda *a: (_ for _ in ()).throw(AssertionError("solved")))
    hands = {"N": Hand.from_pbn("AK2.KQ32.QJ3.K54"), "E": Hand.from_pbn("QJ9.A65.K87.QJ32"),
             "S": Hand.from_pbn("T8.JT987.A65.A76"), "W": Hand.from_pbn("76543.4.T942.T98")}
    played = ["1N", "P", "2D", "P", "2H", "P", "4H", "P", "P", "P"]
    avg = bidpath.average_outcome(make_engine(None), hands, "N", played, 2, "2D", "None", rng=random.Random(1), n=3)
    assert avg == {"points_ns": 0, "deals": 3, "helped": 0, "hurt": 0}


def test_call_averages_are_worked_out_while_the_hand_is_played(monkeypatch):
    """A person's call off the system is averaged once the auction is over, and the review uses that average."""
    import random
    from bridge import bidpath
    from bridge.bidding.conventions import make_engine
    from bridge.core.cards import Hand
    from bridge.game.room import averages_ahead
    engine = make_engine(None)
    hands = {"N": Hand.from_pbn("AK2.KQ32.QJ3.K54"), "E": Hand.from_pbn("QJ9.A65.K87.QJ32"),
             "S": Hand.from_pbn("T8.JT987.A65.A76"), "W": Hand.from_pbn("76543.4.T942.T98")}
    played = ["1N", "P", "4H", "P", "P", "P"]
    monkeypatch.setattr(bidpath, "LAYOUTS", 3)
    monkeypatch.setattr(bidpath.average_outcome, "__defaults__", (None, None, None, 3))
    ready = averages_ahead(engine, hands, "N", played, {"S"}, None, "None", None, random.Random(3))
    assert list(ready) == [(2, "2D")] and ready[(2, "2D")]["deals"] >= 1
    review = {"bidding": [{"index": 2, "system_call": "2D", "outcome": {"actual_dd_ns": 420}}]}
    monkeypatch.setattr(bidpath, "average_outcome", lambda *a, **k: (_ for _ in ()).throw(AssertionError("again")))
    bidpath.add_averages(review, engine, hands, "N", played, "None", ready=ready)
    assert review["bidding"][0]["outcome"]["avg"] == ready[(2, "2D")]
