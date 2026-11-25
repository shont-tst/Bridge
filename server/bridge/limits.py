"""Rate limits per visitor, so a script can't flood the server with rooms, sign-ins or sockets.

A visitor is their internet address. Behind Azure's front door every request arrives from the front door itself, so
the address is the last one in X-Forwarded-For, the one the front door adds. Earlier entries are ignored: a script can
write anything there.

Limits are counted in memory, which is right for this app since it runs as a single copy. BRIDGE_RATE_LIMITS=0
switches them off (the tests do, since every test client comes from the same address).
"""
from __future__ import annotations

import os
import re
import time
from collections import deque

# bucket: (requests allowed, per this many seconds)
LIMITS = {
    "new_room": (20, 3600),
    "room": (60, 60),  # looking a room up or joining it by code
    "auth": (20, 60),  # starting or finishing a passkey sign-in or sign-up, checking an invite
    "api": (300, 60),  # everything else under /api
    # AI apps connected to players' accounts (connector.py): every Claude user comes from Anthropic's few addresses,
    # so this is generous; each player also has their own hourly limit there
    "ai": (600, 60),
}
# wrong table codes from one address before it can't join any table for a while: with 4-letter codes, someone
# guessing could otherwise find a table in a few hours
MAX_MISSES = 10
MISS_WINDOW = 3600  # seconds: misses this old are forgotten, and the block lifts an hour after the last one
MAX_SOCKETS = 20  # open at once from one address
MAX_BODY = 256 * 1024  # bytes in one request: a passkey sign-up is a few KB, a suggestion at most 2,000 characters
_ROOM = re.compile(r"^/(api/rooms/[^/]+(/.*)?|ws/(?!presence$)[^/]+)$")


def bucket_for(method: str, path: str) -> str | None:
    if path == "/api/health":  # Azure's own checks
        return None
    if path in ("/api/rooms", "/api/puzzles/start") and method == "POST":
        return "new_room"
    if _ROOM.match(path):
        return "room"
    if path.startswith("/api/auth/") or path in ("/oauth/register", "/oauth/authorize"):
        return "auth"
    if path in ("/mcp", "/oauth/token") or path.startswith("/.well-known/"):
        return "ai"
    if path.startswith("/api/"):
        return "api"
    return None


def visitor(scope) -> str:
    """The visitor's internet address, for an ASGI scope (or a FastAPI Request's .scope)."""
    forwarded = [v for k, v in scope.get("headers") or () if k == b"x-forwarded-for"]
    last = forwarded[-1].decode("latin-1").split(",")[-1].strip() if forwarded else ""
    return _no_port(last) or (scope.get("client") or ("?",))[0]


def _no_port(addr: str) -> str:
    """Some proxies add the visitor's port ("203.0.113.9:51234", "[2001:db8::1]:51234"), which changes with every
    connection: without this each request would count as a new visitor."""
    if addr.startswith("["):
        return addr[1:].split("]", 1)[0]
    if addr.count(":") == 1:
        return addr.split(":", 1)[0]
    return addr


