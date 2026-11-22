"""The Admin page: only the owner gets in, removing data needs Face ID again, and each tool does what it says."""
import datetime as dt
import time

import pytest

from bridge import app as app_module
from bridge.admin import CONFIRM
from bridge.backups import Backups, Folder
from bridge.game.room import Room
from bridge.limits import Limiter
from test_accounts import auth, client as _client, sign_up  # noqa: F401  (the fixture)


@pytest.fixture()
def client(_client, tmp_path, monkeypatch):
    monkeypatch.setattr(app_module.accounts, "_admin", None)
    monkeypatch.setattr(app_module.admin, "store", app_module.store)
    monkeypatch.setattr(app_module.admin, "confirmed", {})
    monkeypatch.setattr(app_module.admin, "_notice_read", False)
    monkeypatch.setattr(app_module.admin, "_table_limit", None)
    monkeypatch.setattr(app_module.feedback, "store", app_module.store)
    monkeypatch.setattr(app_module, "backups", Backups(app_module.store, Folder(tmp_path / "backups")))
    monkeypatch.setattr(app_module, "limiter", Limiter(enabled=False))
    monkeypatch.delenv("BRIDGE_ADMIN", raising=False)
    return _client


def owner_and_friend(client):
    avery, key = sign_up(client, "Avery")
    inv = client.post("/api/me/invite", headers=auth(avery["token"])).json()
    pat, _ = sign_up(client, "Pat", invite=inv["code"])
    return avery, key, pat


def confirm(client, me, key):
    o = client.post("/api/admin/confirm/options", headers=auth(me["token"])).json()
    r = client.post("/api/admin/confirm/verify", headers=auth(me["token"]),
                    json={"challenge_id": o["challenge_id"], "credential": key.get(o["options"])})
    assert r.status_code == 200, r.text


def test_only_the_first_account_is_admin(client):
    avery, _, pat = owner_and_friend(client)
    assert avery["user"].get("admin") is True and "admin" not in pat["user"]
    assert client.get("/api/admin/players", headers=auth(avery["token"])).status_code == 200
    for who in (auth(pat["token"]), {}):  # anyone else: as if there were no such page
        assert client.get("/api/admin/players", headers=who).status_code == 404
        assert client.post("/api/admin/notice", headers=who, json={"text": "hi"}).status_code == 404
        assert client.get("/api/admin/notice", headers=who).status_code == 404


def test_bridge_admin_names_the_owner_by_friend_code(client, monkeypatch):
    avery, _, pat = owner_and_friend(client)
    monkeypatch.setenv("BRIDGE_ADMIN", pat["user"]["friend_code"])
    assert client.get("/api/admin/players", headers=auth(pat["token"])).status_code == 200
    assert client.get("/api/admin/players", headers=auth(avery["token"])).status_code == 404


def test_removing_a_player_needs_face_id_and_takes_everything(client):
    avery, key, pat = owner_and_friend(client)
    pid = pat["user"]["id"]
    r = client.post("/api/admin/players/remove", headers=auth(avery["token"]), json={"id": pid})
    assert r.status_code == 403 and r.json()["detail"] == CONFIRM
    confirm(client, avery, key)
    assert client.post("/api/admin/players/remove", headers=auth(avery["token"]), json={"id": pid}).status_code == 200
    s = app_module.store
    assert s.get("users", "u", pid) is None and s.query("usercreds", pid) == []
    assert app_module.accounts.links(avery["user"]["id"]) == {}
    assert client.get("/api/me", headers=auth(pat["token"])).status_code == 401
    # never the owner's own account
    r = client.post("/api/admin/players/remove", headers=auth(avery["token"]), json={"id": avery["user"]["id"]})
    assert r.status_code == 400
    assert "Removed a player" in [row["action"] for row in client.get("/api/admin/log", headers=auth(avery["token"])).json()["rows"]]


def test_friends_chart_lists_each_pair_once(client):
    avery, _, pat = owner_and_friend(client)
    inv = client.post("/api/me/invite", headers=auth(pat["token"])).json()
    sam, _ = sign_up(client, "Sam", invite=inv["code"])
    for who in (auth(pat["token"]), {}):
        assert client.get("/api/admin/friends", headers=who).status_code == 404
    r = client.get("/api/admin/friends", headers=auth(avery["token"])).json()
    names = {p["id"]: p["name"] for p in r["players"]}
    assert sorted(names.values()) == ["Avery", "Pat", "Sam"]
    pairs = sorted(tuple(sorted((names[l["a"]], names[l["b"]]))) for l in r["links"])
    assert pairs == [("Avery", "Pat"), ("Pat", "Sam")]  # Sam and Avery aren't friends: invites link two people only
    assert r["waiting"] == []


