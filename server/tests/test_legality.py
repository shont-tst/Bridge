import pytest

from bridge.core.auction import Auction
from bridge.core.board import dealer_for, is_vulnerable, vulnerability_for
from bridge.core.cards import Hand, deal_random, hands_from_pbn
from bridge.core.play import Play, Trick


def auction(dealer, *calls):
    a = Auction(dealer)
    for c in calls:
        a.add(c)
    return a


class TestAuction:
    def test_opening_choices(self):
        a = Auction("N")
        legal = a.legal_calls()
        assert "P" in legal and "1C" in legal and "7N" in legal
        assert "X" not in legal and "XX" not in legal

    def test_bids_must_increase(self):
        a = auction("N", "1H")
        assert not a.is_legal("1D")
        assert not a.is_legal("1H")
        assert a.is_legal("1S")
        with pytest.raises(ValueError):
            a.add("1C")

    def test_double_only_opponents(self):
        a = auction("N", "1H")
        assert a.is_legal("X")  # East may double North
        a.add("P")
        assert not a.is_legal("X")  # South may not double partner
        a.add("P")
        assert a.is_legal("X")  # West may double

    def test_redouble_only_after_double_by_doubled_side(self):
        a = auction("N", "1H", "X")
        assert a.is_legal("XX")  # South
        a.add("P")
        assert not a.is_legal("XX")  # West (doubler's partner)
        a.add("P")
        assert a.is_legal("XX")  # North may redouble
        a.add("XX")
        assert not a.is_legal("X") and not a.is_legal("XX")

    def test_no_double_twice(self):
        a = auction("N", "1H", "X", "P")
        assert not a.is_legal("X")

    def test_completion(self):
        a = auction("N", "P", "P", "P")
        assert not a.is_complete()
        a.add("P")
        assert a.is_complete() and a.is_passed_out() and a.contract() is None
        b = auction("N", "1N", "P", "P", "P")
        assert b.is_complete() and b.legal_calls() == []

    def test_declarer_is_first_to_name_strain(self):
        a = auction("N", "1H", "P", "2C", "P", "2H", "P", "4H", "P", "P", "P")
        ct = a.contract()
        assert (ct.level, ct.strain, ct.declarer, ct.doubled) == (4, "H", "N", 0)
        b = auction("N", "1C", "P", "1H", "P", "2H", "P", "4H", "P", "P", "P")
        assert b.contract().declarer == "S"

    def test_doubled_contract(self):
        a = auction("E", "1S", "2H", "X", "P", "P", "P")
        ct = a.contract()
        assert (ct.level, ct.strain, ct.declarer, ct.doubled) == (2, "H", "S", 1)
        b = auction("E", "1S", "2H", "X", "XX", "P", "P", "P")
        assert b.contract().doubled == 2

    def test_new_bid_clears_double(self):
        a = auction("N", "1H", "X", "2H", "P", "P", "P")
        assert a.contract().doubled == 0

    def test_normalize_aliases(self):
        a = auction("N", "1nt", "dbl")
        assert a.calls == ["1N", "X"]


class TestBoard:
    def test_dealer_cycle(self):
        assert [dealer_for(b) for b in (1, 2, 3, 4, 5)] == list("NESWN")

    def test_vulnerability(self):
        assert [vulnerability_for(b) for b in (1, 2, 3, 4, 13, 16, 17)] == \
            ["None", "NS", "EW", "Both", "Both", "EW", "None"]
        assert is_vulnerable("NS", "S") and not is_vulnerable("NS", "E")
        assert is_vulnerable("Both", "W") and not is_vulnerable("None", "N")


class TestHands:
    def test_deal_random_is_a_full_deck(self):
        hands = deal_random()
        cards = [c for h in hands.values() for c in h.cards]
        assert len(cards) == 52 == len(set(cards))
        assert all(len(h) == 13 for h in hands.values())

    def test_hcp_and_pbn(self):
        h = Hand.from_pbn("AKQJ.T98.765.432")
        assert h.hcp == 10 and h.lengths() == {"S": 4, "H": 3, "D": 3, "C": 3}
        assert h.to_pbn() == "AKQJ.T98.765.432"


PBN = "N:AKQJ.T98.765.432 T98.765.432.AKQJ 765.432.AKQJ.T98 432.AKQJ.T98.765"


class TestPlay:
    def test_must_follow_suit(self):
        p = Play.start("S", "N", hands_from_pbn(PBN))
        assert p.next_to_play == "W"
        p.play("H2") if "H2" in p.hands["W"] else p.play("HA")
        # North holds hearts, must follow
        assert all(c[0] == "H" for c in p.legal_cards("N"))
        with pytest.raises(ValueError):
            p.play("SA")

    def test_cannot_play_out_of_turn(self):
        p = Play.start("S", "N", hands_from_pbn(PBN))
        assert p.legal_cards("N") == []

    def test_void_may_discard_or_ruff(self):
        t = Trick("N", [("N", "H2"), ("E", "S3"), ("S", "H9"), ("W", "HA")])
        assert t.winner("S") == "E"
        assert t.winner("N") == "W"
        assert t.winner("C") == "W"

    def test_full_play_counts_tricks(self):
        p = Play.start("S", "N", hands_from_pbn(PBN))
        while not p.is_complete():
            p.play(p.legal_cards()[0])
        assert len(p.completed_tricks()) == 13
        assert p.tricks_won("NS") + p.tricks_won("EW") == 13
        assert all(len(h) == 0 for h in p.hands.values())
        assert p.next_to_play is None

    def test_trick_winner_leads_next(self):
        p = Play.start("S", "S", hands_from_pbn(PBN))
        lead = p.next_to_play
        for _ in range(4):
            p.play(p.legal_cards()[0])
        assert p.current.leader == p.tricks[0].winner("S")
        assert lead == "W"
