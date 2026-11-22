"""The AI connector end to end: an AI app registers, the player allows it with their passkey account, and the app
reads the review of the board they just played over MCP."""
import base64
import hashlib
import secrets
from urllib.parse import parse_qs, urlsplit

from bridge import app as app_module
from bridge.coach import call_text, card, hand_text

import pytest

from test_accounts import auth, client, play_out, sign_up  # noqa: F401  (client is a fixture)

CLAUDE = "https://claude.ai/api/mcp/auth_callback"


@pytest.fixture()
def ai(client, monkeypatch):  # noqa: F811
    """The client, with the connector on the same fresh storage and tables."""
    c = app_module.connector
    monkeypatch.setattr(c, "store", app_module.store)
    monkeypatch.setattr(c, "rooms", app_module.rooms)
    monkeypatch.setattr(c, "pending", {})
    monkeypatch.setattr(c, "codes", {})
    monkeypatch.setattr(c, "calls", {})
    return client


def pkce():
    verifier = secrets.token_urlsafe(40)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


def connect(client, token, redirect=CLAUDE, app="Claude"):
    """What Claude does when the player adds the connector, with the player tapping Allow. Returns the tokens."""
    reg = client.post("/oauth/register", json={"client_name": "Claude", "redirect_uris": [redirect],
                                               "token_endpoint_auth_method": "none"})
    assert reg.status_code == 201, reg.text
    cid = reg.json()["client_id"]
    verifier, challenge = pkce()
    r = client.get("/oauth/authorize", params={"response_type": "code", "client_id": cid, "redirect_uri": redirect,
                                               "code_challenge": challenge, "code_challenge_method": "S256",
                                               "state": "xyz", "scope": "bridge"}, follow_redirects=False)
    assert r.status_code == 302, r.text
    rid = parse_qs(urlsplit(r.headers["location"]).query)["connect"][0]
    assert client.get(f"/api/connect/{rid}").json() == {"app": app}
    back = client.post("/api/connect/approve", json={"request": rid, "allow": True}, headers=auth(token)).json()
    q = parse_qs(urlsplit(back["redirect"]).query)
    assert back["redirect"].startswith(redirect + "?") and q["state"] == ["xyz"]
    tok = client.post("/oauth/token", data={"grant_type": "authorization_code", "code": q["code"][0],
                                            "redirect_uri": redirect, "client_id": cid, "code_verifier": verifier})
    assert tok.status_code == 200, tok.text
    return {**tok.json(), "client_id": cid}


def rpc(client, access, method, params=None, mid=1):
    r = client.post("/mcp", json={"jsonrpc": "2.0", "id": mid, "method": method, "params": params or {}},
                    headers=auth(access))
    assert r.status_code == 200, r.text
    return r.json()


def test_formatting():
    assert card("HT") == "♥10" and card("SA") == "♠A"
    assert call_text("1N") == "1NT" and call_text("4H") == "4♥" and call_text("P") == "Pass"
    assert hand_text("AK52.QT..J873") == "♠AK52 ♥Q10 ♦— ♣J873"


def test_discovery_and_sign_in_needed(ai):
    client = ai
    meta = client.get("/.well-known/oauth-protected-resource/mcp").json()
    assert meta["resource"].endswith("/mcp") and meta["authorization_servers"]
    server = client.get("/.well-known/oauth-authorization-server").json()
    assert server["code_challenge_methods_supported"] == ["S256"]
    r = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "initialize"})
    assert r.status_code == 401 and "resource_metadata=" in r.headers["www-authenticate"]


def test_only_known_ai_apps_may_register(ai):
    client = ai
    r = client.post("/oauth/register", json={"redirect_uris": ["https://evil.example/cb"]})
    assert r.status_code == 400 and r.json()["error"] == "invalid_redirect_uri"
    for fake in ["https://chatgpt.com/connector/oauth/", "https://chatgpt.com/connector/oauth/a/b",
                 "https://chatgpt.com/connector/oauth/abc?x=https://evil.example",
                 "https://chatgpt.com.evil.example/connector/oauth/abc", "http://chatgpt.com/connector/oauth/abc"]:
        assert client.post("/oauth/register", json={"redirect_uris": [fake]}).status_code == 400, fake