def test_steps_from_the_owner_follow_invites_and_friendships(client):
    avery, key, pat = owner_and_friend(client)
    inv = client.post("/api/me/invite", headers=auth(pat["token"])).json()["code"]
    sam, _ = sign_up(client, "Sam", invite=inv)  # Pat invited Sam
    inv = client.post("/api/me/invite", headers=auth(sam["token"])).json()["code"]
    lee, _ = sign_up(client, "Lee", invite=inv)  # Sam invited Lee
    # Lee later opens Avery's own link: friends directly, but Sam still brought Lee in
    link = client.post("/api/me/invite", headers=auth(avery["token"])).json()["code"]
    client.post("/api/friends/invite", headers=auth(lee["token"]), json={"code": link})
    accts = app_module.accounts
    # an account from before invites were kept: found from the friendship made as it was
    old = accts.user(sam["user"]["id"])
    old.pop("invited_by")
    accts.save_user(old)
    loner = accts._new_user("Robin")  # joined some other way (the family code)
    r = client.get("/api/admin/friends", headers=auth(avery["token"])).json()
    got = {p["name"]: (p["steps"], p["friend_steps"]) for p in r["players"]}
    assert got == {"Avery": (0, 0), "Pat": (1, 1), "Sam": (2, 2), "Lee": (3, 1), "Robin": (None, None)}
    by = {p["name"]: p["invited_by"] for p in r["players"]}
    assert by["Lee"] == sam["user"]["id"] and by["Sam"] == pat["user"]["id"] and by["Avery"] is None
    assert by["Robin"] is None and loner
    chain = {p["name"]: p["chain"] for p in r["players"]}
    assert chain["Lee"] == [avery["user"]["id"], pat["user"]["id"], sam["user"]["id"], lee["user"]["id"]]
    assert chain["Robin"] is None
    listing = client.get("/api/admin/players", headers=auth(avery["token"])).json()["players"]
    assert {p["name"]: (p["steps"], p["friend_steps"]) for p in listing} == got


def test_clear_old_accounts_after_a_year(client):
    avery, key, pat = owner_and_friend(client)
    accts = app_module.accounts
    u = accts.user(pat["user"]["id"])
    u["last_seen"] = time.time() - 400 * 24 * 3600
    accts.save_user(u)
    me = accts.user(avery["user"]["id"])  # the owner is never old, however long away
    me["last_seen"] = 0
    accts.save_user(me)
    listing = client.get("/api/admin/players", headers=auth(avery["token"])).json()
    assert listing["old"] == [pat["user"]["id"]] and listing["old_after_days"] == 365
    confirm(client, avery, key)
    assert client.post("/api/admin/players/clear-old", headers=auth(avery["token"])).json() == {"removed": 1}
    assert [p["name"] for p in client.get("/api/admin/players", headers=auth(avery["token"])).json()["players"]] == ["Avery"]


def test_backups_run_download_and_restore(client):
    avery, key, pat = owner_and_friend(client)
    h = auth(avery["token"])
    name = client.post("/api/admin/backups/run", headers=h).json()["name"]
    assert [f["name"] for f in client.get("/api/admin/backups", headers=h).json()["files"]] == [name]
    assert client.get(f"/api/admin/backups/file?name={name}", headers=h).status_code == 403
    assert client.post("/api/admin/backups/restore", headers=h, json={"name": name}).status_code == 403
    confirm(client, avery, key)
    r = client.get(f"/api/admin/backups/file?name={name}", headers=h)
    assert r.status_code == 200 and r.content[:2] == b"\x1f\x8b"
    assert client.get("/api/admin/backups/file?name=../t.db", headers=h).status_code == 404
    app_module.accounts.remove_user(pat["user"]["id"])
    r = client.post("/api/admin/backups/restore", headers=h, json={"name": name})
    assert r.status_code == 200 and r.json()["records"] > 0
    assert app_module.store.get("users", "u", pat["user"]["id"])["name"] == "Pat"
    files = client.get("/api/admin/backups", headers=h).json()["files"]
    assert [f["before"] for f in files] == [False, True]  # the copy made just before


def test_restore_keeps_three_copies_from_before(tmp_path):
    from bridge.store import SqliteStore
    b = Backups(SqliteStore(tmp_path / "s.db"), Folder(tmp_path / "b"))
    name = b.make(dt.date(2026, 10, 28))
    for minute in range(5):
        b.restore(name, now=dt.datetime(2026, 10, 28, 12, minute))
    assert sum(f["before"] for f in b.files()) == 3


def test_feedback_review(client):
    avery, _, _ = owner_and_friend(client)
    h = auth(avery["token"])
    app_module.feedback.add("More lessons please", "x", name="Pat", user_id="p")
    items = client.get("/api/admin/feedback", headers=h).json()["items"]
    assert items[0]["text"] == "More lessons please"
    r = client.post("/api/admin/feedback/mark", headers=h, json={"key": items[0]["key"], "status": "build"})
    assert r.json()["status"] == "build"
    assert client.post("/api/admin/feedback/mark", headers=h, json={"key": items[0]["key"], "status": "x"}).status_code == 400
    client.post("/api/admin/feedback/delete", headers=h, json={"key": items[0]["key"]})
    assert client.get("/api/admin/feedback", headers=h).json()["items"] == []


