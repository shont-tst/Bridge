"""Opening leads: the card Standard leads lead from a suit, the bots leading and reading it, and the table setting."""
import random

import pytest

from bridge.bidding.conventions import make_engine
from bridge.bidding.lessons import LEADS, signals_deal
from bridge.bots import leads
from bridge.bots.card_play import choose_card
from bridge.bots.difficulty import difficulty
from bridge.bots.sampler import Sampler
from bridge.bots.view import view_for
from bridge.core.auction import Auction
from bridge.core.cards import hands_from_pbn
from bridge.core.play import Play
from bridge.game.room import Room

ENGINE = make_engine()
# West plays 4♠ and North is on lead with ♠9 2, ♥K J 10 9, ♦K 8 5 3 and ♣A 7 2.
HANDS = hands_from_pbn("N:92.KJT9.K853.A72 AKJ4.7643.A2.954 763.Q82.Q74.KJ63 QT85.A5.JT96.QT8")


def _view(seat, *cards, on=True):
    a = Auction("W", ["1S", "P", "4S", "P", "P", "P"])
    ct = a.contract()
    p = Play.start(ct.declarer, ct.strain, HANDS)
    for c in cards:
        p.play(c)
    return view_for(p, a, ct, "None", seat, leads=on)


@pytest.mark.parametrize("holding,trump,card,why", [
    ("SK", "H", "SK", "single"),
    ("SA SK S4", "N", "SA", "ace-king"),
    ("SA S8 S4", "H", "SA", "ace"),
    ("SA S8 S4 S2", "N", "S2", "fourth"),  # against no trump, fourth best from an ace
    ("HA H8 H4", "H", "H4", "low-honor"),  # an ace in trumps isn't led
    ("SK SQ S5", "H", "SK", "sequence"),
    ("SK SQ S5 S2", "N", "SK", "sequence"),  # Standard leads: the same against no trump
    ("SJ ST S3", "N", "SJ", "sequence"),
    ("SK SJ ST S4", "N", "SJ", "inside"),
    ("SA SQ SJ", "N", "SQ", "inside"),
    ("SQ ST S9 S2", "N", "ST", "inside"),
    ("S8 S3", "N", "S8", "doubleton"),
    ("SK S3", "H", "SK", "doubleton"),
    ("SK S7 S3", "N", "S3", "low-honor"),
    ("S8 S6 S2", "N", "S8", "nothing"),
    ("SK SJ S6 S4 S2", "N", "S4", "fourth"),
    ("S9 S7 S5 S3", "N", "S3", "fourth"),
])
def test_method_card(holding, trump, card, why):
    assert leads.method_card(holding.split(), trump) == (card, why)


class TestLeading:
    def test_candidates_are_one_card_per_suit(self):
        assert leads.candidates(_view("N")) == ["S9", "HJ", "D3", "CA"]

    @pytest.mark.parametrize("level", [1, 5, 10])
    def test_bots_lead_by_the_method_at_every_level(self, level):
        for seed in range(4):
            choice = choose_card(_view("N"), ENGINE, difficulty(level), random.Random(seed))
            assert choice.card in ("S9", "HJ", "D3", "CA")
            assert choice.lead == leads.kind(_view("N"), choice.card)

    def test_off_leads_any_card(self):
        view = _view("N", on=False)
        assert not leads.is_opening_lead(view)
        assert choose_card(view, ENGINE, difficulty(10), random.Random(1)).lead is None

    def test_words(self):
        assert leads.words("fourth") == "Standard leads: fourth best."
        assert leads.shows("D3", "S").startswith("Standard leads: fourth best")
        assert leads.shows("SA", "S") == "Standard leads: the ace from ace-king, or rather than lead away from it."


