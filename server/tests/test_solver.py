"""The solver runs in a worker process, and a crash there doesn't stop the server."""
import os
import signal
import threading
import time

import pytest

from endplay.types import Deal, Denom, Player

from bridge import solver
from bridge.core.cards import Hand
from bridge.game.analysis import dd_summary


def _deal():
    d = Deal.from_pbn("N:AKQJ.T98.765.432 T98.765.432.AKQJ 765.432.AKQJ.T98 432.AKQJ.T98.765")
    d.trump, d.first = Denom.spades, Player.west
    return d


def test_solves_in_the_worker():
    [solved] = solver.solve_all_boards([_deal()])
    assert {str(c): t for c, t in solved}  # tricks for each of West's cards
    assert solver.solve_all_boards([]) == []


def test_a_crashed_worker_is_started_again():
    solver.solve_all_boards([_deal()])
    for pid in list(solver._get_pool()._processes):
        os.kill(pid, signal.SIGKILL)  # as if DDS had crashed
    [solved] = solver.solve_all_boards([_deal()])
    assert len(list(solved)) > 0


def test_dd_summary_through_the_worker():
    hands = {s: Hand.from_pbn(h) for s, h in zip("NESW", ["AKQJ.T98.765.432", "T98.765.432.AKQJ",
                                                          "765.432.AKQJ.T98", "432.AKQJ.T98.765"])}
    out = dd_summary(hands, "None", "N")
    assert set(out["tricks"]) == set("SHDCN") and isinstance(out["par_score_ns"], int)


def test_urgent_calls_go_first(monkeypatch):
    """With the worker busy, a bot's card waiting behind a review goes ahead of it."""
    order, release = [], threading.Event()

    def fake_call(fn, *args):
        if args[0] == "first":
            release.wait(5)
        order.append(args[0])
        return args[0]

    monkeypatch.setattr(solver, "_call", fake_call)
    monkeypatch.delenv("BRIDGE_SOLVER_IN_PROCESS", raising=False)
    # one worker, so the others queue behind "first" (a machine with more processors starts more by default)
    monkeypatch.setattr(solver, "workers", lambda: 1)
    monkeypatch.setattr(solver, "_queue", type(solver._queue)())
    monkeypatch.setattr(solver, "_dispatchers", [])

    def at(priority, name):
        with solver.job(solver.Job(priority)):
            solver._run(None, name)

    threads = [threading.Thread(target=at, args=(solver.REVIEW, "first"))]
    threads[0].start()
    time.sleep(0.2)
    for p, name in ((solver.REVIEW, "review"), (solver.WARM, "warm"), (solver.BOT, "bot")):
        threads.append(threading.Thread(target=at, args=(p, name)))
        threads[-1].start()
        time.sleep(0.05)
    release.set()
    for t in threads:
        t.join(5)
    assert order == ["first", "bot", "warm", "review"]


def test_a_cancelled_job_stops_at_the_next_piece(monkeypatch):
    j = solver.Job(solver.WARM)
    calls = []

    def fake_call(fn, deals):
        calls.append(len(deals))
        j.cancel()  # the player played while the first piece was solving
        return [None] * len(deals)

    monkeypatch.setattr(solver, "_call", fake_call)
    monkeypatch.delenv("BRIDGE_SOLVER_IN_PROCESS", raising=False)
    with solver.job(j), pytest.raises(solver.Cancelled):
        solver.solve_all_boards([_deal()] * (solver.CHUNK * 3))
    assert calls == [solver.CHUNK]


def test_big_batches_go_in_pieces():
    out = solver.solve_all_boards([_deal()] * (solver.CHUNK + 1))
    assert len(out) == solver.CHUNK + 1