def test_tables_and_invites(client):
    avery, _, _ = owner_and_friend(client)
    h = auth(avery["token"])
    room = app_module.rooms._adopt(Room("ABCDEF"))
    room.join("Lee")
    client.post("/api/me/invite", headers=h)
    view = client.get("/api/admin/tables", headers=h).json()
    assert view["tables"][0]["code"] == "ABCDEF" and view["tables"][0]["seats"]["S"]["name"] == "Lee"
    assert len(view["invites"]) == 1
    client.post("/api/admin/invites/cancel", headers=h, json={"code": view["invites"][0]["code"]})
    client.post("/api/admin/tables/close", headers=h, json={"code": "ABCDEF"})
    view = client.get("/api/admin/tables", headers=h).json()
    assert view["tables"] == [] and view["invites"] == []


def test_table_limit(client, monkeypatch):
    avery, _, pat = owner_and_friend(client)
    h = auth(avery["token"])
    monkeypatch.setattr(app_module.rooms, "rooms", {})
    assert client.get("/api/admin/tables", headers=h).json()["limit"] == 4  # the default
    assert client.post("/api/admin/tables/limit", headers=auth(pat["token"]), json={"tables": 9}).status_code == 404
    assert client.post("/api/admin/tables/limit", headers=h, json={"tables": 0}).status_code == 400
    assert client.post("/api/admin/tables/limit", headers=h, json={"tables": 2}).json() == {"limit": 2}
    assert app_module.store.get("config", "cfg", "table_limit")["tables"] == 2
    for code in ("AAAAAA", "BBBBBB"):  # two tables with someone at them
        room = app_module.rooms._adopt(Room(code))
        room.join("Lee")
        room.players["S"].connections.add(lambda msg: None)
    app_module.rooms._adopt(Room("CCCCCC")).join("Gone")  # nobody has this one open: it doesn't count
    r = client.post("/api/rooms", json={})
    assert r.status_code == 503 and "All 2 tables are in use" in r.json()["detail"]
    assert client.post("/api/rooms", headers=auth(pat["token"]), json={}).status_code == 503
    assert client.post("/api/rooms", headers=h, json={}).status_code == 200  # the owner can always start one
    client.post("/api/admin/tables/limit", headers=h, json={"tables": 3})
    assert client.post("/api/rooms", json={}).status_code == 200


def test_block_an_address(client):
    avery, _, _ = owner_and_friend(client)
    h = auth(avery["token"])
    assert client.post("/api/admin/safety/block", headers=h, json={"address": "testclient"}).status_code == 400
    assert client.post("/api/admin/safety/block", headers=h, json={"address": "203.0.113.9"}).status_code == 200
    assert "203.0.113.9" in app_module.limiter.blocked
    assert app_module.store.get("config", "cfg", "blocked")["addresses"]["203.0.113.9"]
    assert client.get("/api/admin/safety", headers=h).json()["blocked"][0]["address"] == "203.0.113.9"
    client.post("/api/admin/safety/unblock", headers=h, json={"address": "203.0.113.9"})
    assert app_module.limiter.blocked == {}


def test_a_blocked_address_gets_nothing():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from bridge.limits import RateLimit
    inner = FastAPI()
    inner.get("/api/x")(lambda: {"ok": True})
    lim = Limiter(enabled=False)
    inner.add_middleware(RateLimit, limiter=lim)
    c = TestClient(inner)
    assert c.get("/api/x").status_code == 200
    lim.blocked["testclient"] = {"at": 0, "note": ""}
    assert c.get("/api/x").status_code == 403


def test_refusals_are_reported():
    lim = Limiter(enabled=True)
    for _ in range(25):
        lim.allow("auth", "198.51.100.7")
    rep = lim.report()
    assert rep["refused"][0] == {**rep["refused"][0], "address": "198.51.100.7", "count": 5, "buckets": ["auth"]}
    assert rep["busy"][0] == {"address": "198.51.100.7", "count": 20}


def test_notice_shows_for_everyone(client):
    avery, _, _ = owner_and_friend(client)
    h = auth(avery["token"])
    assert client.get("/api/admin/notice", headers=h).json() == {"notice": None}  # the tab opens with nothing posted
    r = client.post("/api/admin/notice", headers=h, json={"text": "  Updating at 9pm  "})
    assert r.json()["notice"]["text"] == "Updating at 9pm"
    assert client.get("/api/admin/notice", headers=h).json()["notice"]["text"] == "Updating at 9pm"
    assert client.get("/api/config").json()["notice"]["text"] == "Updating at 9pm"
    client.post("/api/admin/notice", headers=h, json={"text": ""})
    assert client.get("/api/config").json()["notice"] is None
