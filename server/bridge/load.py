"""Table load over time, for the Admin page's Load tab.

Every SAMPLE_EVERY seconds the server writes down how many tables were in use (the most at any moment since the last
sample), how many people had the app open at a table, and how long players waited on the server: a bot working out
its card (not counting the pause the app adds on purpose), a Hint they tapped, and the review's odds after a board
ends. Also how many people were turned away by the table limit, and the memory the whole container uses (everything the
server does, feedback included). Rows are kept KEEP_DAYS days, one storage partition per day (UTC). `machine()` says
which processor the server runs on and how much memory it has, for the top of the tab.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import logging
import os
import threading
import time

from .store import Store

SAMPLE_EVERY = 300
KEEP_DAYS = 30
log = logging.getLogger("bridge.load")


def _day(t: float) -> str:
    return dt.datetime.fromtimestamp(t, dt.timezone.utc).strftime("%Y-%m-%d")


def _summary(v: list[float]) -> dict | None:
    if not v:
        return None
    v = sorted(v)
    at = lambda p: round(v[min(len(v) - 1, int(p * len(v)))], 2)
    return {"n": len(v), "p50": at(.5), "p90": at(.9), "max": round(v[-1], 2)}


class Timings:
    """Waits measured since the last sample. Called from the game's worker threads, so it takes a lock."""

    def __init__(self):
        self._lock = threading.Lock()
        self.bot: list[float] = []
        self.hint: list[float] = []
        self.review: list[float] = []  # seconds from a board's end until its review had all its odds
        self.away = 0
        self.peak = 0

    def record(self, kind: str, seconds: float) -> None:
        with self._lock:
            getattr(self, kind).append(seconds)

    def turned_away(self) -> None:
        with self._lock:
            self.away += 1

    def tables(self, live: int) -> None:
        with self._lock:
            self.peak = max(self.peak, live)

    def take(self) -> tuple[list[float], list[float], list[float], int, int]:
        with self._lock:
            out = self.bot, self.hint, self.review, self.away, self.peak
            self.bot, self.hint, self.review, self.away, self.peak = [], [], [], 0, 0
        return out


timings = Timings()  # the game records into this one

MB = 1024 * 1024


def _read(path: str) -> str | None:
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return None


def memory() -> tuple[int | None, int | None]:
    """(MB in use, MB allowed) for the whole container: the server, its solver worker and anything else in it. From
    the container's own figures (cgroup v2, then v1), else this process alone; None where it can't be told."""
    used = _read("/sys/fs/cgroup/memory.current") or _read("/sys/fs/cgroup/memory/memory.usage_in_bytes")
    cap = _read("/sys/fs/cgroup/memory.max") or _read("/sys/fs/cgroup/memory/memory.limit_in_bytes")
    if used and used.isdigit():
        mb = int(used) // MB
    else:
        status = _read("/proc/self/status") or ""
        rss = next((line.split()[1] for line in status.splitlines() if line.startswith("VmRSS:")), None)
        mb = int(rss) // 1024 if rss and rss.isdigit() else None
    limit = int(cap) // MB if cap and cap.isdigit() and int(cap) < 1 << 50 else None  # "max" or huge: no limit set
    return mb, limit


def machine() -> dict:
    """The processor the server is running on now (Azure picks it, and it can change after a restart), the CPUs this
    container may use, and its memory."""
    info = _read("/proc/cpuinfo") or ""
    model = next((line.split(":", 1)[1].strip() for line in info.splitlines() if line.startswith("model name")), None)
    cpus: float | None = None
    quota = (_read("/sys/fs/cgroup/cpu.max") or "").split()
    if len(quota) == 2 and quota[0].isdigit():
        cpus = round(int(quota[0]) / int(quota[1]), 2)
    else:
        q, p = _read("/sys/fs/cgroup/cpu/cpu.cfs_quota_us"), _read("/sys/fs/cgroup/cpu/cpu.cfs_period_us")
        if q and p and q.lstrip("-").isdigit() and int(q) > 0:
            cpus = round(int(q) / int(p), 2)
    if cpus is None:
        cpus = len(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else os.cpu_count()
    used, limit = memory()
    return {"cpu": model, "cpus": cpus, "mem": used, "mem_limit": limit}


class Load:
    def __init__(self, store: Store, t: Timings = timings):
        self.store = store
        self.t = t
        self._kept: str | None = None  # the day old rows were last cleared

    def sample(self, live: int, people: int, now: float | None = None) -> dict:
        now = now or time.time()
        self.t.tables(live)
        bot, hint, review, away, peak = self.t.take()
        row = {"at": now, "tables": peak, "now": live, "people": people,
               "bot": _summary(bot), "hint": _summary(hint), "review": _summary(review), "away": away,
               "mem": memory()[0]}
        self.store.put("load", _day(now), f"{now:014.0f}", row)
        if self._kept != _day(now):
            self._kept = _day(now)
            for back in range(KEEP_DAYS, KEEP_DAYS + 7):  # a few days past the limit, in case the server was down
                old = _day(now - back * 86400)
                for key, _ in self.store.query("load", old):
                    self.store.delete("load", old, key)
        return row

    def rows(self, days: int = 7, now: float | None = None) -> list[dict]:
        now = now or time.time()
        out = []
        for back in range(min(days, KEEP_DAYS) - 1, -1, -1):
            out += [r for _, r in self.store.query("load", _day(now - back * 86400))]
        since = now - days * 86400
        return sorted((r for r in out if r["at"] >= since), key=lambda r: r["at"])

    async def run(self, counts) -> None:
        """Samples forever. `counts()` gives (tables in use, people at tables) right now."""
        while True:
            await asyncio.sleep(SAMPLE_EVERY)
            try:
                live, people = counts()
                await asyncio.to_thread(self.sample, live, people)
            except Exception:  # load figures are a bonus; never stop the server over them
                log.exception("couldn't record the load")
