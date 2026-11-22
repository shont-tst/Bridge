"""Claims: the Claim button shows only when every remaining trick is certain in any order, and ends the hand with them."""
import asyncio
import random

import pytest

from bridge.core.cards import deal_random, partner, same_side, side
from bridge.core.claim import can_claim, claim_line, lowest, trick_plan
from bridge.core.play import Play, Trick
from bridge.game.room import Room
from bridge.game.table import DONE, PLAYING, Table


def _play(declarer, trump, hands, leader):
    return Play(declarer, trump, {s: list(h) for s, h in hands.items()}, [Trick(leader)])


class TestWhenCertain:
    def test_top_cards_in_one_hand(self):
        p = _play("S", "N", {"S": ["SA", "SK", "HA"], "W": ["SQ", "S2", "H2"], "N": ["C2", "C3", "C4"],
                             "E": ["SJ", "HK", "D2"]}, "S")
        assert can_claim(p)

    def test_two_way_finesse_is_not_certain(self):
        # AJ opposite K10, missing the queen: every layout makes double dummy, but only if you guess right
        p = _play("S", "N", {"S": ["SA", "SJ", "S2"], "N": ["SK", "ST", "S3"], "W": ["SQ", "S4", "S5"],
                             "E": ["S6", "S7", "S8"]}, "S")
        assert not can_claim(p)

    def test_outstanding_trump_could_ruff(self):
        p = _play("S", "H", {"S": ["SA", "SK"], "N": ["C2", "C3"], "W": ["SQ", "H2"], "E": ["S2", "D2"]}, "S")
        assert not can_claim(p)

    def test_an_outstanding_trump_means_no_claim(self):
        # the ace of trumps draws West's last trump, but led in another order a spade could be ruffed
        p = _play("S", "H", {"S": ["HA", "SA", "SK"], "N": ["C2", "C3", "C4"], "W": ["SQ", "H2", "S3"],
                             "E": ["S2", "D2", "D3"]}, "S")
        assert not can_claim(p)
        p.hands["W"] = ["SQ", "C9", "S3"]  # trumps drawn: every card wins in any order
        assert can_claim(p) and claim_line(p) == ("HA", "C2")

    def test_crossing_to_dummy_is_not_a_claim(self):
        # South's small heart reaches dummy's top spades, but only played in that order
        p = _play("S", "N", {"S": ["H2", "C2", "C3"], "N": ["HA", "SA", "SK"], "W": ["H3", "SQ", "C4"],
                             "E": ["H4", "S2", "D2"]}, "S")
        assert not can_claim(p)

    def test_dummy_follows_without_taking_the_lead(self):
        p = _play("S", "N", {"S": ["SQ", "SJ"], "N": ["S3", "D9"], "W": ["H3", "H5"], "E": ["H4", "D2"]}, "S")
        assert claim_line(p) == ("SQ", "S3")
        p.hands["N"] = ["SA", "SK"]  # dummy overtakes, but every card is high, so the tricks win in any order
        assert can_claim(p)

    def test_long_suit_needs_the_others_gone_first(self):
        # AKQ32 against J54: three rounds clear their cards, but the 3 and 2 don't win in any order
        p = _play("S", "N", {"S": ["SA", "SK", "SQ", "S3", "S2"], "N": ["C2", "C3", "C4", "C5", "C6"],
                             "W": ["SJ", "S5", "S4", "D2", "D3"], "E": ["H2", "H3", "H4", "H5", "H6"]}, "S")
        assert not can_claim(p)
        p.hands["W"] = ["D4", "D5", "D6", "D2", "D3"]
        assert can_claim(p)

    def test_board_10_ruffing_out_diamonds_is_not_a_claim(self):
        # A reported Board 10 (3H by South, trick 5): a sure line exists (draw trumps, ruff the third diamond), but
        # only played in that order
        p = _play("S", "H", {"N": ["SQ", "ST", "HQ", "HJ", "H8", "DQ", "D9", "D8", "D4"],
                             "E": ["SK", "S7", "S6", "D5", "CA", "CJ", "C8", "C5", "C2"],
                             "S": ["SA", "HK", "H9", "H7", "H4", "DK", "D7", "CQ", "CT"],
                             "W": ["SJ", "S8", "S4", "HT", "H6", "DJ", "DT", "C9", "C6"]}, "N")
        assert not can_claim(p)

    def test_board_3_partners_trumps_ruff_every_loser(self):
        # A reported Board 3 (4S by South, 2026-11-05): North on lead with K43 of diamonds and a club, South holds the
        # four last trumps, all high. Whatever North leads, South wins it, so it is a claim.
        p = _play("S", "S", {"N": ["DK", "D4", "D3", "C2"], "E": ["DQ", "DJ", "D8", "D7"],
                             "S": ["ST", "S8", "S7", "S4"], "W": ["DT", "D5", "CJ", "CT"]}, "N")
        assert can_claim(p)
        p.hands["W"] = ["DT", "D5", "CJ", "S9"]  # West's 9 of trumps beats three of South's
        assert not can_claim(p)

    def test_defender_claims_with_own_cards_only(self):
        p = _play("N", "N", {"E": ["DA", "DK"], "S": ["C2", "C3"], "W": ["DQ", "C4"], "N": ["H2", "H3"]}, "E")
        assert can_claim(p)
        p.hands["W"], p.hands["E"] = ["DA", "C4"], ["DQ", "DK"]  # partner's ace: East can't know it's there
        assert not can_claim(p)

    def test_mid_trick_with_only_trumps_left(self):
        # A reported screenshot: East leads a diamond, South holds the last two trumps
        p = _play("S", "S", {"E": ["D8", "D7"], "S": ["SQ", "SJ"], "W": ["H2", "H3"], "N": ["S9", "S6"]}, "E")
        p.play("D8")
        assert claim_line(p) is None and can_claim(p)
        assert trick_plan(p)["S"] in ("SQ", "SJ")

    def test_last_card(self):
        p = _play("S", "S", {"S": ["S2"], "W": ["H2"], "N": ["C2"], "E": ["D2"]}, "S")
        assert can_claim(p)
        p.hands["W"] = ["S3"]
        assert not can_claim(p)

    def test_mid_trick_needs_this_trick_too(self):
        # West leads the ace: South's top spades win the rest but not this trick
        p = _play("S", "N", {"W": ["HA", "H2"], "N": ["C2", "C3"], "E": ["H3", "H4"], "S": ["SA", "SK"]}, "W")
        p.play("HA")
        p.play("C2")
        p.play("H3")
        assert not can_claim(p)

    def test_mid_trick_overtake_by_opponent_still_to_play(self):
        # South's king could be beaten by West's ace, still to play
        p = _play("S", "N", {"E": ["H2", "S2"], "S": ["HK", "SA"], "W": ["HA", "S3"], "N": ["C2", "C3"]}, "E")
        p.play("H2")
        assert not can_claim(p)


