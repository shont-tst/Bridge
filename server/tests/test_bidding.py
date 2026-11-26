"""Bidding rules, one test class per convention module."""
import random

import pytest

from bridge.bidding.conventions import ALL_CONVENTIONS, make_engine
from bridge.core.auction import Auction
from bridge.core.cards import Hand, deal_random

ENGINE = make_engine()


def H(pbn: str) -> Hand:
    return Hand.from_pbn(pbn)


def bid(hand: str, *calls: str, dealer: str = "N", engine=ENGINE) -> str:
    """What the seat to act bids holding `hand` after `calls` (dealer N)."""
    a = Auction(dealer)
    for c in calls:
        a.add(c)
    return engine.choose(H(hand), a).call


def explain(*calls: str, dealer: str = "N", engine=ENGINE):
    a = Auction(dealer)
    for c in calls:
        a.add(c)
    return engine.explain(a, len(a.calls) - 1)


class TestOpenings:
    @pytest.mark.parametrize("hand,expected", [
        ("AQ3.KJ4.Q873.K92", "1N"),     # 15 balanced
        ("AQ3.KJ4.AQ73.KQ2", "2N"),     # 21 balanced
        ("AKJ52.K4.Q87.J92", "1S"),     # five-card major
        ("AQ52.K4.Q873.J32", "1D"),     # 4 diamonds, 3 clubs → 1D
        ("AQ52.KJ4.Q87.J92", "1C"),     # 3-3 minors → 1C
        ("AQ5.K54.QJ73.K982", "1D"),    # 4-4 minors → 1D
        ("KQJ54.AQ987.4.32", "1S"),     # 5-5: higher-ranking
        ("A2.KQ984.3.AJ987", "1H"),     # 5-5 hearts/clubs → hearts
        ("K2.43.AJ987.KQ54", "1D"),     # longest suit
        ("KQ9873.43.82.J43", "2S"),     # weak two
        ("43.KQJ984.852.43", "2H"),     # weak two
        ("4.KQJ9843.852.43", "3H"),     # three-level pre-empt
        ("AKQJ.AKQ4.AK3.32", "2C"),     # 24 HCP → strong 2C
        ("Q32.K54.Q873.J92", "P"),      # 8 HCP
        ("AJ987.KQ986.2.32", "1S"),     # 10 HCP but Rule of 20
        ("KJ3.Q54.QJ73.K92", "1D"),     # 12 balanced
    ])
    def test_opening(self, hand, expected):
        assert bid(hand) == expected

    def test_weak_two_needs_no_outside_four_card_major(self):
        assert bid("KQ9873.Q432.8.43") != "2S"

    def test_toggle_weak_twos_off(self):
        eng = make_engine({c.id for c in ALL_CONVENTIONS} - {"weak_twos"})
        assert bid("KQ9873.43.82.J43", engine=eng) == "P"

    def test_explain_one_major(self):
        m = explain("1H")
        assert m.length("H")[0] == 5 and m.hcp[0] >= 11

    def test_light_opener_fits_the_bots_picture(self):
        # 10 HCP, 6-4 (Rule of 20) opens. The card-play bots must be able to picture it (the sampler reads `fewest`),
        # while the bidding still counts on opener's usual range.
        from bridge.bots.sampler import _fits
        hand = "AQJ873.K432.8.43"
        assert bid(hand) == "1S"
        eng = make_engine()
        a = Auction("N", ["1S", "P", "2C", "P", "2H"])
        inf = eng.infer(a, "N")
        assert inf.fewest == 10 and inf.hcp[0] >= 11
        assert _fits(list(Hand.from_pbn(hand).cards), inf, 0, 0)


class TestNotrumpResponses:
    @pytest.mark.parametrize("hand,expected", [
        ("Q32.K54.Q873.J92", "2N"),   # 8 balanced
        ("Q32.K54.Q873.Q92", "2N"),   # 9
        ("K32.K54.Q873.Q92", "3N"),   # 10
        ("832.954.Q873.J92", "P"),    # 3
        ("KQ2.KJ4.Q873.KQ2", "4N"),   # 16 quantitative
    ])
    def test_natural(self, hand, expected):
        assert bid(hand, "1N", "P") == expected

    def test_opener_accepts_invitation_with_max(self):
        assert bid("AQ3.KJ4.Q873.KQ2", "1N", "P", "2N", "P") == "3N"
        assert bid("AQ3.KJ4.Q873.K92", "1N", "P", "2N", "P") == "P"

    def test_quantitative(self):
        assert bid("AQ3.KJ4.Q873.KQ2", "1N", "P", "4N", "P") == "6N"
        assert bid("AQ3.KJ4.Q873.K92", "1N", "P", "4N", "P") == "P"


