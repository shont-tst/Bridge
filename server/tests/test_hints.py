"""Hints: suggested calls and cards, and bid previews before a call is made."""
import asyncio
import random

import pytest

from bridge.game.room import Room
from bridge.game.table import BIDDING, PLAYING
from bridge.solver import HINT, WARM


def _room(seed=1):
    room = Room("HINT", seed=seed)
    room.join("Ann")
    room.join("Bob")
    room.new_board()
    return room


def _to_human_turn(t, human="S"):
    while t.controller_to_act() != human:
        if t.is_bot_turn():
            t.bot_step()
        else:
            t.make_call(t.auction.next_to_call, "P")


class TestBiddingHints:
    def test_hint_is_the_system_call_with_its_meaning(self):
        room = _room()
        t = room.table
        _to_human_turn(t)
        h = t.hint("S")
        assert h["phase"] == BIDDING
        assert h["call"] == t.engine.choose(t.hands["S"], t.auction).call
        assert h["call"] in t.auction.legal_calls() and h["text"]

    def test_only_the_seat_to_act_gets_a_hint(self):
        room = _room()
        t = room.table
        _to_human_turn(t)
        with pytest.raises(ValueError):
            t.hint("N")

    def test_bid_previews_cover_every_legal_call(self):
        room = _room()
        t = room.table
        _to_human_turn(t)
        st = t.state_for("S")
        assert set(st["call_meanings"]) == set(st["legal_calls"])
        assert all(m["text"] for m in st["call_meanings"].values())
        assert t.state_for("N")["call_meanings"] == {}  # not North's turn


class TestPlayHints:
    def _playing_table(self, seed):
        room = _room(seed)
        t = room.table
        while t.auction.next_to_call != "S":
            t.make_call(t.auction.next_to_call, "P")
        t.make_call("S", "3N")
        for _ in range(3):
            t.make_call(t.auction.next_to_call, "P")
        assert t.phase == PLAYING
        return t

    def test_card_hint_is_legal_for_the_hand_being_played(self):
        t = self._playing_table(4)
        t.play_card("W", t.play.legal_cards()[0])
        # North is dummy: declarer South gets the hint for dummy's card
        h = t.hint("S", random.Random(1))
        assert h["seat"] == "N" and h["card"] in t.play.legal_cards()

    def test_card_hint_gives_odds_for_the_top_two_cards(self):
        t = self._playing_table(4)
        while t.controller_to_act() != "S" or len(t.play.legal_cards()) < 2:
            t.play_card(t.controller_to_act(), t.play.legal_cards()[0])
        h = t.hint("S", random.Random(1))
        assert h["goal"] == "make" and h["samples"] > 48
        assert h["odds"][0]["card"] == h["card"] and len(h["odds"]) <= 2
        assert all(0 <= o["pct"] <= 100 for o in h["odds"])
        if len(h["odds"]) == 2:
            assert h["odds"][1]["card"] not in h["equal"] + [h["card"]]

    def test_card_hint_ignores_hidden_cards(self):
        """Swapping the two hidden hands must not change the hint."""
        t1 = self._playing_table(5)
        t1.play_card("W", t1.play.legal_cards()[0])
        t2 = self._playing_table(5)
        t2.play_card("W", t2.play.legal_cards()[0])
        pool = t2.play.hands["E"] + t2.play.hands["W"]
        random.Random(3).shuffle(pool)
        n_east = len(t2.play.hands["E"])
        t2.play.hands["E"], t2.play.hands["W"] = pool[:n_east], pool[n_east:]
        assert t1.hint("S", random.Random(2))["card"] == t2.hint("S", random.Random(2))["card"]


def test_hints_can_be_switched_off():
    room = _room()
    _to_human_turn(room.table)
    room.update_settings(hints=False)
    assert room.state_for("S")["settings"]["hints"] is False
    with pytest.raises(ValueError):
        asyncio.run(room.hint("S"))
    room.update_settings(hints=True)
    assert asyncio.run(room.hint("S"))["type"] == "hint"


def test_card_hint_is_worked_out_before_it_is_asked_for():
    async def go():
        room = _room(4)
        t = room.table
        while t.auction.next_to_call != "S":
            t.make_call(t.auction.next_to_call, "P")
        t.make_call("S", "3N")
        for _ in range(3):
            t.make_call(t.auction.next_to_call, "P")
        while t.controller_to_act() != "S":
            t.play_card(t.controller_to_act(), t.play.legal_cards()[0])
        room.kick_hint()
        await asyncio.sleep(0)
        async with room.lock:
            assert len(room._hints) == 1  # started already
        used = room.help.get("S", {}).get("hints", 0)
        future = next(iter(room._hints.values()))
        assert (await room.hint("S")) is await future  # asking reuses it
        assert room.help["S"]["hints"] == used + 1  # and only asking counts

    asyncio.run(go())


def test_a_warm_up_hint_stops_once_the_card_is_played():
    async def go():
        room = _room(4)
        t = room.table
        while t.auction.next_to_call != "S":
            t.make_call(t.auction.next_to_call, "P")
        t.make_call("S", "3N")
        for _ in range(3):
            t.make_call(t.auction.next_to_call, "P")
        while t.controller_to_act() != "S":
            t.play_card(t.controller_to_act(), t.play.legal_cards()[0])
        room.kick_hint()
        await asyncio.sleep(0)
        async with room.lock:
            [j] = room._hint_jobs.values()
        assert j.priority == WARM and not j.cancelled
        await room.handle("S", {"type": "play", "card": t.play.legal_cards()[0]})
        assert j.cancelled and not any(k[2] == len(t.actions) - 1 for k in room._hints)

    asyncio.run(go())


