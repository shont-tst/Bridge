"""Protection from bots and scripts: rate limits, files outside the web folder, caps on what memory can hold."""
import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from bridge import app as server
from bridge.accounts import MAX_CHALLENGES, Accounts
from bridge.feedback import Feedback, no_mentions
from bridge.game.room import Rooms
from bridge.limits import LIMITS, MAX_MISSES, MAX_SOCKETS, Limiter, bucket_for, visitor
from bridge.store import SqliteStore


@pytest.fixture
def limited():
    """The app's own limiter, switched on for one test and cleared afterwards."""
    server.limiter.enabled, server.limiter.hits, server.limiter.sockets = True, {}, {}
    yield server.limiter
    server.limiter.enabled, server.limiter.hits, server.limiter.sockets = False, {}, {}


def test_web_files_stay_inside_the_web_folder(tmp_path):
    web = tmp_path / "dist"
    (web / "assets").mkdir(parents=True)
    (web / "index.html").write_text("page")
    (web / "assets" / "app.js").write_text("js")
    (tmp_path / "secret.txt").write_text("token")
    assert server.web_file(web, "assets/app.js") == (web / "assets" / "app.js").resolve()
    for path in ("../secret.txt", "assets/../../secret.txt", "/etc/hostname", "", "assets"):
        assert server.web_file(web, path) is None


def test_buckets():
    assert bucket_for("POST", "/api/rooms") == "new_room"
    assert bucket_for("GET", "/api/rooms/BCDF") == "room"
    assert bucket_for("GET", "/api/rooms/BCDF/history") == "room"
    assert bucket_for("GET", "/ws/BCDF") == "room"
    assert bucket_for("GET", "/ws/presence") is None
    assert bucket_for("POST", "/api/auth/login/options") == "auth"
    assert bucket_for("GET", "/api/me") == "api"
    assert bucket_for("GET", "/api/health") is None
    assert bucket_for("GET", "/assets/app.js") is None


def test_visitor_is_the_address_the_front_door_added():
    scope = {"client": ("10.0.0.5", 1234), "headers": [(b"x-forwarded-for", b"1.2.3.4, 203.0.113.9")]}
    assert visitor(scope) == "203.0.113.9"  # 1.2.3.4 was written by the visitor, so it can't be trusted
    assert visitor({"client": ("10.0.0.5", 1234), "headers": []}) == "10.0.0.5"
    for xff, who in ((b"203.0.113.9:51234", "203.0.113.9"), (b"[2001:db8::1]:51234", "2001:db8::1"),
                     (b"2001:db8::1", "2001:db8::1")):
        assert visitor({"client": ("10.0.0.5", 1234), "headers": [(b"x-forwarded-for", xff)]}) == who


def test_limit_counts_per_visitor_and_resets():
    lim = Limiter(enabled=True)
    n, window = LIMITS["auth"]
    assert all(lim.allow("auth", "a", now=1000) for _ in range(n))
    assert not lim.allow("auth", "a", now=1000)
    assert lim.allow("auth", "b", now=1000)
    assert lim.allow("auth", "a", now=1000 + window + 1)


def test_sockets_per_visitor():
    lim = Limiter(enabled=True)
    assert all(lim.open_socket("a") for _ in range(MAX_SOCKETS))
    assert not lim.open_socket("a")
    lim.close_socket("a")
    assert lim.open_socket("a")


def test_too_many_new_rooms_is_refused(limited):
    client = TestClient(server.app)
    n = LIMITS["new_room"][0]
    for _ in range(n):
        assert client.post("/api/rooms").status_code == 200
    r = client.post("/api/rooms")
    assert r.status_code == 429 and "wait" in r.json()["detail"]
    other = {"X-Forwarded-For": "198.51.100.7"}
    assert client.post("/api/rooms", headers=other).status_code == 200
    assert client.get("/api/health").status_code == 200  # Azure's checks are never limited


def test_too_many_room_sockets_are_refused(limited):
    client = TestClient(server.app)
    limited.hits[("room", "testclient")] = [9e12] * LIMITS["room"][0]  # this visitor has used up its tries
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws/BCDF") as ws:
            ws.receive_json()


def test_rooms_in_memory_are_capped(monkeypatch):
    rooms = Rooms()
    monkeypatch.setattr(Rooms, "MAX_ROOMS", 3)
    for _ in range(3):
        rooms.create()
    with pytest.raises(RuntimeError):
        rooms.create()


