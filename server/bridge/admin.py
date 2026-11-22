"""The Admin page: the site's owner looks after players, tables, suggestions, backups, abuse and a notice for everyone.

Only one account may use it (Accounts.admin_id). To anyone else every /api/admin address answers 404, as if it didn't
exist. Anything that removes or puts back data (removing players, downloading or restoring a backup) also needs Face
ID again within the last CONFIRM_LIFE seconds, so a phone left signed in isn't enough. Every change is written to
the admin log, which the page shows.
"""
from __future__ import annotations

import json
import secrets
import time

from webauthn import generate_authentication_options, options_to_json, verify_authentication_response
from webauthn.helpers import base64url_to_bytes
from webauthn.helpers.structs import PublicKeyCredentialDescriptor, UserVerificationRequirement

from .accounts import Accounts, AuthError, Origin
from .store import Store

CONFIRM_LIFE = 5 * 60
SIGN_UP_FRIEND_GAP = 60  # seconds: an invite link makes the two friends right as the account is made
OLD_AFTER_DAYS = 365  # an account nobody has used for this long counts as old
LOG_KEEP = 500
NOTICE_MAX = 300
# Tables with someone at them, beyond which nobody but the owner can start a new one. One container of today's size
# (0.5 CPU) keeps about 4 busy level 10 tables playing at full speed (load test, 2026-10-29).
TABLE_LIMIT = 4
TABLE_LIMIT_MAX = 100
CONFIRM = "Please confirm with Face ID"  # the page asks for Face ID when an answer says this


