"""Post-hand review: double-dummy cost per card and bids that left the system."""
import random

from bridge.bidding.conventions import make_engine
from bridge.core.auction import Auction
from bridge.core.cards import deal_random, hands_from_pbn, same_side
from bridge.core.play import Play
from bridge.game.review import bidding_review, board_review, play_review

ENGINE = make_engine()


def _auction(dealer, *calls):
    a = Auction(dealer)
    for c in calls:
        a.add(c)
    return a


def _play_out(hands, contract, pick):
    play = Play.start(contract.declarer, contract.strain, hands)
    while not play.is_complete():
        play.play(pick(play.legal_cards()))
    return play


class TestPlayReview:
    def test_losses_account_for_the_gap_to_double_dummy(self):
        """Each card moves the double-dummy result by exactly its cost to the side
        that played it, so the gaps must add up to the actual result."""
        rng = random.Random(11)
        for _ in range(3):
            hands = deal_random(rng)
            ct = _auction("N", "1N", "P", "3N", "P", "P", "P").contract()
            play = _play_out(hands, ct, lambda legal: rng.choice(legal))
            rev = play_review(hands, ct, play.played_cards())
            assert len(rev["cards"]) == 52
            lost_decl = sum(c["lost"] for c in rev["cards"] if c["role"] == "declarer")
            lost_def = sum(c["lost"] for c in rev["cards"] if c["role"] == "defence")
            assert rev["dd_declarer_tricks"] - lost_decl + lost_def == play.declarer_tricks()
            assert all(c["lost"] >= 0 for c in rev["cards"])
            assert all(bool(c["best"]) == (c["lost"] > 0) for c in rev["cards"])

    def test_dummy_cards_are_charged_to_declarer(self):
        hands = deal_random(random.Random(3))
        ct = _auction("N", "1N", "P", "3N", "P", "P", "P").contract()
        play = _play_out(hands, ct, lambda legal: legal[-1])
        rev = play_review(hands, ct, play.played_cards())
        dummy_cards = [c for c in rev["cards"] if c["seat"] == "S"]
        assert dummy_cards and all(c["by"] == "N" for c in dummy_cards)
        assert rev["lost_by"]["S"] == 0

    def test_a_person_playing_a_bot_declarers_hand_is_charged(self):
        """Bot North declares opposite a person in South, who plays both hands: North's cards are theirs too."""
        hands = deal_random(random.Random(3))
        ct = _auction("N", "1N", "P", "3N", "P", "P", "P").contract()
        play = _play_out(hands, ct, lambda legal: legal[-1])
        rev = play_review(hands, ct, play.played_cards(), human_seats={"S"})
        ns = [c for c in rev["cards"] if c["seat"] in "NS"]
        assert ns and all(c["by"] == "S" for c in ns)
        assert rev["lost_by"]["N"] == 0
        assert rev["lost_by"]["S"] == sum(c["lost"] for c in ns)
        # a person declaring in North with a person in South plays as usual
        both = play_review(hands, ct, play.played_cards(), human_seats={"N", "S"})
        assert all(c["by"] == "N" for c in both["cards"] if c["seat"] in "NS")

    def test_a_cold_grand_slam_loses_nothing(self):
        # North holds all thirteen trumps: 7♠ can't fail however North plays
        hands = hands_from_pbn("N:AKQJT98765432... .AKQJT98765432.. ..AKQJT98765432. "
                               "...AKQJT98765432")
        ct = _auction("N", "7S", "P", "P", "P").contract()
        play = _play_out(hands, ct, lambda legal: legal[0])
        rev = play_review(hands, ct, play.played_cards())
        assert rev["dd_declarer_tricks"] == 13
        assert rev["lost_by"]["N"] == 0


