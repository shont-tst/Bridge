"""The table in the app itself, for playing with no internet (or none good enough).

The app's offline engine runs this module in the browser, in Pyodide (Python built for the browser), with the same
Room, bots, hints, claims and review the server uses. `LocalHost` stands in for the server's /ws/{code} handler
(app.play_ws): each phone at the table (this one, and a partner's joined over the boat's Wi-Fi) is a connection that
sends and receives the same JSON messages a WebSocket would.

Differences from the server:
- No accounts to check: the app says who is signed in, and finished boards are handed back to it (`boards`) to send
  to that account once the internet is back.
- The browser gives the game one thread, so the solver runs on it, in turn with the game (`InlineExecutor`). Work
  done ahead of time (the hint while the player thinks, the review's odds as the board goes) goes to a second copy
  of the engine, the helper (`HelperExecutor`), so it never holds up the game. Without a helper, nothing is worked
  out before it's asked for (`Room.ahead`).
- Each change hands the app a snapshot of the table (`Room.snapshot`), which it keeps on the phone, so the game
  survives the app being closed, and can go back to the server when it can be reached again.
"""
from __future__ import annotations

import asyncio
import copyreg
import itertools
import json
import os
import pickle
import time
from concurrent.futures import Future, ThreadPoolExecutor
from functools import lru_cache
from typing import Callable

from .bidding.conventions import make_engine
from .bidding.engine import BiddingEngine
from .game.odds import odds_ahead
from .game.room import Room, at, averages_ahead
from .game.table import card_hint
from .solver import Cancelled, Job

Post = Callable[[int, str], None]  # (connection, JSON text): connection 0 is the app itself


class InlineExecutor(ThreadPoolExecutor):
    """run_in_executor and to_thread without threads: the call runs at once, and its future is already done. (A
    ThreadPoolExecutor only because asyncio insists on one; it never starts a thread.)"""

    def submit(self, fn, /, *args, **kwargs):
        f: Future = Future()
        try:
            f.set_result(fn(*args, **kwargs))
        except BaseException as exc:
            f.set_exception(exc)
        return f


# The work the helper does: what the server does ahead of time at the solver's lower urgencies.
AHEAD = {card_hint, odds_ahead, averages_ahead}


@lru_cache(maxsize=8)
def _engine(enabled: frozenset) -> BiddingEngine:
    return make_engine(set(enabled))


# an engine goes to the helper as the conventions it plays, and is made (once) there
copyreg.pickle(BiddingEngine, lambda e: (_engine, (frozenset(e.enabled),)))


class HelperExecutor(InlineExecutor):
    """The game's own work runs at once, here; work done ahead of time goes to the helper, one job at a time, most
    urgent first (a hint the player tapped before odds for the review), dropping any nobody needs any more (a warm
    hint for a card already played). `send(job id, pickled call)` hands a job to the helper; `done` takes the answer.
    """

    def __init__(self, send: Callable[[int, bytes], None]):
        super().__init__(max_workers=1)
        self.send = send
        self.waiting: list[tuple[Job | None, int, bytes, Future]] = []
        self.busy: tuple[int, Future] | None = None
        self.ids = itertools.count(1)

    def submit(self, fn, /, *args, **kwargs):
        target = args[1] if fn is at and len(args) > 1 else fn
        if target not in AHEAD or kwargs:
            return super().submit(fn, *args, **kwargs)
        job = args[0] if fn is at and isinstance(args[0], Job) else None
        f: Future = Future()
        try:
            call = pickle.dumps((fn, args))
        except Exception:  # can't go to the helper: do it here
            return super().submit(fn, *args)
        self.waiting.append((job, next(self.ids), call, f))
        self._next()
        return f

    def _next(self) -> None:
        if self.busy:
            return
        for item in list(self.waiting):
            if item[0] is not None and item[0].cancelled:
                self.waiting.remove(item)
                item[3].set_exception(Cancelled())
        if not self.waiting:
            return
        item = min(self.waiting, key=lambda w: (w[0].priority if w[0] else 2, w[1]))
        self.waiting.remove(item)
        job, n, call, f = item
        self.busy = (n, f)
        self.send(n, call)

    def done(self, n: int, answer: bytes) -> None:
        """The helper's answer to job `n`: (True, result) or (False, the exception)."""
        if not self.busy or self.busy[0] != n:
            return
        f = self.busy[1]
        self.busy = None
        ok, value = pickle.loads(answer)
        if ok:
            f.set_result(value)
        else:
            f.set_exception(value)
        self._next()


def _bytes(b) -> bytes:
    """bytes, from a JavaScript Uint8Array too (in the browser)."""
    return b.to_bytes() if hasattr(b, "to_bytes") else bytes(b)


def helper_run(call: bytes) -> bytes:
    """In the helper: run one job, and give back its answer for HelperExecutor.done."""
    fn, args = pickle.loads(_bytes(call))
    try:
        return pickle.dumps((True, fn(*args)))
    except Exception as exc:
        try:
            return pickle.dumps((False, exc))
        except Exception:
            return pickle.dumps((False, RuntimeError(str(exc))))


