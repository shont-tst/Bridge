"""Card-play bot: hidden-information discipline, sampling constraints, legality."""
from dataclasses import replace
import random

from bridge.bidding.conventions import make_engine
from bridge.bots.card_play import _options, choose_card
from bridge.bots.difficulty import difficulty
from bridge.bots.player import BotPlayer
from bridge.bots.sampler import Sampler
from bridge.bots.view import view_for
from bridge.core.auction import Auction, Contract
from bridge.core.cards import HCP_VALUE, Hand, deal_random, hands_from_pbn
from bridge.core.play import Play

ENGINE = make_engine()


def _auction(dealer, *calls):
    a = Auction(dealer)
    for c in calls:
        a.add(c)
    return a


def _swap_hidden(hands, keep):
    """Return hands where the two seats not in `keep` exchange cards randomly but
    keep their counts — the bot's view must not change."""
    hidden = [s for s in "NESW" if s not in keep]
    pool = list(hands[hidden[0]].cards) + list(hands[hidden[1]].cards)
    random.Random(99).shuffle(pool)
    out = dict(hands)
    out[hidden[0]] = Hand.of(pool[:13])
    out[hidden[1]] = Hand.of(pool[13:])
    return out


class TestNoPeeking:
    def test_view_hides_other_hands(self):
        hands = deal_random(random.Random(1))
        a = _auction("N", "1N", "P", "3N", "P", "P", "P")
        ct = a.contract()  # 3N by N, E leads
        play = Play.start(ct.declarer, ct.strain, hands)
        v = view_for(play, a, ct, "None", "E")
        assert v.own_hand == hands["E"].cards
        assert v.dummy_hand is None  # dummy not visible before the opening lead
        assert not hasattr(v, "hands")

    def test_choice_is_independent_of_hidden_cards(self):
        hands = deal_random(random.Random(2))
        a = _auction("N", "1N", "P", "3N", "P", "P", "P")
        ct = a.contract()
        # East leads; East sees only East's hand. North/South/West can be reshuffled
        # among themselves... we keep N (declarer) and W's partner layout varying.
        p1 = Play.start(ct.declarer, ct.strain, hands)
        alt = _swap_hidden(hands, keep="E" + "W")  # N and S exchange cards
        p2 = Play.start(ct.declarer, ct.strain, alt)
        v1 = view_for(p1, a, ct, "None", "E")
        v2 = view_for(p2, a, ct, "None", "E")
        assert v1 == v2
        diff = difficulty(10)
        c1 = choose_card(v1, ENGINE, diff, random.Random(5)).card
        c2 = choose_card(v2, ENGINE, diff, random.Random(5)).card
        assert c1 == c2

    def test_dummy_visible_after_lead(self):
        hands = deal_random(random.Random(3))
        a = _auction("N", "1N", "P", "3N", "P", "P", "P")
        ct = a.contract()
        play = Play.start(ct.declarer, ct.strain, hands)
        play.play(play.legal_cards()[0])
        v = view_for(play, a, ct, "None", "S")  # South is dummy: declarer N decides
        assert v.controller == "N"
        assert set(v.own_hand) == set(play.hands["N"])
        assert set(v.dummy_hand) == set(play.hands["S"])


class TestSampler:
    def test_respects_shown_voids(self):
        rng = random.Random(5)
        while True:  # find a deal where West is void in a suit East can lead
            hands = deal_random(rng)
            voids = [x for x in "SHDC" if hands["W"].length(x) == 0 and hands["E"].length(x)]
            if voids:
                break
        x = voids[0]
        a = _auction("N", "1N", "P", "3N", "P", "P", "P")
        ct = a.contract()
        play = Play.start(ct.declarer, ct.strain, hands)
        play.play(hands["E"].suit(x)[0])          # E leads the suit
        for _ in range(3):                        # S, W (shows out), N
            play.play(play.legal_cards()[0])
        # notrump: West's discard can't win, so West stays hidden from whoever is next
        v = view_for(play, a, ct, "None", play.next_to_play)
        s = Sampler(v, ENGINE, random.Random(1))
        assert x in s.voids["W"] and "W" in s.hidden
        for d in s.sample(15):
            assert all(len(d[seat]) == 12 for seat in "NESW")
            assert len({c for h in d.values() for c in h}) == 48
            assert not any(c[0] == x for c in d["W"])

    def test_uses_auction_constraints(self):
        # North opened 1NT: samples of North's hand (hidden from East) should be 15-17
        rng = random.Random(4)
        while True:
            hands = deal_random(rng)
            if hands["N"].hcp in (15, 16, 17) and ENGINE.choose(hands["N"], Auction("N")).call == "1N":
                break
        a = _auction("N", "1N", "P", "3N", "P", "P", "P")
        ct = a.contract()
        play = Play.start(ct.declarer, ct.strain, hands)
        v = view_for(play, a, ct, "None", "E")
        deals = Sampler(v, ENGINE, random.Random(1)).sample(20)
        for d in deals:
            hcp = sum(HCP_VALUE.get(c[1], 0) for c in d["N"])
            assert 15 <= hcp <= 17


