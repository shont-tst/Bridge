"""Bidding with a part score at rubber (bidding/partscore.py)."""
from bridge.bidding.conventions import make_engine
from bridge.bidding.partscore import Score, finishes_game
from bridge.core.auction import Auction
from bridge.core.cards import Hand

ENGINE = make_engine()


def choose(hand: str, calls: list[str], score: Score | None, dealer: str = "N"):
    return ENGINE.choose(Hand.from_pbn(hand), Auction(dealer, list(calls)), score)


def test_finishes_game():
    assert finishes_game(40, "2H") and not finishes_game(30, "2H")
    assert finishes_game(60, "2C") and finishes_game(60, "1N") and not finishes_game(60, "1S")


def test_stops_once_partner_has_made_it_game():
    hand, calls = "AK3.AQJ54.K32.42", ["1H", "P", "2H", "P"]
    assert choose(hand, calls, None).call == "3H"  # a game try at duplicate
    d = choose(hand, calls, Score(40, 0))
    assert d.call == "P" and "40" in d.note and "♥" in d.note


def test_their_part_score_doesnt_stop_us():
    assert choose("AK3.AQJ54.K32.42", ["1H", "P", "2H", "P"], Score(0, 40)).call == "3H"


def test_bids_only_as_high_as_game_needs():
    assert choose("K32.Q54.KJ32.Q42", ["1N", "P"], None).call == "3N"
    d = choose("K32.Q54.KJ32.Q42", ["1N", "P"], Score(40, 0))
    assert d.call == "2N" and d.note


def test_answers_a_forcing_call():
    # Stayman would finish the game with 60 below, but it's artificial: opener still answers it
    assert choose("K432.Q54.KJ3.Q42", ["1N", "P", "2C", "P"], Score(60, 0)).call == "2S"


def test_competes_lighter_against_their_part_score():
    hand, calls = "KJT63.42.A54.J82", ["1H", "P", "2H"]
    assert choose(hand, calls, None, dealer="E").call == "P"
    d = choose(hand, calls, Score(0, 60), dealer="E")
    assert d.call == "2S" and "60" in d.note


def test_no_part_score_changes_nothing():
    hand, calls = "AK3.AQJ54.K32.42", ["1H", "P", "2H", "P"]
    assert choose(hand, calls, Score(0, 0, "Both")) == choose(hand, calls, None)


def test_table_hint_and_bot_why_use_the_score():
    from bridge.bots.player import BotPlayer
    from bridge.game.table import Table
    hands = {"N": "AQ4.KJ3.AQ54.J53", "E": "J98.A9876.T9.K76", "S": "K32.Q54.KJ32.Q42", "W": "T765.T2.876.AT98"}
    t = Table(ENGINE, 1, {"N", "E", "W"}, BotPlayer(ENGINE), hands={s: Hand.from_pbn(h) for s, h in hands.items()},
              dealer="N", vulnerability="None", score=Score(40, 0))
    t.make_call("N", "1N")
    t.make_call("E", "P")
    hint = t.hint("S")
    assert hint["call"] == "2N" and "40 part score" in hint["text"]
    t.make_call("S", "2N")
    t.make_call("W", "P")
    t.bot_step()  # North, with 2NT already game, passes
    assert t.auction.calls[-1] == "P"
    assert t.bot_why(4)["note"] == "2NT is game with the 40 part score."


def test_bot_level_decides_how_much_score_it_uses():
    from bridge.bots.player import BotPlayer
    score = Score(40, 60)
    assert BotPlayer(ENGINE, level=5).score_for(score) is None
    assert BotPlayer(ENGINE, level=6).score_for(score) == Score(40, 60, compete=False)
    assert BotPlayer(ENGINE, level=8).score_for(score) == score
    # a level 6 bot stops at game but doesn't compete lighter; level 8 does both
    hand, calls = "KJT63.42.A54.J82", ["1H", "P", "2H"]
    a = Auction("E", list(calls))
    assert BotPlayer(ENGINE, level=6).bid(Hand.from_pbn(hand), a, Score(0, 60)).call == "P"
    assert BotPlayer(ENGINE, level=8).bid(Hand.from_pbn(hand), a, Score(0, 60)).call == "2S"
    stop = Auction("N", ["1H", "P", "2H", "P"])
    assert BotPlayer(ENGINE, level=5).bid(Hand.from_pbn("AK3.AQJ54.K32.42"), stop, Score(40, 0)).call == "3H"
    assert BotPlayer(ENGINE, level=6).bid(Hand.from_pbn("AK3.AQJ54.K32.42"), stop, Score(40, 0)).call == "P"


def test_part_score_hint_says_it_once():
    """#171: 'Pass: To play: 1♠ is game with the part score 1♠ is game for North–South (90 below the line).'"""
    d = choose("K93.T9765..KQJ76", ["P", "P", "1D", "1S", "P"], Score(90, 0), dealer="E")
    assert d.call == "P" and d.text == "1♠ is game with the 90 part score."
    d = choose("K32.Q54.KJ32.Q42", ["1N", "P"], Score(40, 0))
    assert d.text.count(".") == 2 and d.text.endswith("is game with the 40 part score, so no need for 3NT.")