def _random_endings(n, seed):
    rng = random.Random(seed)
    found = 0
    while found < n:
        hands = deal_random(rng)
        p = Play.start(rng.choice("NESW"), rng.choice("SHDCN"), hands)
        while not p.is_complete():
            if not p.current.cards and can_claim(p):
                found += 1
                yield p
                break
            p.play(rng.choice(p.legal_cards()))


class TestNeverWrong:
    def test_the_line_wins_every_trick_whatever_the_others_play(self):
        rng = random.Random(7)
        for p in _random_endings(150, seed=3):
            claimer = side(p.next_to_play)
            before = p.tricks_won(claimer)
            left = 13 - len(p.completed_tricks())
            while not p.is_complete():  # the claim's line, the other side (and a defender's partner) at random
                lead, follow = claim_line(p)
                leader = p.next_to_play
                p.play(lead)
                for _ in range(3):
                    seat = p.next_to_play
                    p.play(follow if follow and seat == partner(leader) else rng.choice(p.legal_cards()))
            assert p.tricks_won(claimer) == before + left


def _random_mid_trick(n, seed):
    rng = random.Random(seed)
    found = 0
    while found < n:
        p = Play.start(rng.choice("NESW"), rng.choice("SHDCN"), deal_random(rng))
        while not p.is_complete():
            if p.current.cards and can_claim(p):
                found += 1
                yield p
                break
            p.play(rng.choice(p.legal_cards()))


class TestNeverWrongMidTrick:
    def test_the_plan_then_the_line_win_every_trick(self):
        rng = random.Random(11)
        for p in _random_mid_trick(150, seed=4):
            claimer = side(p.next_to_play)
            before = p.tricks_won(claimer)
            left = 13 - len(p.completed_tricks())
            plan = trick_plan(p)
            while p.current.cards and not p.is_complete():
                seat = p.next_to_play
                p.play(plan[seat] if seat in plan else rng.choice(p.legal_cards()))
            while not p.is_complete():
                lead, follow = claim_line(p)
                leader = p.next_to_play
                p.play(lead)
                for _ in range(3):
                    seat = p.next_to_play
                    p.play(follow if follow and seat == partner(leader) else rng.choice(p.legal_cards()))
            assert p.tricks_won(claimer) == before + left


def _room_at_lead(seed=1):
    room = Room("CLAIM", seed=seed)
    room.join("Ann")
    room.new_board()
    return room


