"""Player accounts: passkey sign-in (Face ID, Touch ID, a fingerprint or the screen lock), invite links, friends,
and the boards each player has finished.

A passkey proves who you are once per device; after that the phone keeps a signed token that lasts a year and is
renewed whenever the app is opened. New accounts need an invite link from someone who already plays (which also
makes the two of you friends), or the family code if one is set (BRIDGE_INVITE_CODE). The very first account needs
neither, so whoever connects the storage can sign up straight away.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import time
from dataclasses import dataclass
from urllib.parse import urlsplit

from webauthn import (generate_authentication_options, generate_registration_options, options_to_json,
                      verify_authentication_response, verify_registration_response)
from webauthn.helpers import base64url_to_bytes, bytes_to_base64url
from webauthn.helpers.structs import (AuthenticatorSelectionCriteria, PublicKeyCredentialDescriptor,
                                      ResidentKeyRequirement, UserVerificationRequirement)

from . import site
from .stats import board_facts, rebuild_part_scores
from .store import Store

TOKEN_LIFE = 365 * 24 * 3600
RENEW_AFTER = 7 * 24 * 3600  # hand out a fresh token when the one in use is more than a week old
CHALLENGE_LIFE = 5 * 60
MAX_CHALLENGES = 1000  # sign-ins in progress at once, so a flood of them can't fill the memory
INVITE_LIFE = 30 * 24 * 3600
DEVICE_LINK_LIFE = 15 * 60
CODE_LETTERS = "BCDFGHJKLMNPQRSTVWXZ23456789"  # no vowels (no accidental words), no 0/1 (no O/I mix-ups)


class AuthError(ValueError):
    """Something the person can fix: shown to them as is."""


def _code(n: int) -> str:
    return "".join(secrets.choice(CODE_LETTERS) for _ in range(n))


def _norm_code(code: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", code.upper())


@dataclass
class Origin:
    rp_id: str  # the site's host name, which every passkey is tied to
    origin: str  # what the browser reports, e.g. https://bridge.example.com


def origin_for(host: str, scheme: str) -> Origin:
    o = site.origin()
    if o:
        return Origin(o.split("://", 1)[1].split(":")[0], o)
    name = host.split(":")[0]
    if name not in ("localhost", "127.0.0.1"):
        scheme = "https"  # behind Azure's front door the app itself sees plain http
    return Origin(name, f"{scheme}://{host}")


# The phone makers' push services: notifications are only ever sent to these, never to an address a player made up
PUSH_HOSTS = ("web.push.apple.com", "fcm.googleapis.com", "push.services.mozilla.com", "notify.windows.com")


def push_service(endpoint: str) -> bool:
    try:
        url = urlsplit(endpoint)
    except ValueError:
        return False
    host = (url.hostname or "").lower()
    return url.scheme == "https" and url.port in (None, 443) and any(
        host == h or host.endswith("." + h) for h in PUSH_HOSTS)


class Accounts:
    def __init__(self, store: Store):
        self.store = store
        self.challenges: dict[str, dict] = {}
        self._secret: bytes | None = None
        self._has_users = False  # once someone has an account it stays so: no need to look again
        # what My stats needs from each saved board (stats.board_facts), per player: worked out once from the boards
        # in storage, then kept up to date as boards are saved or taken back, so My stats doesn't reread every board
        self._facts: dict[str, dict[str, dict]] = {}
        self._admin: str | None = None

    @property
    def enabled(self) -> bool:
        return self.store.durable

    # --- tokens ----------------------------------------------------------------------------
    def secret(self) -> bytes:
        if self._secret is None:
            cfg = self.store.get("config", "cfg", "secret")
            if not cfg:
                cfg = {"key": secrets.token_hex(32)}
                self.store.put("config", "cfg", "secret", cfg)
            self._secret = bytes.fromhex(cfg["key"])
        return self._secret

    # A token carries the account's "generation": Sign out other phones moves it on, which cancels every token made
    # before. Tokens from before generations existed have none, which counts as generation 0.
    def make_token(self, user_id: str, now: float | None = None, gen: int = 0) -> str:
        issued = int(now or time.time())
        body = f"{user_id}.{issued}" + (f".{gen}" if gen else "")
        sig = hmac.new(self.secret(), body.encode(), hashlib.sha256).hexdigest()[:32]
        return f"{body}.{sig}"

    def check_token(self, token: str | None) -> tuple[str, int, int] | None:
        """(user id, when issued, generation), or None for a missing, forged or expired token."""
        try:
            *parts, sig = str(token).split(".")
            if len(parts) not in (2, 3):
                return None
            good = hmac.new(self.secret(), ".".join(parts).encode(), hashlib.sha256).hexdigest()[:32]
            if hmac.compare_digest(sig, good) and time.time() - int(parts[1]) < TOKEN_LIFE:
                return parts[0], int(parts[1]), int(parts[2]) if len(parts) == 3 else 0
        except (ValueError, AttributeError):
            pass
        return None

    def _token_user(self, token: str | None) -> tuple[dict, tuple[str, int, int]] | None:
        found = self.check_token(token) if self.enabled else None
        user = self.user(found[0]) if found else None
        if not user or user.get("gen", 0) != found[2]:  # signed out by Sign out other phones
            return None
        return user, found

    def user_for(self, token: str | None) -> dict | None:
        got = self._token_user(token)
        return got[0] if got else None

    def token_for(self, user: dict) -> str:
        return self.make_token(user["id"], gen=user.get("gen", 0))

    def sign_out_others(self, user: dict) -> str:
        """Cancel every sign-in to this account; the token returned keeps this phone signed in."""
        user["gen"] = user.get("gen", 0) + 1
        self.save_user(user)
        return self.token_for(user)

    # --- users ---------------------------------------------------------------------------
    def user(self, user_id: str) -> dict | None:
        u = self.store.get("users", "u", user_id)
        return {**u, "id": user_id} if u else None

    def has_users(self) -> bool:
        """Whether anyone has an account yet. Asked by every sign-up screen, so it reads storage only until the
        answer is yes."""
        if not self._has_users:
            self._has_users = bool(self.store.query("users", "u"))
        return self._has_users

    def all_users(self) -> list[dict]:
        return [{**u, "id": uid} for uid, u in self.store.query("users", "u")]

    def save_user(self, user: dict) -> None:
        self.store.put("users", "u", user["id"], {k: v for k, v in user.items() if k != "id"})

    def by_friend_code(self, code: str) -> dict | None:
        ref = self.store.get("codes", "code", _norm_code(code))
        return self.user(ref["user"]) if ref else None

    def public(self, user: dict) -> dict:
        out = {"id": user["id"], "name": user["name"], "friend_code": user["friend_code"],
               "notify": user.get("notify", True), "push": bool(user.get("push"))}
        if self.is_admin(user):
            out["admin"] = True
        return out

    def touch(self, user: dict) -> None:
        user["last_seen"] = time.time()
        self.save_user(user)

    def _new_user(self, name: str) -> dict:
        for _ in range(50):
            code = f"{_norm_code(name)[:6] or 'PLAYER'}-{_code(2)}"
            if not self.store.get("codes", "code", _norm_code(code)):
                break
        user = {"id": secrets.token_hex(8), "name": name, "friend_code": code, "created": time.time(),
                "last_seen": time.time(), "notify": True, "push": []}
        self.save_user(user)
        self.store.put("codes", "code", _norm_code(code), {"user": user["id"]})
        return user

    def remove_user(self, user_id: str) -> None:
        """An account and everything kept for it: passkeys, friend code, friends (on both sides), invites it made and
        its saved boards, Your mistakes progress and AI app connections. Suggestions it sent stay, under the name it had."""
        user = self.user(user_id)
        for other in list(self.links(user_id)):
            self.unfriend(user_id, other)
        for cred_id, _ in self.store.query("usercreds", user_id):
            self.store.delete("creds", "c", cred_id)
            self.store.delete("usercreds", user_id, cred_id)
        for key, _ in self.store.query("boards", user_id):
            self.store.delete("boards", user_id, key)
        for pid, _ in self.store.query("puzzles", user_id):  # Your mistakes (puzzles.py)
            self.store.delete("puzzles", user_id, pid)
        for grant, _ in self.store.query("aigrants", user_id):  # AI apps connected to it (connector.py)
            self.store.delete("aigrants", user_id, grant)
        for code, inv in self.store.query("invites", "i"):
            if inv.get("by") == user_id:
                self.store.delete("invites", "i", code)
        if user:
            self.store.delete("codes", "code", _norm_code(user["friend_code"]))
        self.store.delete("users", "u", user_id)
        self._facts.pop(user_id, None)

    # --- the site's owner ----------------------------------------------------------------
    def admin_id(self) -> str | None:
        """The one account that may open the Admin page: BRIDGE_ADMIN (an account id or friend code) when set,
        otherwise the first account ever made. That choice is remembered in storage, so removing accounts can never
        pass it to someone else."""
        if os.environ.get("BRIDGE_ADMIN"):
            want = os.environ["BRIDGE_ADMIN"].strip()
            u = self.user(want) or self.by_friend_code(want)
            return u["id"] if u else None
        if self._admin is None:
            cfg = self.store.get("config", "cfg", "admin")
            if not cfg:
                users = self.all_users()
                if not users:
                    return None
                cfg = {"user": min(users, key=lambda u: u.get("created", 0))["id"]}
                self.store.put("config", "cfg", "admin", cfg)
            self._admin = cfg["user"]
        return self._admin

    def is_admin(self, user: dict | None) -> bool:
        return bool(user) and self.enabled and user["id"] == self.admin_id()

    # --- invites -------------------------------------------------------------------------
    def make_invite(self, user: dict) -> str:
        """A link for a friend: someone new makes an account with it, someone who plays just opens it, and you're
        friends straight away. Tapping Invite again before sharing the last link gives that same link back, so links
        that were made but never sent don't pile up."""
        now = time.time()
        for code, inv in self.store.query("invites", "i"):
            if (inv.get("by") == user["id"] and inv.get("kind") == "account" and not inv.get("sent")
                    and inv.get("made") and inv.get("expires", 0) > now):
                return code
        code = _code(8)
        self.store.put("invites", "i", code, {"by": user["id"], "kind": "account", "made": now,
                                               "expires": now + INVITE_LIFE})
        return code

    def invite_sent(self, user: dict, code: str) -> None:
        """The player shared or copied their invite link, so the next Invite makes a fresh one."""
        inv = self._invite(code)
        if inv and inv[1]["by"] == user["id"] and inv[1]["kind"] == "account" and not inv[1].get("sent"):
            self.store.put("invites", "i", inv[0], {**inv[1], "sent": time.time()})

    def use_invite(self, user: dict, code: str) -> dict:
        """A player who already has an account opens a friend's invite link: they're friends straight away, and the
        link is used up. Returns the friend who made it."""
        inv = self._invite(code)
        if not inv or inv[1]["kind"] != "account":
            raise AuthError("That invite link has been used or has run out. Ask for a new one.")
        by = self.user(inv[1]["by"])
        if not by:
            raise AuthError("The player who made that invite link no longer has an account")
        if by["id"] == user["id"]:
            raise AuthError("That's your own invite link. Send it to a friend.")
        if self.links(user["id"]).get(by["id"]) != "friends":
            self.befriend(user["id"], by["id"])
            self.store.delete("invites", "i", inv[0])
        return by

    def make_device_link(self, user: dict) -> str:
        """A short code that lets a new phone add its own passkey to this account (e.g. iPhone to Android)."""
        code = _code(6)
        self.store.put("invites", "i", code, {"by": user["id"], "kind": "device",
                                               "expires": time.time() + DEVICE_LINK_LIFE})
        return code

    def _invite(self, code: str | None) -> tuple[str, dict] | None:
        if not code:
            return None
        c = _norm_code(code)
        inv = self.store.get("invites", "i", c)
        if not inv or inv["expires"] < time.time():
            return None
        return c, inv

    def signup_status(self, invite: str | None) -> dict:
        """What the sign-up screen needs to know before asking for anything."""
        inv = self._invite(invite)
        by = self.user(inv[1]["by"]) if inv else None
        return {"enabled": self.enabled,
                "invite_ok": bool(inv and inv[1]["kind"] == "account"),
                "device_link": bool(inv and inv[1]["kind"] == "device"),
                "invited_by": by["name"] if by else None,
                "first": self.enabled and not self.has_users(),
                "family_code": bool(os.environ.get("BRIDGE_INVITE_CODE"))}

    def _may_sign_up(self, invite: str | None) -> tuple[str, dict] | None:
        """The invite that lets this sign-up through (None when the family code or first account does)."""
        inv = self._invite(invite)
        if inv and inv[1]["kind"] == "account":
            return inv
        family = os.environ.get("BRIDGE_INVITE_CODE")
        if family and invite and _norm_code(invite) == _norm_code(family):
            return None
        if not self.has_users():
            return None
        raise AuthError("You need an invite link from someone who already plays")

    # --- passkeys ------------------------------------------------------------------------
    def _challenge(self, kind: str, challenge: bytes, **extra) -> str:
        now = time.time()
        self.challenges = {k: v for k, v in self.challenges.items() if v["expires"] > now}
        while len(self.challenges) >= MAX_CHALLENGES:  # a flood of sign-in starts: the oldest go first
            self.challenges.pop(next(iter(self.challenges)))
        cid = secrets.token_urlsafe(12)
        self.challenges[cid] = {"kind": kind, "challenge": challenge, "expires": now + CHALLENGE_LIFE, **extra}
        return cid

    def _take_challenge(self, cid: str, kind: str) -> dict:
        ch = self.challenges.pop(str(cid), None)
        if not ch or ch["kind"] != kind or ch["expires"] < time.time():
            raise AuthError("That took too long. Please try again.")
        return ch

    def register_options(self, origin: Origin, name: str, invite: str | None) -> dict:
        """Step 1 of making an account, or of adding a passkey on a new device (`invite` is then a device link)."""
        if not self.enabled:
            raise AuthError("Accounts aren't switched on yet")
        inv = self._invite(invite)
        if inv and inv[1]["kind"] == "device":
            user = self.user(inv[1]["by"])
            if not user:
                raise AuthError("That code is no longer valid")
            existing = [PublicKeyCredentialDescriptor(id=base64url_to_bytes(c["id"]))
                        for c in self._creds_of(user["id"])]
            target = {"user": user["id"], "device_link": inv[0]}
            name = user["name"]
            user_handle = user["id"].encode()
        else:
            name = " ".join(str(name).split())[:24]
            if not name:
                raise AuthError("Enter your name first")
            self._may_sign_up(invite)
            existing = []
            target = {"name": name, "invite": invite}
            user_handle = secrets.token_bytes(16)
        opts = generate_registration_options(
            rp_id=origin.rp_id, rp_name=site.app_name(), user_id=user_handle, user_name=name, user_display_name=name,
            exclude_credentials=existing,
            authenticator_selection=AuthenticatorSelectionCriteria(
                resident_key=ResidentKeyRequirement.REQUIRED,
                user_verification=UserVerificationRequirement.PREFERRED))
        cid = self._challenge("register", opts.challenge, user_handle=user_handle, **target)
        return {"challenge_id": cid, "options": json.loads(options_to_json(opts))}

    def register_verify(self, origin: Origin, cid: str, credential: dict) -> dict:
        ch = self._take_challenge(cid, "register")
        try:
            v = verify_registration_response(credential=credential, expected_challenge=ch["challenge"],
                                             expected_rp_id=origin.rp_id, expected_origin=origin.origin)
        except Exception as exc:
            raise AuthError("Face ID didn't finish setting up. Please try again.") from exc
        if "user" in ch:  # a new device on an existing account
            user = self.user(ch["user"])
            self.store.delete("invites", "i", ch["device_link"])
        else:
            inv = self._may_sign_up(ch.get("invite"))
            user = self._new_user(ch["name"])
            if inv:
                self.store.delete("invites", "i", inv[0])
                inviter = self.user(inv[1]["by"])
                if inviter:
                    user["invited_by"] = inviter["id"]  # for Admin's steps from the owner (admin.py)
                    self.save_user(user)
                    self.befriend(inviter["id"], user["id"])
        cred_id = bytes_to_base64url(v.credential_id)
        self.store.put("creds", "c", cred_id, {
            "user": user["id"], "handle": bytes_to_base64url(ch["user_handle"]),
            "key": bytes_to_base64url(v.credential_public_key), "count": v.sign_count, "created": time.time()})
        self.store.put("usercreds", user["id"], cred_id, {"id": cred_id})
        return {"token": self.token_for(user), "user": self.public(user)}

    def _creds_of(self, user_id: str) -> list[dict]:
        return [c for _, c in self.store.query("usercreds", user_id)]

    def login_options(self, origin: Origin) -> dict:
        if not self.enabled:
            raise AuthError("Accounts aren't switched on yet")
        # no list of passkeys: the phone offers whichever one it has for this site
        opts = generate_authentication_options(rp_id=origin.rp_id,
                                               user_verification=UserVerificationRequirement.PREFERRED)
        return {"challenge_id": self._challenge("login", opts.challenge),
                "options": json.loads(options_to_json(opts))}

    def login_verify(self, origin: Origin, cid: str, credential: dict) -> dict:
        ch = self._take_challenge(cid, "login")
        cred_id = str(credential.get("id", ""))
        stored = self.store.get("creds", "c", cred_id)
        if not stored:
            raise AuthError("This passkey isn't linked to an account here any more")
        try:
            v = verify_authentication_response(
                credential=credential, expected_challenge=ch["challenge"], expected_rp_id=origin.rp_id,
                expected_origin=origin.origin, credential_public_key=base64url_to_bytes(stored["key"]),
                credential_current_sign_count=stored["count"])
        except Exception as exc:
            raise AuthError("Sign-in didn't go through. Please try again.") from exc
        stored["count"] = v.new_sign_count
        self.store.put("creds", "c", cred_id, stored)
        user = self.user(stored["user"])
        if not user:
            raise AuthError("This account no longer exists")
        self.touch(user)
        return {"token": self.token_for(user), "user": self.public(user)}

    def me(self, token: str | None) -> dict | None:
        """The signed-in player, with a renewed token once the old one is a week old."""
        got = self._token_user(token)
        if not got:
            return None
        user, found = got
        self.touch(user)
        fresh = self.token_for(user) if time.time() - found[1] > RENEW_AFTER else token
        return {"token": fresh, "user": self.public(user)}

    # --- friends -------------------------------------------------------------------------
    # Each side keeps its own row: "friends", "out" (asked, waiting) or "in" (asked by them).
    def befriend(self, a: str, b: str) -> None:
        now = time.time()
        self.store.put("friends", a, b, {"state": "friends", "since": now})
        self.store.put("friends", b, a, {"state": "friends", "since": now})

    def links(self, user_id: str) -> dict[str, str]:
        return {other: row["state"] for other, row in self.store.query("friends", user_id)}

    def friend_ids(self, user_id: str) -> list[str]:
        return [o for o, s in self.links(user_id).items() if s == "friends"]

    def played_together(self, user_id: str, others, at: float) -> None:
        """Note on each friend's row that these two just finished a board at the same table (partners or opponents)."""
        for other in others:
            row = self.store.get("friends", user_id, other)
            if row and row.get("state") == "friends" and (row.get("played") or 0) < at:
                self.store.put("friends", user_id, other, {**row, "played": at})

    def last_played(self, user_id: str) -> dict[str, float]:
        """friend id -> when the two last finished a board together (0: never). Friends whose row hasn't been
        stamped yet are looked up once in this player's saved boards, by name (boards from before this was kept)."""
        rows = {o: r for o, r in self.store.query("friends", user_id) if r.get("state") == "friends"}
        missing = {o for o, r in rows.items() if "played" not in r}
        if missing:
            names: dict[str, list[str]] = {}
            for o in missing:
                other = self.user(o)
                if other:
                    names.setdefault(other["name"].casefold(), []).append(o)
            found: dict[str, float] = {}
            for rec in self.boards(user_id):  # newest first
                seat = rec.get("seat")
                for s, name in (rec.get("players") or {}).items():
                    if s == seat or not isinstance(name, str) or s in (rec.get("bots") or []):
                        continue
                    for o in names.get(name.casefold(), ()):
                        found.setdefault(o, rec.get("finished_at") or 0)
                if len(found) == len(missing):
                    break
            for o in missing:
                rows[o] = {**rows[o], "played": found.get(o, 0)}
                self.store.put("friends", user_id, o, rows[o])
        return {o: r.get("played") or 0 for o, r in rows.items()}

    def request_friend(self, user: dict, who: str) -> dict:
        """`who` is a friend code, or a name when only one player has it."""
        other = self.by_friend_code(who)
        if not other:
            wanted = " ".join(str(who).split()).casefold()
            named = [u for u in self.all_users() if u["name"].casefold() == wanted and u["id"] != user["id"]]
            if len(named) > 1:
                raise AuthError(f"More than one player is called {named[0]['name']}. Ask for their friend code.")
            other = named[0] if named else None
        if not other:
            raise AuthError("No player has that name or friend code")
        if other["id"] == user["id"]:
            raise AuthError("That's your own friend code")
        state = self.links(user["id"]).get(other["id"])
        if state == "friends":
            raise AuthError(f"You and {other['name']} are already friends")
        if state == "in":  # they asked first: asking back says yes
            self.befriend(user["id"], other["id"])
        else:
            now = time.time()
            self.store.put("friends", user["id"], other["id"], {"state": "out", "since": now})
            self.store.put("friends", other["id"], user["id"], {"state": "in", "since": now})
        return other

    def answer_friend(self, user: dict, other_id: str, accept: bool) -> None:
        if self.links(user["id"]).get(other_id) != "in":
            raise AuthError("No friend request from that player")
        if accept:
            self.befriend(user["id"], other_id)
        else:
            self.unfriend(user["id"], other_id)

    def unfriend(self, a: str, b: str) -> None:
        for x, y in ((a, b), (b, a)):
            try:
                self.store.delete("friends", x, y)
            except Exception:
                pass

    # --- notifications -------------------------------------------------------------------
    def save_table_settings(self, user_id: str, chosen: dict) -> None:
        """Table settings this player last chose (room.REMEMBERED), so their next new table starts with them."""
        user = self.user(user_id)
        if user and any(self.table_settings(user).get(k) != v for k, v in chosen.items()):
            user["table"] = {**user.get("table", {}), **chosen}
            self.save_user(user)

    @staticmethod
    def table_settings(user: dict) -> dict:
        """What a new table of theirs starts with; before 1.55 only the scoring was kept."""
        return {**({"scoring": user["scoring"]} if user.get("scoring") else {}), **user.get("table", {})}

    # --- Learn to play ----------------------------------------------------------------------
    TUTORIAL_GAMES = ("Hearts", "Spades", "Oh Hell", "Euchre", "Pinochle")

    @staticmethod
    def tutorial(user: dict) -> dict:
        """Learn to play: the card games this player said they know (None until asked) and the steps they finished."""
        t = user.get("tutorial") or {}
        return {"games": t.get("games"), "done": t.get("done", [])}

    def save_tutorial(self, user: dict, games, done) -> dict:
        """Keeps only known games and step numbers 1 to 7, so nothing else can be stored here."""
        t = self.tutorial(user)
        if games is not None:
            t["games"] = [g for g in self.TUTORIAL_GAMES if g in games] if isinstance(games, list) else []
        if isinstance(done, list):
            t["done"] = sorted({int(n) for n in done if isinstance(n, int) and 1 <= n <= 7} | set(t["done"]))
        if t != self.tutorial(user):
            user["tutorial"] = t
            self.save_user(user)
        return t

    def set_notify(self, user: dict, on: bool) -> None:
        user["notify"] = bool(on)
        if not on:
            user["push"] = []  # nothing is kept that could still reach the phone
        self.save_user(user)

    def add_push(self, user: dict, sub: dict) -> None:
        if not isinstance(sub, dict) or not push_service(str(sub.get("endpoint", ""))):
            raise AuthError("That notification sign-up didn't work")
        subs = [s for s in user.get("push", []) if s.get("endpoint") != sub["endpoint"]]
        user["push"] = (subs + [{"endpoint": sub["endpoint"], "keys": sub.get("keys", {})}])[-5:]
        user["notify"] = True
        self.save_user(user)

    def drop_push(self, user_id: str, endpoint: str) -> None:
        user = self.user(user_id)
        if user:
            user["push"] = [s for s in user.get("push", []) if s.get("endpoint") != endpoint]
            self.save_user(user)

    # --- saved boards ----------------------------------------------------------------------
    @staticmethod
    def board_key(record: dict) -> str:
        return f"{record.get('finished_at', 0):014.3f}-{record.get('room', '')}-{record.get('board', 0)}"

    def save_board(self, user_id: str, record: dict) -> None:
        key = self.board_key(record)
        self.store.put("boards", user_id, key, record)
        if record.get("with"):  # the friends list puts whoever you last played with first
            self.played_together(user_id, record["with"], record.get("finished_at") or time.time())
        if user_id in self._facts:
            self._facts[user_id][key] = board_facts({**record, "key": key})

    def update_board(self, user_id: str, key: str, record: dict) -> None:
        """Save a board again with something worked out later (backfill.py), leaving the friends order alone."""
        self.store.put("boards", user_id, key, record)
        if user_id in self._facts:
            self._facts[user_id][key] = board_facts({**record, "key": key})

    def drop_board(self, user_id: str, record: dict) -> None:
        key = self.board_key(record)
        self.store.delete("boards", user_id, key)
        self._facts.get(user_id, {}).pop(key, None)

    def facts(self, user_id: str) -> list[dict]:
        """stats.board_facts for every board this player has finished."""
        if user_id not in self._facts:
            records = self.boards(user_id)
            rebuild_part_scores(records)  # boards saved before 1.93 didn't keep the rubber's part score
            self._facts[user_id] = {r["key"]: board_facts(r) for r in records}
        return list(self._facts[user_id].values())

    def boards(self, user_id: str) -> list[dict]:
        """Newest first."""
        return [{**r, "key": k} for k, r in reversed(self.store.query("boards", user_id))]

    def board(self, user_id: str, key: str) -> dict | None:
        return self.store.get("boards", user_id, key)

