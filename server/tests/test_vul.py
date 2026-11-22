"""Bidding with the vulnerability in mind (bidding/vul.py), and the Fable review fixes (2026-11-12)."""
from bridge.bidding.conventions import make_engine
from bridge.bidding.vul import ALL, RISKY, Vul
from bridge.bots.player import BotPlayer
from bridge.core.auction import Auction
from bridge.core.cards import Hand

ENGINE = make_engine()


def bid(hand: str, *calls: str, dealer: str = "N", vul=None) -> str:
    return ENGINE.choose(Hand.from_pbn(hand), Auction(dealer, list(calls)), vul=vul).call


class TestVulnerableGame:
    def test_vulnerable_bids_the_close_game(self):
        calls = ("P", "P", "1H", "P", "2H", "P")
        assert bid("Q94.AKQ76.A973.T", *calls, vul="None") == "3H"
        assert bid("Q94.AKQ76.A973.T", *calls, vul="NS") == "4H"

    def test_not_told_the_vulnerability_bids_as_before(self):
        assert bid("Q94.AKQ76.A973.T", "P", "P", "1H", "P", "2H", "P") == "3H"


class TestFavorable:
    def test_compete_lighter_not_vulnerable_against_vulnerable(self):
        assert bid("AJ642.JT.75.5432", "P", "1H", dealer="E", vul="None") == "P"
        assert bid("AJ642.JT.75.5432", "P", "1H", dealer="E", vul="NS") == "1S"  # West: they (NS) are vulnerable

    def test_sacrifice_with_a_ten_card_fit_and_shortness(self):
        calls = ("3D", "P", "4D", "X", "P", "4H")
        assert bid("KQT98.2.T65.K632", *calls, vul="EW") == "5D"
        assert bid("KQT98.2.T65.K632", *calls, vul="Both") == "P"

    def test_no_sacrifice_with_a_flat_hand(self):
        assert bid("T9.983.QT753.A83", "1C", "1D", "1H", "P", "3H", "P", "4H", vul="NS") == "P"


class TestByLevel:
    def test_levels_use_more_of_it(self):
        assert BotPlayer(ENGINE, level=5).vul_for("NS") is None
        assert BotPlayer(ENGINE, level=6).vul_for("NS") == Vul("NS", ALL - RISKY)
        assert BotPlayer(ENGINE, level=8).vul_for("NS") == Vul("NS", ALL)

    def test_middle_levels_skip_the_risky_parts(self):
        calls = Auction("E", ["P", "1H"])
        hand = Hand.from_pbn("AJ642.JT.75.5432")
        assert ENGINE.choose(hand, calls, vul=BotPlayer(ENGINE, level=6).vul_for("NS")).call == "P"
        assert ENGINE.choose(hand, calls, vul=BotPlayer(ENGINE, level=9).vul_for("NS")).call == "1S"


class TestFableReview:
    def test_penalty_double_only_of_a_1nt_opening(self):
        assert bid("KQJ9.AJ632.A.J64", "1S", "P", "1N", "P", "P", dealer="W") != "X"
        assert bid("KQJ9.AJ632.A.J64", "1N", dealer="W") == "X"

    def test_long_major_pulls_partners_3nt(self):
        assert bid("KQJ9543.KT6.A5.T", "P", "1S", "P", "1N", "P", "3S", "P", "3N", "P", dealer="E") == "4S"

    def test_blackwood_stops_in_5_of_the_trump_suit(self):
        assert bid("A9.Q5.A972.KQ932", "1S", "P", "2C", "P", "4C", "P", "4N", "P", "5C", "P", dealer="S") == "P"

    def test_jump_raise_over_their_overcall_is_a_limit_raise(self):
        a = Auction("N", ["P", "P", "1S", "2C", "3S"])
        assert ENGINE.explain(a, 4).hcp == (10, 12)
        assert bid("AKQT95.AT5.43.74", "P", "P", "1S", "2C", "3S", "P") == "4S"

    def test_raise_partners_overcall_over_their_raise(self):
        assert bid("AT75.654.T873.K8", "1D", "1H", "2D", dealer="S") == "2H"

    def test_opener_does_not_jump_to_2nt_with_a_minimum(self):
        assert bid("4.KJ4.KQ2.QJ8543", "1C", "1H", "1S", "P", dealer="W") != "2N"

    def test_advancer_raises_one_level_after_their_raise(self):
        assert bid("A86.K982.984.Q98", "1D", "1H", "1S", dealer="N") == "2H"
