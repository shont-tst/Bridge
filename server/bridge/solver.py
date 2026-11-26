"""The double-dummy solver (DDS, through endplay), run in a worker process of its own.

DDS is C code that isn't safe to run from two threads at once, and a crash inside it would take the whole server
down with every table on it. In a worker process, calls queue up there instead of behind one lock in the server, and
if the worker ever crashes it is started again and the call tried once more; the tables carry on.

BRIDGE_SOLVER_WORKERS sets how many workers run side by side (default: one per processor the container may use, since
each keeps one processor busy; each also holds DDS's memory), and
BRIDGE_DDS_THREADS how many threads DDS may use inside each. BRIDGE_SOLVER_IN_PROCESS=1 calls DDS directly instead,
for scripts that already run their own worker processes (scripts/calibrate.py).

Every table shares the workers, so calls wait in one queue, most urgent first (see `job`): a bot's card or a tapped
hint goes ahead of a hint worked out in case it's tapped, and that ahead of the end-of-board review. Big batches go in small pieces, so an
urgent call never waits long behind them, and a job nobody needs any more (the player has already played) stops at the
next piece.
"""
from __future__ import annotations

import logging
import multiprocessing
import os
import itertools
import queue
import threading
from concurrent.futures import Future, ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool

log = logging.getLogger("bridge.solver")
_pool: ProcessPoolExecutor | None = None
_lock = threading.Lock()

# how urgent a call is: lower goes first. Someone is waiting for a bot's card or a hint they tapped alike, so those
# take turns; a hint worked out in case it's tapped, and the review's odds, wait.
BOT = HINT = 0
WARM, REVIEW = 1, 2
CHUNK = 8  # deals sent to a worker at a time


class Cancelled(Exception):
    """The job was cancelled: nobody is waiting for its answer."""


class Job:
    """How urgent the solver calls made on this thread are, and whether they are still wanted. `priority` can be
    raised while the job runs (a hint being worked out ahead is tapped), and `cancel()` stops it at the next piece."""

    def __init__(self, priority: int):
        self.priority = priority
        self.cancelled = False

    def cancel(self) -> None:
        self.cancelled = True


_local = threading.local()


class job:
    """`with job(Job(BOT)): ...` runs the solver calls inside at that urgency (default REVIEW)."""

    def __init__(self, j: Job):
        self.j = j

    def __enter__(self) -> Job:
        self.prev = getattr(_local, "job", None)
        _local.job = self.j
        return self.j

    def __exit__(self, *exc) -> None:
        _local.job = self.prev


def _current() -> Job:
    return getattr(_local, "job", None) or Job(REVIEW)


_queue: queue.PriorityQueue = queue.PriorityQueue()
_seq = itertools.count()
_dispatchers: list[threading.Thread] = []


def _read(path: str) -> str | None:
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return None


def cpus() -> float:
    """The processors this container may use: its CPU quota (cgroup v2, then v1), else the cores it may run on."""
    quota = (_read("/sys/fs/cgroup/cpu.max") or "").split()
    if len(quota) == 2 and quota[0].isdigit():
        return round(int(quota[0]) / int(quota[1]), 2)
    q, p = _read("/sys/fs/cgroup/cpu/cpu.cfs_quota_us"), _read("/sys/fs/cgroup/cpu/cpu.cfs_period_us")
    if q and p and q.lstrip("-").isdigit() and int(q) > 0:
        return round(int(q) / int(p), 2)
    return len(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else (os.cpu_count() or 1)


def workers() -> int:
    """How many solver workers to run: BRIDGE_SOLVER_WORKERS if it's set, else one per whole processor (at least 1),
    so a bigger container uses its extra processors without another setting."""
    set_to = os.environ.get("BRIDGE_SOLVER_WORKERS", "").strip()
    if set_to.isdigit() and int(set_to) > 0:
        return int(set_to)
    return max(1, int(cpus()))


def _start_worker() -> None:
    if os.environ.get("BRIDGE_DDS_THREADS"):  # cap DDS threads (and memory) on small VMs
        from endplay._dds import SetMaxThreads
        SetMaxThreads(int(os.environ["BRIDGE_DDS_THREADS"]))


def _get_pool() -> ProcessPoolExecutor:
    global _pool
    with _lock:
        if _pool is None:
            _pool = ProcessPoolExecutor(max_workers=workers(),
                                        mp_context=multiprocessing.get_context("spawn"), initializer=_start_worker)
        return _pool


def _restart(broken: ProcessPoolExecutor) -> None:
    global _pool
    with _lock:
        if _pool is broken:
            _pool = None
    broken.shutdown(wait=False, cancel_futures=True)


def _dispatch() -> None:
    """One per worker: hands the most urgent waiting call to the pool, so the pool never holds a queue of its own."""
    while True:
        _, _, fn, args, fut = _queue.get()
        if not fut.set_running_or_notify_cancel():
            continue
        try:
            fut.set_result(_call(fn, *args))
        except BaseException as exc:
            fut.set_exception(exc)


def _start_dispatchers() -> None:
    with _lock:
        if not _dispatchers:
            for _ in range(workers()):
                t = threading.Thread(target=_dispatch, name="solver-dispatch", daemon=True)
                t.start()
                _dispatchers.append(t)


def _run(fn, *args):
    j = _current()
    if j.cancelled:
        raise Cancelled()
    if os.environ.get("BRIDGE_SOLVER_IN_PROCESS") == "1":
        return fn(*args)
    _start_dispatchers()
    fut: Future = Future()
    _queue.put((j.priority, next(_seq), fn, args, fut))
    return fut.result()


def _call(fn, *args):
    for attempt in (1, 2):
        pool = _get_pool()
        try:
            return pool.submit(fn, *args).result()
        except BrokenProcessPool:
            log.error("the solver worker stopped; starting it again (attempt %d)", attempt)
            _restart(pool)
            if attempt == 2:
                raise


# --- in the worker ---------------------------------------------------------------------------------
def _solve_all(deals: list) -> list:
    from endplay.dds import solve_all_boards
    return list(solve_all_boards(deals))


def _dd_table_and_par(deal, vul, dealer) -> tuple[list, int, list[str]]:
    from endplay.dds import calc_dd_table, par
    table = calc_dd_table(deal)
    p = par(table, vul, dealer)
    return table.to_list(), p.score, sorted({str(c) for c in p})


# --- what the game calls -----------------------------------------------------------------------------
def solve_all_boards(deals: list) -> list:
    """For each endplay Deal, the tricks each legal card of the player to move would take (endplay's SolvedBoard)."""
    deals = list(deals)
    out: list = []
    for i in range(0, len(deals), CHUNK):  # in pieces: see the top of this file
        out += _run(_solve_all, deals[i:i + CHUNK])
    return out


def dd_table_and_par(deal, vul, dealer) -> tuple[list, int, list[str]]:
    """(DD table as endplay's to_list(), par score for NS, par contracts) for a whole deal."""
    return _run(_dd_table_and_par, deal, vul, dealer)


def shutdown() -> None:
    global _pool
    with _lock:
        pool, _pool = _pool, None
    if pool:
        pool.shutdown(wait=False, cancel_futures=True)
