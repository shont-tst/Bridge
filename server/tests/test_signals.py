"""Defensive signals: which card a defender picks to signal, what partner reads from it, and the table setting."""
import random

from bridge.bidding.conventions import make_engine
from bridge.bidding.lessons import SIGNALS, signals_deal
from bridge.bots import signals
from bridge.bots.card_play import choose_card
from bridge.bots.difficulty import difficulty
from bridge.bots.sampler import Sampler
from bridge.bots.view import view_for
from bridge.core.auction import Auction
from bridge.core.cards import hands_from_pbn
from bridge.core.play import Play
from bridge.game.room import Room

ENGINE = make_engine()
# West plays 4♠ and North leads the ♥K. South has ♥Q 8 2 (likes hearts); North has ♦K 8 5 3 (four, an even number).
HANDS = hands_from_pbn("N:92.KJT9.K853.A72 AKJ4.7643.A2.954 763.Q82.Q74.KJ63 QT85.A5.JT96.QT8")


def _start(*cards):
    a = Auction("W", ["1S", "P", "4S", "P", "P", "P"])
    ct = a.contract()
    p = Play.start(ct.declarer, ct.strain, HANDS)
    for c in cards:
        p.play(c)
    return p, a, ct


def _view(seat, method, *cards):
    p, a, ct = _start(*cards)
    return view_for(p, a, ct, "None", seat, method)


class TestGiving:
    def test_attitude_on_partners_lead(self):
        assert signals.pick(_view("S", "standard", "HK", "H3"), "H2", ["H8", "H2"])[0] == "H8"
        assert signals.pick(_view("S", "upside", "HK", "H3"), "H2", ["H8", "H2"])[0] == "H2"

    def test_count_on_declarers_lead(self):
        cards = ("HK", "H3", "H8", "HA", "DJ")
        assert signals.pick(_view("N", "standard", *cards), "D3", ["D8", "D5", "D3"])[0] == "D8"
        assert signals.pick(_view("N", "upside", *cards), "D3", ["D8", "D5", "D3"])[0] == "D3"

    def test_no_signal_without_the_setting_or_for_declarer(self):
        assert signals.pick(_view("S", None, "HK", "H3"), "H2", ["H8", "H2"]) == ("H2", None)
        assert signals.situation([("N", ())], "W", "S5", "W", "S", None) is None

    def test_words(self):
        _, said = signals.pick(_view("S", "standard", "HK", "H3"), "H2", ["H8", "H2"])
        assert signals.words(said) == "Standard signals: a high card says it likes ♥."
        assert signals.words(said, you=True) == "Standard signals: a high card says you like ♥."

    def test_bot_signals_at_the_table(self):
        choice = choose_card(_view("S", "standard", "HK", "H3"), ENGINE, difficulty(10), random.Random(1))
        assert choice.card != "H2"  # never the discouraging card with the queen
        if choice.card == "H8":
            assert choice.signal["kind"] == "attitude" and choice.signal["yes"]


class TestReading:
    def test_consistent(self):
        view = _view("N", "standard", "HK", "H3", "H8", "HA")
        seen = signals.seen(view)
        assert [(s.seat, s.card, s.sig.kind) for s in seen] == [("S", "H8", "attitude")]
        rest = ["S7", "S6", "S3", "D7", "D4", "C6", "C3"]
        assert signals.consistent(view, seen, "S", ["HQ", "H2"] + rest)
        assert not signals.consistent(view, seen, "S", ["H5", "H2"] + rest)  # high without an honor
        assert signals.consistent(view, seen, "S", ["CK", "CJ"] + rest)  # the 8 was its lowest: it said no

    def test_partner_reads_the_signal(self):
        view = _view("N", "standard", "HK", "H3", "H8", "HA")
        for deal in Sampler(view, ENGINE, random.Random(3)).sample(40):
            south = deal["S"]
            if any(c in south for c in ("H5", "H2")):
                assert "HQ" in south

    def test_no_reading_without_the_setting(self):
        assert signals.seen(_view("N", None, "HK", "H3", "H8", "HA")) == []


class TestTable:
    def test_setting(self):
        room = Room("SIG", seed=1)
        assert room.settings.signals == "off" and room.settings.method is None
        room.update_settings(signals="upside")
        assert room.settings.to_dict()["signals"] == "upside"
        room.update_settings(practice=SIGNALS)
        assert room.settings.signals == "upside"  # practice keeps the chosen method
        room.update_settings(signals="off")
        assert room.settings.practice is None  # switching signals off ends their practice

    def test_practice_switches_signals_on(self):
        room = Room("SIG", seed=1)
        room.update_settings(practice=SIGNALS)
        assert room.settings.signals == "standard"
        assert room.settings.to_dict()["practice_title"] == "Signals"

    def test_restore_keeps_signals(self):
        room = Room("SIG", seed=1)
        room.update_settings(signals="standard")
        room.join("Ann", seat="S")
        room.new_board()
        back = Room.restore(room.snapshot())
        assert back.settings.signals == "standard" and back.table.signals == "standard"

    def test_practice_deal_has_east_or_west_declare(self):
        rng = random.Random(5)
        for _ in range(3):
            hands, dealer = signals_deal(ENGINE, rng)
            a = Auction(dealer)
            while not a.is_complete():
                a.add(ENGINE.choose(hands[a.next_to_call], a).call)
            assert a.contract().declarer in "EW"


def test_hint_says_what_the_card_signals():
    from bridge.game.table import card_hint
    hint = card_hint(_view("S", "standard", "HK", "H3"), ENGINE, random.Random(2))
    if hint["card"] == "H8":
        assert hint["signal"] == "Standard signals: a high card says you like ♥."
    assert hint["card"] != "H2"


def test_practice_starts_with_south_defending():
    room = Room("SIG", seed=4)
    room.join("Ann", seat="S")
    room.update_settings(practice=SIGNALS)
    room.new_board()
    t = room.table
    assert t.phase == "playing" and t.contract.declarer in "EW" and not t.can_undo()