class TestStayman:
    def test_ask(self):
        assert bid("K932.K54.Q87.J92", "1N", "P") == "2C"
        m = explain("1N", "P", "2C")
        assert m.artificial and m.forcing

    @pytest.mark.parametrize("hand,expected", [
        ("AQ3.KJ4.Q873.K92", "2D"),
        ("AQ3.KJ42.Q87.K92", "2H"),
        ("AQ32.KJ4.Q87.K92", "2S"),
        ("AQ32.KJ42.Q8.K92", "2H"),   # both majors: hearts first
    ])
    def test_reply(self, hand, expected):
        assert bid(hand, "1N", "P", "2C", "P") == expected

    def test_fit_game_and_invite(self):
        assert bid("K932.K54.Q87.J92", "1N", "P", "2C", "P", "2S", "P") == "3S"   # 9: invite
        assert bid("K932.K54.A87.J92", "1N", "P", "2C", "P", "2S", "P") == "4S"   # 13: game
        assert bid("K932.K54.A87.J92", "1N", "P", "2C", "P", "2H", "P") == "3N"   # no fit

    def test_opener_finds_spades_after_2n(self):
        # 1NT-2C-2H-2NT: responder has four spades; opener with four spades bids them
        assert bid("AQ32.KJ42.Q8.K92", "1N", "P", "2C", "P", "2H", "P", "2N", "P") in ("3S", "4S")

    def test_garbage_stayman(self):
        assert bid("Q9832.J954.87.92", "1N", "P") == "2C"
        assert bid("Q9832.J954.87.92", "1N", "P", "2C", "P", "2D", "P") == "2S"
        assert bid("Q9832.J954.87.92", "1N", "P", "2C", "P", "2H", "P") == "P"

    def test_reply_after_overcall(self):
        # 1NT-2C-(2D): opener still shows a major; Pass denies one; X is penalty
        assert bid("K763.KQ82.AK4.T9", "1N", "P", "2C", "2D") == "2H"
        assert bid("AQ32.K3.KQ92.J92", "1N", "P", "2C", "2D") == "2S"
        assert bid("AQ3.K32.QJ92.KJ9", "1N", "P", "2C", "2D") == "P"
        assert bid("AQ3.K32.KQJ9.J92", "1N", "P", "2C", "2D") == "X"
        m = explain("1N", "P", "2C", "2D", "P")
        assert m.length("H") == (0, 3) and m.length("S") == (0, 3)

    def test_reply_after_higher_overcall_needs_max(self):
        assert bid("AQ3.KJ32.K92.KJ9", "1N", "P", "2C", "2S") == "3H"   # 17
        assert bid("A3.KJ32.K92.Q982", "1N", "P", "2C", "2S") == "P"    # 15

    def test_reply_after_double(self):
        assert bid("AQ3.KJ42.Q87.K92", "1N", "P", "2C", "X") == "2H"
        assert bid("AQ3.KJ4.Q873.K92", "1N", "P", "2C", "X") == "2D"

    def test_responder_after_contested_reply(self):
        assert bid("A432.J543.Q87.K2", "1N", "P", "2C", "2D", "2H", "P") == "4H"
        assert bid("A432.J543.QJ7.K2", "1N", "P", "2C", "2D", "P", "P") == "3N"
        assert bid("Q9832.J954.87.92", "1N", "P", "2C", "2D", "P", "P") == "2S"
        assert bid("A432.J543.Q87.K2", "1N", "P", "2C", "2D", "X", "P") == "P"

    def test_three_club_stayman_over_2nt(self):
        assert bid("K932.854.Q87.J92", "2N", "P") == "3C"
        assert bid("AQ3.KJ42.AQ7.K92", "2N", "P", "3C", "P") == "3H"


