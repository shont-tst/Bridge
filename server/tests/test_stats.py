"""My stats from saved boards, and the level on the bots' scale."""
import time

from bridge import stats
from bridge.stats import board_facts, level_for, my_stats, rating


def rec(seat="S", declarer="S", lost_me=0, lead_lost=0, made=True, makeable=True, score_ns=420, par_ns=420,
        days_ago=1, bidding=(), hints=0, undos=0, key="k"):
    needed = 10
    leader = {"S": "W", "N": "E", "E": "S", "W": "N"}[declarer]
    cards = [{"trick": 1, "seat": leader, "by": leader, "card": "SA", "lost": lead_lost, "best": [], "role": "defence"}]
    cards.append({"trick": 2, "seat": seat, "by": seat, "card": "HA", "lost": lost_me, "best": [], "role": "declarer"})
    return {"key": key, "seat": seat, "room": "ROOM", "board": 1, "finished_at": time.time() - days_ago * 86400,
            "contract": {"level": 4, "strain": "S", "declarer": declarer, "doubled": 0},
            "declarer_tricks": needed if made else needed - 1, "score_ns": score_ns, "difficulty": 6,
            "players": {"S": "Avery"}, "bots": ["N", "E", "W"], "dd": {"par_score_ns": par_ns},
            "help": {seat: {"hints": hints, "undos": undos}},
            "review": {"bidding": list(bidding),
                       "play": {"cards": cards, "dd_declarer_tricks": needed if makeable else needed - 1}}}


def test_declarer_board():
    f = board_facts(rec(lost_me=1, made=False))
    assert f["role"] == "declarer" and f["lost"] == 1 and f["makeable"] and not f["made"]


def test_defender_opening_lead_that_cost():
    f = board_facts(rec(seat="W", declarer="S", lead_lost=1, score_ns=-50, par_ns=420))
    assert f["role"] == "defender" and f["lead_cost"] is True and f["lost"] == 1
    assert f["score"] == 50 and f["par"] == -420  # from West's side


def test_dummy_counts_nothing_for_card_play():
    f = board_facts(rec(seat="N", declarer="S"))
    assert f["role"] == "dummy" and f["lost"] is None


def test_summary_and_sensible_alternatives_not_counted():
    bids = [{"seat": "S", "minor": True, "convention": "stayman"}, {"seat": "S", "minor": False, "convention": "stayman"},
            {"seat": "N", "minor": False, "convention": "weak_twos"}]
    s = my_stats([rec(bidding=bids, hints=2, undos=1), rec(made=False, score_ns=-50, key="k2")])["now"]
    assert s["boards"] == 2 and s["made"] == 1 and s["makeable"] == 2
    assert s["off_system_per_10"] == 5.0 and s["off_system_by"] == [("Stayman", 1)]
    assert s["hints_per_board"] == 1.0 and s["vs_par"] == -235.0


def test_thirty_days_compares_with_the_month_before():
    out = my_stats([rec(lost_me=0), rec(lost_me=2, days_ago=40, key="old")], 30)
    assert out["now"]["declarer_lost"] == 0 and out["before"]["declarer_lost"] == 2
    assert my_stats([rec(), rec(days_ago=400, key="o")], None)["now"]["boards"] == 2


def test_level_for_interpolates_and_clamps():
    curve = {1: 3.0, 5: 1.0, 10: 0.0}
    assert level_for(3.5, curve) == 1
    assert level_for(2.0, curve) == 3.0
    assert level_for(0.0, curve) == 10
    assert level_for(0.5, curve) == 7.5


def test_level_needs_twenty_hands(monkeypatch):
    monkeypatch.setattr(stats, "_calibration", lambda: {1: {"declaring": 2.0, "defending": 1.0},
                                                       10: {"declaring": 0.0, "defending": 0.0}})
    few = [rec(key=str(i)) for i in range(5)]
    assert rating([board_facts(r) for r in few])["level"] is None
    many = [rec(key=str(i), lost_me=1) for i in range(25)]
    r = rating([board_facts(r) for r in many])
    assert r["declaring"] == 5.5 and r["level"] == 5.5 and r["hands"] == 25
    assert r["low"] == r["high"] == 5.5  # every hand the same: no spread


def test_level_margin_of_error(monkeypatch):
    monkeypatch.setattr(stats, "_calibration", lambda: {1: {"declaring": 2.0, "defending": 1.0},
                                                       10: {"declaring": 0.0, "defending": 0.0}})
    mixed = [rec(key=str(i), lost_me=i % 3) for i in range(30)]  # 0, 1, 2 lost: averages 1, level 5.5
    r = rating([board_facts(r) for r in mixed])
    assert r["level"] == 5.5 and r["low"] < 5.5 < r["high"]
    assert r["high"] - r["level"] == r["level"] - r["low"]


def test_calibration_file_is_in_order():
    cal = stats._calibration()
    assert sorted(cal) == list(range(1, 11))
    assert cal[1]["declaring"] > cal[10]["declaring"]


def test_bot_info_table_matches_the_calibration():
    """The app's "How bot strength works" table shows the same numbers the player's level is read from."""
    import json
    from scripts.calibrate import OUT, WEB, web_table
    assert json.loads(WEB.read_text()) == web_table(json.loads(OUT.read_text())["levels"])


def test_facts_are_kept_up_to_date_without_rereading(tmp_path):
    from bridge.accounts import Accounts
    from bridge.stats import history_from_facts
    from bridge.store import SqliteStore
    acc = Accounts(SqliteStore(tmp_path / "s.db", durable=True))
    first = rec(key=None)
    acc.save_board("u1", first)
    assert len(acc.facts("u1")) == 1
    acc.store.query = None  # from here on, nothing may be read from storage again
    second = {**rec(key=None), "finished_at": first["finished_at"] + 60}
    acc.save_board("u1", second)
    assert len(acc.facts("u1")) == 2
    acc.drop_board("u1", first)
    assert [f["at"] for f in acc.facts("u1")] == [second["finished_at"]]
    assert len(history_from_facts(acc.facts("u1"), role="defender")) == 0
    assert len(history_from_facts(acc.facts("u1"), limit=1)) == 1


def test_off_system_calls_helped_or_cost_counts_only_calls_nobody_bid_after():
    from bridge.stats import summarize
    f = board_facts(rec())
    f["bid_outcomes"] = [{"verdict": "helped", "points": 170, "contract_set_by": "your call"},
                         {"verdict": "hurt", "points": -240, "contract_set_by": "your call"},
                         {"verdict": "no difference", "points": 0, "contract_set_by": "your call"},
                         {"verdict": "hurt", "points": -500, "contract_set_by": "partner bid on"},
                         {"verdict": None, "points": None}]
    s = summarize([f])
    assert (s["off_system_helped"], s["off_system_cost"], s["off_system_same"]) == (1, 1, 1)
    assert s["off_system_points"] == round((170 - 240) / 3, 2)
    assert summarize([board_facts(rec(key="k3"))])["off_system_points"] is None