class LocalHost:
    def __init__(self, post: Post, snapshot: dict | None = None, settings: dict | None = None,
                 code: str = "HOME", practice: str | None = None, helper: Callable[[int, bytes], None] | None = None):
        os.environ.setdefault("BRIDGE_DATA_DIR", "/tmp/bridge")
        self.executor = HelperExecutor(helper) if helper else InlineExecutor()
        asyncio.get_running_loop().set_default_executor(self.executor)
        self.post = post
        if snapshot:
            self.room = Room.restore(snapshot)
        else:
            self.room = Room(code)
            self.room.apply_remembered(settings or {})
            if practice:
                self.room.update_settings(practice=practice)
        self.room.ahead = helper is not None
        self.room.on_change = self._changed
        self.tokens: dict[int, str] = {}  # each connection's seat token, once joined
        self.senders: dict[int, Callable] = {}

    # --- what the app hears about -------------------------------------------------------------------
    def _changed(self, room: Room) -> None:
        """Every change: the table to keep, and finished boards (and ones Undo took back) for the account."""
        msg = {"type": "saved", "snap": room.snapshot()}
        if room.finished:
            msg["boards"] = [{"user": u, "rec": r} for u, r in room.finished]
            room.finished.clear()
        if room.retracted:
            msg["drop"] = [{"user": u, "rec": r} for u, r in room.retracted]
            room.retracted.clear()
        if room.chose:
            msg["chose"] = [c for _, c in room.chose]
            room.chose.clear()
        self.post(0, json.dumps(msg))

    def helper_done(self, n: int, answer: bytes) -> None:
        if isinstance(self.executor, HelperExecutor):
            self.executor.done(n, _bytes(answer))

    def snapshot(self) -> str:
        return json.dumps(self.room.snapshot())

    # --- one phone at the table ---------------------------------------------------------------------------
    def _sender(self, conn: int):
        async def send(msg: dict) -> None:
            self.post(conn, json.dumps(msg))
        return send

    async def receive(self, conn: int, text: str) -> None:
        """One message from a phone, as app.play_ws handles one from a WebSocket."""
        room = self.room
        send = self.senders.get(conn) or self.senders.setdefault(conn, self._sender(conn))
        try:
            msg = json.loads(text)
        except ValueError:
            return
        if not isinstance(msg, dict):
            return
        token = self.tokens.get(conn)
        if token is None:
            await self._join(conn, send, msg)
            return
        seat, me = room.person(token)
        if msg.get("type") == "ping":
            await send({"type": "pong", "rev": room.rev})
            return
        if msg.get("type") == "sync":
            if me:
                me.connections.add(send)
            await send(room.state_for(seat, me))
            return
        if me and msg.get("type") != "away":
            me.last = time.time()
        if msg.get("type") == "away":
            if me:
                me.away = True
                self._changed(room)
                await room.recheck_ready()
            return
        try:
            if msg.get("type") == "hint":
                if seat is None:
                    raise ValueError("take a seat to play")
                try:
                    await send(await room.hint(seat))
                except ValueError as exc:
                    await send({"type": "error", "message": str(exc)})
                return
            await room.handle(seat, msg, token)
        except ValueError as exc:
            await send({"type": "error", "message": str(exc)})

    async def _join(self, conn: int, send, hello: dict) -> None:
        room = self.room
        if hello.get("type") != "join":
            await send({"type": "error", "message": "first message must be join"})
            return
        user = hello.get("user") if isinstance(hello.get("user"), dict) else None
        name = str((user or {}).get("name") or hello.get("name") or "")[:24]
        try:
            seat, token = room.join(name, hello.get("token"), hello.get("seat"), (user or {}).get("id"))
        except ValueError as exc:
            await send({"type": "error", "message": str(exc), "fatal": True})
            return
        if hello.get("solo") and seat == "S" and len(room.players) == 1:
            room.update_settings(solo=True)
        if hello.get("watch") and seat is None:
            room.watch(token)
        self.tokens[conn] = token
        me = room.person(token)[1]
        me.away = False
        me.connections.add(send)
        room.back(me)
        await send({"type": "joined", "room": room.code, "seat": seat, "token": token})
        if room.table is None and room.can_start():
            room.new_board()
        await room.broadcast()
        room.kick_bots()

    async def close(self, conn: int) -> None:
        """A phone went away (the partner's left the Wi-Fi, or this app's table was closed)."""
        token = self.tokens.pop(conn, None)
        send = self.senders.pop(conn, None)
        p = self.room.person(token)[1] if token else None
        if p and send:
            p.connections.discard(send)
            p.last = time.time()
            if not p.connections and self.room.person(token)[0]:
                asyncio.create_task(self.room.broadcast_when_away())
            try:
                await self.room.recheck_ready()
            except Exception:
                pass