class Limiter:
    def __init__(self, enabled: bool | None = None):
        self.enabled = os.environ.get("BRIDGE_RATE_LIMITS", "1") != "0" if enabled is None else enabled
        self.hits: dict[tuple[str, str], list[float]] = {}
        self.sockets: dict[str, int] = {}
        self.refused: deque[tuple[float, str, str]] = deque(maxlen=2000)  # (when, who, bucket), for the Admin page
        self.blocked: dict[str, dict] = {}  # address -> {"at", "note"}: set on the Admin page, kept in storage
        self.misses: dict[str, list[float]] = {}  # address -> when it tried a table code that doesn't exist

    def allow(self, bucket: str, who: str, now: float | None = None) -> bool:
        if not self.enabled:
            return True
        now = now or time.time()
        limit, window = LIMITS[bucket]
        if len(self.hits) > 20_000:  # forget visitors who have gone quiet
            self.hits = {k: v for k, v in self.hits.items() if v and now - v[-1] < 3600}
        times = [t for t in self.hits.get((bucket, who), []) if now - t < window]
        if len(times) >= limit:
            self.hits[(bucket, who)] = times
            self.refused.append((now, who, bucket))
            return False
        self.hits[(bucket, who)] = times + [now]
        return True

    def missed_code(self, who: str, now: float | None = None) -> None:
        """`who` tried to join a table that doesn't exist (a wrong code, or one that has ended)."""
        if not self.enabled:
            return
        now = now or time.time()
        if len(self.misses) > 20_000:
            self.misses = {k: v for k, v in self.misses.items() if v and now - v[-1] < MISS_WINDOW}
        self.misses[who] = [t for t in self.misses.get(who, []) if now - t < MISS_WINDOW] + [now]

    def too_many_misses(self, who: str, now: float | None = None) -> bool:
        """Whether `who` has tried MAX_MISSES wrong table codes in the last hour: then it can't join any table, even
        with the right code, until an hour after its last wrong one. Shows on the Admin page as refused for "codes"."""
        if not self.enabled:
            return False
        now = now or time.time()
        recent = [t for t in self.misses.get(who, []) if now - t < MISS_WINDOW]
        if len(recent) < MAX_MISSES:
            return False
        self.refused.append((now, who, "codes"))
        return True

    def report(self, now: float | None = None) -> dict:
        """For the Admin page: who was refused in the last day, who is busiest in the last 10 minutes, open sockets."""
        now = now or time.time()
        refused: dict[str, dict] = {}
        for at, who, bucket in self.refused:
            if now - at < 24 * 3600:
                r = refused.setdefault(who, {"address": who, "count": 0, "last": at, "buckets": []})
                r["count"] += 1
                r["last"] = max(r["last"], at)
                if bucket not in r["buckets"]:
                    r["buckets"].append(bucket)
        busy: dict[str, int] = {}
        for (_bucket, who), times in self.hits.items():
            n = sum(1 for t in times if now - t < 600)
            if n:
                busy[who] = busy.get(who, 0) + n
        return {"enabled": self.enabled,
                "refused": sorted(refused.values(), key=lambda r: -r["count"])[:30],
                "busy": [{"address": a, "count": n} for a, n in sorted(busy.items(), key=lambda x: -x[1])[:10]],
                "sockets": sorted(({"address": a, "count": n} for a, n in self.sockets.items()),
                                  key=lambda x: -x["count"])[:10],
                "blocked": [{"address": a, **b} for a, b in sorted(self.blocked.items())]}

    def open_socket(self, who: str) -> bool:
        if not self.enabled:
            return True
        if self.sockets.get(who, 0) >= MAX_SOCKETS:
            return False
        self.sockets[who] = self.sockets.get(who, 0) + 1
        return True

    def close_socket(self, who: str) -> None:
        if who in self.sockets:
            self.sockets[who] -= 1
            if self.sockets[who] <= 0:
                del self.sockets[who]


class RateLimit:
    """ASGI middleware: refuses a request over its limit with 429, and a socket with close code 1008."""

    def __init__(self, app, limiter: Limiter):
        self.app = app
        self.limiter = limiter

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket"):
            return await self.app(scope, receive, send)
        who = visitor(scope)
        if who in self.limiter.blocked:  # blocked on the Admin page: nothing at all
            if scope["type"] == "http":
                await send({"type": "http.response.start", "status": 403,
                            "headers": [(b"content-type", b"application/json")]})
                await send({"type": "http.response.body", "body": b'{"detail":"Not allowed."}'})
            else:
                await send({"type": "websocket.close", "code": 1008})
            return
        bucket = bucket_for(scope.get("method", "GET"), scope["path"])
        ok = bucket is None or self.limiter.allow(bucket, who)
        if scope["type"] == "http":
            size = next((v for k, v in scope.get("headers") or () if k == b"content-length"), b"0")
            if not size.isdigit() or int(size) > MAX_BODY:
                await send({"type": "http.response.start", "status": 413,
                            "headers": [(b"content-type", b"application/json")]})
                await send({"type": "http.response.body", "body": b'{"detail":"That request is too large."}'})
                return
            if ok:
                return await self.app(scope, receive, send)
            await send({"type": "http.response.start", "status": 429,
                        "headers": [(b"content-type", b"application/json"), (b"retry-after", b"60")]})
            await send({"type": "http.response.body",
                        "body": b'{"detail":"Too many requests. Please wait a minute and try again."}'})
            return
        if not ok or not self.limiter.open_socket(who):
            await send({"type": "websocket.close", "code": 1008})
            return
        try:
            await self.app(scope, receive, send)
        finally:
            self.limiter.close_socket(who)