class TestJacoby:
    def test_transfers(self):
        assert bid("932.Q8754.87.J92", "1N", "P") == "2D"
        assert bid("Q8754.932.87.J92", "1N", "P") == "2H"
        m = explain("1N", "P", "2D")
        assert m.artificial and m.length("H")[0] == 5 and m.length("D") == (0, 13)

    def test_opener_completes(self):
        assert bid("AQ3.KJ4.Q873.K92", "1N", "P", "2D", "P") == "2H"
        assert bid("AQ3.KJ4.Q873.K92", "1N", "P", "2H", "P") == "2S"

    @pytest.mark.parametrize("hand,expected", [
        ("932.Q8754.87.J92", "P"),     # weak
        ("932.KQ8754.87.A2", "3H"),    # 9, six hearts → invite
        ("932.KQ875.Q7.Q92", "2N"),    # 9, five hearts → 2NT
        ("A32.KQ8754.K7.Q2", "4H"),    # 14 six hearts → game
        ("A32.KQ875.K7.Q92", "3N"),    # game, five hearts → 3NT
    ])
    def test_responder_rebid(self, hand, expected):
        assert bid(hand, "1N", "P", "2D", "P", "2H", "P") == expected

    def test_opener_converts_3nt_with_support(self):
        assert bid("AQ3.KJ4.Q873.K92", "1N", "P", "2D", "P", "2H", "P", "3N", "P") == "4H"
        assert bid("AQ3.KJ.Q8743.K92", "1N", "P", "2D", "P", "2H", "P", "3N", "P") == "P"

    def test_transfers_over_2nt(self):
        assert bid("932.Q8754.87.J92", "2N", "P") == "3D"
        assert bid("AQ3.KJ4.AQ73.K92", "2N", "P", "3D", "P") == "3H"

    def test_toggle_off_gives_natural_meaning(self):
        eng = make_engine({c.id for c in ALL_CONVENTIONS} - {"jacoby", "minor_transfer"})
        m = explain("1N", "P", "2D", engine=eng)
        assert not m.artificial and m.length("D")[0] == 5
        assert bid("932.Q8754.87.J92", "1N", "P", engine=eng) == "2H"


class TestMinorTransfer:
    def test_sequence(self):
        assert bid("93.54.Q87542.J92", "1N", "P") == "2S"
        assert bid("AQ3.KJ4.Q873.K92", "1N", "P", "2S", "P") == "3C"
        assert bid("93.54.Q87542.J92", "1N", "P", "2S", "P", "3C", "P") == "3D"
        assert bid("93.54.J92.Q87542", "1N", "P", "2S", "P", "3C", "P") == "P"


class TestGerber:
    def test_ask_and_reply(self):
        assert bid("AK3.KQ4.KQ73.Q92", "1N", "P") == "4C"
        assert bid("AQ3.KJ4.Q873.K92", "1N", "P", "4C", "P") == "4H"   # one ace
        assert bid("AQ3.AJ4.Q873.K92", "1N", "P", "4C", "P") == "4S"   # two aces

    def test_signoff_when_two_aces_missing(self):
        assert bid("KQ3.KQ4.KQ73.QJ2", "1N", "P", "4C", "P", "4H", "P") == "4N"


class TestSuitResponses:
    @pytest.mark.parametrize("hand,expected", [
        ("Q32.K54.Q873.J92", "2H"),     # 8, 3-card support
        ("Q32.K54.AQ73.J92", "3H"),     # 11, limit raise
        ("K932.54.Q873.J92", "1S"),     # new suit at 1 level
        ("K93.54.AQ873.KJ2", "2D"),     # 13, two-level new suit
        ("K93.5.Q8732.J932", "1N"),     # 6-10, nothing else
        ("K93.J5.AQ73.QT92", "2N"),     # 11-12 balanced (limit style)
        ("K93.J5.AQ73.KJ92", "3N"),     # 13-15 balanced (limit style)
        ("932.54.Q873.J932", "P"),      # 3 HCP
        ("AKQ93.5.AK73.K92", "2S"),     # 19+, jump shift
    ])
    def test_response_to_1h(self, hand, expected):
        assert bid(hand, "1H", "P") == expected

    def test_limit_nt_responses_meaning(self):
        assert explain("1H", "P", "2N").hcp == (11, 12)
        assert explain("1H", "P", "3N").hcp == (13, 15)

    def test_major_over_longer_minor_when_weak(self):
        # < 12 HCP: a 1-level four-card major beats a longer minor at the 2 level
        assert bid("K932.54.J9.Q8732", "1D", "P") == "1S"

    def test_balanced_11_15_uses_limit_nt_not_two_level_minor(self):
        assert bid("K93.J5.AQ73.QT92", "1H", "P") == "2N"


ON = make_engine({c.id for c in ALL_CONVENTIONS if c.default_on} | {"jacoby_2nt", "negative_doubles"})


