import pytest

from bridge.core.auction import Contract
from bridge.core.scoring import duplicate_score, imps


def c(text, doubled=0):
    return Contract(int(text[0]), text[1], "S", doubled)


@pytest.mark.parametrize("contract,tricks,vul,expected", [
    # part scores
    (c("1N"), 7, False, 90),
    (c("2C"), 8, False, 90),
    (c("2H"), 9, False, 140),
    (c("1S"), 8, True, 110),
    # games
    (c("3N"), 9, False, 400),
    (c("3N"), 9, True, 600),
    (c("4H"), 10, False, 420),
    (c("4S"), 11, True, 650),
    (c("5C"), 11, False, 400),
    (c("5D"), 11, True, 600),
    (c("3N"), 10, False, 430),
    # slams
    (c("6S"), 12, False, 980),
    (c("6N"), 12, True, 1440),
    (c("7N"), 13, True, 2220),
    (c("7C"), 13, False, 1440),
    # doubled making
    (c("2H", 1), 8, False, 470),
    (c("1N", 1), 7, False, 180),
    (c("1N", 1), 7, True, 180),
    (c("2S", 1), 9, True, 870),
    (c("4H", 1), 10, True, 790),
    (c("1C", 2), 7, False, 230),
    (c("1C", 2), 8, False, 430),
    # undoubled down
    (c("4S"), 9, False, -50),
    (c("4S"), 7, True, -300),
    # doubled down
    (c("3N", 1), 8, False, -100),
    (c("3N", 1), 7, False, -300),
    (c("3N", 1), 6, False, -500),
    (c("3N", 1), 5, False, -800),
    (c("3N", 1), 4, False, -1100),
    (c("3N", 1), 8, True, -200),
    (c("3N", 1), 7, True, -500),
    (c("3N", 1), 6, True, -800),
    (c("7N", 1), 0, True, -3800),
    # redoubled down
    (c("2S", 2), 6, False, -600),
    (c("2S", 2), 7, True, -400),
])
def test_duplicate_score(contract, tricks, vul, expected):
    assert duplicate_score(contract, tricks, vul) == expected


def test_passed_out_scores_zero():
    assert duplicate_score(None, 0, True) == 0


@pytest.mark.parametrize("diff,expected", [
    (0, 0), (10, 0), (20, 1), (40, 1), (50, 2), (420, 9), (-620, -12),
    (1430, 16), (4000, 24), (9999, 24),
])
def test_imps(diff, expected):
    assert imps(diff) == expected
