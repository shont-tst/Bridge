"""Who is in the app right now, for friends lists, and invites to play.

Every signed-in phone keeps one "presence" socket open while the app is open. A friend shows as ready to play when
they have one open and aren't at a table, at a table when one of their phones is seated in a room, and otherwise
by when they were last here.
"""
from __future__ import annotations

import asyncio
import time
from typing import Awaitable, Callable

from .accounts import Accounts
from .push import Push

Sender = Callable[[dict], Awaitable[None]]


class Social:
    def __init__(self, accounts: Accounts, push: Push):
        self.accounts = accounts
        self.push = push
        self.sockets: dict[str, set[Sender]] = {}  # user id -> presence sockets
        self.seated: dict[str, dict[Sender, str]] = {}  # user id -> {room socket: room code}

    # --- presence ------------------------------------------------------------------------
    def status(self, user_id: str) -> dict:
        rooms = set(self.seated.get(user_id, {}).values())
        if rooms:
            return {"status": "table", "room": sorted(rooms)[0]}
        if self.sockets.get(user_id):
            return {"status": "ready"}
        return {"status": "away"}

    async def connect(self, user_id: str, send: Sender) -> None:
        was = self.status(user_id)["status"]
        self.sockets.setdefault(user_id, set()).add(send)
        if self.status(user_id)["status"] != was:
            await self.tell_friends(user_id)

    async def disconnect(self, user_id: str, send: Sender) -> None:
        was = self.status(user_id)["status"]
        self.sockets.get(user_id, set()).discard(send)
        if self.status(user_id)["status"] != was:
            await asyncio.to_thread(self._seen, user_id)
            await self.tell_friends(user_id)

    async def sit(self, user_id: str, send: Sender, room: str) -> None:
        was = self.status(user_id)
        self.seated.setdefault(user_id, {})[send] = room
        if self.status(user_id) != was:
            await self.tell_friends(user_id)

    async def stand(self, user_id: str, send: Sender) -> None:
        was = self.status(user_id)
        self.seated.get(user_id, {}).pop(send, None)
        if self.status(user_id) != was:
            await asyncio.to_thread(self._seen, user_id)
            await self.tell_friends(user_id)
            await self.refresh(user_id)  # back in the lobby: who you just played with moves up your own list

    def _seen(self, user_id: str) -> None:
        user = self.accounts.user(user_id)
        if user:
            self.accounts.touch(user)

    # --- friends lists ---------------------------------------------------------------------
    def friends_view(self, user_id: str) -> dict:
        """The friends list for one player: friends, requests to answer, requests waiting."""
        out = {"type": "friends", "friends": [], "incoming": [], "outgoing": []}
        played = self.accounts.last_played(user_id)
        for other_id, state in self.accounts.links(user_id).items():
            other = self.accounts.user(other_id)
            if not other:
                continue
            row = {"id": other_id, "name": other["name"]}
            if state == "friends":
                st = self.status(other_id)
                row.update(st, last_seen=other.get("last_seen"),
                           notify=bool(other.get("notify", True) and other.get("push")))
                out["friends"].append(row)
            else:
                out["incoming" if state == "in" else "outgoing"].append(row)
        for rows in out.values():  # requests: alphabetical, so one is always in the same place
            if isinstance(rows, list):
                rows.sort(key=lambda f: (f["name"].casefold(), f["id"]))
        # friends: whoever you last finished a board with first (partner or opponent), then the ones you've never
        # played with, alphabetically. Friends from the same board keep alphabetical order.
        out["friends"].sort(key=lambda f: -played.get(f["id"], 0))
        return out

    async def send_to(self, user_id: str, msg: dict) -> int:
        n = 0
        for send in list(self.sockets.get(user_id, ())):
            try:
                await send(msg)
                n += 1
            except Exception:
                self.sockets[user_id].discard(send)
        return n

    async def refresh(self, user_id: str) -> None:
        if self.sockets.get(user_id):
            await self.send_to(user_id, await asyncio.to_thread(self.friends_view, user_id))

    async def tell_friends(self, user_id: str) -> None:
        ids = await asyncio.to_thread(self.accounts.friend_ids, user_id)
        for other in ids:
            await self.refresh(other)

    # --- invites ----------------------------------------------------------------------------
    async def invite(self, user: dict, friend_id: str, room: str, origin: str) -> dict:
        """Ask a friend to join `room`: a banner if the app is open on one of their phones, otherwise a phone
        notification (when they have those turned on). Neither: the app offers a link to send them instead."""
        if friend_id not in await asyncio.to_thread(self.accounts.friend_ids, user["id"]):
            raise ValueError("You can only invite friends")
        msg = {"type": "invite", "from": user["name"], "from_id": user["id"], "room": room, "at": time.time()}
        shown = await self.send_to(friend_id, msg)
        pushed = 0
        if not shown:
            friend = await asyncio.to_thread(self.accounts.user, friend_id)
            if friend:
                pushed = await asyncio.to_thread(
                    self.push.send, friend, f"{user['name']} wants to play",
                    "Tap to join the table.", f"{origin}/?room={room}")
        return {"shown": bool(shown), "notified": bool(pushed)}

    async def answer_invite(self, user: dict, inviter_id: str, room: str, accept: bool) -> None:
        await self.send_to(inviter_id, {"type": "invite_answer", "from": user["name"], "room": room,
                                        "accepted": bool(accept)})