def test_chatgpt_connects_with_its_own_return_address(ai):
    """ChatGPT gives each app its own return address now; the old shared one still works too."""
    client = ai
    avery, _ = sign_up(client, "Avery")
    for redirect in ["https://chatgpt.com/connector/oauth/c_0a1B2c3D-4e_5", "https://chatgpt.com/connector_platform_oauth_redirect"]:
        tokens = connect(client, avery["token"], redirect, "ChatGPT")
        assert rpc(client, tokens["access_token"], "tools/list")["result"]["tools"]


def test_claude_reviews_the_board_you_just_played(ai):
    client = ai
    avery, _ = sign_up(client, "Avery")
    tokens = connect(client, avery["token"])
    access = tokens["access_token"]

    init = rpc(client, access, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                              "clientInfo": {"name": "claude", "version": "1"}})["result"]
    assert init["protocolVersion"] == "2025-06-18" and "Trust the facts" in init["instructions"]
    note = client.post("/mcp", json={"jsonrpc": "2.0", "method": "notifications/initialized"}, headers=auth(access))
    assert note.status_code == 202
    names = {t["name"] for t in rpc(client, access, "tools/list")["result"]["tools"]}
    assert names == {"last_board_review", "recent_boards", "board_review", "my_stats", "current_board",
                     "app_hint", "board_reviews", "coaching_overview", "mistake_patterns", "bidding_history",
                     "coaching_notes"}

    none_yet = rpc(client, access, "tools/call", {"name": "last_board_review", "arguments": {}})["result"]
    assert none_yet["isError"]

    code = client.post("/api/rooms").json()["code"]
    with client.websocket_connect(f"/ws/{code}") as ws:
        ws.send_json({"type": "join", "auth": avery["token"], "solo": True})
        assert ws.receive_json()["type"] == "joined"
        play_out(app_module.rooms.get(code), ws)
    app_module.accounts._facts.clear()  # the test's tables save through their own Accounts

    sheet = rpc(client, access, "tools/call", {"name": "last_board_review", "arguments": {}})["result"]
    assert not sheet["isError"]
    data = sheet["structuredContent"]
    assert data["you"] == "South" and set(data["hands"]) == {"North", "East", "South", "West"}
    assert data["auction"] and all("seat" in a and "call" in a for a in data["auction"])

    boards = rpc(client, access, "tools/call", {"name": "recent_boards", "arguments": {}})["result"]
    key = boards["structuredContent"]["boards"][0]["key"]
    one = rpc(client, access, "tools/call", {"name": "board_review", "arguments": {"key": key}})["result"]
    assert one["structuredContent"]["board"] == data["board"]
    stats = rpc(client, access, "tools/call", {"name": "my_stats", "arguments": {"days": 7}})["result"]
    assert not stats["isError"]

    def tool(name, **args):
        r = rpc(client, access, "tools/call", {"name": name, "arguments": args})["result"]
        assert not r["isError"], r
        return r["structuredContent"]

    many = tool("board_reviews", keys=[key, "nope"])["boards"]
    assert many[0]["board"] == data["board"] and many[1]["error"]
    page = tool("recent_boards", limit=1, since="2020-01-01")
    assert page["total"] == 1 and "next_cursor" not in page
    assert tool("recent_boards", until="2020-01-01")["total"] == 0
    ov = tool("coaching_overview", own_play_only=True)
    assert ov["boards"] == 1 and ov["working_on"] == [] and "bot_benchmarks" in ov
    assert "by_kind" in tool("mistake_patterns", days=30)
    every = tool("bidding_history", all_calls=True)
    assert every["boards"] and every["boards"][0]["calls"][0]["your_call"]

    added = tool("coaching_notes", action="add", text="Count trumps  before drawing the last one")["notes"]
    assert [n["note"] for n in added] == ["Count trumps before drawing the last one"]
    assert tool("coaching_overview")["working_on"][0]["id"] == added[0]["id"]
    assert tool("coaching_notes", action="remove", id=added[0]["id"])["notes"] == []