def _deal_to_claim(t: Table, rng):
    """Bid and play (bots and random human cards) until the human can claim."""
    while t.phase != DONE:
        c = t.controller_to_act()
        if t.phase == PLAYING and t.can_claim(c):
            return True
        if t.is_bot_turn():
            t.bot_step()
        elif t.phase == PLAYING:
            t.play_card(c, rng.choice(t.play.legal_cards()))
        else:
            t.make_call(t.auction.next_to_call, t.engine.choose(t.hands[t.auction.next_to_call], t.auction).call)
    return False


class TestAtTheTable:
    def _claimable(self):
        rng = random.Random(5)
        for seed in range(1, 60):
            room = _room_at_lead(seed)
            if _deal_to_claim(room.table, rng):
                return room
        raise AssertionError("no claimable position found")

    def test_claim_ends_the_hand_with_every_trick(self):
        room = self._claimable()
        t = room.table
        me = t.controller_to_act()
        assert room.state_for("S", room.players["S"])["table"]["can_claim"] == (me == "S")
        claimer = side(t.play.next_to_play)
        before = t.play.tricks_won(claimer)
        left = 13 - len(t.play.completed_tricks())
        asyncio.run(room.handle(me, {"type": "claim"}))
        assert t.phase == DONE and t.result.claimed
        assert t.play.tricks_won(claimer) == before + left
        assert room.history[-1]["claimed"] == t.result.claimed

    def test_undo_and_restore(self):
        room = self._claimable()
        t = room.table
        me = t.controller_to_act()
        cards = len(t.play.played_cards())
        asyncio.run(room.handle(me, {"type": "claim"}))
        again = Room.restore(room.snapshot())
        assert again.table.phase == DONE and again.table.result.claimed == t.result.claimed
        room.undo()
        assert t.phase == PLAYING and len(t.play.played_cards()) < cards + 1
        assert not room.history

    def test_refused_when_not_certain(self):
        room = _room_at_lead(2)
        t = room.table
        while t.phase != PLAYING or t.is_bot_turn():
            if t.is_bot_turn():
                t.bot_step()
            else:
                t.make_call(t.auction.next_to_call, t.engine.choose(t.hands[t.auction.next_to_call], t.auction).call)
            if t.phase == DONE:
                return
        if not t.can_claim(t.controller_to_act()):
            try:
                t.claim(t.controller_to_act())
            except ValueError:
                return
            raise AssertionError("claim allowed")


def _deal_to_bot_claim(t: Table, rng):
    """Bid and play (bots, and random cards for the human) until a bot claims: an offer, or a claim with nobody on
    the other side to ask."""
    while t.phase != DONE:
        if t.claim_offer:
            return "offer"
        c = t.controller_to_act()
        if t.is_bot_turn():
            step = t.bot_step()
            if step.get("claim"):
                return "claimed"
        elif t.phase == PLAYING:
            t.play_card(c, rng.choice(t.play.legal_cards()))
        else:
            t.make_call(t.auction.next_to_call, t.engine.choose(t.hands[t.auction.next_to_call], t.auction).call)
    return None