def test_sign_ins_in_progress_are_capped(tmp_path):
    acc = Accounts(SqliteStore(tmp_path / "a.db", durable=True))
    for i in range(MAX_CHALLENGES + 50):
        acc._challenge("login", b"x")
    assert len(acc.challenges) == MAX_CHALLENGES


def test_signed_in_suggestions_become_issues(tmp_path, monkeypatch):
    monkeypatch.setenv("BRIDGE_FEEDBACK_TOKEN", "t")
    monkeypatch.setenv("BRIDGE_FEEDBACK_REPO", "owner/feedback")
    filed = []
    monkeypatch.setattr(Feedback, "_file_issue", lambda self, token, repo, key, rec: filed.append(rec["text"]))

    class AtOnce:  # file the issue straight away instead of on a thread of its own
        def __init__(self, target, args, daemon):
            self.go = lambda: target(*args)

        def start(self):
            self.go()

    monkeypatch.setattr("bridge.feedback.threading.Thread", AtOnce)
    fb = Feedback(SqliteStore(tmp_path / "f.db"))
    fb.add("from Ann", "u1", name="Ann", user_id="u1")
    assert filed == ["from Ann"]


def test_guests_cant_send_suggestions(tmp_path):
    fb = Feedback(SqliteStore(tmp_path / "f.db"))
    with pytest.raises(ValueError):
        fb.add("from a guest", "1.2.3.4")
    assert fb.all() == []


def test_mentions_dont_notify():
    assert no_mentions("ask @octocat") == "ask @​octocat"


def test_room_codes_are_four_letters():
    assert all(len(Rooms().create().code) == 4 for _ in range(20))


def test_no_room_lookup_without_joining():
    client = TestClient(server.app)
    code = client.post("/api/rooms").json()["code"]
    assert client.get(f"/api/rooms/{code}").status_code == 404
    assert client.get(f"/api/rooms/{code}/history").status_code == 404


def test_security_headers():
    h = TestClient(server.app).get("/api/health").headers
    assert "frame-ancestors 'none'" in h["Content-Security-Policy"] and "script-src 'self'" in h["Content-Security-Policy"]
    assert h["X-Content-Type-Options"] == "nosniff" and h["X-Frame-Options"] == "DENY"
    assert h["Referrer-Policy"] == "same-origin" and "max-age" in h["Strict-Transport-Security"]


def test_a_socket_that_never_says_hello_is_let_go(monkeypatch):
    monkeypatch.setattr(server, "HELLO_WAIT", 0.2)
    client = TestClient(server.app)
    code = client.post("/api/rooms").json()["code"]
    with client.websocket_connect(f"/ws/{code}") as ws:
        with pytest.raises(WebSocketDisconnect):
            ws.receive_json()  # nothing sent: closed after HELLO_WAIT
    with client.websocket_connect("/ws/presence") as ws:
        ws.send_json(["not", "an", "object"])
        with pytest.raises(WebSocketDisconnect):
            ws.receive_json()


def test_large_requests_are_refused():
    r = TestClient(server.app).post("/api/feedback", content=b"x" * (300 * 1024),
                                    headers={"content-type": "application/json"})
    assert r.status_code == 413


def test_too_many_wrong_table_codes_blocks_joining_any_table(limited):
    limited.misses = {}
    client = TestClient(server.app)
    code = client.post("/api/rooms").json()["code"]
    for _ in range(MAX_MISSES):
        with client.websocket_connect("/ws/ZZZZ") as ws:
            assert "ended" in ws.receive_json()["message"]
    with client.websocket_connect(f"/ws/{code}") as ws:  # even the right code, for an hour after
        msg = ws.receive_json()
        assert msg["fatal"] and "wrong table codes" in msg["message"]
    assert any("codes" in r["buckets"] for r in limited.report()["refused"])
    limited.misses = {}
    with client.websocket_connect(f"/ws/{code}") as ws:
        ws.send_json({"type": "join", "name": "Ann"})
        assert ws.receive_json()["type"] == "joined"


def test_wrong_table_codes_are_forgotten_after_an_hour():
    lim = Limiter(enabled=True)
    for i in range(MAX_MISSES):
        lim.missed_code("1.2.3.4", now=1000.0 + i)
    assert lim.too_many_misses("1.2.3.4", now=1100.0) and not lim.too_many_misses("5.6.7.8", now=1100.0)
    assert not lim.too_many_misses("1.2.3.4", now=1000.0 + MAX_MISSES + 3600)