def test_refresh_disconnect_and_sign_out_others(ai):
    client = ai
    avery, _ = sign_up(client, "Avery")
    tokens = connect(client, avery["token"])
    fresh = client.post("/oauth/token", data={"grant_type": "refresh_token", "client_id": tokens["client_id"],
                                              "refresh_token": tokens["refresh_token"]})
    assert fresh.status_code == 200
    # the old refresh token is used up
    again = client.post("/oauth/token", data={"grant_type": "refresh_token", "client_id": tokens["client_id"],
                                              "refresh_token": tokens["refresh_token"]})
    assert again.status_code == 400

    # an AI token is not an app sign-in, and the other way round
    assert client.get("/api/me", headers=auth(fresh.json()["access_token"])).status_code == 401
    r = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "ping"}, headers=auth(avery["token"]))
    assert r.status_code == 401

    conns = client.get("/api/me/ai", headers=auth(avery["token"])).json()
    assert [c["app"] for c in conns] == ["Claude"]
    left = client.post("/api/me/ai/remove", json={"id": conns[0]["id"]}, headers=auth(avery["token"])).json()
    assert left == []
    r = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
                    headers=auth(fresh.json()["access_token"]))
    assert r.status_code == 401

    tokens = connect(client, avery["token"])
    assert rpc(client, tokens["access_token"], "ping")["result"] == {}
    new = client.post("/api/me/sign-out-others", headers=auth(avery["token"])).json()
    r = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
                    headers=auth(tokens["access_token"]))
    assert r.status_code == 401
    assert client.get("/api/me/ai", headers=auth(new["token"])).json() == []


def test_dont_allow_and_bad_pkce(ai):
    client = ai
    avery, _ = sign_up(client, "Avery")
    cid = client.post("/oauth/register", json={"redirect_uris": [CLAUDE]}).json()["client_id"]
    verifier, challenge = pkce()
    params = {"response_type": "code", "client_id": cid, "redirect_uri": CLAUDE, "code_challenge": challenge,
              "code_challenge_method": "S256", "state": "s"}
    rid = parse_qs(urlsplit(client.get("/oauth/authorize", params=params, follow_redirects=False)
                            .headers["location"]).query)["connect"][0]
    no = client.post("/api/connect/approve", json={"request": rid, "allow": False}, headers=auth(avery["token"]))
    assert "error=access_denied" in no.json()["redirect"]

    rid = parse_qs(urlsplit(client.get("/oauth/authorize", params=params, follow_redirects=False)
                            .headers["location"]).query)["connect"][0]
    yes = client.post("/api/connect/approve", json={"request": rid, "allow": True}, headers=auth(avery["token"]))
    code = parse_qs(urlsplit(yes.json()["redirect"]).query)["code"][0]
    bad = client.post("/oauth/token", data={"grant_type": "authorization_code", "code": code, "client_id": cid,
                                            "redirect_uri": CLAUDE, "code_verifier": "wrong"})
    assert bad.status_code == 400 and bad.json()["error"] == "invalid_grant"
    # a wrong return address is refused without sending the player anywhere
    r = client.get("/oauth/authorize", params={**params, "redirect_uri": "https://evil.example/cb"},
                   follow_redirects=False)
    assert r.status_code == 400 and "location" not in r.headers


