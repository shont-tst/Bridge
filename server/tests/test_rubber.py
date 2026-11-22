from bridge.core.auction import Contract
from bridge.core.cards import Hand
from bridge.core.rubber import Rubber, honors

# no one holds four honors in spades or hearts, or four aces
PLAIN = {
    "N": Hand.of(["SA", "SK", "S2", "S3", "HA", "H2", "H3", "D2", "D3", "D4", "C2", "C3", "C4"]),
    "E": Hand.of(["SQ", "SJ", "S4", "S5", "HK", "H4", "H5", "D5", "D6", "D7", "C5", "C6", "C7"]),
    "S": Hand.of(["ST", "S6", "S7", "S8", "HQ", "HJ", "H6", "DA", "D8", "D9", "CA", "C8", "C9"]),
    "W": Hand.of(["S9", "HT", "H7", "H8", "H9", "DK", "DQ", "DJ", "DT", "CK", "CQ", "CJ", "CT"]),
}


def test_part_scores_add_up_to_game():
    r = Rubber()
    assert r.record(1, Contract(2, "S", "S"), 8, PLAIN) == 60
    assert r.games == {"NS": 0, "EW": 0} and r.below["NS"] == 60
    assert r.record(2, Contract(2, "H", "N"), 9, PLAIN) == 90  # 60 below, 30 above
    assert r.games["NS"] == 1 and r.below == {"NS": 0, "EW": 0}
    assert r.vulnerability() == "NS"


def test_rubber_bonus_two_games_to_none():
    r = Rubber()
    r.record(1, Contract(4, "S", "S"), 10, PLAIN)
    net = r.record(2, Contract(3, "N", "N"), 9, PLAIN)
    assert net == 100 + 700
    assert r.finished[0]["winner"] == "NS" and r.finished[0]["NS"] == 120 + 100 + 700
    assert r.games == {"NS": 0, "EW": 0} and r.lines == [] and r.number == 2


def test_rubber_bonus_two_games_to_one():
    r = Rubber()
    r.record(1, Contract(4, "S", "S"), 10, PLAIN)
    r.record(2, Contract(5, "C", "W"), 11, PLAIN)
    assert r.vulnerability() == "Both"
    net = r.record(3, Contract(4, "H", "N"), 10, PLAIN)
    assert net == 120 + 500


def test_penalties_go_to_defenders_and_use_vulnerability():
    r = Rubber()
    r.record(1, Contract(4, "S", "S"), 10, PLAIN)  # N–S now vulnerable
    assert r.record(2, Contract(4, "S", "S"), 8, PLAIN) == -200
    assert r.lines[-1].side == "EW" and r.lines[-1].where == "above"


def test_honors():
    hands = dict(PLAIN)
    hands["S"] = Hand.of(["SA", "SK", "SQ", "SJ", "HQ", "HJ", "H6", "DA", "D8", "D9", "CA", "C8", "C9"])
    assert honors(hands, "S") == ("S", 100, "four honors")
    assert honors(PLAIN, "S") is None
    aces = dict(PLAIN)
    aces["W"] = Hand.of(["SA", "HA", "DA", "CA", "HT", "H7", "H8", "H9", "DK", "DQ", "CK", "CQ", "CJ"])
    assert honors(aces, "N") == ("W", 150, "four aces")


def test_finished_rubber_keeps_its_pad():
    r = Rubber()
    r.record(1, Contract(4, "S", "S"), 10, PLAIN)
    r.record(2, Contract(3, "N", "N"), 9, PLAIN)
    f = r.finished[0]
    assert f["board"] == 2 and f["games"] == {"NS": 2, "EW": 0}
    assert [l["what"] for l in f["lines"]] == ["4S", "3N", "rubber"]
    assert f["game_ends"] == [1, 2]
    assert sum(l["points"] for l in f["lines"] if l["side"] == "NS") == f["NS"]