class TestReading:
    def test_consistent(self):
        view = _view("E", "HJ")
        rest = ["S9", "S2", "D8", "D5", "D3", "C7", "C2", "DK", "CA"]
        assert leads.consistent(view, "N", ["HK", "HT", "H9"] + rest)
        assert not leads.consistent(view, "N", ["HK", "H5", "H9"] + rest)  # from K J 9 5 it leads the 5
        assert leads.consistent(view, "E", ["HK", "H5", "H9"] + rest)  # only the leader is read

    def test_declarer_reads_the_lead(self):
        view = _view("E", "HJ")
        deals = Sampler(view, ENGINE, random.Random(3)).sample(40)
        assert deals
        for deal in deals:
            hearts = sorted(c for c in deal["N"] + ["HJ"] if c[0] == "H")
            # the ♥J alone, the top of two, J 10 or K J 10 and so on, but never ♥J 5 3 or ♥J 8 5 4
            assert len(hearts) <= 2 or "HT" in hearts
            assert leads.consistent(view, "N", deal["N"])

    def test_no_reading_with_leads_off(self):
        view = _view("E", "HJ", on=False)
        assert leads.opening(view) is None
        assert Sampler(view, ENGINE, random.Random(3)).leader is None

    def test_a_lead_off_the_method_is_dropped(self):
        view = _view("E", "H9")  # not Standard from ♥K J 10 9: no layout fits, so the lead is dropped, not the deal
        assert len(Sampler(view, ENGINE, random.Random(3)).sample(10)) == 10


class TestTable:
    def test_on_by_default_and_remembered(self):
        room = Room("LEAD", seed=1)
        assert room.settings.leads and room.settings.to_dict()["leads"] is True
        room.update_settings(leads=False)
        assert room.settings.leads is False
        room.update_settings(practice=LEADS)
        assert room.settings.leads  # practicing leads switches them on
        assert room.settings.to_dict()["practice_title"] == "Opening leads"
        room.update_settings(leads=False)
        assert room.settings.practice is None  # switching leads off ends their practice

    def test_restore_keeps_leads(self):
        room = Room("LEAD", seed=1)
        room.update_settings(leads=False)
        room.join("Ann", seat="S")
        room.new_board()
        assert room.table.leads is False
        back = Room.restore(room.snapshot())
        assert back.settings.leads is False and back.table.leads is False

    def test_practice_deal_has_east_declare(self):
        rng = random.Random(5)
        for _ in range(3):
            hands, dealer = signals_deal(ENGINE, rng, declarers="E")
            a = Auction(dealer)
            while not a.is_complete():
                a.add(ENGINE.choose(hands[a.next_to_call], a).call)
            assert a.contract().declarer == "E"

    def test_page(self):
        from fastapi.testclient import TestClient

        from bridge.app import app
        page = TestClient(app).get("/api/conventions/leads").json()
        assert page["title"] == "Opening leads" and page["situations"][0]["play"].startswith("Lead ♠K")


def test_hint_names_the_rule():
    from bridge.game.table import card_hint
    hint = card_hint(_view("N"), ENGINE, random.Random(2))
    assert hint["card"] in ("S9", "HJ", "D3", "CA")
    assert hint["signal"] == leads.words(leads.kind(_view("N"), hint["card"]))


def test_practice_starts_at_souths_lead():
    room = Room("LEAD", seed=3)
    room.join("Ann", seat="S")
    room.update_settings(practice=LEADS)
    for _ in range(2):
        room.new_board()
        t = room.table
        assert t.phase == "playing" and t.contract.declarer == "E" and t.play.next_to_play == "S"
        assert not t.can_undo()  # the calls made for South can't be taken back
        back = Room.restore(room.snapshot())
        assert back.table.fixed == t.fixed and not back.table.can_undo()
        t.phase = "done"


def test_turning_practice_on_mid_board_deals_the_practice_board_now():
    # A reported case: at a table alone, Board 1 already dealt, then Learn & practice, Practice this
    import asyncio
    room = Room("LEAD", seed=5)
    room.join("Ann", seat="S")
    room.new_board()
    assert room.table.phase == "bidding" and room.board_no == 1

    async def go():
        await room.handle("S", {"type": "settings", "practice": LEADS})
    asyncio.run(go())
    t = room.table
    assert room.board_no == 2 and t.phase == "playing" and t.contract.declarer == "E" and t.play.next_to_play == "S"
