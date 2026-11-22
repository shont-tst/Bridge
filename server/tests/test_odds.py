import random

from bridge.bidding.conventions import ALL_CONVENTIONS, make_engine
from bridge.core.auction import Contract
from bridge.core.cards import SEATS, deal_random
from bridge.core.play import Play
from bridge.game.odds import add_odds, best_card, card_odds


def _board(seed=5):
    hands = deal_random(random.Random(seed))
    contract = Contract(3, "N", "S")
    p = Play.start("S", "N", hands)
    while not p.is_complete():
        p.play(p.legal_cards()[0])
    return hands, contract, p.played_cards()


def test_card_odds_are_percentages_for_the_players_goal():
    engine = make_engine({c.id for c in ALL_CONVENTIONS if c.default_on})
    hands, contract, play = _board()
    calls = ["1N", "P", "3N", "P", "P", "P"]  # dealer South
    odds = card_odds(engine, hands, "S", "None", calls, contract, play, 4, random.Random(1), samples=12)
    assert odds is not None
    assert odds["goal"] == ("make" if play[4][0] in "NS" else "beat")
    assert 0 <= odds["played"] <= odds["best_pct"] <= 100
    assert odds["samples"] > 0
    assert odds["better"] in (True, False) and odds["tricks"] is None
    if odds["best"] == play[4][1]:
        assert not odds["better"]


def test_add_odds_only_for_costly_cards():
    engine = make_engine({c.id for c in ALL_CONVENTIONS if c.default_on})
    hands, contract, play = _board()
    cards = [{"lost": 1 if i in (4, 5) else 0, "by": s if s != "N" else "S"} for i, (s, _) in enumerate(play)]
    review = {"play": {"cards": cards}}
    add_odds(review, engine, hands, "S", "None", ["1N", "P", "3N", "P", "P", "P"], contract, play,
             {"S", "N"}, random.Random(2))
    with_odds = [i for i, c in enumerate(cards) if "odds" in c]
    assert set(with_odds) <= {4, 5}




def test_bad_luck_is_not_a_mistake():
    """Both cards reach the target as often: the one played is not flagged, whatever double dummy says."""
    assert best_card({"HA": 100, "HT": 100}, "HT") == ("HT", False)


def test_a_clearly_better_chance_is_flagged():
    assert best_card({"HA": 90, "HT": 70}, "HT") == ("HA", True)
    assert best_card({"HA": 73, "HT": 70}, "HT")[1] is False  # within the noise


def test_odds_for_the_tricks_the_side_could_have_had():
    engine = make_engine({c.id for c in ALL_CONVENTIONS if c.default_on})
    hands, contract, play = _board()
    calls = ["1N", "P", "3N", "P", "P", "P"]
    odds = card_odds(engine, hands, "S", "None", calls, contract, play, 4, random.Random(1), samples=12, reach=2,
                     hindsight=play[4][1])
    assert odds is not None
    assert odds["hindsight"] == play[4][1] and odds["hindsight_pct"] == odds["played"]
    assert odds["tricks"] == 2 + _won_before(hands, contract, play, 4)


def _won_before(hands, contract, play, index):
    from bridge.core.cards import side
    p = Play.start(contract.declarer, contract.strain, hands)
    for _, card in play[:index]:
        p.play(card)
    return p.tricks_won(side(play[index][0]))


def test_hindsight_is_the_best_bet_among_the_cards_that_worked():
    """When several cards would have worked this time, the review names the one with the best odds, so a better bet
    that also worked isn't set against another card that worked."""
    engine = make_engine({c.id for c in ALL_CONVENTIONS if c.default_on})
    hands, contract, play = _board()
    calls = ["1N", "P", "3N", "P", "P", "P"]
    p = Play.start(contract.declarer, contract.strain, hands)
    for _, card in play[:4]:
        p.play(card)
    legal = p.legal_cards()
    odds = card_odds(engine, hands, "S", "None", calls, contract, play, 4, random.Random(1), samples=12, reach=2,
                     hindsight=legal)
    assert odds is not None
    assert odds["hindsight"] == odds["best"] and odds["hindsight_pct"] == odds["best_pct"]


def test_odds_ahead_finds_the_same_costly_cards_as_the_review():
    """Worked out card by card during the board, each card's cost matches the end-of-board review's."""
    from bridge.game.odds import odds_ahead
    from bridge.game.review import play_review
    engine = make_engine({c.id for c in ALL_CONVENTIONS if c.default_on})
    hands, contract, play = _board()
    calls = ["1N", "P", "3N", "P", "P", "P"]
    cards = play_review(hands, contract, play)["cards"]
    for i in range(12):
        ahead = odds_ahead(engine, hands, "S", "None", calls, contract, play[:i + 1], random.Random(i))
        assert ahead["lost"] == cards[i]["lost"]
        if cards[i]["lost"] <= 0:
            assert ahead["odds"] is None


def test_add_odds_uses_odds_worked_out_during_the_board(monkeypatch):
    import bridge.game.odds as odds_mod
    engine = make_engine({c.id for c in ALL_CONVENTIONS if c.default_on})
    hands, contract, play = _board()
    cards = [{"lost": 1 if i in (4, 5) else 0, "by": "S"} for i in range(len(play))]
    worked = []
    real = odds_mod.card_odds
    monkeypatch.setattr(odds_mod, "card_odds", lambda *a, **k: worked.append(a[7]) or real(*a, **k))
    ready = {4: {"lost": 1, "odds": {"played": 40, "best": "SA"}}, 5: {"lost": 2, "odds": {"played": 1}}}
    add_odds({"play": {"cards": cards}}, engine, hands, "S", "None", ["1N", "P", "3N", "P", "P", "P"], contract,
             play, {"S"}, random.Random(2), ready=ready)
    assert cards[4]["odds"] == {"played": 40, "best": "SA"}  # used as it was
    assert worked == [5]  # its cost differs from the review's (a card taken back and played again): worked out again


def test_the_review_odds_are_ready_when_the_board_ends(monkeypatch):
    """The table works out each card's odds as it's played, so the review needn't start them at the end."""
    import asyncio
    import bridge.game.odds as odds_mod
    from bridge.game.room import Room
    from bridge.game.table import DONE

    async def go():
        room = Room("ODDS", seed=4)
        room.join("Ann")
        room.new_board()
        t = room.table
        t.bot_claims = False
        while t.auction.next_to_call != "S":
            t.make_call(t.auction.next_to_call, "P")
        t.make_call("S", "3N")
        for _ in range(3):
            t.make_call(t.auction.next_to_call, "P")
        while t.phase != DONE:
            t.play_card(t.controller_to_act(), t.play.legal_cards()[-1])
            room.kick_odds_ahead()
            await room._ahead_task
        room.record_result()
        review = t.result.review
        assert sum(1 for k in room._ahead if k[2] != "bids") == 52  # every card, and the bidding once
        monkeypatch.setattr(odds_mod, "card_odds", lambda *a, **k: (_ for _ in ()).throw(AssertionError("again")))
        room.fill_odds(t, review)
        assert "odds_error" not in review and review["odds_pending"] is False
        costly = [c for c in review["play"]["cards"] if c["lost"] > 0]
        assert costly and all("odds" in c for c in costly)

    asyncio.run(go())