class TestBiddingReview:
    def test_flags_calls_that_differ_from_the_system(self):
        rng = random.Random(7)
        while True:
            hands = deal_random(rng)
            if ENGINE.choose(hands["N"], Auction("N")).call == "1N":
                break
        calls = ["2N", "P", "P", "P"]  # North should have opened 1NT
        out = bidding_review(ENGINE, "N", calls, hands, {"N", "S"})
        assert out[0]["index"] == 0 and out[0]["seat"] == "N"
        assert out[0]["system_call"] == "1N" and out[0]["call"] == "2N"
        assert out[0]["system_meaning"]

    def test_system_calls_are_not_flagged_and_bots_are_skipped(self):
        hands = deal_random(random.Random(9))
        a = Auction("N")
        while not a.is_complete():
            a.add(ENGINE.choose(hands[a.next_to_call], a).call)
        assert bidding_review(ENGINE, "N", a.calls, hands, {"N", "S"}) == []
        wild = ["7N", "X", "XX", "P", "P", "P"]
        flagged = bidding_review(ENGINE, "N", wild, hands, {"N", "S"})
        assert {f["seat"] for f in flagged} <= {"N", "S"}

    def test_board_review_for_a_passed_out_board(self):
        hands = deal_random(random.Random(1))
        rev = board_review(ENGINE, hands, "N", ["P"] * 4, None, [], {"N", "S"})
        assert rev["play"] is None
        assert all(same_side(f["seat"], "N") for f in rev["bidding"])


def test_a_trick_given_straight_back_is_charged_to_neither_side():
    """A reported Board 8 (2026-11-04): South's ♦2 cost a trick only if West ducked; West took the ace and gave it
    straight back, so the review charges neither card."""
    from bridge.game.review import _given_back

    cards = [
        {"seat": "E", "by": "W", "card": "DT", "lost": 0},
        {"seat": "S", "by": "S", "card": "D2", "lost": 1},
        {"seat": "W", "by": "W", "card": "DA", "lost": 1},
        {"seat": "N", "by": "N", "card": "D7", "lost": 0},
        {"seat": "W", "by": "W", "card": "C5", "lost": 2},  # later, with North in between: not "straight back"
    ]
    _given_back(cards, "W")
    assert cards[1]["back"] == 1 and cards[1]["given_back"] == {"card": "DA", "by": "W", "seat": "W"}
    assert cards[2]["back"] == 1
    assert "back" not in cards[4]


def test_a_trick_given_back_by_the_next_trick_is_noted_not_netted():
    """A reported Board 5 (2026-11-12, #154): the ♦Q finesse lost a trick, and West's ♥5 at trick 8 gave it back after
    South had followed. The ♦Q is still charged, with a note saying who gave it back."""
    from bridge.game.review import _gave_back_later, _given_back

    cards = [
        {"trick": 7, "seat": "S", "by": "S", "card": "D6", "lost": 0},
        {"trick": 7, "seat": "W", "by": "W", "card": "D5", "lost": 0},
        {"trick": 7, "seat": "N", "by": "S", "card": "DQ", "lost": 1},
        {"trick": 7, "seat": "E", "by": "E", "card": "DK", "lost": 0},
        {"trick": 8, "seat": "E", "by": "E", "card": "CK", "lost": 0},
        {"trick": 8, "seat": "S", "by": "S", "card": "C6", "lost": 0},
        {"trick": 8, "seat": "W", "by": "W", "card": "H5", "lost": 1},
        {"trick": 9, "seat": "E", "by": "E", "card": "DT", "lost": 3},
    ]
    _given_back(cards, "N")
    _gave_back_later(cards, "N")
    assert "back" not in cards[2] and "back" not in cards[6]
    assert cards[2]["later_back"] == {"card": "H5", "by": "W", "seat": "W", "trick": 8}
    assert "later_back" not in cards[6]  # the other side's card isn't noted against ours


def test_no_note_when_our_side_costs_another_trick_first():
    from bridge.game.review import _gave_back_later

    cards = [
        {"trick": 3, "seat": "N", "by": "N", "card": "DQ", "lost": 1},
        {"trick": 3, "seat": "E", "by": "E", "card": "DK", "lost": 0},
        {"trick": 4, "seat": "S", "by": "S", "card": "S2", "lost": 1},
        {"trick": 4, "seat": "W", "by": "W", "card": "H5", "lost": 1},
        {"trick": 6, "seat": "W", "by": "W", "card": "C5", "lost": 1},
    ]
    _gave_back_later(cards, "N")
    assert "later_back" not in cards[0]
    assert cards[2]["later_back"]["card"] == "H5"


def test_opener_passing_over_a_double_waits():
    """A reported Board 3 (#153): opener's Pass over a reopening double read "No reason to bid further" with 16 HCP."""
    from bridge.core.auction import Auction

    assert ENGINE.explain_next(Auction("S", ["1D", "P", "P", "X"]), "P").text == "Nothing to add over the double yet"
    assert ENGINE.explain_next(Auction("S", ["1D", "P", "1H", "P"]), "P").text != "Nothing to add over the double yet"