class TestFullPlay:
    def test_bots_play_complete_legal_deals(self):
        rng = random.Random(8)
        bot = BotPlayer(ENGINE, level=4, seed=1)
        for _ in range(2):
            hands = deal_random(rng)
            a = Auction("N")
            while not a.is_complete():
                a.add(bot.bid(hands[a.next_to_call], a).call)
            ct = a.contract()
            if ct is None:
                continue
            play = Play.start(ct.declarer, ct.strain, hands)
            while not play.is_complete():
                seat = play.next_to_play
                v = view_for(play, a, ct, "None", seat)
                choice = bot.play(v)
                assert choice.card in play.legal_cards(seat)
                play.play(choice.card)
            assert play.tricks_won("NS") + play.tricks_won("EW") == 13

    def test_difficulty_levels(self):
        assert difficulty(1).samples < difficulty(10).samples
        assert difficulty(10).temperature == 0 and difficulty(10).blunder == 0
        assert difficulty(99).level == 10 and difficulty(-3).level == 1


class TestSoftenedChoice:
    """A lower level errs between real plans, not by throwing away a free ruff (feedback on board 6, 2026-10-30)."""

    def test_equal_cards_are_one_choice(self):
        per = {"D2": [8, 9], "D5": [8, 9], "D7": [8, 9], "S7": [9, 8]}
        assert sorted(_options(list(per), per, prune=False)) == ["D2", "S7"]

    def test_card_beaten_in_every_layout_is_dropped(self):
        per = {"S7": [10, 11, 10], "SJ": [10, 11, 10], "D2": [9, 11, 9], "HA": [11, 9, 9]}
        assert sorted(_options(list(per), per, prune=True)) == ["HA", "S7"]
        assert sorted(_options(list(per), per, prune=False)) == ["D2", "HA", "S7"]

    def test_dummy_ruffs_from_level_four_up(self):
        # Board 6 from the feedback: 2♠ by East, dummy West void in clubs with ♠J7. Declarer leads ♣4 to dummy.
        hands = hands_from_pbn("N:6432.72.AQ6.QT63 AKQ985.J43.3.874 T.KT65.984.AJ952 J7.AQ98.KJT752.K")
        play = Play.start("E", "S", hands)
        for c in ["CA", "CK", "C3", "C7", "C2", "D5", "CQ", "C8", "S2", "SK", "ST", "SJ", "C4", "C5"]:
            play.play(c)
        view = view_for(play, _auction("E", "2S", "P", "P", "P"), Contract(2, "S", "E"), "NS", "W")
        # A free ruff is an obvious move that intermediate players don't miss: from level 4 a bot
        # never passes one up, however hazy it is about the side suits.
        for level in (4, 6):
            rng = random.Random(5)
            diff = replace(difficulty(level), blunder=0.0)
            picks = [choose_card(view, ENGINE, diff, rng).card for _ in range(20)]
            assert picks == ["S7"] * 20, level

    def test_levels_keep_their_shape(self):
        for level in range(1, 11):
            d = difficulty(level)
            assert d.notice == (1.0 if level >= 4 else 0.0)
            assert d.forget == 0.0 or 4 <= level <= 7


class TestSideSuitMemory:
    """Middle levels lose track of the side suits instead of missing a free ruff."""

    def _view(self):
        # 4♠ by South after six tricks: side-suit small cards have gone and West showed out of clubs
        hands = hands_from_pbn("N:Q72.K84.K73.Q752 643.QJT6.QJT.A63 AKJT98.A5.A8.K84 5.9732.96542.JT9")
        play = Play.start("S", "S", hands)
        guard = random.Random(3)
        while len(play.completed_tricks()) < 6:
            play.play(guard.choice(play.legal_cards()))
        return view_for(play, _auction("S", "1S", "P", "2S", "P", "4S", "P", "P", "P"), Contract(4, "S", "S"),
                        "None", play.next_to_play)

    def test_perfect_memory_changes_nothing(self):
        view = self._view()
        a, b = Sampler(view, ENGINE, random.Random(1)), Sampler(view, ENGINE, random.Random(1), forget=0.0)
        assert a.unknown == b.unknown and a.voids == b.voids

    def test_only_small_side_suit_cards_from_earlier_tricks_blur(self):
        view = self._view()
        sure = Sampler(view, ENGINE, random.Random(1))
        hazy = Sampler(view, ENGINE, random.Random(1), forget=1.0)
        assert len(hazy.unknown) == len(sure.unknown)  # the count of unseen cards stays right
        back = set(hazy.unknown) - set(sure.unknown)   # played cards it thinks are still out
        gone = set(sure.unknown) - set(hazy.unknown)   # unseen cards it thinks have gone
        assert back and len(back) == len(gone)
        earlier = {c for _, cards in view.tricks[:-1] for _, c in cards}
        for c in back | gone:
            assert c[0] != "S" and c[1] in "23456789"
        assert back <= earlier
        assert not back & set(view.own_hand) and not back & set(view.dummy_hand or ())
        for seat, suits in sure.voids.items():  # a void in trumps is never forgotten
            assert ("S" in suits) == ("S" in hazy.voids[seat])

    def test_what_is_forgotten_stays_forgotten_through_the_board(self):
        view = self._view()
        first = Sampler(view, ENGINE, random.Random(1), forget=0.5)
        again = Sampler(view, ENGINE, random.Random(2), forget=0.5)
        assert set(first.unknown) - set(Sampler(view, ENGINE, random.Random(1)).unknown) == \
            set(again.unknown) - set(Sampler(view, ENGINE, random.Random(2)).unknown)
        assert first.voids == again.voids

    def test_a_hazy_bot_still_plays_a_legal_card(self):
        view = self._view()
        for seed in range(5):
            diff = replace(difficulty(5), forget=1.0, blunder=0.0)
            assert choose_card(view, ENGINE, diff, random.Random(seed)).card in view.legal