def test_tapping_hint_hurries_its_warm_up():
    async def go():
        room = _room(4)
        t = room.table
        while t.auction.next_to_call != "S":
            t.make_call(t.auction.next_to_call, "P")
        t.make_call("S", "3N")
        for _ in range(3):
            t.make_call(t.auction.next_to_call, "P")
        while t.controller_to_act() != "S":
            t.play_card(t.controller_to_act(), t.play.legal_cards()[0])
        room.kick_hint()
        await asyncio.sleep(0)
        async with room.lock:
            [j] = room._hint_jobs.values()
        await room.hint("S")
        assert j.priority == HINT

    asyncio.run(go())


def test_card_hint_picks_the_card_with_the_best_odds(monkeypatch):
    """The bot's score counts beating the contract as worth only one trick, so it can like a club that wins more
    tricks on average over a spade that beats the contract more often. The hint goes by the odds it shows."""
    from types import SimpleNamespace

    import bridge.game.table as table_mod
    from bridge.bots.card_play import CardChoice

    scores = {"C2": 3.6, "C6": 3.6, "S6": 3.5, "H5": 2.0}  # average tricks plus the one-trick bonus
    made = {"C2": 29, "C6": 29, "S6": 38, "H5": 10}
    monkeypatch.setattr(table_mod, "choose_card",
                        lambda *a, **k: CardChoice("C2", scores, 100, "best average", made))
    view = SimpleNamespace(seat="W", declarer="N")
    h = table_mod.card_hint(view, None)
    assert h["card"] == "S6" and h["equal"] == [] and h["goal"] == "beat"
    assert h["odds"] == [{"card": "S6", "pct": 38}, {"card": "C2", "pct": 29}]

    made["S6"] = 29  # same odds: more tricks on average wins, and the bot's own pick among equals
    h = table_mod.card_hint(view, None)
    assert h["card"] == "C2" and h["equal"] == ["C2", "C6"]
    assert h["odds"] == [{"card": "C2", "pct": 29}, {"card": "S6", "pct": 29}]


def test_close_calls_get_more_layouts():
    from bridge.bots.card_play import CardChoice, merge, top_two_gap
    a = CardChoice("SA", {"SA": 1.5, "SK": 1.0, "S2": 1.0}, 2, "r", {"SA": 1, "SK": 1, "S2": 1},
                   {"SA": [2, 1], "SK": [1, 1], "S2": [1, 1]})
    assert top_two_gap(a) == 0  # ♠K and ♠2 do the same everywhere: one choice, as often as ♠A
    b = CardChoice("SK", {"SA": 0.0, "SK": 2.0, "S2": 2.0}, 2, "r", {"SA": 0, "SK": 2, "S2": 2},
                   {"SA": [0, 0], "SK": [2, 2], "S2": [2, 2]})
    m = merge(a, b)
    assert m.samples == 4 and m.made == {"SA": 1, "SK": 3, "S2": 3} and len(m.layouts["SA"]) == 4
    assert m.card == "S2"  # the lowest of the cards that do best over all four layouts
    assert top_two_gap(CardChoice("SA", {"SA": 1.0}, 2, "r", {"SA": 1}, {"SA": [1, 1]})) is None


def test_hint_goes_by_one_trick_more_when_making_is_about_equal(monkeypatch):
    """A reported board 8 (2026-11-20): the hint said ♣K 99% · ♣J 98% to make 3♥, the review ♣K 68% vs 34% for the
    10th trick. When making is about equal, the hint ranks by one trick more, as the review does, and shows it."""
    from types import SimpleNamespace

    import bridge.game.table as table_mod
    from bridge.bots.card_play import CardChoice

    # declarer needs 3 more tricks; each layout's value is its tricks, plus 1 when it reaches 3
    layouts = {"CJ": [5.0] * 4 + [4.0] * 6, "CK": [5.0] * 7 + [4.0] * 3, "C5": [2.0] * 10}
    made = {"CJ": 10, "CK": 10, "C5": 0}
    scores = {c: sum(v) / 10 for c, v in layouts.items()}
    monkeypatch.setattr(table_mod, "choose_card",
                        lambda *a, **k: CardChoice("CJ", scores, 10, "best average", made, layouts))
    monkeypatch.setattr(table_mod, "_need", lambda view: 3)
    view = SimpleNamespace(seat="N", declarer="S", contract=SimpleNamespace(level=3), signals=None)
    h = table_mod.card_hint(view, None)
    assert h["card"] == "CK"
    assert h["odds"] == [{"card": "CK", "pct": 100}, {"card": "CJ", "pct": 100}]
    assert h["extra"] == {"label": "10 tricks", "odds": [{"card": "CK", "pct": 70}, {"card": "CJ", "pct": 40}]}

    made["CJ"] = 6  # making is no longer about equal: the hint goes by making alone
    layouts["CJ"] = [5.0] * 6 + [2.0] * 4
    h = table_mod.card_hint(view, None)
    assert h["card"] == "CK" and "extra" not in h