@pytest.mark.bot_claims
class TestBotClaims:
    def _find(self, want):
        rng = random.Random(7)
        for seed in range(1, 150):
            room = _room_at_lead(seed)
            if _deal_to_bot_claim(room.table, rng) == want:
                return room
        raise AssertionError(f"no bot {want} found")

    def test_offer_waits_for_the_other_side(self):
        room = self._find("offer")
        t = room.table
        offer = room.state_for("S", room.players["S"])["table"]["claim_offer"]
        by = offer["by"]
        assert offer["you_decide"] and not same_side(by, "S") and offer["tricks"] >= 2
        assert sorted(offer["cards"]) == sorted(t.play.hands[by])
        if by == t.contract.declarer:  # dummy's cards come with declarer's claim
            assert sorted(offer["dummy_cards"]) == sorted(t.play.hands[t.play.dummy])
        else:
            assert offer["dummy_cards"] is None
        assert not t.is_bot_turn() and not t.can_claim("S")
        with pytest.raises(ValueError):
            t.play_card(t.controller_to_act(), t.play.legal_cards()[0])

    def test_accept_gives_the_claimer_every_trick(self):
        room = self._find("offer")
        t = room.table
        by = t.claim_offer["by"]
        before, left = t.play.tricks_won(side(by)), t.tricks_left()
        asyncio.run(room.handle("S", {"type": "claim_answer", "accept": True}))
        assert t.phase == DONE and t.result.claimed == by
        assert t.play.tricks_won(side(by)) == before + left
        again = Room.restore(room.snapshot())
        assert again.table.phase == DONE and again.table.result.claimed == by

    def test_reject_plays_on_and_the_bot_does_not_claim_again(self):
        room = self._find("offer")
        t = room.table
        by = t.claim_offer["by"]
        t.answer_claim("S", False)
        assert t.claim_offer is None and t.is_bot_turn() and by in t.claim_refused
        rng = random.Random(3)
        while t.phase != DONE:
            assert t.claim_offer is None
            if t.is_bot_turn():
                assert not t.bot_step().get("claim")
            else:
                t.play_card(t.controller_to_act(), rng.choice(t.play.legal_cards()))

    def test_a_rejected_claim_stays_rejected_after_undo(self):
        # A reported Board 6: after Reject and then Undo, the bot claimed again and play stuck
        room = self._find("offer")
        t = room.table
        by = t.claim_offer["by"]
        t.answer_claim("S", False)
        rng = random.Random(4)
        while t.phase != DONE and t.controller_to_act() in t.bot_seats:
            t.bot_step()
        if t.phase == DONE:
            return
        t.play_card("S", rng.choice(t.play.legal_cards()))
        t.undo()
        assert by in t.claim_refused
        while t.phase != DONE:
            assert t.claim_offer is None
            if t.is_bot_turn():
                assert not t.bot_step().get("claim")
            else:
                t.play_card(t.controller_to_act(), rng.choice(t.play.legal_cards()))

    def test_only_the_other_side_answers(self):
        room = self._find("offer")
        t = room.table
        by = t.claim_offer["by"]
        with pytest.raises(ValueError):
            t.answer_claim(by, True)

    def test_offer_survives_a_restart(self):
        room = self._find("offer")
        again = Room.restore(room.snapshot())
        assert again.table.claim_offer == room.table.claim_offer and not again.table.is_bot_turn()

    def test_a_person_playing_both_hands_decides(self):
        # the bot partner (N) declares, so South plays both hands: a defender's claim is put to South, not taken
        for seed in range(1, 40):
            t = _room_at_lead(seed).table
            if _deal_to_bot_claim(t, random.Random(7)) == "offer" and t.contract.declarer == "N" \
                    and t.claim_offer["by"] in "EW":
                break
        else:
            pytest.fail("no deal where a defender claims against North")
        assert t.claim_offer["deciders"] == ["S"]

    def test_nobody_to_ask_claims_at_once(self):
        room = self._find("claimed")
        t = room.table
        assert t.phase == DONE and same_side(t.result.claimed, "S")

    def test_a_claim_nobody_saw_keeps_its_cards_for_a_pop_up(self):
        # Feedback #156: a bot partner's claim on defense, with only bots to decide, ended the hand without showing
        # its cards. They're kept on the result, and South (who didn't see them) isn't among those who saw them.
        room = self._find("claimed")
        r = room.table.result
        assert r.claim_cards and r.claimed in r.claim_cards and sum(map(len, r.claim_cards.values())) > 0
        assert "S" not in r.claim_saw and r.claimed in r.claim_saw
        shown = room.state_for("S", room.players["S"])["table"]["result"]
        assert shown["claim_cards"] == r.claim_cards

    def test_accepting_a_claim_counts_as_seeing_it(self):
        room = self._find("offer")
        t = room.table
        by = t.claim_offer["by"]
        cards = sorted(t.play.hands[by])
        asyncio.run(room.handle("S", {"type": "claim_answer", "accept": True}))
        assert "S" in t.result.claim_saw and sorted(t.result.claim_cards[by]) == cards
        again = Room.restore(room.snapshot())
        assert "S" in again.table.result.claim_saw  # a restored claim doesn't pop up again


@pytest.mark.bot_claims
def test_with_two_defenders_the_first_accept_settles_it():
    # Feedback #164: the first to accept goes straight on to the score; the partner, who hadn't answered, gets the
    # claimer's cards in a pop-up to look over (they're not among those who saw it). No board starts until both
    # tap Next board, as usual.
    rng = random.Random(7)
    for seed in range(1, 300):
        room = Room("CLAIM", seed=seed)
        room.join("Ann")
        room.join("Bob")
        room.new_board()
        t = room.table
        if _deal_to_bot_claim(t, rng) == "offer" and len(t.claim_offer["deciders"]) == 2:
            break
    else:
        raise AssertionError("no claim offer to two people found")
    first, other = t.claim_offer["deciders"]
    by = t.claim_offer["by"]
    asyncio.run(room.handle(first, {"type": "claim_answer", "accept": True}))
    assert t.phase == DONE and t.result.claimed == by and t.result.claim_accepted == first
    assert first in t.result.claim_saw and other not in t.result.claim_saw
    shown = room.state_for(other, room.players[other])["table"]
    assert shown["claim_offer"] is None and shown["result"]["claim_cards"] == t.result.claim_cards