class Admin:
    def __init__(self, store: Store, accounts: Accounts):
        self.store = store
        self.accounts = accounts
        self.confirmed: dict[str, float] = {}  # admin id -> until when Face ID counts as just given
        self._notice: dict | None = None
        self._notice_read = False
        self._table_limit: int | None = None

    # --- Face ID again, for anything that removes or puts back data ------------------------------------
    def confirm_options(self, user: dict, origin: Origin) -> dict:
        creds = [PublicKeyCredentialDescriptor(id=base64url_to_bytes(c["id"]))
                 for c in self.accounts._creds_of(user["id"])]
        opts = generate_authentication_options(rp_id=origin.rp_id, allow_credentials=creds,
                                               user_verification=UserVerificationRequirement.REQUIRED)
        cid = self.accounts._challenge("admin", opts.challenge, user=user["id"])
        return {"challenge_id": cid, "options": json.loads(options_to_json(opts))}

    def confirm_verify(self, user: dict, origin: Origin, cid: str, credential: dict) -> None:
        ch = self.accounts._take_challenge(cid, "admin")
        cred_id = str(credential.get("id", ""))
        stored = self.store.get("creds", "c", cred_id)
        if ch.get("user") != user["id"] or not stored or stored.get("user") != user["id"]:
            raise AuthError("That wasn't your passkey")
        try:
            v = verify_authentication_response(
                credential=credential, expected_challenge=ch["challenge"], expected_rp_id=origin.rp_id,
                expected_origin=origin.origin, credential_public_key=base64url_to_bytes(stored["key"]),
                credential_current_sign_count=stored["count"], require_user_verification=True)
        except Exception as exc:
            raise AuthError("Face ID didn't go through. Please try again.") from exc
        stored["count"] = v.new_sign_count
        self.store.put("creds", "c", cred_id, stored)
        self.confirmed[user["id"]] = time.time() + CONFIRM_LIFE

    def is_confirmed(self, user: dict) -> bool:
        return self.confirmed.get(user["id"], 0) > time.time()

    # --- the log ---------------------------------------------------------------------------------------
    def log(self, user: dict, action: str, detail: str = "") -> None:
        now = time.time()
        self.store.put("adminlog", "a", f"{now:014.3f}-{secrets.token_hex(2)}",
                       {"at": now, "who": user["name"], "action": action, "detail": detail[:300]})
        rows = self.store.query("adminlog", "a")
        for key, _ in rows[:max(0, len(rows) - LOG_KEEP)]:
            self.store.delete("adminlog", "a", key)

    def log_rows(self, limit: int = 100) -> list[dict]:
        return [r for _, r in reversed(self.store.query("adminlog", "a")[-limit:])]

    # --- players ---------------------------------------------------------------------------------------
    def players(self) -> list[dict]:
        out = []
        users = self.accounts.all_users()
        sep = self._separation(users, self._pairs(users))
        for u in users:
            links = self.accounts.links(u["id"])
            out.append({"id": u["id"], "name": u["name"], "friend_code": u.get("friend_code"),
                        "created": u.get("created"), "last_seen": u.get("last_seen") or u.get("created"),
                        "boards": len(self.accounts.facts(u["id"])),
                        "friends": sum(1 for s in links.values() if s == "friends"),
                        "passkeys": len(self.accounts._creds_of(u["id"])),
                        "notify": bool(u.get("notify", True) and u.get("push")),
                        "admin": u["id"] == self.accounts.admin_id(), **sep[u["id"]],
                        # AI coach: the apps connected now, and the last call that pulled their data (connector.py)
                        "ai_apps": sorted(({"app": g.get("app") or "AI app", "used": g.get("used")}
                                           for _, g in self.store.query("aigrants", u["id"])
                                           if g.get("gen", 0) == u.get("gen", 0)), key=lambda a: a["app"]),
                        "ai_used": u.get("ai_used")})
        return sorted(out, key=lambda p: -(p["last_seen"] or 0))

    def old_players(self, now: float | None = None) -> list[dict]:
        """Accounts not used for OLD_AFTER_DAYS, never the admin's own."""
        cutoff = (now or time.time()) - OLD_AFTER_DAYS * 24 * 3600
        return [p for p in self.players() if not p["admin"] and (p["last_seen"] or 0) < cutoff]

    def remove_player(self, user_id: str) -> dict:
        target = self.accounts.user(user_id)
        if not target:
            raise ValueError("No such player")
        if target["id"] == self.accounts.admin_id():
            raise ValueError("That's your own account")
        self.accounts.remove_user(user_id)
        return target

    # --- who is friends with whom ----------------------------------------------------------------------
    def friends(self) -> dict:
        """Every player and every friendship, each pair once (both sides keep a row), for the Friends chart.
        A request one side sent and the other hasn't answered is listed apart, under `waiting`."""
        users = self.accounts.all_users()
        known = {u["id"] for u in users}
        pairs: dict[tuple[str, str], float | None] = {}
        waiting = []
        for u in users:
            for other, row in self.store.query("friends", u["id"]):
                if other not in known:
                    continue
                if row.get("state") == "friends":
                    pairs.setdefault(tuple(sorted((u["id"], other))), row.get("since"))
                elif row.get("state") == "out":
                    waiting.append({"from": u["id"], "to": other, "since": row.get("since")})
        admin_id = self.accounts.admin_id()
        sep = self._separation(users, pairs)
        players = [{"id": u["id"], "name": u["name"], "admin": u["id"] == admin_id,
                    "last_seen": u.get("last_seen") or u.get("created"), **sep[u["id"]]} for u in users]
        return {"players": sorted(players, key=lambda p: p["name"].lower()),
                "links": [{"a": a, "b": b, "since": t} for (a, b), t in sorted(pairs.items())],
                "waiting": waiting}

    # --- steps from the owner ---------------------------------------------------------------------------
    def _pairs(self, users: list[dict]) -> dict[tuple[str, str], float | None]:
        known = {u["id"] for u in users}
        pairs: dict[tuple[str, str], float | None] = {}
        for u in users:
            for other, row in self.store.query("friends", u["id"]):
                if other in known and row.get("state") == "friends":
                    pairs.setdefault(tuple(sorted((u["id"], other))), row.get("since"))
        return pairs

    def _separation(self, users: list[dict], pairs: dict) -> dict[str, dict]:
        """For each player: who invited them, the invites between the owner and them (`steps`, with `chain` from the
        owner down to them) and the fewest friendships between (`friend_steps`). None where it isn't known."""
        owner = self.accounts.admin_id()
        invited_by = self._invited_by(users, pairs)
        steps = self._invite_steps(owner, invited_by)
        by_friends = self._friend_steps(owner, pairs)
        out = {}
        for u in users:
            chain = None
            if u["id"] in steps:
                chain, at = [u["id"]], u["id"]
                while at != owner:
                    at = invited_by[at]
                    chain.insert(0, at)
            out[u["id"]] = {"invited_by": invited_by.get(u["id"]), "steps": steps.get(u["id"]), "chain": chain,
                            "friend_steps": by_friends.get(u["id"])}
        return out

    @staticmethod
    def _invited_by(users: list[dict], pairs: dict) -> dict[str, str]:
        """Who brought each player in with an invite link. Accounts made since 2.25 keep it (`invited_by`). For
        older ones it's the friend made at the moment the account was (an invite link makes the two friends straight
        away), when that friendship is still there."""
        known = {u["id"]: u for u in users}
        out: dict[str, str] = {}
        for u in users:
            if u.get("invited_by") in known:
                out[u["id"]] = u["invited_by"]
                continue
            made = u.get("created") or 0
            best = None
            for (a, b), since in pairs.items():
                if u["id"] not in (a, b) or not since:
                    continue
                other = b if a == u["id"] else a
                gap = since - made
                if 0 <= gap <= SIGN_UP_FRIEND_GAP and (known[other].get("created") or 0) < made:
                    if best is None or gap < best[0]:
                        best = (gap, other)
            if best:
                out[u["id"]] = best[1]
        return out

    @staticmethod
    def _invite_steps(owner: str | None, invited_by: dict[str, str]) -> dict[str, int]:
        """Invites between the owner and each player: 1 for someone the owner invited, 2 for someone they invited,
        and so on. Players whose chain doesn't reach the owner are left out."""
        steps: dict[str, int] = {owner: 0} if owner else {}
        for start in invited_by:
            path, at = [], start
            while at not in steps and at in invited_by and at not in path:
                path.append(at)
                at = invited_by[at]
            if at in steps:
                for i, pid in enumerate(reversed(path), 1):
                    steps[pid] = steps[at] + i
        return steps

    @staticmethod
    def _friend_steps(owner: str | None, pairs: dict) -> dict[str, int]:
        """The fewest friendships between the owner and each player (friends of friends are 2)."""
        if not owner:
            return {}
        near: dict[str, list[str]] = {}
        for a, b in pairs:
            near.setdefault(a, []).append(b)
            near.setdefault(b, []).append(a)
        steps, queue = {owner: 0}, [owner]
        for at in queue:
            for nxt in near.get(at, ()):
                if nxt not in steps:
                    steps[nxt] = steps[at] + 1
                    queue.append(nxt)
        return steps

    # --- invites waiting to be used ---------------------------------------------------------------------
    def invites(self) -> list[dict]:
        now = time.time()
        out = []
        for code, inv in self.store.query("invites", "i"):
            if inv.get("expires", 0) < now:
                self.store.delete("invites", "i", code)  # tidy up as we go
                continue
            by = self.accounts.user(inv.get("by", ""))
            out.append({"code": code, "kind": inv.get("kind"), "by": by["name"] if by else "?",
                        "expires": inv["expires"], "made": inv.get("made"), "sent": inv.get("sent")})
        return sorted(out, key=lambda i: i["expires"])

    def cancel_invite(self, code: str) -> None:
        if not self.store.get("invites", "i", code):
            raise ValueError("No such invite")
        self.store.delete("invites", "i", code)

    # --- the notice everyone sees in the lobby ----------------------------------------------------------
    def notice(self) -> dict | None:
        if not self._notice_read:
            self._notice = self.store.get("config", "cfg", "notice")
            self._notice_read = True
        return self._notice

    def set_notice(self, text: str | None) -> dict | None:
        text = " ".join((text or "").split())
        if len(text) > NOTICE_MAX:
            raise ValueError(f"Please keep it under {NOTICE_MAX} characters")
        if text:
            self._notice = {"text": text, "at": time.time()}
            self.store.put("config", "cfg", "notice", self._notice)
        else:
            self._notice = None
            self.store.delete("config", "cfg", "notice")
        self._notice_read = True
        return self._notice

    def forget(self) -> None:
        """After a backup is put back: read everything kept in memory from storage again."""
        self._notice_read = False
        self.accounts._secret = None
        self.accounts._facts = {}
        self.accounts._admin = None


    # --- how many tables may be in play at once ---------------------------------------------------------
    def table_limit(self) -> int:
        if self._table_limit is None:
            saved = self.store.get("config", "cfg", "table_limit") or {}
            self._table_limit = int(saved.get("tables", TABLE_LIMIT))
        return self._table_limit

    def set_table_limit(self, tables) -> int:
        try:
            n = int(tables)
        except (TypeError, ValueError):
            raise ValueError("Please enter a number of tables") from None
        if not 1 <= n <= TABLE_LIMIT_MAX:
            raise ValueError(f"Please choose between 1 and {TABLE_LIMIT_MAX} tables")
        self.store.put("config", "cfg", "table_limit", {"tables": n, "at": time.time()})
        self._table_limit = n
        return n


def live(room) -> bool:
    """Someone has the table open on a phone or tablet."""
    return any(p.connections for p in [*room.players.values(), *room.watchers.values()])


def table_view(room, now: float | None = None) -> dict:
    """A table in play, for the Admin page."""
    now = now or time.time()
    seats = {}
    for seat in "NESW":
        p = room.players.get(seat)
        seats[seat] = ({"name": p.name, "here": bool(p.connections), "account": bool(p.user)} if p else None)
    return {"code": room.code, "created": room.created, "active": room.active, "board": room.board_no,
            "seats": seats, "watchers": len(room.watchers),
            "here": live(room),
            "solo": room.settings.solo}
