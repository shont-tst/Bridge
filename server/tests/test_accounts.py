"""Accounts end to end through the API: a software passkey signs up and in, friends, invites, saved boards,
and a table that carries on after the server restarts."""
import base64
import hashlib
import json
import os
import struct
import time

os.environ["BRIDGE_BOT_DELAY"] = "0"

import cbor2  # noqa: E402
import pytest  # noqa: E402
from cryptography.hazmat.primitives import hashes  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import ec  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from bridge import app as app_module  # noqa: E402
from bridge.accounts import Accounts  # noqa: E402
from bridge.game.room import Player, Room, Rooms  # noqa: E402
from bridge.game.table import DONE  # noqa: E402
from bridge.core.rubber import Line  # noqa: E402
from bridge.store import SqliteStore  # noqa: E402

ORIGIN = "https://testserver"  


def b64u(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def unb64u(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


class SoftPasskey:
    """What Face ID does, in software: makes a key for the site and signs sign-in challenges with it."""

    def __init__(self):
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.cred_id = os.urandom(16)
        self.count = 0
        self.user_handle = b""

    def _auth_data(self, rp_id: str, flags: int, attested: bytes = b"") -> bytes:
        self.count += 1
        return hashlib.sha256(rp_id.encode()).digest() + bytes([flags]) + struct.pack(">I", self.count) + attested

    def create(self, options: dict) -> dict:
        self.user_handle = unb64u(options["user"]["id"])
        nums = self.key.public_key().public_numbers()
        cose = cbor2.dumps({1: 2, 3: -7, -1: 1, -2: nums.x.to_bytes(32, "big"), -3: nums.y.to_bytes(32, "big")})
        attested = b"\0" * 16 + struct.pack(">H", len(self.cred_id)) + self.cred_id + cose
        auth = self._auth_data(options["rp"]["id"], 0x45, attested)  # user present + verified + key included
        client = json.dumps({"type": "webauthn.create", "challenge": options["challenge"], "origin": ORIGIN}).encode()
        att = cbor2.dumps({"fmt": "none", "attStmt": {}, "authData": auth})
        return {"id": b64u(self.cred_id), "rawId": b64u(self.cred_id), "type": "public-key",
                "response": {"clientDataJSON": b64u(client), "attestationObject": b64u(att)}}

    def get(self, options: dict) -> dict:
        auth = self._auth_data(options["rpId"], 0x05)
        client = json.dumps({"type": "webauthn.get", "challenge": options["challenge"], "origin": ORIGIN}).encode()
        sig = self.key.sign(auth + hashlib.sha256(client).digest(), ec.ECDSA(hashes.SHA256()))
        return {"id": b64u(self.cred_id), "rawId": b64u(self.cred_id), "type": "public-key",
                "response": {"clientDataJSON": b64u(client), "authenticatorData": b64u(auth),
                             "signature": b64u(sig), "userHandle": b64u(self.user_handle)}}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """A fresh, empty store for each test."""
    store = SqliteStore(tmp_path / "t.db", durable=True)
    accounts = Accounts(store)
    monkeypatch.setattr(app_module, "store", store)
    monkeypatch.setattr(app_module.accounts, "store", store)
    monkeypatch.setattr(app_module.accounts, "_secret", None)
    monkeypatch.setattr(app_module.accounts, "challenges", {})
    monkeypatch.setattr(app_module.accounts, "_has_users", False)
    monkeypatch.setattr(app_module.accounts, "_facts", {})
    monkeypatch.setattr(app_module.push, "_keys", None)
    monkeypatch.setattr(app_module, "rooms", Rooms(store, accounts.save_board, accounts.drop_board,
                                                       accounts.save_table_settings))
    monkeypatch.delenv("BRIDGE_INVITE_CODE", raising=False)
    return TestClient(app_module.app)


def sign_up(client, name, invite=None, key=None):
    key = key or SoftPasskey()
    opts = client.post("/api/auth/register/options", json={"name": name, "invite": invite})
    assert opts.status_code == 200, opts.text
    o = opts.json()
    done = client.post("/api/auth/register/verify",
                       json={"challenge_id": o["challenge_id"], "credential": key.create(o["options"])})
    assert done.status_code == 200, done.text
    return done.json(), key


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def test_first_account_needs_no_invite_but_the_second_does(client):
    assert client.get("/api/auth/signup").json()["first"] is True
    me, _ = sign_up(client, "Avery")
    assert me["user"]["name"] == "Avery" and me["token"]
    r = client.post("/api/auth/register/options", json={"name": "Stranger"})
    assert r.status_code == 400 and "invite" in r.json()["detail"]


def test_sign_in_again_with_the_same_passkey(client):
    me, key = sign_up(client, "Avery")
    o = client.post("/api/auth/login/options").json()
    r = client.post("/api/auth/login/verify", json={"challenge_id": o["challenge_id"],
                                                    "credential": key.get(o["options"])})
    assert r.status_code == 200, r.text
    assert r.json()["user"]["id"] == me["user"]["id"]
    assert client.get("/api/me", headers=auth(r.json()["token"])).json()["user"]["name"] == "Avery"
    assert client.get("/api/me", headers=auth("forged.1.abc")).status_code == 401


def test_a_challenge_works_once(client):
    _, key = sign_up(client, "Avery")
    o = client.post("/api/auth/login/options").json()
    cred = key.get(o["options"])
    assert client.post("/api/auth/login/verify", json={"challenge_id": o["challenge_id"],
                                                       "credential": cred}).status_code == 200
    assert client.post("/api/auth/login/verify", json={"challenge_id": o["challenge_id"],
                                                       "credential": cred}).status_code == 400


def test_invite_link_makes_an_account_and_friends(client):
    avery, _ = sign_up(client, "Avery")
    inv = client.post("/api/me/invite", headers=auth(avery["token"])).json()
    assert inv["url"].endswith(f"?invite={inv['code']}")
    status = client.get(f"/api/auth/signup?invite={inv['code']}").json()
    assert status["invite_ok"] and status["invited_by"] == "Avery"
    pat, _ = sign_up(client, "Pat", invite=inv["code"])
    links = app_module.accounts.links(avery["user"]["id"])
    assert links == {pat["user"]["id"]: "friends"}
    # used up
    assert client.post("/api/auth/register/options", json={"name": "Lee", "invite": inv["code"]}).status_code == 400


def test_family_code_lets_anyone_with_it_sign_up(client, monkeypatch):
    sign_up(client, "Avery")
    monkeypatch.setenv("BRIDGE_INVITE_CODE", "GOLD-SPADE")
    sign_up(client, "Robin", invite="gold spade")


def test_device_link_adds_a_second_passkey_to_the_same_account(client):
    avery, _ = sign_up(client, "Avery")
    code = client.post("/api/me/device-link", headers=auth(avery["token"])).json()["code"]
    assert client.get(f"/api/auth/signup?invite={code}").json()["device_link"]
    android, _ = sign_up(client, "", invite=code)
    assert android["user"]["id"] == avery["user"]["id"]


def test_friend_requests_by_code_and_by_name(client):
    avery, _ = sign_up(client, "Avery")
    inv = client.post("/api/me/invite", headers=auth(avery["token"])).json()["code"]
    pat, _ = sign_up(client, "Pat", invite=inv)
    inv2 = client.post("/api/me/invite", headers=auth(pat["token"])).json()["code"]
    lee, _ = sign_up(client, "Lee", invite=inv2)  # friends with Pat, not Avery
    r = client.post("/api/friends/request", headers=auth(avery["token"]), json={"who": "lee"})
    assert r.status_code == 200 and r.json()["name"] == "Lee"
    assert app_module.accounts.links(lee["user"]["id"])[avery["user"]["id"]] == "in"
    r = client.post("/api/friends/answer", headers=auth(lee["token"]),
                    json={"id": avery["user"]["id"], "accept": True})
    assert r.status_code == 200
    assert app_module.accounts.links(avery["user"]["id"])[lee["user"]["id"]] == "friends"
    r = client.post("/api/friends/request", headers=auth(pat["token"]),
                    json={"who": avery["user"]["friend_code"]})
    assert r.status_code == 400 and "already" in r.json()["detail"]


def test_a_player_who_already_plays_opens_an_invite_link(client):
    avery, _ = sign_up(client, "Avery")
    inv = client.post("/api/me/invite", headers=auth(avery["token"])).json()["code"]
    pat, _ = sign_up(client, "Pat", invite=inv)
    inv2 = client.post("/api/me/invite", headers=auth(pat["token"])).json()["code"]
    lee, _ = sign_up(client, "Lee", invite=inv2)  # friends with Pat, not Avery
    link = client.post("/api/me/invite", headers=auth(avery["token"])).json()["code"]
    r = client.post("/api/friends/invite", headers=auth(avery["token"]), json={"code": link})
    assert r.status_code == 400 and "your own" in r.json()["detail"]
    r = client.post("/api/friends/invite", headers=auth(lee["token"]), json={"code": link.lower()})
    assert r.status_code == 200 and r.json()["name"] == "Avery"
    assert app_module.accounts.links(avery["user"]["id"])[lee["user"]["id"]] == "friends"
    assert [f["name"] for f in app_module.social.friends_view(avery["user"]["id"])["friends"]] == ["Lee", "Pat"]
    r = client.post("/api/friends/invite", headers=auth(pat["token"]), json={"code": link})
    assert r.status_code == 400 and "used" in r.json()["detail"]  # one use
    # already friends: nothing changes and the link stays good for someone else
    again = client.post("/api/me/invite", headers=auth(avery["token"])).json()["code"]
    assert client.post("/api/friends/invite", headers=auth(pat["token"]), json={"code": again}).status_code == 200
    assert app_module.accounts._invite(again)


def test_invite_again_before_sending_gives_the_same_link(client):
    avery, _ = sign_up(client, "Avery")
    a = client.post("/api/me/invite", headers=auth(avery["token"])).json()["code"]
    b = client.post("/api/me/invite", headers=auth(avery["token"])).json()["code"]
    assert a == b  # tapped Invite twice without sharing: still one link
    assert client.post("/api/me/invite/sent", headers=auth(avery["token"]), json={"code": a}).status_code == 200
    c = client.post("/api/me/invite", headers=auth(avery["token"])).json()["code"]
    assert c != a  # the first one went out, so a fresh one
    rows = {i["code"]: i for i in app_module.Admin(app_module.store, app_module.accounts).invites()}
    assert rows[a]["sent"] and not rows[c]["sent"] and rows[c]["made"]
    # someone else can't mark your link as sent
    pat, _ = sign_up(client, "Pat", invite=a)
    client.post("/api/me/invite/sent", headers=auth(pat["token"]), json={"code": c})
    assert not app_module.accounts._invite(c)[1].get("sent")


def test_presence_and_instant_invite(client):
    avery, _ = sign_up(client, "Avery")
    inv = client.post("/api/me/invite", headers=auth(avery["token"])).json()["code"]
    pat, _ = sign_up(client, "Pat", invite=inv)
    with client.websocket_connect("/ws/presence") as ps:
        ps.send_json({"token": pat["token"]})
        first = ps.receive_json()
        assert first["friends"][0]["name"] == "Avery" and first["friends"][0]["status"] == "away"
        with client.websocket_connect("/ws/presence") as ss:
            ss.send_json({"token": avery["token"]})
            assert ss.receive_json()["friends"][0]["status"] == "ready"
            assert ps.receive_json()["friends"][0]["status"] == "ready"  # Pat sees Avery arrive
            code = client.post("/api/rooms").json()["code"]
            r = client.post("/api/play/invite", headers=auth(avery["token"]),
                            json={"friend": pat["user"]["id"], "room": code})
            assert r.json() == {"shown": True, "notified": False}
            msg = ps.receive_json()
            assert msg["type"] == "invite" and msg["from"] == "Avery" and msg["room"] == code
            # Avery sits down: Pat sees them at a table
            with client.websocket_connect(f"/ws/{code}") as table:
                table.send_json({"type": "join", "auth": avery["token"]})
                assert table.receive_json()["seat"] == "S"
                seen = ps.receive_json()
                assert seen["friends"][0]["status"] == "table" and seen["friends"][0]["room"] == code


def test_invite_to_a_friend_who_is_away_sends_a_notification(client, monkeypatch):
    avery, _ = sign_up(client, "Avery")
    inv = client.post("/api/me/invite", headers=auth(avery["token"])).json()["code"]
    pat, _ = sign_up(client, "Pat", invite=inv)
    code = client.post("/api/rooms").json()["code"]
    sent = []
    monkeypatch.setattr(app_module.push, "send", lambda user, title, body, url: sent.append((title, url)) or 1)
    r = client.post("/api/play/invite", headers=auth(avery["token"]), json={"friend": pat["user"]["id"], "room": code})
    assert r.json() == {"shown": False, "notified": True}
    assert sent[0][0] == "Avery wants to play" and sent[0][1].endswith(f"/?room={code}")
    # no notifications turned on: nothing reaches them, so the app offers a link instead
    monkeypatch.setattr(app_module.push, "send", lambda *a: 0)
    r = client.post("/api/play/invite", headers=auth(avery["token"]), json={"friend": pat["user"]["id"], "room": code})
    assert r.json() == {"shown": False, "notified": False}


def test_invite_to_a_stranger_is_refused(client):
    avery, _ = sign_up(client, "Avery")
    code = client.post("/api/rooms").json()["code"]
    r = client.post("/api/play/invite", headers=auth(avery["token"]), json={"friend": "nobody", "room": code})
    assert r.status_code == 400


def test_notifications_off_forgets_the_phone(client):
    avery, _ = sign_up(client, "Avery")
    sub = {"endpoint": "https://fcm.googleapis.com/fcm/send/abc", "keys": {"p256dh": "x", "auth": "y"}}
    me = client.post("/api/me/push", headers=auth(avery["token"]), json={"subscription": sub}).json()
    assert me["notify"] and me["push"]
    me = client.post("/api/me/notify", headers=auth(avery["token"]), json={"on": False}).json()
    assert me["notify"] is False and me["push"] is False
    assert app_module.push.send(app_module.accounts.user(avery["user"]["id"]), "t", "b", "u") == 0


def test_push_key_is_made_once_and_kept(client):
    k1 = client.get("/api/config").json()["push_key"]
    app_module.push._keys = None
    assert client.get("/api/config").json()["push_key"] == k1
    assert len(unb64u(k1)) == 65  # an uncompressed P-256 point, as browsers want it


def test_finished_board_is_saved_to_the_players_account(client):
    avery, _ = sign_up(client, "Avery")
    code = client.post("/api/rooms").json()["code"]
    with client.websocket_connect(f"/ws/{code}") as ws:
        ws.send_json({"type": "join", "auth": avery["token"], "solo": True})
        assert ws.receive_json()["type"] == "joined"
        room = app_module.rooms.get(code)
        play_out(room, ws)
    uid = avery["user"]["id"]
    boards = app_module.accounts.boards(uid)
    assert len(boards) == 1 and boards[0]["seat"] == "S" and boards[0]["room"] == code


def play_out(room, ws):
    """Drive the board to the end from the socket, making South's (and dummy's) moves as they come up."""
    for _ in range(600):
        msg = ws.receive_json()
        if msg["type"] != "state" or not msg["table"]:
            continue
        t = msg["table"]
        if t["phase"] == DONE:
            # wait for the saving pass
            import time
            for _ in range(40):
                if not room.finished:
                    break
                time.sleep(0.05)
            time.sleep(0.6)
            return
        if t["your_turn"]:
            if t["phase"] == "bidding":
                ws.send_json({"type": "call", "call": "P"})
            else:
                ws.send_json({"type": "play", "card": t["legal_cards"][0]})
    raise AssertionError("board never finished")


def test_a_table_carries_on_after_a_restart(tmp_path):
    store = SqliteStore(tmp_path / "r.db")
    room = Room("KTRZ", seed=3)
    room.players["S"] = Player("Avery", "tok", user="u1")
    room.update_settings(solo=True)
    room.new_board()
    t = room.table
    while t.phase == "bidding":
        if t.is_bot_turn():
            t.bot_step()
        else:
            t.make_call(t.seat_to_act(), "P")
    for _ in range(9):  # a couple of tricks in
        if t.phase != "playing":
            break
        if t.is_bot_turn():
            t.bot_step()
        else:
            seat = t.seat_to_act()
            t.play_card(t.controller_of(seat), t.play.legal_cards(seat)[0])
    room.rev = 7
    store.put("rooms", "r", "KTRZ", room.snapshot())

    after = Rooms(store).get("ktrz")  # a new copy of the server
    assert after is not room and after.rev == 7
    assert after.table.actions == t.actions
    assert after.table.state_for("S") == t.state_for("S")
    assert after.players["S"].user == "u1" and after.settings.solo
    assert after.rng.random() == room.rng.random()  # the next deal comes out the same


def test_undo_takes_a_saved_board_back_out(tmp_path):
    store = SqliteStore(tmp_path / "u.db", durable=True)
    accounts = Accounts(store)
    room = Room("UNDO", seed=5)
    room.players["S"] = Player("Avery", "tok", user="u1")
    room.update_settings(solo=True)
    room.new_board()
    t = room.table
    while t.phase != DONE:
        if t.is_bot_turn():
            t.bot_step()
        elif t.phase == "bidding":
            t.make_call(t.seat_to_act(), "P")
        else:
            seat = t.seat_to_act()
            t.play_card(t.controller_of(seat), t.play.legal_cards(seat)[0])
    room.record_result()
    user, rec = room.finished.pop()
    accounts.save_board(user, rec)
    assert len(accounts.boards("u1")) == 1
    room.undo()
    user, rec = room.retracted.pop()
    accounts.drop_board(user, rec)
    assert accounts.boards("u1") == []


def test_sign_out_other_phones(client):
    avery, key = sign_up(client, "Avery")
    old = avery["token"]
    assert client.get("/api/me", headers=auth(old)).status_code == 200
    r = client.post("/api/me/sign-out-others", headers=auth(old))
    assert r.status_code == 200
    new = r.json()["token"]
    assert client.get("/api/me", headers=auth(new)).status_code == 200  # this phone stays in
    assert client.get("/api/me", headers=auth(old)).status_code == 401  # every other one is out
    # signing in again with the passkey works, and gives a token of the new generation
    o = client.post("/api/auth/login/options").json()
    again = client.post("/api/auth/login/verify", json={"challenge_id": o["challenge_id"],
                                                         "credential": key.get(o["options"])}).json()
    assert client.get("/api/me", headers=auth(again["token"])).status_code == 200


def test_tokens_from_before_generations_still_work(client):
    avery, _ = sign_up(client, "Avery")
    uid = avery["user"]["id"]
    assert avery["token"].count(".") == 2  # an account that never signed out others: same token shape as before
    assert app_module.accounts.user_for(app_module.accounts.make_token(uid))["id"] == uid
    assert app_module.accounts.user_for(app_module.accounts.make_token(uid, gen=1)) is None


@pytest.mark.parametrize("endpoint, ok", [
    ("https://fcm.googleapis.com/fcm/send/abc", True),
    ("https://web.push.apple.com/QAbc", True),
    ("https://updates.push.services.mozilla.com/wpush/v2/abc", True),
    ("https://wns2-par02p.notify.windows.com/w/?token=abc", True),
    ("https://push.example/abc", False),
    ("https://evil.com/fcm.googleapis.com", False),
    ("https://fcm.googleapis.com.evil.com/x", False),
    ("http://fcm.googleapis.com/fcm/send/abc", False),
    ("https://fcm.googleapis.com:8443/x", False),
    ("https://10.0.0.4/x", False),
])
def test_notifications_only_go_to_the_push_services(client, endpoint, ok):
    avery, _ = sign_up(client, "Avery")
    sub = {"endpoint": endpoint, "keys": {"p256dh": "x", "auth": "y"}}
    r = client.post("/api/me/push", headers=auth(avery["token"]), json={"subscription": sub})
    assert (r.status_code == 200) is ok


def test_new_tables_start_with_the_settings_last_chosen(client):
    def settings(code):
        return app_module.rooms.get(code).settings

    # a guest: the defaults at first, then whatever this phone last chose
    first = settings(client.post("/api/rooms").json()["code"])
    assert (first.scoring, first.hints, first.undo, first.ai_coach) == ("rubber", True, True, True)
    assert settings(client.post("/api/rooms", json={"scoring": "duplicate"}).json()["code"]).scoring == "duplicate"
    assert settings(client.post("/api/rooms", json={"scoring": "nonsense"}).json()["code"]).scoring == "rubber"
    phone = settings(client.post("/api/rooms", json={"settings": {
        "hints": False, "difficulty": 9, "trick_pause": 3.0, "conventions": ["stayman", "made_up"],
        "practice": "stayman"}}).json()["code"])
    assert (phone.hints, phone.difficulty, phone.trick_pause) == (False, 9, 3.0)
    assert phone.conventions == {"stayman"} and phone.practice is None  # practice is never carried over

    # signed in: the account remembers the choices made at a table, whatever the phone says
    avery, _ = sign_up(client, "Avery")
    code = client.post("/api/rooms", headers=auth(avery["token"]), json={"scoring": "rubber"}).json()["code"]
    with client.websocket_connect(f"/ws/{code}") as ws:
        ws.send_json({"type": "join", "auth": avery["token"], "solo": True})
        assert ws.receive_json()["type"] == "joined"
        ws.send_json({"type": "settings", "scoring": "duplicate"})
        ws.send_json({"type": "settings", "ai_coach": False, "undo": False})
        for _ in range(50):
            msg = ws.receive_json()
            if msg["type"] == "state" and not msg["settings"]["ai_coach"]:
                break
        uid = avery["user"]["id"]
        for _ in range(100):  # saved off the event loop, within a second
            if app_module.accounts.user(uid).get("table", {}).get("ai_coach") is False:
                break
            time.sleep(0.05)
    assert app_module.accounts.user(uid)["table"] == {"scoring": "duplicate", "ai_coach": False, "undo": False}
    code = client.post("/api/rooms", headers=auth(avery["token"]), json={"scoring": "rubber"}).json()["code"]
    s = settings(code)
    assert (s.scoring, s.ai_coach, s.undo, s.hints) == ("duplicate", False, False, True)


def test_home_menu_shows_and_saves_the_settings_new_tables_start_with(client):
    # a guest: the defaults, with this phone's choices on top (invalid ones dropped)
    d = client.post("/api/table-defaults", json={"settings": {"difficulty": 3, "scoring": "nonsense"}}).json()
    assert (d["difficulty"], d["scoring"], d["leads"], d["practice"]) == (3, "rubber", True, None)
    assert client.post("/api/me/table-settings", json={"settings": {"hints": False}}).status_code == 401

    # signed in: saved with the account, so the next new table starts with them
    avery, _ = sign_up(client, "Avery")
    h = auth(avery["token"])
    now = client.post("/api/me/table-settings", headers=h,
                      json={"settings": {"hints": False, "signals": "upside", "difficulty": 99, "practice": "stayman",
                                         "conventions": ["stayman", "made_up"]}}).json()
    assert (now["hints"], now["signals"], now["difficulty"], now["practice"]) == (False, "upside", 10, None)
    assert app_module.accounts.user(avery["user"]["id"])["table"] == {
        "hints": False, "signals": "upside", "difficulty": 10, "conventions": ["stayman"]}
    d = client.post("/api/table-defaults", headers=h, json={"settings": {"hints": True}}).json()
    assert (d["hints"], d["signals"]) == (False, "upside")  # the account's choices win over the phone's
    s = app_module.rooms.get(client.post("/api/rooms", headers=h).json()["code"]).settings
    assert (s.hints, s.signals, s.difficulty, s.conventions) == (False, "upside", 10, {"stayman"})


def test_practice_from_the_home_menu_starts_a_table_on_it(client):
    def made(body):
        return app_module.rooms.get(client.post("/api/rooms", json=body).json()["code"]).settings

    s = made({"practice": "signals", "settings": {"signals": "off"}})
    assert (s.practice, s.signals) == ("signals", "standard")
    assert made({"practice": "leads", "settings": {"leads": False}}).leads is True
    assert client.post("/api/rooms", json={"practice": "made_up"}).status_code == 400


def next_of(ws, kind):
    for _ in range(100):
        msg = ws.receive_json()
        if msg["type"] == kind:
            return msg
    raise AssertionError(f"no {kind} message")


def my_table(client, who) -> dict:
    """/api/me/table without the copy of the table that comes with a bot table (checked in test_offline.py)."""
    found = client.get("/api/me/table", headers=auth(who["token"])).json()
    found.pop("snap", None)
    return found


def test_another_device_takes_over_the_seat(client):
    """Opening the app on the iPad moves the game there; the phone is told, and can't play until it takes it back."""
    avery, _ = sign_up(client, "Avery")
    assert my_table(client, avery) == {}
    code = client.post("/api/rooms").json()["code"]
    hello = {"type": "join", "auth": avery["token"], "solo": True}
    with client.websocket_connect(f"/ws/{code}") as phone:
        phone.send_json({**hello, "device": "p1", "device_name": "iPhone", "takeover": True})
        assert next_of(phone, "joined")["seat"] == "S"
        assert my_table(client, avery) == {"room": code, "jump": True}
        assert client.get("/api/me/table", headers=auth(avery["token"])).json()["snap"]["code"] == code  # to carry on offline
        with client.websocket_connect(f"/ws/{code}") as ipad:
            ipad.send_json({**hello, "device": "d2", "device_name": "iPad", "takeover": True})
            assert next_of(ipad, "joined")["seat"] == "S"
            assert next_of(phone, "moved")["to"] == "iPad"
        # the phone wakes and reconnects on its own: it doesn't grab the game back
        with client.websocket_connect(f"/ws/{code}") as phone2:
            phone2.send_json({**hello, "device": "p1", "device_name": "iPhone"})
            assert next_of(phone2, "moved")["to"] == "iPad"
        # Continue here does
        with client.websocket_connect(f"/ws/{code}") as phone3:
            phone3.send_json({**hello, "device": "p1", "device_name": "iPhone", "takeover": True})
            next_of(phone3, "state")
            phone3.send_json({"type": "away"})  # tapped Leave
            phone3.send_json({"type": "hint"})
            next_of(phone3, "hint")
    assert my_table(client, avery) == {"room": code, "jump": False}


def test_table_is_found_in_storage_after_a_deploy(client):
    avery, _ = sign_up(client, "Avery")
    code = client.post("/api/rooms").json()["code"]
    with client.websocket_connect(f"/ws/{code}") as ws:
        ws.send_json({"type": "join", "auth": avery["token"], "solo": True, "device": "p1", "takeover": True})
        next_of(ws, "joined")
    app_module.rooms.save_all()
    app_module.rooms.rooms.clear()  # a new copy of the server: nothing in memory yet
    assert my_table(client, avery) == {"room": code, "jump": True}


def test_back_to_your_table_lasts_longer_mid_board(client):
    """The lobby offers the way back for 2 hours after you last played, or 12 if you left in the middle of a rubber."""
    avery, _ = sign_up(client, "Avery")
    code = client.post("/api/rooms").json()["code"]
    with client.websocket_connect(f"/ws/{code}") as ws:
        ws.send_json({"type": "join", "auth": avery["token"], "solo": True, "device": "p1", "takeover": True})
        next_of(ws, "joined")
        next_of(ws, "state")
    room = app_module.rooms.rooms[code]
    me = room.players["S"]
    assert not room._mid_game("S")  # only the bots have bid so far
    me.last = time.time() - 3 * 3600
    assert my_table(client, avery) == {}
    room.table.actions.append(("S", "call", "P"))  # South has bid: in the middle of the first board of the rubber
    assert my_table(client, avery) == {"room": code, "jump": False}
    room.table.actions.clear()
    room.rubber.lines.append(Line(1, "NS", "below", 60, "2♠"))  # a board scored, the rubber not over yet
    app_module.rooms.save_all()
    app_module.rooms.rooms.clear()  # after a deploy, read from storage
    assert my_table(client, avery) == {"room": code, "jump": False}
    me.last = time.time() - 13 * 3600
    app_module.rooms.rooms[code] = room
    assert my_table(client, avery) == {}
    room.rubber.lines.clear()
    room.settings.scoring = "duplicate"
    room.table.actions.append(("S", "call", "P"))  # duplicate scoring: only an unfinished board counts
    me.last = time.time() - 3 * 3600
    assert my_table(client, avery) == {"room": code, "jump": False}


def test_tutorial_progress_follows_the_account(client):
    """Learn to play: games and finished steps are kept on the account; anything unexpected is dropped."""
    out, _ = sign_up(client, "Ann")
    h = auth(out["token"])
    assert client.get("/api/me/tutorial").status_code == 401
    assert client.get("/api/me/tutorial", headers=h).json() == {"games": None, "done": []}
    r = client.post("/api/me/tutorial", headers=h, json={"games": ["Euchre", "Hearts", "Poker"], "done": [2, 99, "x"]})
    assert r.json() == {"games": ["Hearts", "Euchre"], "done": [2]}
    # finished steps are only added, and leaving games out keeps them
    r = client.post("/api/me/tutorial", headers=h, json={"done": [1]})
    assert r.json() == {"games": ["Hearts", "Euchre"], "done": [1, 2]}
    assert client.get("/api/me/tutorial", headers=h).json() == {"games": ["Hearts", "Euchre"], "done": [1, 2]}
    assert client.post("/api/me/tutorial", headers=h, json={"games": []}).json()["games"] == []


def test_friends_list_puts_who_you_last_played_with_first(client):
    avery, _ = sign_up(client, "Avery")
    ids = {}
    for name in ["Pat", "Lee", "Ann", "Bo"]:
        inv = client.post("/api/me/invite", headers=auth(avery["token"])).json()["code"]
        ids[name] = sign_up(client, name, invite=inv)[0]["user"]["id"]
    me = avery["user"]["id"]
    order = lambda: [f["name"] for f in app_module.social.friends_view(me)["friends"]]
    assert [f["name"] for f in app_module.social.friends_view(ids["Ann"])["friends"]] == ["Avery"]
    # a board from before this was kept (no "with"): found once by the names at the table, partner or opponent
    app_module.accounts.save_board(me, {"room": "OLD", "board": 1, "finished_at": 1000.0, "seat": "S",
                                        "players": {"S": "Avery", "E": "Pat"}, "bots": ["N", "W"]})
    assert order() == ["Pat", "Ann", "Bo", "Lee"]  # never played with the rest: alphabetical
    # newer boards: Lee and Bo at the same table (same time, so alphabetical between them), then Pat again
    app_module.accounts.save_board(me, {"room": "R1", "board": 1, "finished_at": 2000.0, "seat": "S",
                                        "players": {}, "with": [ids["Lee"], ids["Bo"]]})
    assert order() == ["Bo", "Lee", "Pat", "Ann"]
    app_module.accounts.save_board(me, {"room": "R2", "board": 1, "finished_at": 3000.0, "seat": "S",
                                        "players": {}, "with": [ids["Pat"]]})
    assert order() == ["Pat", "Bo", "Lee", "Ann"]
    # a bot with a friend's name doesn't count
    app_module.accounts.save_board(ids["Ann"], {"room": "R3", "board": 1, "finished_at": 4000.0, "seat": "S",
                                                "players": {"S": "Ann", "N": "Avery"}, "bots": ["N"]})
    assert [f["name"] for f in app_module.social.friends_view(ids["Ann"])["friends"]] == ["Avery"]
    assert app_module.accounts.last_played(ids["Ann"])[me] == 0


def test_boards_played_offline_reach_my_stats(client):
    me, _ = sign_up(client, "Avery")
    rec = {"board": 1, "room": "HOME", "finished_at": 1763680000.5, "hands": {"N": "", "E": "", "S": "", "W": ""},
           "seat": "S", "with": ["x", 3]}
    assert client.post("/api/me/offline-boards", json={"boards": [rec]}).status_code == 401
    r = client.post("/api/me/offline-boards", json={"boards": [rec]}, headers=auth(me["token"]))
    assert r.status_code == 200 and r.json() == {"saved": 1}
    saved = app_module.accounts.boards(me["user"]["id"])
    assert len(saved) == 1 and saved[0]["offline"] is True and saved[0]["with"] == ["x"]
    r = client.post("/api/me/offline-boards", json={"drop": [rec]}, headers=auth(me["token"]))
    assert r.status_code == 200 and app_module.accounts.boards(me["user"]["id"]) == []
    bad = client.post("/api/me/offline-boards", json={"boards": [{"board": "1"}]}, headers=auth(me["token"]))
    assert bad.status_code == 400


def test_a_table_played_offline_comes_back_to_the_server(client):
    me, _ = sign_up(client, "Avery")
    room = Room("HOME")
    _, token = room.join("Avery", None, None, "not-me")
    room.new_board()
    r = client.post("/api/rooms/carry", json={"snap": room.snapshot(), "token": token}, headers=auth(me["token"]))
    assert r.status_code == 200, r.text
    code = r.json()["code"]
    back = app_module.rooms.rooms[code]
    assert back.players["S"].user == me["user"]["id"] and back.table.hands == room.table.hands
    assert client.post("/api/rooms/carry", json={"snap": room.snapshot(), "token": "nope"}).status_code == 400


def test_a_saved_board_comes_with_its_auction_explained(client):
    """Hand history shows the auction as at the table: each call with what it meant in the system."""
    me, _ = sign_up(client, "Avery")
    user = client.get("/api/me", headers=auth(me["token"])).json()["user"]["id"]
    app_module.accounts.save_board(user, {"room": "R1", "board": 1, "finished_at": 1000.0, "seat": "S", "dealer": "N",
                                          "calls": ["1N", "P", "3N", "P", "P", "P"], "conventions": []})
    key = app_module.accounts.boards(user)[0]["key"]
    rec = client.get(f"/api/me/boards/{key}", headers=auth(me["token"])).json()
    assert [(a["seat"], a["call"]) for a in rec["auction"]] == [("N", "1N"), ("E", "P"), ("S", "3N"), ("W", "P"),
                                                               ("N", "P"), ("E", "P")]
    assert "balanced" in rec["auction"][0]["meaning"]["text"]


def test_your_tables_lists_and_quits_your_tables(client):
    assert client.get("/api/me/tables").status_code == 401
    avery, _ = sign_up(client, "Avery")
    h = auth(avery["token"])
    code = client.post("/api/rooms", headers=h).json()["code"]
    with client.websocket_connect(f"/ws/{code}") as ws:
        ws.send_json({"type": "join", "auth": avery["token"], "solo": True, "device": "p1", "takeover": True})
        next_of(ws, "joined")
    assert [t["room"] for t in client.get("/api/me/tables", headers=h).json()["tables"]] == [code]
    assert client.post("/api/me/tables/claim", headers=h).status_code == 404  # no bot table on another phone
    assert client.post("/api/me/tables/quit", headers=h, json={"room": code.lower()}).json() == {"ok": True}
    assert client.get("/api/me/tables", headers=h).json()["tables"] == []
    assert client.post("/api/me/tables/quit", headers=h, json={"room": code}).status_code == 404
