"""The Admin page's Load tab: samples of tables in use and players' waits, kept 30 days; the owner's limit alert."""
import time

from bridge import app as app_module
from bridge.load import KEEP_DAYS, SPEED_DAYS, Load, Timings
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


def test_a_day_reaches_back_past_midnight_utc(tmp_path):
    """Samples are kept by UTC day, so the last 24 hours read in the afternoon (US time) start the day before."""
    load = Load(SqliteStore(tmp_path / "s.db"), Timings())
    midnight = 1_800_000_000 - 1_800_000_000 % 86400
    load.sample(0, 0, now=midnight - 6 * 3600)  # yesterday (UTC), 22 hours ago
    load.sample(0, 0, now=midnight + 15 * 3600)
    assert [r["at"] for r in load.rows(1, now=midnight + 16 * 3600)] == [midnight - 6 * 3600, midnight + 15 * 3600]
    assert [r["at"] for r in load.rows(1, now=midnight + 19 * 3600)] == [midnight + 15 * 3600]  # 25 hours: too old


def test_a_sample_names_the_background_jobs_that_ran(tmp_path):
    t = Timings()
    load = Load(SqliteStore(tmp_path / "s.db"), t)
    with t.working("Backup"):
        pass
    with t.working("Second tables for saved boards"):
        assert load.sample(0, 0, now=1_800_000_000)["jobs"] == ["Backup", "Second tables for saved boards"]
        assert load.sample(0, 0, now=1_800_000_300)["jobs"] == ["Second tables for saved boards"]  # still running
    assert load.sample(0, 0, now=1_800_000_600)["jobs"] == []


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


def test_speed_checks_are_written_down_with_what_was_going_on(tmp_path):
    t = Timings()
    load = Load(SqliteStore(tmp_path / "s.db"), t)
    start = 1_800_000_000
    with t.working("Backup"):
        row = load.speed(3.5, "daily", tables=2, now=start)
    assert row["seconds"] == 3.5 and row["why"] == "daily" and row["tables"] == 2 and row["jobs"] == ["Backup"]
    assert "cpu" in row
    load.speed(3.7, "phone", tables=0, now=start + 3600)
    assert [r["seconds"] for r in load.speeds(now=start + 7200)] == [3.5, 3.7]
    assert load.rows(7, now=start + 7200) == []  # not mixed in with the samples
    later = start + (SPEED_DAYS + 1) * 86400
    load.speed(3.6, "start", tables=0, now=later)
    assert [r["seconds"] for r in load.speeds(now=later)] == [3.6]  # older than SPEED_DAYS: cleared


def test_the_daily_speed_check_waits_for_4_am_pacific():
    import datetime as dt
    utc = dt.timezone.utc
    # 2026-11-26 16:30 UTC is 8:30 AM Pacific: 19.5 hours to go
    assert app_module.SpeedCheck.until_quiet(dt.datetime(2026, 11, 26, 16, 30, tzinfo=utc)) == 19.5 * 3600
    # 11:00 UTC is 3 AM Pacific: an hour
    assert app_module.SpeedCheck.until_quiet(dt.datetime(2026, 11, 26, 11, 0, tzinfo=utc)) == 3600


def test_the_load_tab_gets_the_speed_history(client, monkeypatch):
    avery, _, _ = owner_and_friend(client)
    monkeypatch.setattr(app_module, "speed_bench", lambda: 1.25)
    monkeypatch.setattr(app_module, "speed_check", app_module.SpeedCheck())
    client.get("/api/speed")  # a phone's ask is written down too
    r = client.get("/api/admin/load", headers=auth(avery["token"])).json()
    assert [(s["seconds"], s["why"]) for s in r["speed"]][-1] == (1.25, "phone")


def test_the_suggested_table_limit_follows_processors_and_the_speed_check():
    from bridge.load import suggest_limit
    now = 1_800_000_000
    m = {"cpu": "Fast chip", "cpus": 2}
    checks = [{"at": now - 30 * 86400, "seconds": 1.0, "cpu": "Fast chip"},  # too old to count
              {"at": now - 3600, "seconds": 5.0, "cpu": "Slow chip"},  # another processor
              {"at": now - 7200, "seconds": 4.0, "cpu": "Fast chip"},  # busy
              {"at": now - 600, "seconds": 3.5, "cpu": "Fast chip"}]  # the quickest recent one counts
    s = suggest_limit(m, checks, workers=2, now=now)
    assert s == {"tables": 8, "cpus": 2, "workers": 2, "seconds": 3.5}
    assert suggest_limit(m, checks, workers=1, now=now)["tables"] == 4  # an idle processor adds nothing
    assert suggest_limit({"cpu": "Fast chip", "cpus": 1}, [dict(checks[-1], seconds=1.75)], workers=1, now=now)["tables"] == 8
    assert suggest_limit({"cpu": "x", "cpus": 0.5}, [], workers=1, now=now) == {"tables": 2, "cpus": 0.5, "workers": 1, "seconds": None}
    assert suggest_limit({"cpu": "x", "cpus": 1}, [{"at": now, "seconds": 30.0, "cpu": "x"}], workers=1, now=now)["tables"] == 1
    assert suggest_limit({"cpu": "x", "cpus": 64}, [{"at": now, "seconds": 0.5, "cpu": "x"}], workers=64, now=now, most=100)["tables"] == 100


def test_the_tables_tab_has_a_suggested_limit(client):
    avery, _, _ = owner_and_friend(client)
    s = client.get("/api/admin/tables", headers=auth(avery["token"])).json()["suggest"]
    assert s["tables"] >= 1 and set(s) == {"tables", "cpus", "workers", "seconds"}


def test_solver_workers_follow_the_processors_unless_set(monkeypatch):
    from bridge import solver
    monkeypatch.delenv("BRIDGE_SOLVER_WORKERS", raising=False)
    monkeypatch.setattr(solver, "cpus", lambda: 2.0)
    assert solver.workers() == 2
    monkeypatch.setattr(solver, "cpus", lambda: 0.5)
    assert solver.workers() == 1  # half a processor still needs one
    monkeypatch.setenv("BRIDGE_SOLVER_WORKERS", "3")
    assert solver.workers() == 3