def test_coaching_during_play_only_when_the_table_allows_it(ai):
    client = ai
    avery, _ = sign_up(client, "Avery")
    access = connect(client, avery["token"])["access_token"]
    call = lambda name: rpc(client, access, "tools/call", {"name": name, "arguments": {}})["result"]  # noqa: E731

    assert "not seated" in call("current_board")["structuredContent"]["error"]
    code = client.post("/api/rooms", json={"settings": {"ai_coach": False}}).json()["code"]  # on by default
    with client.websocket_connect(f"/ws/{code}") as ws:
        ws.send_json({"type": "join", "auth": avery["token"], "solo": True})
        assert ws.receive_json()["type"] == "joined"
        room = app_module.rooms.get(code)
        for _ in range(200):  # wait for South's first turn
            msg = ws.receive_json()
            if msg["type"] == "state" and msg["table"] and msg["table"]["your_turn"]:
                break
        off = call("current_board")
        assert off["isError"] and "Allow AI coaching" in off["structuredContent"]["error"]
        assert call("app_hint")["isError"]

        ws.send_json({"type": "settings", "ai_coach": True})
        while not (msg["type"] == "state" and msg["settings"]["ai_coach"]):
            msg = ws.receive_json()
        board = call("current_board")["structuredContent"]
        assert board["you"] == "South" and board["your_turn"] and board["calls_you_may_make"]
        assert list(board["hands_you_can_see"]) == ["South"]
        call("current_board")  # the same decision counts once
        hint = call("app_hint")["structuredContent"]
        assert "suggested_call" in hint
        assert room.help["S"] == {"coach": 1, "hints": 1}
        ws.send_json({"type": "settings", "ai_coach": True})  # a fresh state for play_out to start from
        play_out(room, ws)

    review = call("last_board_review")["structuredContent"]
    assert review["you_used"]["ai_coach_questions"] == 1 and review["you_used"]["hints"] == 1
    assert "no board in progress" in call("current_board")["structuredContent"]["error"].lower()


def test_admin_and_the_player_see_the_last_real_data_pull(ai, monkeypatch):
    client = ai
    monkeypatch.setattr(app_module.accounts, "_admin", None)
    monkeypatch.setattr(app_module.admin, "store", app_module.store)
    avery, _ = sign_up(client, "Avery")
    tokens = connect(client, avery["token"])
    access = tokens["access_token"]
    me = lambda: next(p for p in client.get("/api/admin/players", headers=auth(avery["token"])).json()["players"])
    assert me()["ai_apps"] == [{"app": "Claude", "used": None}] and me()["ai_used"] is None
    # connecting, listing tools, an answer that's only an error and a token refresh aren't data pulls
    rpc(client, access, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {}})
    rpc(client, access, "tools/list")
    assert rpc(client, access, "tools/call", {"name": "last_board_review", "arguments": {}})["result"]["isError"]
    client.post("/oauth/token", data={"grant_type": "refresh_token", "client_id": tokens["client_id"],
                                      "refresh_token": tokens["refresh_token"]})
    assert me()["ai_used"] is None
    assert not rpc(client, access, "tools/call", {"name": "my_stats", "arguments": {}})["result"]["isError"]
    used = me()["ai_used"]
    assert used["app"] == "Claude" and used["tool"] == "My stats" and used["at"] > 0
    assert me()["ai_apps"][0]["used"] == pytest.approx(used["at"], abs=2)
    # the player's own list of connections shows it too
    mine = client.get("/api/me/ai", headers=auth(avery["token"])).json()
    rows = mine["connections"] if isinstance(mine, dict) else mine
    assert rows[0]["used"] == pytest.approx(used["at"], abs=2)
    # still shown after the app is disconnected
    app_module.connector.forget(avery["user"]["id"])
    assert me()["ai_apps"] == [] and me()["ai_used"]["app"] == "Claude"


def test_the_coach_sees_a_bot_table_played_on_the_phone(ai):
    from bridge.game.room import Room
    client = ai
    avery, _ = sign_up(client, "Avery")
    access = connect(client, avery["token"])["access_token"]
    call = lambda name: rpc(client, access, "tools/call", {"name": name, "arguments": {}})["result"]  # noqa: E731
    room = Room("HOME")  # the table bridge/local.py plays on the phone
    _, seat = room.join("Avery", None, None, avery["user"]["id"])
    room.update_settings(solo=True)
    room.new_board()
    r = client.post("/api/me/parked", json={"snap": room.snapshot(), "token": seat}, headers=auth(avery["token"]))
    assert r.status_code == 200 and r.json() == {}
    board = call("current_board")["structuredContent"]
    assert board["you"] == "South" and list(board["hands_you_can_see"]) == ["South"]