class TestJacoby2NTAndNegativeDoubles:
    """Both are off by default (they aren't on the No Fear cheat sheet); these tests switch them on."""

    def test_off_by_default(self):
        assert not {"jacoby_2nt", "negative_doubles"} & ENGINE.enabled
        assert explain("1H", "P", "2N").hcp == (11, 12)

    def test_jacoby_2nt_with_four_trumps_and_game_values(self):
        assert bid("KQ93.A5.KJ73.Q92", "1S", "P", engine=ON) == "2N"

    def test_opener_shows_shortness_then_strength(self):
        assert bid("AKJ93.Q8742.K5.4", "1S", "P", "2N", "P", engine=ON) == "3C"
        assert bid("AKJ93.Q874.K52.4", "1S", "P", "2N", "P", engine=ON) == "3C"
        assert bid("AKJ93.Q87.K52.Q4", "1S", "P", "2N", "P", engine=ON) == "3N"
        assert bid("KJ953.Q87.K52.Q4", "1S", "P", "2N", "P", engine=ON) == "4S"

    def test_negative_double_shows_the_unbid_major(self):
        assert bid("KJ93.854.Q52.K94", "1C", "1H", engine=ON) == "X"
        assert explain("1C", "1H", "X", engine=ON).length("S") == (4, 13)

    def test_opener_answers_a_negative_double(self):
        assert bid("AQ84.K2.83.AJ952", "1C", "1H", "X", "P", engine=ON) == "1S"

    def test_without_negative_doubles_double_is_for_penalty(self):
        assert explain("1C", "1H", "X").text.startswith("Penalty")

    def test_skip_four_card_diamonds_for_major(self):
        assert bid("932.K954.Q873.J9", "1C", "P") == "1H"

    def test_minor_raise(self):
        assert bid("932.54.KQ873.J92", "1D", "P") == "2D"


class TestOpenerRebids:
    def test_after_single_raise(self):
        assert bid("AKJ52.K4.Q87.J92", "1S", "P", "2S", "P") == "P"
        assert bid("AKJ52.KQ4.Q87.J9", "1S", "P", "2S", "P") == "3S"    # 17 TP
        assert bid("AKJ52.KQ4.A87.A9", "1S", "P", "2S", "P") == "4S"    # 21

    def test_after_limit_raise(self):
        assert bid("AKJ52.K4.987.J92", "1S", "P", "3S", "P") == "P"     # 13 TP
        assert bid("AKJ52.K4.A87.J92", "1S", "P", "3S", "P") == "4S"

    def test_balanced_minimum(self):
        assert bid("KJ3.Q54.AJ73.K92", "1D", "P", "1H", "P") == "1N"
        assert bid("KJ3.Q54.AJ73.K92", "1D", "P", "1S", "P") == "1N"

    def test_raise_with_four(self):
        assert bid("KJ32.Q5.AJ73.K92", "1D", "P", "1S", "P") == "2S"

    def test_balanced_18_19_jump_to_2nt(self):
        assert bid("AJ3.KQ4.AJ73.K92", "1D", "P", "1S", "P") == "2N"

    def test_reverse_with_16(self):
        assert bid("A3.AKJ4.KQ873.92", "1D", "P", "1S", "P") == "2H"

    def test_minimum_new_lower_suit(self):
        assert bid("K3.AKJ74.2.Q9873", "1H", "P", "1S", "P") == "2C"


class TestWeakTwos:
    def test_responses(self):
        assert bid("A32.K54.Q873.J92", "2H", "P") == "3H"          # pre-emptive raise
        assert bid("AJ3.K542.Q87.J92", "2H", "P") == "4H"          # four trumps
        assert bid("AK3.A5.KQ873.J92", "2H", "P") == "2N"          # 16, feature ask

    def test_feature_reply(self):
        assert bid("43.KQJ984.852.43", "2H", "P", "2N", "P") == "3H"   # minimum
        assert bid("43.KQJ984.A52.43", "2H", "P", "2N", "P") == "3N"   # max, top honors
        assert bid("43.KJT984.A52.43", "2H", "P", "2N", "P") == "3D"   # feature


class TestStrong2C:
    def test_responses(self):
        assert bid("932.54.Q873.J932", "2C", "P") == "2D"
        assert bid("932.KQ954.A87.J2", "2C", "P") == "2H"

    def test_opener_rebid(self):
        assert bid("AKQ.AKQ4.KJ3.Q32", "2C", "P", "2D", "P") == "2N"
        assert bid("AKQJ.AKQ54.AK3.2", "2C", "P", "2D", "P") == "2H"


class TestCompetitive:
    def test_simple_overcall(self):
        assert bid("AQJ93.54.Q87.J92", "1H") == "1S"

    def test_takeout_double(self):
        assert bid("AQ93.5.KJ87.Q932", "1H") == "X"

    def test_1nt_overcall(self):
        assert bid("AQ3.KJ4.Q873.KJ2", "1H") == "1N"

    def test_weak_jump_overcall(self):
        assert bid("KQJ984.54.Q87.92", "1H") == "2S"

    def test_double_of_1nt_is_penalty(self):
        assert bid("AQ3.KJ4.AQ73.K92", "1N") == "X"
        assert explain("1N", "X").hcp[0] >= 15

    def test_advance_takeout_double(self):
        # 1H X P ?  — weak hand bids its longest unbid suit, preferring a major
        assert bid("Q932.854.J873.92", "1H", "X", "P") == "1S"
        assert bid("Q932.854.KJ73.A2", "1H", "X", "P") == "2S"  # 10: jump

    def test_advance_overcall_with_support(self):
        assert bid("K82.854.Q873.932", "1H", "1S", "P") == "2S"

    def test_strong_doubler_bids_again(self):
        # 1C X 1D P P ?  — East's 20 HCP with five spades must not pass
        assert bid("AK865.3.KQJ9.AK3", "1C", "X", "1D", "P", "P") == "1S"

    def test_explain_takeout_double(self):
        m = explain("1H", "X")
        assert m.forcing and m.hcp[0] >= 11


