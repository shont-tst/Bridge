"""Learn to play steps 4 and 5: the stored deals still teach their lesson, and Hint's solver route works."""
import json

import pytest
from fastapi.testclient import TestClient

from bridge import app as app_module
from scripts import tutorial_deals as td

DEALS = json.loads(td.OUT.read_text())


def hands(entry):
    return {p: entry["hands"][p].split() for p in td.SEATS}


def test_every_lesson_has_deals():
    assert set(DEALS) == set(td.LESSONS)
    for key, found in DEALS.items():
        assert len(found) >= 2, key


@pytest.mark.parametrize("key", sorted(td.LESSONS))
def test_deals_pass_their_lesson(key):
    """The same check that picked them: whole deals, the solver agrees the idea is needed (or the contract beatable)."""
    for entry in DEALS[key]:
        h = hands(entry)
        assert sorted(c for p in td.SEATS for c in h[p]) == sorted(s + r for s in "SHDC" for r in td.RANKS)
        assert td.LESSONS[key](h) == {k: entry[k] for k in ("declarer", "trump", "needed")}, (key, entry)


def test_hint_gives_tricks_for_each_legal_card():
    entry = DEALS["4.3"][0]
    h = hands(entry)
    leader = td.SEATS[(td.SEATS.index(entry["declarer"]) + 1) % 4]
    lead = h[leader].pop(0)
    client = TestClient(app_module.app)
    r = client.post("/api/tutorial/hint", json={"hands": h, "trump": entry["trump"], "leader": leader, "trick": [lead]})
    assert r.status_code == 200
    tricks = r.json()["tricks"]
    follower = td.SEATS[(td.SEATS.index(leader) + 1) % 4]
    same = [c for c in h[follower] if c[0] == lead[0]]
    assert set(tricks) == set(same or h[follower])
    assert all(0 <= n <= 13 for n in tricks.values())


@pytest.mark.parametrize("body", [
    {},
    {"hands": "x", "trump": "N", "leader": "N"},
    {"hands": {"N": ["SA"], "E": ["SA"], "S": ["SK"], "W": ["SQ"]}, "trump": "N", "leader": "N"},  # the same card twice
    {"hands": {"N": ["SA", "S2"], "E": ["SK"], "S": ["SQ"], "W": ["SJ"]}, "trump": "N", "leader": "N"},  # lengths differ
    {"hands": {"N": ["SA"], "E": ["SK"], "S": ["SQ"], "W": ["SJ"]}, "trump": "X", "leader": "N"},
    {"hands": {"N": ["SA"], "E": ["SK"], "S": ["SQ"], "W": ["SJ"]}, "trump": "N", "leader": "N", "trick": ["ZZ"]},
])
def test_hint_refuses_a_position_that_cant_happen(body):
    assert TestClient(app_module.app).post("/api/tutorial/hint", json=body).status_code == 400
