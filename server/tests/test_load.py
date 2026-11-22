"""The Admin page's Load tab: samples of tables in use and players' waits, kept 30 days; the owner's limit alert."""
import time

from bridge import app as app_module
from bridge.load import KEEP_DAYS, Load, Timings
from bridge.store import SqliteStore
from test_accounts import auth  # noqa: F401
from test_accounts import client as _client  # noqa: F401  (the fixture test_admin's builds on)
from test_admin import client, owner_and_friend  # noqa: F401


def test_a_sample_sums_up_the_waits_since_the_last(tmp_path):
    t = Timings()
    load = Load(SqliteStore(tmp_path / "s.db"), t)
    for s in (0.1, 0.2, 0.3, 4.0):
        t.record("bot", s)
    t.record("hint", 1.5)
    t.tables(3)
    t.turned_away()
    row = load.sample(live=1, people=2, now=1_800_000_000)
    assert row["tables"] == 3 and row["now"] == 1 and row["people"] == 2 and row["away"] == 1
    assert row["bot"] == {"n": 4, "p50": 0.3, "p90": 4.0, "max": 4.0} and row["hint"]["n"] == 1
    row = load.sample(live=0, people=0, now=1_800_000_300)  # nothing since
    assert row["bot"] is None and row["tables"] == 0 and row["away"] == 0
    assert [r["at"] for r in load.rows(7, now=1_800_000_400)] == [1_800_000_000, 1_800_000_300]


def test_old_samples_are_cleared(tmp_path):
    load = Load(SqliteStore(tmp_path / "s.db"), Timings())
    start = 1_800_000_000
    load.sample(0, 0, now=start)
    later = start + (KEEP_DAYS + 1) * 86400
    load.sample(0, 0, now=later)
    assert [r["at"] for r in load.rows(30, now=later)] == [later]
    assert not load.store.query("load", time.strftime("%Y-%m-%d", time.gmtime(start)))


def test_turned_away_alerts_the_owner_once_a_day(client, monkeypatch):
    avery, _, pat = owner_and_friend(client)
    sent = []
    monkeypatch.setattr(app_module.push, "send", lambda user, title, body, url: sent.append((user["name"], body)))
    monkeypatch.setattr(app_module, "table_counts", lambda: (4, 4))
    monkeypatch.setattr(app_module.threading, "Thread",
                        lambda target, args, daemon: type("T", (), {"start": lambda self: target(*args)})())
    app_module.store.delete("config", "cfg", "limit_alert")
    before = app_module.load_timings.away
    for _ in range(3):
        assert client.post("/api/rooms", headers=auth(pat["token"]), json={}).status_code == 503
    assert sent == [("Avery", "Someone couldn't start a table: all 4 are in use.")]  # to the owner only, once
    assert app_module.load_timings.away == before + 3
    view = client.get("/api/admin/load", headers=auth(avery["token"])).json()
    assert view["limit"] == 4 and view["now"] == {"tables": 4, "people": 4} and "rows" in view
    assert client.get("/api/admin/load", headers=auth(pat["token"])).status_code == 404


def test_a_sample_has_the_review_wait_and_the_memory(tmp_path):
    from bridge.load import machine
    t = Timings()
    load = Load(SqliteStore(tmp_path / "s.db"), t)
    t.record("review", 2.5)
    row = load.sample(live=0, people=0, now=1_800_000_000)
    assert row["review"]["max"] == 2.5
    assert row["mem"] is None or row["mem"] > 0
    m = machine()
    assert set(m) == {"cpu", "cpus", "mem", "mem_limit"} and m["cpus"]
