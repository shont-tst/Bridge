"""Convention explainers and practice deals."""
import asyncio
import random

import pytest
from fastapi.testclient import TestClient

from bridge.app import app
from bridge.bidding.conventions import ALL_CONVENTIONS, BY_ID, make_engine, requirements
from bridge.bidding.lessons import LESSONS, STUDENT, examples_for, practice_deal, uses_lesson
from bridge.core.auction import Auction
from bridge.game.room import Room

ENGINE = make_engine({c.id for c in ALL_CONVENTIONS})


def test_every_switchable_convention_has_a_lesson():
    assert {c.id for c in ALL_CONVENTIONS if not c.core} == {l.conv for l in LESSONS.values() if l.conv}


def test_base_system_lessons_name_real_rules():
    names = {r.name for c in ALL_CONVENTIONS for r in c.rules}
    for lesson in LESSONS.values():
        assert set(lesson.rules) <= names, lesson.id
        assert lesson.conv or lesson.title


@pytest.mark.parametrize("conv", sorted(LESSONS))
def test_examples_are_legal_and_use_the_convention(conv):
    lesson = LESSONS[conv]
    assert lesson.explainer and lesson.examples
    for title, calls in lesson.examples:
        a = Auction(lesson.dealer, list(calls))
        assert a.is_complete(), title
        assert any(ENGINE.explain_rule(a, i) and lesson.uses(ENGINE.explain_rule(a, i))
                   for i in range(len(calls))), f"{conv}: {title} never uses the convention"
    for ex in examples_for(ENGINE, lesson):
        assert all(c["text"] for c in ex["calls"])


@pytest.mark.parametrize("conv", sorted(LESSONS))
def test_practice_deals_bring_up_the_convention(conv):
    rng = random.Random(1)
    for _ in range(3):
        hands, dealer = practice_deal(ENGINE, conv, rng)
        assert len({c for h in hands.values() for c in h.cards}) == 52
        assert all(len(h) == 13 for h in hands.values())
        assert uses_lesson(ENGINE, hands, dealer, LESSONS[conv])
        # the human in South is the one who uses the convention
        assert dealer == LESSONS[conv].seats()[0]


class TestPracticeRoom:
    def _room(self):
        room = Room("PRAC", seed=2)
        room.join("Ann")
        room.join("Bob")
        return room

    def test_practice_switches_the_convention_on_and_deals_for_it(self):
        room = self._room()
        room.update_settings(conventions=["stayman"])  # Jacoby off
        room.update_settings(practice="minor_transfer")
        assert {"minor_transfer", "jacoby"} <= room.settings.conventions
        asyncio.run(room.handle("S", {"type": "next_board"}))
        t = room.table
        assert t.dealer == "N"  # North opens 1NT; South uses the transfer
        assert uses_lesson(room.engine, t.hands, t.dealer, LESSONS["minor_transfer"])

    def test_switching_the_convention_off_stops_practice(self):
        room = self._room()
        room.update_settings(practice="stayman")
        room.update_settings(conventions=["jacoby"])
        assert room.settings.practice is None
        room.update_settings(practice="gerber")
        room.update_settings(practice="")
        assert room.settings.practice is None

    def test_practicing_part_of_the_base_system(self):
        room = self._room()
        room.update_settings(practice="takeout_doubles")
        room.update_settings(conventions=["stayman"])
        assert room.settings.practice == "takeout_doubles"
        assert room.settings.to_dict()["practice_title"] == "Takeout doubles"
        asyncio.run(room.handle("S", {"type": "next_board"}))
        assert room.table.dealer == "E"

    def test_unknown_practice_is_rejected(self):
        with pytest.raises(ValueError):
            self._room().update_settings(practice="nonsense")


def test_convention_page_api():
    client = TestClient(app)
    listing = client.get("/api/conventions").json()
    assert {c["id"] for c in listing if c["lesson"]} == {l.conv for l in LESSONS.values() if l.conv}
    topics = client.get("/api/lessons").json()
    assert {t["id"] for t in topics} == {"takeout_doubles", "overcalls", "major_raises"}
    page = client.get("/api/conventions/overcalls").json()
    assert page["title"] == "Overcalls" and page["examples"] and page["student"] == "overcaller"
    page = client.get("/api/conventions/stayman").json()
    assert page["explainer"] and page["examples"][0]["calls"][1]["text"]
    assert client.get("/api/conventions/openings").json()["lesson"] is False
    assert client.get("/api/conventions/nope").status_code == 404


def test_requirements_include_needed_conventions():
    assert requirements("minor_transfer") == {"minor_transfer", "jacoby"}
    assert requirements("stayman") == {"stayman"}
    assert set(BY_ID) >= {l.conv for l in LESSONS.values() if l.conv}