class TestBlackwood:
    def test_responses(self):
        auction = ("1S", "P", "3S", "P", "4N", "P")
        assert bid("Q932.K54.Q87.J92", *auction) == "5C"
        assert bid("A932.K54.Q87.J92", *auction) == "5D"
        assert bid("A932.A54.Q87.J92", *auction) == "5H"

    def test_signoff_with_two_aces_missing(self):
        auction = ("1S", "P", "3S", "P", "4N", "P", "5D", "P")
        # opener holds one ace: only two between us → sign off at 5S
        assert bid("KQJ52.KQ4.KQ7.Q2", *auction) == "5S"

    def test_slam_with_one_ace_missing(self):
        auction = ("1S", "P", "3S", "P", "4N", "P", "5H", "P")
        assert bid("AKJ52.KQ4.KQ7.Q2", *auction) == "6S"


class TestEngineProperties:
    def test_random_auctions_complete_legally(self):
        rng = random.Random(7)
        for i in range(60):
            hands = deal_random(rng)
            a = Auction("NESW"[i % 4])
            while not a.is_complete():
                call = ENGINE.choose(hands[a.next_to_call], a).call
                assert a.is_legal(call)
                a.add(call)
                assert len(a.calls) < 60

    def test_every_call_has_an_explanation(self):
        rng = random.Random(11)
        hands = deal_random(rng)
        a = Auction("N")
        while not a.is_complete():
            a.add(ENGINE.choose(hands[a.next_to_call], a).call)
        for i in range(len(a.calls)):
            assert ENGINE.explain(a, i).text

    def test_core_conventions_cannot_be_disabled(self):
        eng = make_engine(set())
        assert {"openings", "general"} <= eng.enabled


class TestExplanationsMatchBids:
    """Found by simulating thousands of deals: a call must be explained the way it was meant."""

    def test_new_suit_is_not_read_as_a_raise(self):
        m = explain("1S", "P", "2C")
        assert m.hcp[0] >= 11 and "aise" not in m.text

    def test_one_level_new_suit_shows_four(self):
        assert explain("1H", "P", "1S").length("S")[0] == 4

    def test_new_suit_rebid_after_two_level_response_is_not_a_jump_shift(self):
        m = explain("1S", "P", "2C", "P", "2H")
        assert m.hcp[1] < 19 and not m.game_forcing

    def test_three_level_raise_of_one_level_response_is_a_jump_raise(self):
        assert explain("1H", "P", "1S", "P", "3S").text.startswith("Jump raise")

    def test_cheapest_rebid_of_own_suit_is_not_a_jump(self):
        assert explain("1C", "P", "2D", "P", "3C").text.startswith("Rebid")

    def test_no_slam_from_misread_rebid(self):
        # 1S-2C-2H used to read as a 19-21 jump shift, and responder bid 6NT
        assert bid("54.AT.K43.KQ9642", "P", "1S", "P", "2C", "P", "2H", "P", dealer="N") != "6N"


class TestStrongHandsInCompetition:
    def test_responder_does_not_pass_game_values_after_overcall(self):
        assert bid("AKQ75.A3.2.KQJ42", "1H", "3D") == "3S"
        assert bid("642.AQJ4.743.AK6", "1D", "1S") == "2S"   # cue bid, game forcing
        assert explain("1D", "1S", "2S").game_forcing

    def test_advancer_with_stopper_in_their_major_bids_notrump(self):
        assert bid("AJT2.J94.JT8.KT7", "1S", "X", "P") == "1N"

    def test_forced_four_level_advance_is_not_shown_as_strong(self):
        assert bid("J975.J643.KJ.T53", "3S", "X", "P") == "4H"
        assert explain("3S", "X", "P", "4H").hcp[0] == 0

    def test_advancer_bids_game_over_preempt_with_values(self):
        assert bid("K96.T9543.AKQ8.3", "3D", "X", "P") == "4H"

    def test_no_five_level_cue_bid_when_partner_is_in_game(self):
        # they bid 2H-4H, partner overcalled 4S: a 5H cue bid could be passed out
        assert bid("KQ3.82.AQ73.J962", "2H", "P", "4H", "4S", "P", dealer="S") == "P"

    def test_overcaller_answers_cue_bid_above_3nt(self):
        # they opened 2S, partner cue-bid 4S over my 4C: I must bid
        assert bid("J.742.AKQ7.AJT73", "2S", "P", "3S", "4C", "P", "4S", "P", dealer="W") == "5C"

    def test_no_crash_when_no_room_left(self):
        assert bid("532.AK6.Q8753.32", "2C", "P", "3C", "P", "3S", "P", "6N", "P", "7H", "P", "P", "X",
                   "P", dealer="S")


class TestSweepFindings:
    """Holes found by scripts/bidding_sweep.py (bots bidding thousands of deals against double-dummy par)."""

    def test_overcall_one_honor_with_11_points(self):
        assert bid("A9.K9742.K76.Q104", "1C", dealer="W") == "1H"
        assert bid("A9.K9742.976.J104", "1C", dealer="W") == "P"  # 8 HCP: two honors still needed

    def test_raise_reopening_overcall_after_their_double(self):
        # A reported board (Nov 2, board 1): P (1H) P (P) 1S (X)
        assert bid("K98.52.A842.Q974", "P", "1H", "P", "P", "1S", "X") == "2S"

    def test_flat_hand_declines_game_try(self):
        assert bid("K32.J632.J76.K43", "1H", "P", "2H", "P", "3H", "P") == "P"
        assert bid("K32.J632.J76.A43", "1H", "P", "2H", "P", "3H", "P") == "4H"

    def test_four_card_major_before_penalty_double(self):
        # A reported board: 1C (1D), 10 HCP and Q-10-9-2 behind the overcaller. Show the spades, don't double.
        assert bid("AQJ2.J765.QT92.2", "1C", "1D") == "1S"

    def test_penalty_double_needs_strong_trumps(self):
        assert bid("K2.J76.KQT9.Q754", "1C", "1D") == "X"   # 4 with two of the top three
        assert bid("72.K76.QT873.AJ4", "1C", "1D") == "X"   # 5 with two honors
        assert bid("K2.KJ7.QT92.Q754", "1C", "1D") != "X"   # 4 with only Q-10
        assert explain("1C", "1D", "X").text.startswith("Penalty double")

    def test_hint_text_matches_meaning_of_penalty_double(self):
        a = Auction("N", ["1C", "1D"])
        dec = ENGINE.choose(H("K2.J76.KQT9.Q754"), a)
        assert dec.call == "X" and dec.text == explain("1C", "1D", "X").text

    def test_double_is_negative_when_negative_doubles_are_on(self):
        neg = make_engine({c.id for c in ALL_CONVENTIONS if c.default_on} | {"negative_doubles"})
        assert bid("AQJ2.J765.QT92.2", "1C", "1D", engine=neg) == "X"
        assert explain("1C", "1D", "X", engine=neg).text.startswith("Negative double")

    def test_rescue_partners_overcall_doubled_for_penalty(self):
        assert bid("85..K97652.T8762", "P", "1D", "1H", "X", dealer="S") == "2C"

    def test_slam_try_opposite_a_limited_raise(self):
        assert bid("KT2.AJ.AQ6.K6432", "1H", "P", "2C", "P", "3C", "P") == "4N"

    def test_no_invitation_out_of_a_doubled_contract(self):
        assert bid("863.Q4.T87.AJ863", "1S", "2H", "2S", "X", "P", "P") == "P"

    def test_game_after_contested_stayman_counts_the_five_card_major(self):
        assert bid("QJT43.T953.5.AQ7", "1N", "P", "2C", "2D", "P", "P", dealer="E") == "3S"

    @pytest.mark.parametrize("hand,calls,dealer,expected", [
        ("A8754.AJT.5.A965", ("1C", "P", "P"), "E", "1S"),   # suit too weak to overcall directly
        ("AK92.A732.T5.953", ("1C", "P", "P"), "N", "X"),    # 11 HCP, three clubs
        ("KJ4.Q93.AJ52.Q84", ("1D", "P", "P"), "N", "1N"),   # 11-14 balanced
        ("J865.AKJ5.A43.J3", ("2D", "P", "P"), "N", "X"),    # over a weak two
    ])
    def test_reopen_in_the_pass_out_seat(self, hand, calls, dealer, expected):
        assert bid(hand, *calls, dealer=dealer) == expected

    def test_opener_rebids_over_their_overcall(self):
        assert bid("K.AKQ5.4.KQT9652", "1C", "P", "1D", "1S") == "3C"
        assert bid("A5.KQ84.QJ963.K2", "1D", "P", "1H", "1S") == "3H"
        assert bid("A5.KQ84.AJ963.K2", "1D", "P", "1H", "1S") == "4H"
        assert bid("Q5.K84.AJ963.K82", "1D", "P", "1H", "1S") == "P"

    def test_strong_doubler_bids_again_over_their_raise(self):
        assert bid("AKQ976.Q98.AT.KQ", "1H", "X", "P", "2C", "2H", dealer="E") == "2S"

    def test_feature_shows_a_maximum_so_it_is_not_passed(self):
        assert bid("A8.KJ93.KT5.A872", "2D", "P", "2N", "P", "3S", "P", dealer="E") == "3N"

    def test_no_notrump_game_without_a_stopper_in_their_suit(self):
        assert bid("5.KQT98.73.QJ875", "P", "1S", "2D", "P", "P", "2S", "P", dealer="E") == "P"

    def test_partners_notrump_over_their_suit_counts_as_a_stopper(self):
        assert bid("AK74.983.AT42.A2", "1D", "1H", "1S", "P", "2N", "P", dealer="E") != "P"

    def test_long_strong_suit_rather_than_notrump(self):
        assert bid("32.AKQT984..KQJ5", "1H", "X", "1S", "P", dealer="S") == "3H"

    def test_game_in_the_fit_once_past_3nt(self):
        assert bid("T2.AQ8.QJ3.AQT32", "P", "1S", "2D", "3C", "P", "4C", "P", dealer="E") == "5C"

    @pytest.mark.parametrize("hand,calls,dealer,expected", [
        ("T3.KQJT.KT53.K93", ("1N", "2C"), "S", "3N"),     # game values, stopper
        ("KT982.A63.874.K7", ("1N", "2C"), "N", "3S"),     # five spades, game forcing
        ("9652.K9753.KQ6.A", ("1N", "2C"), "W", "3H"),
        ("A73.4.KQ82.97432", ("1N", "2S"), "W", "2N"),     # 9 HCP: invite
        ("QT753.83.J74.962", ("1N", "2C"), "N", "2S"),     # weak: compete
    ])
    def test_answer_1nt_after_their_overcall(self, hand, calls, dealer, expected):
        assert bid(hand, *calls, dealer=dealer) == expected

    def test_advancer_counts_on_a_two_level_overcall(self):
        assert bid("K76.AJT5.QJT4.64", "P", "1D", "2C", "P", dealer="E") == "2N"

    def test_responder_raise_after_2c_shows_support(self):
        assert bid("A3.AJ973.AK.AJ72", "2C", "P", "2D", "P", "2H", "P", "3H", "P", dealer="W") == "4H"

    def test_opener_raises_after_a_double_of_the_response(self):
        # A reported Board 3: 1H Pass 1S Double, opener with four spades raises as without the double
        assert bid("AK62.A9764.753.7", "1H", "P", "1S", "X", dealer="S") == "2S"
        assert bid("AK62.A9764.753.7", "1H", "P", "1S", "P", dealer="S") == "2S"

    def test_minor_opening_with_a_shorter_major_says_so(self):
        # A reported Board 7: 1D with six diamonds and five spades; the meaning mustn't say "no 5-card major"
        a = Auction("S")
        dec = ENGINE.choose(H("KT854.A3.KQJT82."), a)
        assert dec.call == "1D" and "no 5-card major" not in dec.meaning.text


class TestHandSweep:
    """Found by `python -m scripts.hand_sweep` (see HAND-SWEEP.md); deals are named by sweep set and seed."""

    @pytest.mark.parametrize("hand,calls,dealer", [
        ("Q43.AK3.AK6.AQ97", ("2C", "2D", "P", "P"), "N"),            # 2C strong seed 60000
        ("Q3.AK974.A85.AKQ", ("2C", "3S", "P", "P"), "N"),            # 2C strong seed 60030
        ("AJ63.A7.AQJ4.AQ6", ("2C", "P", "2D", "2H"), "N"),           # 2C strong seed 60019
    ])
    def test_strong_2c_opener_acts_over_interference(self, hand, calls, dealer):
        assert bid(hand, *calls, dealer=dealer) != "P"

    def test_raise_shows_the_length_that_makes_a_fit(self):
        # random seed 137: E opened 1C, W bid 1S (4+), E raised with 4: W with 13 must see the 8-card fit
        m = explain("P", "1C", "1D", "1S", "P", "3S")
        assert m.length("S")[0] == 4
        assert bid("AK62.AJ93.872.J5", "P", "1C", "1D", "1S", "P", "3S", "P") == "4S"
        # partner rebid a 6-card suit: a 2-card raise is a fit (random seed 24)
        assert explain("1S", "2H", "P", "P", "2S", "P", "3S", dealer="W").length("S")[0] == 2

    def test_no_double_jump_invitation_in_a_minor(self):
        # preempt seed 80035: 10 HCP, 7 diamonds; 4D (past 3NT) was an "invitation"
        assert bid("Q9.862.AKJT832.8", "1D", "1H", "1S", "P") == "2D"

    def test_reopening_with_15_plus_balanced_doubles(self):
        # random seed 222: 17 balanced in the pass-out seat bid 1NT, which reopening shows as 11-14
        assert bid("KJ5.AT6.AT93.AJT", "1D", "P", "P", dealer="E") == "X"

    def test_forced_preference_does_not_promise_a_fit(self):
        # random seed 1: S must answer partner's double; 3D with three is a preference, so N with 4 doesn't raise
        assert explain("1D", "1H", "P", "2H", "X", "P", "3D").length("D")[0] == 3
        assert bid("KJ74.J8.AKJ5.AQ6", "1D", "1H", "P", "2H", "X", "P", "3D", "P") == "P"

    def test_running_minor_bids_3nt_over_their_overcall(self):
        # 1NT set, seed 20024: 1NT (2C) with seven solid diamonds
        assert bid("6543.4.AKQJ653.6", "1N", "2C") == "3N"

    def test_transfer_completed_after_a_double(self):
        # 1NT set, seed 30013: opener completes; the table no longer calls it a natural 4-card suit
        assert bid("KJ6.AQ964.K3.KJ9", "1N", "P", "2H", "X") == "2S"
        assert explain("1N", "P", "2H", "X", "2S").length("S")[0] < 4

    @pytest.mark.parametrize("calls,dealer,hand,suit,n", [
        (("P", "1S", "P", "2H", "P", "3H"), "E", "QJ863.843.QJ2.AK", "H", 3),          # random seed 26
        (("2C", "P", "2D", "P", "2S"), "N", "AJ54.A.AKT7.AK94", "S", 4),                 # 2C set, seed 60022
    ])
    def test_explained_length_fits_the_bid(self, calls, dealer, hand, suit, n):
        assert bid(hand, *calls[:-1], dealer=dealer) == calls[-1]
        assert explain(*calls, dealer=dealer).length(suit)[0] <= n

    @pytest.mark.parametrize("calls,dealer,hand", [
        (("2H", "P", "2N", "P", "3H"), "E", "5.AJ8543.JT54.QJ"),                         # random seed 166: 9, no feature
        (("3H", "X", "P", "4C"), "N", "T73.AQ3.Q53.QJ64"),                               # pre-empt set, seed 80020: 11
        (("P", "P", "1D", "1S", "1N", "2S", "P"), "E", "2.AK52.K8743.AK9"),             # random seed 154: 17
        (("1C", "X", "1S", "P", "2N", "P"), "N", "A9765.AK5.KQ74.K"),                    # random seed 257: 19
    ])
    def test_explained_strength_fits_the_bid(self, calls, dealer, hand):
        from bridge.bidding.evaluation import Eval
        assert bid(hand, *calls[:-1], dealer=dealer) == calls[-1]
        lo, hi = explain(*calls, dealer=dealer).hcp
        assert lo <= Eval(H(hand)).hcp <= hi


class TestCompetingAfterTheirBid:
    """When the opponents bid over us: compete in a known fit, or bid a long suit again (checked on sweeps)."""

    def test_raises_a_known_fit_to_the_three_level(self):
        # sweep seed 500409: partner's weak two, they overcall 3♦, 3 spades and 9 HCP: 3♠ (a 9-card fit)
        assert bid("T84.QJ84.AJ2.Q87", "2S", "3D", dealer="E") == "3S"

    def test_rebids_a_six_card_suit_at_the_two_level(self):
        # sweep seed 500318: 1♥ (1♠) 2♥ P P, six spades: 2♠
        assert bid("KT9743.T.AQ652.A", "1H", "1S", "2H", "P", "P", dealer="S") == "2S"

    def test_no_rebid_over_their_3nt(self):
        # sweep seed 508227: bidding a 7-card suit again over their 3NT lost on re-dealt layouts
        assert bid("KJT8743.K65.J4.4", "1D", "1S", "3N", "P", "P", dealer="W") == "P"

    def test_no_rebid_when_partner_doubled_them(self):
        # sweep seed 506608: partner's penalty double of 2♦ stands
        assert bid("T.AQT832.5.KT975", "1H", "2D", "X", "P", dealer="N") == "P"

    def test_doubles_their_game_with_quick_tricks_when_partner_has_values(self):
        # sweep seed 133: partner responded 1♠, they sacrifice in 5♦; ♠AK ♥AQ is 3½ quick tricks
        assert bid("AKT98.AQ8643.5.6", "1H", "X", "1S", "P", "4S", "X", "P", "5D") == "X"

    def test_no_double_of_their_game_when_partner_has_shown_nothing(self):
        # 4 quick tricks, but partner passed: on re-dealt layouts this double lost too often
        assert bid("KQ2.AKJ64.A43.54", "1H", "4S", "P", "P") == "P"
