"""Rooms: a 4-letter code up to four phones join (and more to watch); holds the table, settings and history."""
from __future__ import annotations

import asyncio
import copy
import json
import logging
import os
import random
import secrets
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable

from ..bidding.conventions import ALL_CONVENTIONS, BY_ID, make_engine, requirements
from ..bidding.lessons import LEADS, LESSONS, SIGNALS, lesson_title, practice_deal, signals_deal
from ..bots.signals import METHODS
from ..bidding.partscore import Score
from ..bidpath import MAX_AVERAGED, add_averages, add_outcomes, average_outcome
from ..core.board import is_vulnerable
from ..core.par import par as par_from_tricks
from ..core.scoring import duplicate_score
from ..bots.player import BotPlayer
from ..core.cards import SEATS, partner
from ..core.auction import Auction
from ..core.cards import Hand
from ..core.rubber import Line, Rubber
from ..load import timings
from ..solver import BOT, HINT, WARM, Job, job as solver_job
from ..tutorial import bidding_deal
from .analysis import dd_summary
from .odds import MAX_CARDS as MAX_ODDS_CARDS, add_odds, odds_ahead
from .second import add_split, second_table
from .replay import RETIRE, at_spot, build as build_replay, card_facts, check as check_replay, judge_call, judge_card
from .review import asked_marks, bidding_review, board_review, solve_undone, take_back_note, undone_review
from .table import BIDDING, DONE, PLAYING, Table, card_hint_first, card_hint_more

CODE_LETTERS = "BCDFGHJKLMNPQRSTVWXZ"  # no vowels: avoids accidental words
CODE_LENGTH = 4  # 160,000 codes; tables made between 1.19 and 1.72 have 6 and still work
SEAT_NAME = {"N": "North", "E": "East", "S": "South", "W": "West"}
BOT_DELAY = float(os.environ.get("BRIDGE_BOT_DELAY", "0.7"))
CLAIM_CARD = 0.5  # seconds between the cards of a claim played out on the table
CLAIM_TRICK = 1.0  # and the extra look at each finished trick (the app holds it as long: CLAIM_TRICK in TableView)
DEAL_PAUSE = 2.0  # the phones animate the deal before the first call
TRICK_PAUSES = (1.0, 2.0, 3.0, 4.0)  # how long a finished trick stays on the table

Sender = Callable[[dict], Awaitable[None]]
log = logging.getLogger("bridge.rooms")

def at(j: Job | int, fn: Callable, *args):
    """Runs fn(*args) with its double-dummy solver calls at this urgency: every table shares the solver, so a bot's
    card goes ahead of a hint worked out in case it's tapped (bridge/solver.py)."""
    with solver_job(j if isinstance(j, Job) else Job(j)):
        return fn(*args)


def data_dir() -> Path:
    d = Path(os.environ.get("BRIDGE_DATA_DIR", Path(__file__).resolve().parents[2] / "data"))
    d.mkdir(parents=True, exist_ok=True)
    return d


@dataclass
class Player:
    name: str
    token: str
    connections: set = field(default_factory=set)  # set of sender callables
    user: str | None = None  # the signed-in player's account, so their boards are saved
    since: int = 0  # the first board this player sat for from the start (only those are saved to their account)
    watching: bool = False  # not seated: chose to watch (sees all four hands) rather than still picking a seat
    pending: str | None = None  # a watcher's seat, taken at the next board
    seen: int = 0  # the board this person last saw hands of without sitting it out, so they can't sit it again
    device: str | None = None  # the phone or tablet that plays this seat when they have the app open on more than one
    device_name: str = ""  # what to call it, e.g. "iPad", on the others
    last: float = 0  # when they last had the table open, so another phone can go straight back to it
    away: bool = False  # tapped Leave: opening the app elsewhere shows the lobby, not this table
    covered: bool = False  # gone, and the others chose to play on: a bot plays this seat until they're back
    done: list = field(default_factory=list)  # the ids of their last few calls and cards, so a resent one counts once


# Table settings a new table takes from the ones its maker last chose (their account's, or their phone's).
# Practice and solo belong to one table, so they start fresh.
REMEMBERED = ("difficulty", "conventions", "hints", "undo", "ai_coach", "trick_pause", "scoring", "signals", "leads")


@dataclass
class Settings:
    difficulty: int = 6
    conventions: set[str] = field(
        default_factory=lambda: {c.id for c in ALL_CONVENTIONS if c.default_on})
    solo: bool = False  # a bot sits North (partner) when only one human plays
    hints: bool = True  # players may ask for a suggested call or card
    ai_coach: bool = True  # a player's own AI assistant may see their seat during a board (connector.py)
    practice: str | None = None  # deal boards where this convention comes up
    trick_pause: float = 2.0  # seconds a finished trick stays in the middle before bots lead again
    undo: bool = True  # players may take back calls and cards, back to the start of the board
    scoring: str = "rubber"  # or "duplicate"
    tutorial: int | None = None  # a Learn to play table (step 6 or 7): its boards stay out of My stats
    signals: str = "off"  # defensive signals the bots give and read: "off", "standard" or "upside" (bots/signals.py)
    leads: bool = True  # the bots lead, and read the opening lead, by Standard leads (bots/leads.py)
    # a deal played again (game/replay.py): the spec, and for Your mistakes the puzzles' order ("queue", "pos"),
    # whose they are ("user"), the answer to the one on the table ("answer"), whether the player is trying it again
    # after a wrong answer ("retry": judged but not saved) and whether the player chose to play on from it
    # ("playing_on"). Its boards stay out of My stats.
    replay: dict | None = None
    # A new table starts with the settings its maker last chose (REMEMBERED), or these defaults the first time.

    def to_dict(self) -> dict:
        return {"difficulty": self.difficulty, "conventions": sorted(self.conventions),
                "solo": self.solo, "hints": self.hints, "ai_coach": self.ai_coach, "practice": self.practice,
                "practice_title": lesson_title(self.practice) if self.practice else None,
                "trick_pause": self.trick_pause, "undo": self.undo, "scoring": self.scoring, "tutorial": self.tutorial,
                "signals": self.signals, "leads": self.leads, "replay": self.replay_shown()}

    def replay_shown(self) -> dict | None:
        """What the app needs to know about a replay: never the deal itself, which the table shows as it should."""
        r = self.replay
        if not r:
            return None
        out = {"board": r["board"], "puzzles": "queue" in r}
        if "queue" in r:
            p = r.get("puzzle") or {}
            out.update(n=r["pos"] + 1, of=len(r["queue"]), key=p.get("key"), kind=p.get("kind"),
                       trick=p["index"] // 4 + 1 if p.get("kind") == "card" else None,
                       answer=r.get("answer"), playing_on=bool(r.get("playing_on")))
        return out

    @property
    def method(self) -> str | None:
        """The signals method the bots use, or None when the table plays none."""
        return None if self.signals == "off" else self.signals


def averages_ahead(engine, hands: dict[str, Hand], dealer: str, calls: list[str], people: set[str], score,
                   vulnerability: str, below: dict | None, rng: random.Random) -> dict:
    """The averages the review will show for people's calls off the system (bidpath.add_averages), worked out while
    the hand is played: {(index, system call): average}. Up to as many calls as the review averages."""
    out = {}
    for b in bidding_review(engine, dealer, calls, hands, people, score, vulnerability)[:MAX_AVERAGED]:
        out[(b["index"], b["system_call"])] = average_outcome(engine, hands, dealer, calls, b["index"],
                                                             b["system_call"], vulnerability, score, below, rng)
    return out


class Room:
    # Your mistakes: (user id, puzzle id) -> that puzzle's replay spec, or None. The server sets it (app.py, puzzles.py);
    # the phone has no puzzles.
    puzzle_loader: Callable[[str, str], dict | None] | None = None
    # Work out the card hint as soon as it's a person's turn, and the review's odds as the board goes. The app's
    # offline engine turns this off (bridge/local.py): in a browser the solver can't run beside the game, so work
    # nobody has asked for yet would hold up the player's next card.
    ahead = True

    def __init__(self, code: str, seed: int | None = None):
        self.code = code
        self.created = time.time()
        self.active = self.created  # the last change, for the Admin page
        self.players: dict[str, Player] = {}  # seated people, by seat; the bots play every other seat
        self.watchers: dict[str, Player] = {}  # everyone else at the table, by token: picking a seat or watching
        self.settings = Settings()
        self.rng = random.Random(seed)
        self.board_no = 0
        self.table: Table | None = None
        self.history: list[dict] = []
        self.rubber = Rubber()
        self._rubber_before: Rubber | None = None  # the rubber before the last board was scored, for undo
        self.lock = asyncio.Lock()
        self._bot_task: asyncio.Task | None = None
        self._odds_task: asyncio.Task | None = None
        # the review's odds for each card, worked out as the board goes (odds.odds_ahead), by board, table and the
        # cards played up to and including it, so a card taken back with Undo and played again is worked out again
        self._ahead: dict[tuple, dict] = {}
        self._ahead_task: asyncio.Task | None = None
        # card hints by decision, so a second tap reuses the first: (the first answer, the answer firmed up on a close
        # call, or the same answer when it isn't close)
        self._hints: dict[tuple, tuple[asyncio.Future, asyncio.Future]] = {}
        self._hint_jobs: dict[tuple, Job] = {}  # their solver jobs, to hurry one when tapped or stop it once played
        self.help: dict[str, dict[str, int]] = {}  # hints, undos and AI coach questions each seat used on this board
        # for an AI coach (coach.py), on this board: [seat, decision (the number of actions before it), "hints" or
        # "coach"] for each time someone asked before a call or card, and each call or card a person took back with
        # undo, with the position it was made in (see Room.undo)
        self.asked: list[list] = []
        self.undone: list[dict] = []
        self.ready: set[str] = set()  # seats that tapped Next board: the next deal waits for every person at the table
        # Skip hand with a person as partner: the seat that asked to throw this hand in, waiting on the partner's yes,
        # and the seat whose partner said no (told so until they do something else)
        self.skip_ask: str | None = None
        self.skip_no: str | None = None
        self._last_counted: dict[str, tuple] = {}  # the last decision each kind of help was counted for
        self.finished: list[tuple[str, dict]] = []  # boards to save to players' accounts: (user id, record)
        self._to_save: list[tuple[str, dict]] = []  # the last board's records, to save again once its odds are in
        self._second_save: list[tuple[str, dict]] = []  # ... and again once its second table is in
        self.retracted: list[tuple[str, dict]] = []  # saved boards taken back by undo, to remove again
        self.rev = 0  # goes up with every change, so a saved copy can tell whether it is the latest
        self.on_change: Callable[["Room"], None] | None = None
        self.chose: list[tuple[str, dict]] = []  # (user id, settings): a signed-in player's choices, to remember
        # (user id, puzzle id, right, or None when removed): Your mistakes answers to save
        self.puzzle_marks: list[tuple[str, str, bool | None]] = []
        self._puzzle_facts: tuple[str, asyncio.Future] | None = None  # what judging the card puzzle needs (replay.py)
        self._rebuild_engine()

    # --- configuration --------------------------------------------------------------
    def _rebuild_engine(self) -> None:
        self.engine = make_engine(self.settings.conventions)
        self.bot = BotPlayer(self.engine, self.settings.difficulty, seed=self.rng.random())

    def bot_seats(self) -> set[str]:
        return set(SEATS) - {s for s, p in self.players.items() if not p.covered}

    AWAY = 180  # closed the app this long ago: the others are asked whether to play on with a bot

    def gone(self) -> dict[str, dict]:
        """People at the table who tapped Leave, or closed the app 3 minutes ago or more: the
        others choose to play on with a bot in that seat or to wait. `since` tells one time they left from the next."""
        now = time.time()
        out = {}
        for s, p in self.players.items():
            if p.away or (not p.connections and now - p.last >= self.AWAY):
                out[s] = {"name": p.name, "left": p.away, "since": round(p.last), "bot": p.covered}
        return out

    def cover(self, seat: str | None, target: str) -> None:
        """Someone still at the table chose to play on: a bot plays `target` until its person is back."""
        if seat is None or seat not in self.players or seat in self.gone():
            raise ValueError("take a seat to play")
        if target not in self.gone():
            raise ValueError("they're back")
        p = self.players[target]
        p.covered = True
        if self._mid_board():
            self.table.bot_seats.add(target)

    def back(self, p: "Player") -> None:
        """A person a bot was playing for came back: they play their seat again from here."""
        if not p.covered:
            return
        p.covered = False
        seat = next((s for s, q in self.players.items() if q is p), None)
        if seat and self._mid_board():
            self.table.bot_seats.discard(seat)

    async def broadcast_when_away(self) -> None:
        """Someone just closed the app: once they've been gone long enough, tell the others."""
        await asyncio.sleep(self.AWAY + 1)
        if self.gone():
            await self.broadcast()

    def update_settings(self, difficulty: int | None = None, conventions: list[str] | None = None,
                        solo: bool | None = None, hints: bool | None = None,
                        practice: str | None | bool = False, trick_pause: float | None = None,
                        undo: bool | None = None, scoring: str | None = None,
                        ai_coach: bool | None = None, signals: str | None = None, leads: bool | None = None) -> None:
        """`practice`: a convention id, None (or "") to stop, False to leave unchanged."""
        if difficulty is not None:
            self.settings.difficulty = max(1, min(10, int(difficulty)))
        if conventions is not None:
            self.settings.conventions = set(conventions)
            conv = LESSONS[self.settings.practice].conv if self.settings.practice in LESSONS else None
            if practice is False and conv and conv not in self.settings.conventions:
                self.settings.practice = None  # switching a convention off ends its practice
        if solo is not None:
            self.settings.solo = bool(solo)
        if hints is not None:
            self.settings.hints = bool(hints)
        if trick_pause is not None:
            if float(trick_pause) not in TRICK_PAUSES:
                raise ValueError(f"trick pause must be one of {TRICK_PAUSES}")
            self.settings.trick_pause = float(trick_pause)
        if undo is not None:
            self.settings.undo = bool(undo)
        if ai_coach is not None:
            self.settings.ai_coach = bool(ai_coach)
        if scoring is not None and scoring != self.settings.scoring:
            if scoring not in ("duplicate", "rubber"):
                raise ValueError("scoring must be duplicate or rubber")
            self.settings.scoring = scoring
            self.rubber = Rubber()  # switching starts a fresh rubber at the next board
        if signals is not None:
            if signals not in ("off", *METHODS):
                raise ValueError("signals must be off, standard or upside")
            self.settings.signals = signals
            if signals == "off" and practice is False and self.settings.practice == SIGNALS:
                self.settings.practice = None  # switching signals off ends their practice
        if leads is not None:
            self.settings.leads = bool(leads)
            if not leads and practice is False and self.settings.practice == LEADS:
                self.settings.practice = None  # switching leads off ends their practice
        if practice is not False:
            if practice and practice not in LESSONS and practice not in (SIGNALS, LEADS):
                raise ValueError(f"no practice deals for {practice!r}")
            self.settings.practice = practice or None
        if self.settings.practice == SIGNALS:
            if self.settings.signals == "off":  # practicing signals switches them on
                self.settings.signals = "standard"
        elif self.settings.practice == LEADS:
            self.settings.leads = True  # practicing leads switches them on
        elif self.settings.practice and LESSONS[self.settings.practice].conv:  # practicing a convention switches it on
            self.settings.conventions |= requirements(self.settings.practice)
        self._rebuild_engine()
        if self.table:
            self.table.engine = self.engine
            self.table.bot = self.bot
            self.table.signals = self.settings.method
            self.table.leads = self.settings.leads
            self.table.bot_seats = self.bot_seats()

    def start_tutorial(self, step: int) -> None:
        """Learn to play steps 6 (bidding) and 7 (scoring): a table of one with bots at level 2, hints and undo on,
        the cheat sheet's defaults, and rubber scoring for step 7."""
        if step not in (6, 7):
            raise ValueError("Learn to play has a table only for steps 6 and 7")
        self.update_settings(difficulty=2, conventions=[c.id for c in ALL_CONVENTIONS if c.default_on], solo=True,
                             hints=True, practice=None, undo=True, ai_coach=False,
                             scoring="rubber" if step == 7 else "duplicate", signals="off")
        self.settings.tutorial = step

    def apply_remembered(self, chosen: dict) -> None:
        """Start with the settings a player last chose at a table (REMEMBERED), skipping any that are no longer valid."""
        for k, v in (chosen or {}).items():
            if k not in REMEMBERED or v is None:
                continue
            if k == "conventions":
                v = [c for c in v if c in BY_ID] if isinstance(v, list) else None
            try:
                self.update_settings(**{k: v})
            except (ValueError, TypeError):
                pass

    # --- seating -------------------------------------------------------------------------
    def person(self, token: str | None) -> tuple[str | None, Player | None]:
        """(seat, player) for a token: seat None for someone watching or picking a seat."""
        for s, p in self.players.items():
            if p.token == token:
                return s, p
        return None, self.watchers.get(token or "")

    def join(self, name: str, token: str | None = None, seat: str | None = None,
             user: str | None = None) -> tuple[str | None, str]:
        """Returns (seat, token); seat None to pick one (or watch). Reconnecting with a token, or signed in to the
        same account from any of your phones, puts you back where you were. A new table's first two people sit
        South and North; anyone after that picks a seat."""
        for s, p in [*self.players.items(), *((None, w) for w in self.watchers.values())]:
            if (token and p.token == token) or (user and p.user == user):
                p.name = name or p.name
                p.user = user or p.user
                p.last, p.away = time.time(), False
                self.back(p)
                return s, p.token
        p = Player(name or "Guest", secrets.token_urlsafe(16), user=user, last=time.time())
        self.watchers[p.token] = p
        if seat is None and len(self.players) < 2 and not self.settings.solo:
            seat = next((s for s in ("S", "N") if self._free(s)), None)
        if seat is None and not self.players:
            seat = self.settings.replay["seat"] if self.settings.replay else "S"  # a replay: the seat played then
        if seat is not None:
            try:
                self.sit(p.token, seat)
            except ValueError:
                pass
        return self.person(p.token)[0], p.token

    def hold(self, token: str, device: str | None, device_name: str, takeover: bool) -> str | None:
        """Which of a player's phones plays for them when the app is open on more than one. Opening the app (or
        tapping Continue here) moves the game to that phone; a phone that only reconnects, say after sleeping, doesn't
        take it back. Returns the name of the phone that has the game, when it isn't this one."""
        p = self.person(token)[1]
        if not device or not p:  # an app from before 1.36 doesn't say which phone it is
            return None
        if takeover or not p.device or p.device == device:
            p.device, p.device_name = device, device_name
            return None
        return p.device_name or "another device"

    def _free(self, seat: str, other_than: Player | None = None) -> bool:
        return seat not in self.players and not any(
            w.pending == seat for w in self.watchers.values() if w is not other_than)

    def _mid_board(self) -> bool:
        return self.table is not None and self.table.phase != DONE

    def _mid_game(self, seat: str) -> bool:
        """In the middle of a rubber (or, with duplicate scoring, of a board this seat has bid or played on), so the
        lobby offers the way back for longer. A fresh deal the bots opened on doesn't count."""
        if self.settings.scoring == "rubber" and self.rubber.lines:
            return True
        return self._mid_board() and any(a[0] == seat for a in self.table.actions)

    def sit(self, token: str, seat: str) -> None:
        """Take `seat` from the bot (or an empty seat). Someone who has already seen this board's hands, by watching
        it or sitting elsewhere, takes the seat at the next board instead."""
        if seat not in SEATS:
            raise ValueError("no such seat")
        now, p = self.person(token)
        if p is None:
            raise ValueError("join the table first")
        if now == seat:
            return
        if not self._free(seat, p):
            taken = self.players.get(seat) or next(w for w in self.watchers.values() if w.pending == seat)
            raise ValueError(f"{taken.name} has {SEAT_NAME[seat]}")
        t = self.table
        if now is not None:
            if self._mid_board():
                raise ValueError("change seats when this board ends")
            del self.players[now]
        elif self._mid_board() and (p.watching or p.seen == t.board):
            p.pending, p.watching = seat, True
            return
        else:
            del self.watchers[p.token]
        p.pending, p.watching = None, False
        self.players[seat] = p
        if t and t.phase != DONE:
            t.bot_seats.discard(seat)  # the bot stops; the person plays this seat from here
            p.since = t.board if not t.actions else t.board + 1
        else:
            p.since = self.board_no + 1

    def stand(self, token: str) -> None:
        """Leave your seat (the bot takes over), or stop waiting for one, and go back to picking."""
        seat, p = self.person(token)
        if p is None:
            return
        if seat is None:
            p.pending, p.watching = None, False
            return
        del self.players[seat]
        self.watchers[p.token] = p
        p.watching, p.pending = False, None
        if self._mid_board():
            p.seen = self.table.board
            self.table.bot_seats.add(seat)

    def watch(self, token: str) -> None:
        seat, p = self.person(token)
        if p is None:
            return
        if seat is not None:
            self.stand(token)
        p.watching = True
        if self.table:
            p.seen = self.table.board

    def can_start(self) -> bool:
        """A table for two waits for the second person; with a bot partner, one is enough."""
        return len(self.players) >= (1 if self.settings.solo else 2)

    def _both_sides(self) -> bool:
        """People on both sides: then nobody may take back a call or card (it might be an opponent's)."""
        humans = set(SEATS) - (self.table.bot_seats if self.table else self.bot_seats())
        return bool(humans & {"N", "S"}) and bool(humans & {"E", "W"})

    # --- boards --------------------------------------------------------------------------
    def holding_up(self) -> list[str]:
        """Seats of people at the table who haven't tapped Next board yet. Someone who has left the table (closed the
        app, or tapped Leave) doesn't hold up the others."""
        return [s for s, p in self.players.items() if s not in self.ready and p.connections and not p.away]

    async def _deal_if_ready(self) -> None:
        """Deal the next board once someone has asked for it and nobody at the table is still looking at this one."""
        if self.ready and (not self.table or self.table.phase == DONE) and self.can_start() and not self.holding_up():
            # a practice deal can take a moment to find: keep the event loop free
            await asyncio.get_running_loop().run_in_executor(None, self.new_board)

    async def recheck_ready(self) -> None:
        """Someone left or closed the app: the people still here may have all asked for the next board."""
        async with self.lock:
            await self._deal_if_ready()
        await self.broadcast()
        self.kick_bots()

    def _can_redeal(self) -> bool:
        """Whether the board in progress can be thrown in for a practice deal: someone playing alone (as with Skip
        hand), or nobody has called or played on it yet."""
        t = self.table
        if not t or t.phase == DONE:
            return False
        return len(self.players) == 1 or not t.can_undo()

    def skip_partner(self, seat: str | None) -> str | None | bool:
        """Who must agree before `seat` throws this hand in with Skip hand: None when nobody need (playing alone, or
        a bot plays for their partner who is away), the partner's seat when the two partners are the only people at
        the table, and False when it isn't offered (people on the other side, or a deal played again)."""
        if seat is None or seat not in self.players or self.settings.replay:
            return False
        others = set(self.players) - {seat}
        if not others:
            return None
        if others != {partner(seat)}:
            return False
        return None if self.players[partner(seat)].covered else partner(seat)

    def _skip_asked(self) -> str | None:
        """The seat whose ask to skip this hand is still open: the hand is still being played, and the two partners
        are still the only people at the table."""
        s = self.skip_ask
        if s is None or not self.table or self.table.phase == DONE or self.skip_partner(s) != partner(s):
            return None
        return s

    def new_board(self) -> None:
        self.board_no += 1
        self.help = {}
        self.skip_ask = self.skip_no = None
        self.asked, self.undone = [], []
        self.ready = set()
        for p in list(self.watchers.values()):  # watchers waiting for a seat sit down now
            if p.pending and p.pending not in self.players:
                del self.watchers[p.token]
                self.players[p.pending] = p
                p.since, p.pending, p.watching = self.board_no, None, False
            if p.watching:
                p.seen = self.board_no
        if self.settings.replay:  # the same deal again, from where the player chose (game/replay.py)
            self.table = build_replay(self.settings.replay, self.engine, self.bot_seats(), self.bot, self.rng,
                                      self.settings.method, self.settings.leads)
            return
        hands = dealer = None
        if self.settings.tutorial == 6:
            hands, dealer = bidding_deal(self.engine, self.board_no, self.rng)
        elif self.settings.practice in (SIGNALS, LEADS):
            self._deal_defense_practice("EW" if self.settings.practice == SIGNALS else "E")
            return
        elif self.settings.practice:
            hands, dealer = practice_deal(self.engine, self.settings.practice, self.rng)
        rubber = self.settings.scoring == "rubber"
        vul = self.rubber.vulnerability() if rubber else None
        score = Score.from_rubber(self.rubber.below, vul) if rubber else None
        self.table = Table(self.engine, self.board_no, self.bot_seats(), self.bot, rng=self.rng,
                           hands=hands, dealer=dealer, vulnerability=vul, score=score, signals=self.settings.method,
                           leads=self.settings.leads)

    def _deal_defense_practice(self, declarers: str, tries: int = 20) -> None:
        """Signals and opening leads practice start at the play, with South defending: the system bids all four
        hands, South's too, on a deal where East or West (`declarers`) declares, and those calls can't be undone. For
        opening leads East declares, so South leads."""
        rubber = self.settings.scoring == "rubber"
        vul = self.rubber.vulnerability() if rubber else None
        for _ in range(tries):
            hands, dealer = signals_deal(self.engine, self.rng, declarers=declarers)
            score = Score.from_rubber(self.rubber.below, vul) if rubber else None
            t = Table(self.engine, self.board_no, self.bot_seats(), self.bot, rng=self.rng, hands=hands,
                      dealer=dealer, vulnerability=vul, score=score, signals=self.settings.method,
                      leads=self.settings.leads)
            while t.phase == BIDDING:  # the same calls the bots would make (the rubber score included)
                seat = t.auction.next_to_call
                t.make_call(seat, self.bot.bid(t.hands[seat], t.auction, t.score).call)
            if t.contract and t.contract.declarer in declarers:
                break
        t.fixed = len(t.actions)
        self.table = t

    def record_result(self) -> None:
        t = self.table
        if not t or t.phase != DONE or not t.result or t.result.dd is not None:
            return
        try:
            t.result.dd = dd_summary(t.hands, t.vulnerability, t.dealer)
        except Exception as exc:  # analysis is a bonus; never break the game over it
            t.result.dd = {"error": str(exc)}
        try:
            t.result.review = board_review(
                self.engine, t.hands, t.dealer, list(t.auction.calls), t.contract,
                t.play.played_cards() if t.play else [], set(SEATS) - t.bot_seats, t.score, t.vulnerability)
        except Exception as exc:
            t.result.review = {"error": str(exc)}
        # at rubber, each side's part score when the board was dealt: it decides what a contract is worth (a 2♥ that
        # finishes the game is a game), for par and the coach's comparisons (stats.py, bidpath.py)
        below = dict(self.rubber.below) if self.settings.scoring == "rubber" else None
        if below is not None and t.result.dd and t.result.dd.get("tricks"):
            try:  # the end-of-board panel shows par on the same scoring (core/par.py)
                rp = par_from_tricks(t.result.dd["tricks"], t.vulnerability, below)
                c = t.contract
                mine = 0
                if c:
                    side = "NS" if c.declarer in "NS" else "EW"
                    mine = duplicate_score(c, t.result.declarer_tricks, is_vulnerable(t.vulnerability, c.declarer),
                                           below[side]) * (1 if side == "NS" else -1)
                t.result.dd["rubber"] = {"par_score_ns": rp["score_ns"], "par_contracts": rp["contracts"],
                                         "below": below, "score_ns": mine}
            except Exception as exc:
                log.warning("could not work out rubber par: %s", exc)
        try:  # what each call off the system gained or lost against the system's call (bidpath.py)
            add_outcomes({"review": t.result.review, "dd": t.result.dd, "hands": t.result.hands, "dealer": t.dealer,
                          "calls": list(t.auction.calls), "vulnerability": t.vulnerability, "below_before": below},
                         self.engine, t.score)
        except Exception as exc:
            log.warning("could not work out bidding outcomes: %s", exc)
        rv = t.result.review or {}
        if rv.get("play") or any(b.get("outcome") for b in rv.get("bidding") or []):
            t.result.review["odds_pending"] = True  # filled in just after the result is shown
        if self._second_seats(t) and isinstance(t.result.review, dict) and "error" not in t.result.review:
            t.result.review["second_pending"] = True  # the second table plays once the odds are in (game/second.py)
        if self.settings.scoring == "rubber":
            self._rubber_before = copy.deepcopy(self.rubber)
            t.result.score_ns = self.rubber.record(t.board, t.contract, t.result.declarer_tricks, t.hands)
        t.result.asked = asked_marks(t.actions, self.asked)  # the review marks them "After a hint" (#153)
        rec = {"room": self.code, "players": {s: p.name for s, p in self.players.items()}, "below_before": below,
               "undone": undone_review(self.engine, t, self.undone),
               "difficulty": self.settings.difficulty, "practice": self.settings.practice,
               "scoring": self.settings.scoring, "bots": sorted(t.bot_seats),
               "conventions": sorted(self.settings.conventions), "help": copy.deepcopy(self.help),
               "tutorial": self.settings.tutorial, "signals": self.settings.method,
               "leads": self.settings.leads, **t.result.to_dict()}
        self.history.append(rec)
        # the other signed-in people who played this board, for the order of the friends list
        humans = {p.user for seat, p in self.players.items() if p.user and seat not in t.bot_seats}
        with_ = {u: sorted(humans - {u}) for u in humans}
        # Learn to play's hands, and deals played again, don't go into My stats
        self._to_save = [] if self.settings.tutorial or self.settings.replay else [
            (p.user, {**rec, "seat": seat, "with": with_[p.user]}) for seat, p in self.players.items()
            if p.user and seat not in t.bot_seats and p.since <= t.board]
        self.finished.extend(self._to_save)
        try:
            with open(data_dir() / "history.jsonl", "a") as f:
                f.write(json.dumps(rec) + "\n")
        except OSError:
            pass

    def totals(self) -> dict:
        ns = sum(r["score_ns"] for r in self.history)
        return {"boards": len(self.history), "score_ns": ns}

    # --- messaging -----------------------------------------------------------------------
    def state_for(self, seat: str | None, person: Player | None = None) -> dict:
        watching = seat is None and person is not None and person.watching
        table = self.table.state_for(seat, all_hands=watching) if self.table else None
        if table and self._both_sides():
            table["can_undo"] = False
        r = self.settings.replay
        if table and r:
            # a deal played again starts part way through: the cards before it, for Tricks so far
            table["played"] = [list(x) for x in self.table.play.played_cards()] if self.table.play else []
            if self._puzzle_open():
                table["can_claim"] = False  # the puzzle asks for one card
            if r.get("answer") and not r.get("playing_on"):  # answered: nothing more to play until they choose
                table.update(your_turn=False, legal_cards=[], legal_calls=[], call_meanings={}, can_claim=False)
        return {
            "type": "state",
            "room": self.code,
            "rev": self.rev,  # the phone checks this against the pong, to notice an update it missed
            "you": seat,
            "watching": watching,
            "choosing": seat is None and not watching,
            "pending": person.pending if person and seat is None else None,
            "players": {s: p.name for s, p in self.players.items()},
            "gone": self.gone(),
            "connected": {s: bool(p.connections) for s, p in self.players.items()},
            "waiting": {w.pending: w.name for w in self.watchers.values() if w.pending},
            "watchers": sorted(w.name for w in self.watchers.values() if w.connections and w.watching),
            "bots": sorted(self.table.bot_seats if self._mid_board() else self.bot_seats()),
            "settings": self.settings.to_dict(),
            "waiting_for_partner": not self.can_start(),
            # after Next board: who the next deal is waiting for
            "next_ready": seat in self.ready,
            "next_waiting": [self.players[s].name for s in self.holding_up()] if self.ready else [],
            "can_skip": self.skip_partner(seat) is not False,
            # Skip hand with a person as partner: who asked (the partner answers), and the partner who said no
            "skip_ask": (lambda s: {"by": s, "name": self.players[s].name} if s else None)(self._skip_asked()),
            "skip_no": self.players[partner(seat)].name if seat and self.skip_no == seat
            and partner(seat) in self.players else None,
            "tutorial_call": self._tutorial_call(seat),
            "table": table,
            "totals": self.totals(),
            "rubber": self.rubber.to_dict() if self.settings.scoring == "rubber" else None,
            "signed_in": sorted(s for s, p in self.players.items() if p.user),
            "help": self.help.get(seat, {}) if seat else {},
            "history": [
                {"board": r["board"], "contract": r["contract"], "tricks": r["declarer_tricks"],
                 "score_ns": r["score_ns"],
                 "par_ns": (r.get("dd") or {}).get("par_score_ns")}
                for r in self.history[-20:]
            ],
        }

    def _tutorial_call(self, seat: str | None) -> str | None:
        """Learn to play step 6: the cheat sheet's call for the player whose turn it is, so the app can check theirs."""
        t = self.table
        if self.settings.tutorial != 6 or not t or t.phase != BIDDING or seat is None or t.auction.next_to_call != seat:
            return None
        try:
            return self.engine.choose(t.hands[seat], t.auction).call
        except Exception:
            return None

    async def broadcast(self) -> None:
        self.rev += 1
        self.active = time.time()
        if self.on_change:
            self.on_change(self)
        people = [*self.players.items(), *((None, w) for w in self.watchers.values())]
        carry = None
        for seat, p in people:
            for send in list(p.connections):
                try:
                    await send(self.state_for(seat, p))
                    # the app keeps the table, so it can carry on with no internet (bridge/local.py)
                    if getattr(send, "carry", False) and self.carriable():
                        carry = carry or {"type": "carry", "snap": self.snapshot()}
                        await send(carry)
                except Exception:
                    # Close it too: a socket left open but no longer sent to still answers pings and takes taps,
                    # so the phone shows an old trick and never knows to connect again.
                    log.warning("table %s: an update to %s failed; closing that connection", self.code,
                                seat or "a watcher", exc_info=True)
                    p.connections.discard(send)
                    close = getattr(send, "close", None)
                    if close:
                        asyncio.create_task(close())

    def carriable(self) -> bool:
        """One person playing with the bots: the app can carry this table on by itself when the server can't be
        reached (bridge/local.py). With other people at the table it can't: one phone mustn't hold their cards."""
        return len(self.players) == 1 and not self.watchers and not self.settings.replay  # replays stay here

    async def handle(self, seat: str | None, msg: dict[str, Any], token: str | None = None) -> None:
        """Apply one client message from `seat` (None: someone watching or picking a seat)."""
        kind = msg.get("type")
        async with self.lock:
            if seat is not None and seat == self.skip_no and kind not in ("ping", "skip", "skip_answer"):
                self.skip_no = None
            if kind in ("sit", "stand", "watch"):
                if kind == "sit":
                    self.sit(token, str(msg.get("seat", "")))
                elif kind == "stand":
                    self.stand(token)
                else:
                    self.watch(token)
                if self.table is None and self.can_start():
                    self.new_board()
                await self._deal_if_ready()
            elif seat is None and kind != "ping":  # someone watching can't change the table's settings
                raise ValueError("take a seat to play")
            elif kind in ("call", "play") and not self._fresh(seat, msg):
                return  # sent again after a dropped connection, and already made: nothing to do
            elif kind in ("call", "play") and self._puzzle_open():
                await self._answer(seat, kind, msg)  # Your mistakes: judged, not played
                self._made(seat, msg)
            elif kind == "puzzle_retry":  # after a wrong answer: the same spot again, for practice (not saved)
                r = self._require_replay()
                if not (r.get("answer") and not r["answer"].get("right") and "queue" in r) or r.get("playing_on"):
                    raise ValueError("there's nothing to try again")
                r["answer"], r["retry"] = None, True
            elif kind == "puzzle_remove":  # after a wrong answer: "Don't show this again" (they disagree it was a mistake)
                r = self._require_replay()
                a = r.get("answer")
                if not (a and not a.get("right") and "queue" in r) or r.get("playing_on"):
                    raise ValueError("only after a wrong answer")
                if not r.get("removed"):
                    a["removed"] = r["removed"] = True
                    if r.get("user"):
                        self.puzzle_marks.append((r["user"], r["puzzle"]["id"], None))
            elif kind == "play_on":  # after answering: carry on from the puzzle's spot
                r = self._require_replay()
                r["answer"], r["playing_on"] = None, True
            elif kind == "replay":  # play this deal again, from the start or (`from`) after that many calls and cards
                await asyncio.get_running_loop().run_in_executor(None, self._replay_from, msg.get("from"))
            elif kind == "puzzle_next" or (kind == "next_board" and self.settings.replay):
                if (self.settings.replay or {}).get("queue") is not None:
                    await asyncio.get_running_loop().run_in_executor(None, self._next_puzzle)
                else:  # a deal played again: Next plays it again from the start
                    await asyncio.get_running_loop().run_in_executor(None, self._replay_from, 0)
            elif kind == "call":
                self._require_table().make_call(seat, str(msg.get("call", "")))
                self._made(seat, msg)
            elif kind == "play":
                self._require_table().play_card(seat, str(msg.get("card", "")))
                self._made(seat, msg)
            elif kind == "claim":
                if self._puzzle_open():
                    raise ValueError("Answer first: pick your card.")
                await asyncio.get_running_loop().run_in_executor(None, self._require_table().claim, seat)
            elif kind == "bot_for":  # someone left: play on with a bot in their seat
                self.cover(seat, str(msg.get("seat", "")))
            elif kind == "undo":
                self.undo()
                self.ready = set()
                self._count(seat, "undos")
            elif kind == "skip":
                # throw this hand in, unscored, and deal the next: at once when playing alone, or once a person
                # playing as partner agrees (Skip hand from both, or Skip hand on the partner's ask)
                ask = self.skip_partner(seat)
                if ask is False:
                    raise ValueError("skipping a hand is only when your partner is the only other person playing")
                if not self.table or self.table.phase == DONE:
                    raise ValueError("no hand in progress to skip")
                self.skip_no = None
                if ask is None or self._skip_asked() == ask:
                    await asyncio.get_running_loop().run_in_executor(None, self.new_board)
                else:
                    self.skip_ask = seat
            elif kind == "skip_answer":  # the partner's answer to an ask to skip, or the asker taking it back
                asker = self._skip_asked()
                if asker is None:
                    if self.skip_no == seat:
                        self.skip_no = None  # seen that the partner said no
                elif seat == asker:
                    self.skip_ask = None
                elif msg.get("agree"):
                    await asyncio.get_running_loop().run_in_executor(None, self.new_board)
                else:
                    self.skip_ask, self.skip_no = None, asker
            elif kind == "next_board":
                if self.table and self.table.phase != DONE:
                    raise ValueError("finish this board first")
                if not self.can_start():
                    raise ValueError("waiting for your partner to join")
                self.ready.add(seat)  # everyone at the table gets to finish looking at this board first
                await self._deal_if_ready()
            elif kind == "settings":
                practice = self.settings.practice
                self.update_settings(msg.get("difficulty"), msg.get("conventions"),
                                     msg.get("solo"), msg.get("hints"),
                                     msg.get("practice", False), msg.get("trick_pause"),
                                     msg.get("undo"), msg.get("scoring"), msg.get("ai_coach"), msg.get("signals"),
                                     msg.get("leads"))
                user = self.players[seat].user if seat in self.players else None
                now = self.settings.to_dict()
                chosen = {k: now[k] for k in REMEMBERED if msg.get(k) is not None}
                if user and chosen:
                    self.chose.append((user, chosen))
                if self.settings.practice and self.settings.practice != practice and self._can_redeal():
                    # practice starts now, not after a hand that isn't practice
                    await asyncio.get_running_loop().run_in_executor(None, self.new_board)
            elif kind == "ping":
                return
            else:
                raise ValueError(f"unknown message type {kind!r}")
            if self.table and self.table.phase == DONE:
                await asyncio.get_running_loop().run_in_executor(None, at, HINT, self.record_result)
        await self.broadcast()
        self.kick_bots()
        self.kick_hint()
        self.kick_odds_ahead()
        self.kick_odds()

    def undo(self) -> None:
        """Take back the last call or card a person made on this board (and the bots' after it).
        Undoing from the finished board also takes its score back out."""
        if not self.settings.undo:
            raise ValueError("undo is switched off for this table")
        if self._both_sides():
            raise ValueError("undo is off when people play on both sides")
        t = self._require_table()
        was_done = t.phase == DONE
        taken = take_back_note(t, self.asked)
        t.undo()
        if taken:
            self.undone.append(taken)
        self._to_save, self._second_save = [], []
        # help asked for later decisions goes; help for the decision being made again stays (they saw it)
        self.asked = [a for a in self.asked if a[1] <= len(t.actions)]
        if was_done and self.history and self.history[-1]["board"] == t.board:
            gone = self.history.pop()
            for user in {p.user for p in self.players.values() if p.user and p.since <= t.board}:
                rec = {**gone, "seat": None}
                waiting = [f for f in self.finished if f[0] == user and f[1].get("finished_at") == gone.get("finished_at")]
                if waiting:
                    self.finished = [f for f in self.finished if f not in waiting]
                else:
                    self.retracted.append((user, rec))
            if self._rubber_before is not None:
                self.rubber = self._rubber_before
                self._rubber_before = None

    async def hint(self, seat: str, later: Callable[[dict], Awaitable] | None = None) -> dict:
        """A suggestion for `seat` only; nothing is broadcast and the board doesn't change.

        Only the quick part holds the room lock: a card hint is worked out from a copy of what the player can see,
        so the player can still play (and the bots keep going) while it is thinking. Asking again for the same
        decision waits for, or reuses, the first answer instead of starting another.

        On a close call the first answer comes at once, marked `firming`, and the answer over more layouts goes to
        `later` (marked `firmer`) when it's in, unless the decision is made first. Without `later` the answer waits
        for the firmer one."""
        if not self.settings.hints:
            raise ValueError("hints are switched off for this table")
        if self._puzzle_open():
            raise ValueError("Hints come after you answer.")
        self._count(seat, "hints")
        async with self.lock:
            t = self._require_table()
            ready = self._card_hint(t, seat)
            j = self._hint_jobs.get(self._hint_key(t, seat))
            if j:
                j.priority = min(j.priority, HINT)  # asked for now: ahead of other tables' warm-ups
        if isinstance(ready, dict):
            return ready
        first, final = ready
        if final.done() or later is None:
            return await asyncio.shield(final)
        hint = await asyncio.shield(first)
        if hint.get("firming"):
            asyncio.create_task(self._send_firmer(final, later))
        return hint

    @staticmethod
    async def _send_firmer(final: asyncio.Future, later: Callable[[dict], Awaitable]) -> None:
        try:
            await later({**await asyncio.shield(final), "firmer": True})
        except Exception:  # stopped once the card was played, or the phone has gone: nobody to tell
            pass

    def coach_view(self, seat: str) -> dict:
        """What a player's own AI assistant sees of the board in progress: exactly what `seat` sees, only at tables
        that allow AI coaching. Asking while it's their turn counts as AI coach help for the review."""
        if not self.settings.ai_coach:
            raise ValueError("AI coaching during play is off at this table")
        t = self._require_table()
        if t.phase == DONE:
            raise ValueError("no board in progress")
        if t.controller_to_act() == seat:
            self._count(seat, "coach")
        return self.state_for(seat, self.players.get(seat))

    def _card_hint(self, table: Table, seat: str) -> dict | tuple[asyncio.Future, asyncio.Future]:
        """A bidding hint outright, or the card hint for this decision, (first answer, firmed-up answer): the one
        already being worked out, or a new one. Call with the room lock held."""
        key = self._hint_key(table, seat)
        work = self._hints.get(key)
        if work is None:
            ready = table.hint_start(seat)
            if isinstance(ready, dict):
                return ready
            self._drop_stale_hints()
            j = self._hint_jobs[key] = Job(WARM)
            loop = asyncio.get_running_loop()
            work = self._hints[key] = (loop.create_future(), loop.create_future())
            for f in work:
                f.add_done_callback(lambda f: f.cancelled() or f.exception())  # a warm-up nobody asked for may fail quietly
            # each part gets its own layouts: on a phone each runs in the helper, from a copy of its random numbers
            rngs = random.Random(self.rng.random()), random.Random(self.rng.random())
            asyncio.create_task(self._work_hint(j, ready, table.engine, rngs, f"{table.board}/{len(table.actions)}",
                                                *work))
        return work

    @staticmethod
    async def _work_hint(j: Job, view, engine, rngs: tuple, decision: str, first: asyncio.Future,
                         final: asyncio.Future) -> None:
        """The first answer from HINT_SAMPLES layouts, then, on a close call, HINT_MORE more (table.card_hint)."""
        loop = asyncio.get_running_loop()
        try:
            hint, close = await loop.run_in_executor(None, at, j, card_hint_first, view, engine, rngs[0])
            hint["decision"] = decision  # the app keeps a hint it was told to hide hidden when it's firmed up
            first.set_result(hint)
            if close is not None:
                hint = await loop.run_in_executor(None, at, j, card_hint_more, view, engine, close, rngs[1])
                hint["decision"] = decision
            final.set_result(hint)
        except Exception as exc:  # stopped once the decision was made (solver.Cancelled), or failed
            for f in (first, final):
                if not f.done():
                    f.set_exception(exc)

    @staticmethod
    def _hint_key(table: Table, seat: str) -> tuple:
        return (table.board, id(table), len(table.actions), seat)

    def _drop_stale_hints(self) -> None:
        """Stop working out hints for decisions already made, tapped or not: the app drops a hint that comes after the
        card or call anyway, and a tapped one shares the solver with the bots at top urgency, so letting it run on
        would only hold up the bots' next cards."""
        t = self.table
        now = (t.board, id(t), len(t.actions)) if t else None
        for key in [k for k in self._hints if k[:3] != now]:
            self._hints.pop(key)
            j = self._hint_jobs.pop(key, None)
            if j:
                j.cancel()

    def kick_hint(self) -> None:
        """Start the card hint as soon as it's a person's turn to play, so Hint answers at once when tapped.
        It isn't counted as a hint until they ask for it. At a card puzzle, start on what judging the answer needs."""
        self._puzzle_ahead()
        self._drop_stale_hints()
        t = self.table
        if self.ahead and self.settings.hints and t and t.phase == PLAYING and t.controller_to_act() in self.players \
                and not t.is_bot_turn():
            asyncio.create_task(self._warm_hint())

    async def _warm_hint(self) -> None:
        async with self.lock:
            t = self.table
            seat = t.controller_to_act() if t and t.phase == PLAYING else None
            if seat in self.players and not t.is_bot_turn():
                try:
                    self._card_hint(t, seat)
                except ValueError:
                    pass

    def _count(self, seat: str, what: str) -> None:
        """Hints, undos and AI coach questions are counted in the review; asking twice for the same decision (a hint,
        or the AI coach) counts once."""
        t = self.table
        if what in ("hints", "coach") and t is not None:
            key = (seat, t.board, len(t.actions))
            if key == self._last_counted.get(what):
                return
            self._last_counted[what] = key
        self.help.setdefault(seat, {})
        self.help[seat][what] = self.help[seat].get(what, 0) + 1
        if what in ("hints", "coach") and t is not None and [seat, len(t.actions), what] not in self.asked:
            self.asked.append([seat, len(t.actions), what])

    def _board_for_report(self, board: int) -> tuple[Table, list]:
        """The board a player's feedback is about, and the cards played on it so far: the one on the table, or one
        from this table's history once it has moved on (rebuilt from its record)."""
        t = self.table
        if t and t.board == board:
            return t, [list(x) for x in t.play.played_cards()] if t.play else []
        rec = next((r for r in reversed(self.history) if r["board"] == board), None)
        if rec is None:
            raise ValueError("that board is no longer at this table")
        t = Table(self.engine, board, set(rec.get("bots") or []), self.bot,
                  hands={s: Hand.from_pbn(h) for s, h in rec["hands"].items()},
                  dealer=rec["dealer"], vulnerability=rec["vulnerability"])
        for c in rec["calls"]:
            t.auction.add(c)
        t.phase = DONE
        return t, [list(x) for x in rec.get("play") or []]

    def board_report(self, board: int) -> dict:
        """Everything the owner needs to follow a player's note about a board: the deal, the auction, the cards
        played so far and the table's settings."""
        t, played = self._board_for_report(board)
        return {"room": self.code, "board": board, "dealer": t.dealer, "vulnerability": t.vulnerability,
                "hands": {s: t.hands[s].to_pbn() for s in SEATS}, "calls": list(t.auction.calls),
                "play": played, "phase": t.phase,
                "bots": sorted(t.bot_seats), "conventions": sorted(self.settings.conventions),
                "difficulty": self.settings.difficulty, **self._result_report(board)}

    def _result_report(self, board: int) -> dict:
        """Once the board is over, feedback sent under the review also carries the result and what the review
        flagged: the calls that weren't the system's and the cards that cost a trick."""
        t = self.table
        r = t.result.to_dict() if t and t.board == board and t.result else \
            next((x for x in reversed(self.history) if x["board"] == board), None)
        if not r:
            return {}
        review = r.get("review") or {}
        cards = [{k: c.get(k) for k in ("trick", "seat", "by", "card", "lost", "best", "odds", "back")}
                 for c in ((review.get("play") or {}).get("cards") or []) if c.get("lost")]
        calls = [{k: c.get(k) for k in ("index", "seat", "call", "system_call", "minor")} for c in review.get("bidding") or []]
        return {"result": {"contract": r.get("contract"), "declarer_tricks": r.get("declarer_tricks"),
                           "score_ns": r.get("score_ns"), "claimed": r.get("claimed")},
                "review": {"calls": calls, "cards": cards}}

    def card_report(self, board: int, card: str) -> dict:
        """A board report about one card a bot played: also the card, who played it and how the bot picked it."""
        rep = self.board_report(board)
        who = next((s for s, c in rep["play"] if c == card), None)
        if who is None:
            raise ValueError("that card hasn't been played")
        t = self.table if self.table and self.table.board == board else None
        return {**rep, "card": card, "seat": who, "how": t.card_why.get(card) if t else None}

    def bid_report(self, board: int, index: int) -> dict:
        """A board report about one call a player thinks was wrong: also the call and the rule behind it."""
        t = self._board_for_report(board)[0]
        if not 0 <= index < len(t.auction.calls):
            raise ValueError("no such call")
        seat = Auction(t.dealer, t.auction.calls[:index]).next_to_call
        why = t._work_out_why(index, True)
        return {**self.board_report(board), "index": index, "seat": seat, "call": t.auction.calls[index],
                "bot": seat in t.bot_seats, "meaning": t.engine.explain(t.auction, index).text,
                "rule": why["rule"], "convention": why["convention"]}

    def _fresh(self, seat: str, msg: dict[str, Any]) -> bool:
        """On a poor connection the app keeps sending a call or card until the table answers, so the same one can
        arrive twice: its id says whether it was made already. `at` is the table as the app saw it when the player
        tapped (board and step): if the table has moved on since (Undo, a claim, a bot covering the seat), the
        call or card was meant for a moment that's gone, and making it now could play it at the wrong trick."""
        mid = msg.get("id")
        p = self.players.get(seat)
        if mid and p and mid in p.done:
            return False
        at, t = msg.get("at"), self.table
        if at and t and at != f"{t.board}/{len(t.actions)}":
            raise ValueError(f"The table moved on before your {'card' if msg.get('type') == 'play' else 'call'} "
                             "got through.")
        return True

    def _made(self, seat: str, msg: dict[str, Any]) -> None:
        p, mid = self.players.get(seat), msg.get("id")
        if p and mid:
            p.done = [*p.done[-19:], str(mid)[:40]]

    def _require_table(self) -> Table:
        if not self.table:
            raise ValueError("no board in progress")
        return self.table

    # --- deals played again, and Your mistakes (game/replay.py) ----------------------------------------------------
    def start_replay(self, spec: dict, queue: list[str] | None = None, pos: int = 0, user: str | None = None) -> None:
        """Play a deal again with bots in the other seats, from the spec's starting point, at the table's settings
        then (its conventions, the bots' level, signals and leads; the part scores bid as they were). `queue` makes it
        Your mistakes: the puzzle ids in order, this one at `pos`, all `user`'s. Raises ValueError for a bad spec."""
        spec = check_replay(spec)
        conv = spec.get("conventions")
        level = spec.get("difficulty")
        self.update_settings(difficulty=level if isinstance(level, int) else None,
                             conventions=[c for c in conv if c in BY_ID] if isinstance(conv, list) else None,
                             signals=spec.get("signals") if spec.get("signals") in METHODS else "off",
                             leads=spec["leads"] if isinstance(spec.get("leads"), bool) else None,
                             solo=True, practice=None, scoring="duplicate")
        self.settings.tutorial = None
        replay = {**spec, "answer": None, "playing_on": False}
        if queue is not None:
            replay.update(queue=list(queue), pos=pos, user=user)
        build_replay(replay, self.engine, self.bot_seats(), self.bot, random.Random(0), None, True)  # it can be played
        self.settings.replay = replay
        self._puzzle_facts = None
        if self.players:
            self.new_board()

    def _require_replay(self) -> dict:
        if not self.settings.replay:
            raise ValueError("this table isn't playing a deal again")
        return self.settings.replay

    def _replay_from(self, start) -> None:
        """Play the deal again from the start, or after `start` calls and cards: those of the board just finished
        when it is over (Play on from here under its review), or else the ones the replay began with."""
        r = self._require_replay()
        t = self.table
        if t and t.phase == DONE and t.result:
            r["calls"], r["play"] = list(t.result.calls), [list(x) for x in t.result.play]
        r["from"] = max(0, min(int(start or 0), len(r["calls"]) + len(r["play"])))
        r["answer"] = None
        r["playing_on"] = True  # a puzzle played again is no longer a puzzle
        self.new_board()

    def _next_puzzle(self) -> None:
        """Your mistakes: on to the next puzzle in the queue (one whose board can't be read is passed over)."""
        r = self._require_replay()
        queue, user = r.get("queue"), r.get("user")
        if queue is None or not self.puzzle_loader:
            raise ValueError("no more puzzles here")
        pos = r["pos"] + 1
        while pos < len(queue):
            spec = self.puzzle_loader(user, queue[pos])
            if spec:
                self.start_replay(spec, queue, pos, user)
                return
            pos += 1
        raise ValueError("That was the last one.")

    def _puzzle_open(self) -> bool:
        """At a puzzle's spot, before the answer."""
        r = self.settings.replay
        return bool(r and r.get("puzzle") and "queue" in r and not r.get("answer") and not r.get("playing_on")
                    and self.table and at_spot(self.table, r))

    def _puzzle_ahead(self) -> None:
        """At a card puzzle, work out what judging any card there needs while the player thinks (replay.card_facts):
        each card's odds, and the tricks it takes as the cards lay."""
        r = self.settings.replay
        if not self._puzzle_open() or r["puzzle"]["kind"] != "card":
            return
        pid = r["puzzle"]["id"]
        if self._puzzle_facts and self._puzzle_facts[0] == pid:
            return
        future = asyncio.get_running_loop().run_in_executor(None, at, HINT, card_facts, self.engine, dict(r),
                                                            random.Random(self.rng.random()))
        future.add_done_callback(lambda f: f.cancelled() or f.exception())
        self._puzzle_facts = (pid, future)

    async def _answer(self, seat: str, kind: str, msg: dict[str, Any]) -> None:
        """Judge the player's call or card at a puzzle's spot. Nothing is played: the answer goes on the table's state
        for the app to show, and to the player's puzzles to save (Rooms.save_puzzle)."""
        t, r = self.table, self.settings.replay
        if seat != t.controller_to_act():
            raise ValueError("it isn't your turn")
        p = r["puzzle"]
        if kind == "play":
            card = str(msg.get("card", ""))
            if card not in t.play.legal_cards():
                raise ValueError("that card can't be played now")
            self._puzzle_ahead()
            if not self._puzzle_facts:
                raise ValueError("this puzzle needs a card")
            facts = await asyncio.shield(self._puzzle_facts[1])
            answer = judge_card(r, facts, card)
        else:
            answer = judge_call(self.engine, r, str(msg.get("call", "")))
        if r.get("retry"):  # Try again after a wrong answer: shown, but the first answer is the one that counts
            answer.update(right_count=p.get("right", 0), retired=False, retry=True, removed=bool(r.get("removed")))
            r["answer"] = answer
            return
        right = p.get("right", 0) + (1 if answer["right"] else 0)
        answer.update(right_count=right, retired=right >= RETIRE)
        r["answer"] = answer
        if r.get("user"):
            self.puzzle_marks.append((r["user"], p["id"], answer["right"]))

    # --- bots ----------------------------------------------------------------------------
    def kick_bots(self) -> None:
        if self._bot_task is None or self._bot_task.done():
            self._bot_task = asyncio.create_task(self._run_bots())

    async def _run_bots(self) -> None:
        loop = asyncio.get_running_loop()
        while self.table and self.table.is_bot_turn():
            await asyncio.sleep(self._wait())
            async with self.lock:
                if not (self.table and self.table.is_bot_turn()):
                    break
                card = self.table.phase == PLAYING
                started = time.monotonic()
                await loop.run_in_executor(None, at, BOT, self.table.bot_step)
                if card:  # for the Admin page's Load tab: how long players waited on the bot's thinking
                    timings.record("bot", time.monotonic() - started)
                if self.table.phase == DONE:
                    await loop.run_in_executor(None, at, HINT, self.record_result)
            await self.broadcast()
            self.kick_odds_ahead()
        self.kick_hint()
        self.kick_odds()


    # --- review odds -----------------------------------------------------------------
    def kick_odds(self) -> None:
        t = self.table
        review = t.result.review if t and t.phase == DONE and t.result else None
        if review and (review.get("odds_pending") or review.get("second_pending")) and (self._odds_task is None or self._odds_task.done()):
            self._odds_task = asyncio.create_task(self._fill_odds(t, review))

    def kick_odds_ahead(self) -> None:
        """Work out the review's odds for the cards played so far while the board goes on, at the solver's lowest
        urgency, so they're ready when it ends instead of being started then. Bots and hints still go first."""
        t = self.table
        if self.ahead and t and t.play and t.contract and (self._ahead_task is None or self._ahead_task.done()):
            self._ahead_task = asyncio.create_task(self._odds_ahead(t))

    def _ahead_key(self, t: Table, play: list, i: int) -> tuple:
        return (t.board, id(t), tuple(map(tuple, play[:i + 1])))

    def _below(self) -> dict | None:
        """At rubber, each side's part score when the board was dealt (as record_result keeps it)."""
        return dict(self.rubber.below) if self.settings.scoring == "rubber" else None

    async def _odds_ahead(self, t: Table) -> None:
        loop = asyncio.get_running_loop()
        for key in [k for k in self._ahead if k[:2] != (t.board, id(t))]:  # earlier boards' are no longer needed
            self._ahead.pop(key)
        # first the bidding: each call a person made off the system, averaged over deals like this one (bidpath.py),
        # as soon as the auction is over, since it doesn't depend on the play
        async with self.lock:
            if self.table is not t or not t.play:
                return
            # once the board is over the rubber has moved on, and the review works the averages out itself
            playing = t.phase == PLAYING
            calls, below = list(t.auction.calls), self._below()
        key = (t.board, id(t), "bids", tuple(calls), json.dumps(below, sort_keys=True))
        if playing and key not in self._ahead:
            try:
                self._ahead[key] = await loop.run_in_executor(None, averages_ahead, self.engine, t.hands, t.dealer,
                                                              calls, set(SEATS) - t.bot_seats, t.score,
                                                              t.vulnerability, below,
                                                              random.Random(self.rng.random()))
            except Exception as exc:
                log.warning("could not average bidding outcomes during the board: %s", exc)
                self._ahead[key] = {}
        while True:
            async with self.lock:  # a bot may be playing its card in another thread
                if self.table is not t or not t.play:
                    return
                play = [tuple(x) for x in t.play.played_cards()]
            i = next((i for i in range(len(play)) if self._ahead_key(t, play, i) not in self._ahead), None)
            if i is None:
                return
            if sum(1 for k, v in self._ahead.items()
                   if k[:2] == (t.board, id(t)) and k[2] != "bids" and v["odds"]) >= MAX_ODDS_CARDS:
                return  # as many as the review shows; any others are worked out at the end, people's first
            try:
                done = await loop.run_in_executor(None, odds_ahead, self.engine, t.hands, t.dealer, t.vulnerability,
                                                  list(t.auction.calls), t.contract, play[:i + 1],
                                                  random.Random(self.rng.random()))
            except Exception as exc:  # a bonus: the review works them out at the end instead
                log.warning("could not work out odds during the board: %s", exc)
                return
            self._ahead[self._ahead_key(t, play, i)] = done

    def fill_odds(self, t: Table, review: dict) -> None:
        play = [tuple(x) for x in t.play.played_cards()] if t.play else []
        ready = {i: self._ahead[k] for i in range(len(play)) if (k := self._ahead_key(t, play, i)) in self._ahead}
        try:
            add_odds(review, self.engine, t.hands, t.dealer, t.vulnerability, list(t.auction.calls), t.contract,
                     t.play.played_cards(), set(SEATS) - t.bot_seats, random.Random(self.rng.random()), ready=ready)
        except Exception as exc:  # odds are a bonus; never break the review over them
            review["odds_error"] = str(exc)
        try:  # was each call off the system a good bet: averaged over deals like this one (bidpath.py)
            below = (t.result.dd or {}).get("rubber", {}).get("below")
            bids = self._ahead.get((t.board, id(t), "bids", tuple(t.auction.calls), json.dumps(below, sort_keys=True)))
            add_averages(review, self.engine, t.hands, t.dealer, list(t.auction.calls), t.vulnerability, t.score,
                         below, random.Random(self.rng.random()), ready=bids)
        except Exception as exc:
            log.warning("could not average bidding outcomes: %s", exc)
        last = self.history[-1] if self.history else None
        if last and t.result and last.get("finished_at") == t.result.finished_at and last.get("undone"):
            try:  # cards taken back with Undo: what each would have cost, at the same low urgency as the odds
                solve_undone(t.hands, last["undone"])
            except Exception as exc:
                log.warning("could not work out undone cards: %s", exc)
        review["odds_pending"] = False
        # the board went to players' accounts as soon as it ended: save it again now that its review is complete
        if t.result and self.history and self.history[-1].get("finished_at") == t.result.finished_at:
            self.finished.extend(self._to_save)
            self._second_save = list(self._to_save)  # and once more when the second table is in
        self._to_save = []

    async def _fill_odds(self, t: Table, review: dict) -> None:
        # at the solver's lowest urgency, the default: bots and hints on the next board go first
        if self._ahead_task and not self._ahead_task.done():  # the card it's on now would only be worked out twice
            await asyncio.wait([self._ahead_task])
        await asyncio.get_running_loop().run_in_executor(None, self.fill_odds, t, review)
        waited = time.time() - t.result.finished_at if t.result else None
        if waited is not None and 0 <= waited < 3600:  # for the Admin page's Load tab (not a board from before a restart)
            timings.record("review", waited)
        await self.broadcast()
        if review.get("second_pending"):
            await self._second_tables(t, review)

    def _second_seats(self, t: Table) -> list[str]:
        """The people's seats that get a second table (game/second.py): not in Learn to play, whose hands aren't
        saved, and only where the work can be done after the board without holding up the game (`ahead`)."""
        if not self.ahead or self.settings.tutorial or self.settings.replay:
            return []
        return sorted(set(SEATS) - t.bot_seats)

    async def _second_tables(self, t: Table, review: dict) -> None:
        """Play the board again with the strongest bot in each person's seat, at the solver's lowest urgency, then
        save the board again with it."""
        loop = asyncio.get_running_loop()
        below = (t.result.dd or {}).get("rubber", {}).get("below") if t.result else None
        out = {}
        for seat in self._second_seats(t):
            try:
                out[seat] = await loop.run_in_executor(
                    None, second_table, self.engine, t.hands, t.dealer, t.vulnerability, t.score, seat,
                    set(SEATS) - t.bot_seats, self.settings.difficulty, t.signals, t.leads, below, t.contract,
                    t.result.declarer_tricks if t.result else 0, random.Random(self.rng.random()))
                add_split(out[seat], t.contract, t.result.dd if t.result else None, t.vulnerability, below)
            except Exception as exc:  # a bonus: the review goes without it
                log.warning("could not play the second table: %s", exc)
        if not (t.result and t.result.review is review):  # taken back with Undo meanwhile
            return
        if out:
            review["second"] = out
        review["second_pending"] = False
        self.finished.extend(self._second_save)
        self._second_save = []
        await self.broadcast()

    def _wait(self) -> float:
        """How long before a bot acts. A claim's cards go quickly, with a short look at each finished trick."""
        t = self.table
        if not BOT_DELAY or not t or not t.claiming:
            return BOT_DELAY + self._pause()
        return CLAIM_CARD + (CLAIM_TRICK if not t.play.current.cards and t.play.completed_tricks() else 0)

    def _pause(self) -> float:
        """Extra wait before a bot acts: while the phones animate the deal, or while a
        finished trick is still on show. None when bots are set to act at once (tests)."""
        t = self.table
        if not BOT_DELAY or not t:
            return 0.0
        if t.phase == "bidding" and not t.auction.calls:
            return DEAL_PAUSE
        if t.play and not t.play.current.cards and t.play.completed_tricks():
            return self.settings.trick_pause
        return 0.0


    # --- saving, so a table carries on after the server restarts (every deploy) ---------------------
    def snapshot_brief(self) -> dict:
        """The few parts of snapshot() that brief() reads, and who has the table open now (open)."""
        return {"code": self.code, "board_no": self.board_no, "saved": time.time(),
                "settings": {"scoring": self.settings.scoring, "practice": self.settings.practice,
                             "replay": bool(self.settings.replay), "tutorial": self.settings.tutorial},
                "players": {s: {"name": p.name, "user": p.user, "last": p.last, "open": bool(p.connections)}
                            for s, p in self.players.items()},
                "rubber": {"lines": [l.to_dict() for l in self.rubber.lines]}}

    def snapshot(self) -> dict:
        t = self.table
        table = None
        if t:
            table = {"board": t.board, "dealer": t.dealer, "vulnerability": t.vulnerability,
                     "score": t.score.to_dict() if t.score else None,
                     "hands": {s: t.hands[s].to_pbn() for s in SEATS}, "bots": sorted(t.bot_seats),
                     "actions": [list(a) for a in t.actions], "card_why": t.card_why,
                     "claiming": bool(t.claiming),
                     "fixed": t.fixed,
                     "dd": t.result.dd if t.result else None,
                     "review": t.result.review if t.result else None,
                     "finished_at": t.result.finished_at if t.result else None}
        state = self.rng.getstate()
        return {
            "v": 1, "code": self.code, "created": self.created, "rev": self.rev, "saved": time.time(),
            "settings": {**asdict(self.settings), "conventions": sorted(self.settings.conventions)},
            "players": {s: {"name": p.name, "token": p.token, "user": p.user, "since": p.since, "device": p.device,
                            "device_name": p.device_name, "last": p.last, "away": p.away,
                            "covered": p.covered, "done": p.done}
                        for s, p in self.players.items()},
            "rng": [state[0], list(state[1]), state[2]],
            "board_no": self.board_no, "help": self.help, "asked": self.asked, "undone": self.undone,
            "rubber": {"number": self.rubber.number, "games": self.rubber.games, "below": self.rubber.below,
                       "lines": [l.to_dict() for l in self.rubber.lines], "game_ends": self.rubber.game_ends,
                       "finished": self.rubber.finished},
            # only what the score strip and totals need: whole boards are kept in players' accounts
            "history": [{"board": r["board"], "contract": r["contract"], "declarer_tricks": r["declarer_tricks"],
                         "score_ns": r["score_ns"],
                         "dd": {"par_score_ns": (r.get("dd") or {}).get("par_score_ns")}}
                        for r in self.history],
            "table": table,
        }

    @classmethod
    def restore(cls, snap: dict) -> "Room":
        room = cls(snap["code"])
        room.created = snap["created"]
        room.rev = snap["rev"]
        st = dict(snap["settings"])
        st["conventions"] = set(st["conventions"])
        # tables saved before 1.18 could have 1.5 or 2.5 seconds: take the nearest choice there is now
        st["trick_pause"] = min(TRICK_PAUSES, key=lambda p: (abs(p - st.get("trick_pause", 2.0)), p))
        room.settings = Settings(**st)
        room._rebuild_engine()  # before the dealing sequence is put back: making the bots draws from it
        room.players = {s: Player(p["name"], p["token"], user=p.get("user"), since=p.get("since", 0),
                                  device=p.get("device"), device_name=p.get("device_name", ""),
                                  last=p.get("last", 0), away=p.get("away", False),
                                  covered=p.get("covered", False), done=p.get("done") or [])
                        for s, p in snap["players"].items()}
        v, internal, gauss = snap["rng"]
        room.rng.setstate((v, tuple(internal), gauss))
        room.board_no = snap["board_no"]
        room.help = snap.get("help") or {}
        room.asked, room.undone = snap.get("asked") or [], snap.get("undone") or []
        r = snap["rubber"]
        room.rubber = Rubber(r["number"], r["games"], r["below"], [Line(**l) for l in r["lines"]],
                             r["game_ends"], r["finished"])
        room.history = snap["history"]
        t = snap.get("table")
        if t:
            table = Table(room.engine, t["board"], set(t.get("bots") or room.bot_seats()), room.bot, rng=room.rng,
                          hands={s: Hand.from_pbn(h) for s, h in t["hands"].items()}, dealer=t["dealer"],
                          vulnerability=t["vulnerability"],
                          score=Score.from_rubber(t["score"], t["score"]["vulnerability"]) if t.get("score") else None,
                          signals=room.settings.method, leads=room.settings.leads)
            for who, kind, what in t["actions"]:
                table.replay(who, kind, what)
            table.card_why = t.get("card_why") or {}
            table.fixed = t.get("fixed", 0)
            if table.result:
                table.result.dd, table.result.review = t["dd"], t["review"]
                table.result.asked = asked_marks(table.actions, room.asked)
                table.result.finished_at = t["finished_at"] or table.result.finished_at
            room.table = table
            if t.get("claiming"):  # saved while a claim was being played out: it ended at once as it was replayed
                room.record_result()
        return room


def _mid_game(snap: dict, seat: str) -> bool:
    """Room._mid_game for a table saved in storage."""
    if snap["settings"].get("scoring") == "rubber" and (snap.get("rubber") or {}).get("lines"):
        return True
    t = snap.get("table")
    return bool(t and not t.get("finished_at") and any(a[0] == seat for a in t["actions"]))


def brief(snap: dict, seat: str, now: float) -> dict | None:
    """One line of the home screen's Your tables, from a saved table (or Room.snapshot_brief): who else plays there,
    who of them has it open now, the board, the rubber so far from this seat's side, and when this seat last played."""
    if snap["settings"].get("replay") or snap["settings"].get("tutorial"):
        return None  # a deal played again, or Learn to play: they have their own ways back
    me = snap["players"][seat]
    others = [p for s, p in snap["players"].items() if s != seat]
    mine = "NS" if seat in "NS" else "EW"
    lines = (snap.get("rubber") or {}).get("lines") or []
    rubber = snap["settings"].get("scoring") == "rubber"
    return {
        "room": snap["code"], "seat": seat, "board": snap.get("board_no", 0),
        "people": [p["name"] for p in others],
        "here": [p["name"] for p in others if p.get("open")],
        "we": sum(l["points"] for l in lines if l["side"] == mine) if rubber else None,
        "they": sum(l["points"] for l in lines if l["side"] != mine) if rubber else None,
        "last": me.get("last", 0) or snap.get("saved", 0),
        "lesson": snap["settings"].get("practice"),
    }


def _server_code(code: str) -> bool:
    """A code the server gives tables (four letters now, six for old tables)."""
    return len(code) in (4, 6) and set(code) <= set(CODE_LETTERS)


class TableClosed(ValueError):
    """The table was closed on the Admin page: a copy of it on a phone can't bring it back."""


class Rooms:
    """Every table in play. With a store, each table is saved as it changes and picked up again after a restart,
    so a deploy no longer ends games: the phones reconnect and carry on."""

    KEEP = 2 * 24 * 3600  # a saved table nobody has touched for this long is not brought back
    MAX_ROOMS = 500  # tables in memory at once: far more than friends and family play, but bounded

    def __init__(self, store=None, save_board: Callable[[str, dict], None] | None = None,
                 drop_board: Callable[[str, dict], None] | None = None,
                 save_settings: Callable[[str, dict], None] | None = None,
                 save_puzzle: Callable[[str, str, bool | None], None] | None = None):
        self.rooms: dict[str, Room] = {}
        self.store = store
        self.parked: dict[str, dict] = {}  # user id: a bot table played on their phone (see park)
        self.closed: dict[str, float] = {}  # code: when the Admin page closed it (see close)
        self.save_board = save_board  # (user id, record): a finished board, for that player's history
        self.drop_board = drop_board  # the same, for a board taken back by undo after it was saved
        self.save_settings = save_settings  # (user id, settings): what a player chose, for their next table
        self.save_puzzle = save_puzzle  # (user id, puzzle id, right or None if removed): Your mistakes (puzzles.py)
        self._dirty: set[str] = set()
        self._saver: asyncio.Task | None = None
        self._boot: list[dict] | None = None  # the tables in storage at start, for tables_of

    def _adopt(self, room: Room) -> Room:
        room.on_change = self._changed
        self.rooms[room.code] = room
        return room

    def create(self, chosen: dict | None = None) -> Room:
        self._evict_old()
        if len(self.rooms) >= self.MAX_ROOMS:  # a flood of new rooms: let go of empty ones sooner
            self._evict_old(max_age=3600)
        if len(self.rooms) >= self.MAX_ROOMS:
            raise RuntimeError("too many rooms")
        room = Room(self._new_code())
        room.apply_remembered(chosen or {})
        return self._adopt(room)

    def carry_back(self, snap: dict, token: str, user: str | None) -> Room:
        """A table the app carried on by itself (bridge/local.py) comes back to the server. It keeps its code if that
        is still this table's (the same seat token), and gets a new one otherwise (a table started offline, or one the
        server has let go of and given away). Raises ValueError if it isn't a table one person plays with the bots."""
        try:
            room = Room.restore(snap)
        except Exception as exc:
            raise ValueError("that table can't be read") from exc
        if self.was_closed(room.code, token):
            raise TableClosed(f"Table {room.code} was closed")
        if not room.carriable() or room.person(token)[1] is None:
            raise ValueError("only your own table with the bots can come back")
        for p in room.players.values():  # the account it plays for is the one signed in, whatever the phone says
            p.user = user
            p.connections = set()
        here = self.get(room.code) if len(room.code) in (4, 6) and room.code.isalpha() else None
        if here is None or here.person(token)[1] is None:
            if here is not None or self._saved(room.code) or not (len(room.code) == CODE_LENGTH
                                                                   and set(room.code) <= set(CODE_LETTERS)):
                room.code = self._new_code()
        elif any(p.connections for p in [*here.players.values(), *here.watchers.values()]):
            raise ValueError("this table is open on another device")
        room.rev = max(room.rev, here.rev + 1 if here else 0)
        return self._adopt(room)

    CLOSED_FOR = 7 * 24 * 3600  # a closed table's code is remembered this long, so copies on phones end too

    def close(self, code: str) -> Room | None:
        """The Admin page closes a table: here, in storage, and on the phones holding a copy of it (park, carry_back
        and table_for refuse it, and the app lets it go). A copy can have another code (a table started on a phone is
        "HOME" there and got a code here when another device picked it up), so its seats' tokens are remembered too.
        Returns the table if it was in memory."""
        room = self.rooms.pop(code, None)
        keys = [code] if _server_code(code) else []  # never "HOME", the code every table on a phone starts with
        if room:
            keys += [f"seat:{p.token}" for p in room.players.values() if p.token]
        for user, was in list(self.parked.items()):
            if was.get("taken") == code or (keys and (was.get("snap") or {}).get("code") == code):
                self.parked.pop(user, None)
                keys.append(f"seat:{was['token']}")
        if self.store:
            try:
                self.store.delete("rooms", "r", code)
            except Exception as exc:
                log.warning("could not delete table %s from storage: %s", code, exc)
        self._mark_closed(keys)
        return room

    async def quit(self, code: str, token: str) -> None:
        """A player quits a table for good (Leave, then Quit table). With only bots for company the table ends, on
        every device. With other people it goes on for them: the bot takes the seat, and the player doesn't stay on as
        someone watching, so a table left to one person and the bots can go to that person's phone again
        (Room.carriable). Either way the table doesn't come back to this player, here or from a copy on a phone (by its
        seat)."""
        room = await self.aget(code)
        seat = room.person(token)[0] if room else None
        if room and seat is not None:
            if room.carriable():
                self.close(room.code)
            else:
                async with room.lock:
                    room.stand(token)
                    room.watchers.pop(token, None)
                await room.broadcast()
        for user, was in list(self.parked.items()):
            if was["token"] == token:
                self.parked.pop(user, None)
        self._mark_closed([f"seat:{token}"])

    def _mark_closed(self, keys: list[str]) -> None:
        now = time.time()
        self.closed = {k: at for k, at in self.closed.items() if now - at < self.CLOSED_FOR}
        for key in keys:
            self.closed[key] = now
        if self.store and keys:
            try:
                for key in keys:
                    self.store.put("rooms", "closed", key, {"at": now})
            except Exception as exc:
                log.warning("could not remember a closed table in storage: %s", exc)

    def was_closed(self, code: str, token: str | None = None) -> bool:
        """Whether the Admin page closed this table: by its code here, or by the seat (a copy with another code)."""
        keys = ([code] if _server_code(code) else []) + ([f"seat:{token}"] if token else [])
        return any(self._closed_at(k) for k in keys)

    def _closed_at(self, key: str) -> bool:
        at = self.closed.get(key)
        if at is None and self.store:  # closed before a restart
            try:
                at = (self.store.get("rooms", "closed", key) or {}).get("at")
            except Exception:
                at = None
            if at is not None:
                self.closed[key] = at
        return at is not None and time.time() - at < self.CLOSED_FOR

    BOTH = 120  # a copy from another device this recent means two devices are playing the table at once

    def park(self, user: str, snap: dict, token: str, device: str | None = None) -> str | None:
        """A signed-in player's bot table on their phone (bridge/local.py) sends a copy here after each change, so the
        app opened on their other phone or iPad can carry on with it (table_for). Returns the table's code here once
        another device has taken it over, so the phone follows it to the server.

        Two devices playing the same table at once (each carried on with its own copy with no internet, say): the copy
        further on is brought here and both devices follow it, so they're at one table again."""
        code = str(snap.get("code", ""))
        if self.was_closed(code, token):
            self.parked.pop(user, None)
            raise TableClosed(f"Table {code} was closed")
        now = time.time()
        was = self.parked.get(user)
        if was and was["token"] == token and was.get("taken"):
            follow = was.get("follow")  # the devices still to follow it here, when we know them (two at once, below)
            # otherwise a copy of the taken table itself is that table come back to a device between boards
            if device in follow if follow is not None else was["taken"] != code:
                room = self.rooms.get(was["taken"])
                if room and room.person(token)[1]:
                    if follow is not None:
                        follow.discard(device)
                    return room.code
        if (was and device and was.get("device") and was["device"] != device and was["token"] == token
                and not was.get("taken") and now - was["at"] < self.BOTH):
            other = was["device"]
            if snap.get("rev", 0) > was["snap"].get("rev", 0):
                self.parked[user] = {"snap": snap, "token": token, "at": now, "device": device}
            claimed = self._claim(user)
            if claimed:
                self.parked[user]["follow"] = {other}  # this device follows now, the other at its next copy
                return claimed[1]
        self.parked[user] = {"snap": snap, "token": token, "at": now, "device": device}
        return None

    def parked_room(self, user: str) -> tuple[float, Room] | None:
        """The bot table this player is playing on their phone, as of its last copy, for their AI coach to look at
        (connector.py). Not a table here: nothing played on it counts."""
        was = self.parked.get(user)
        if not was or was.get("taken") or time.time() - was["at"] > self.JUMP:
            return None
        try:
            return was["at"], Room.restore(was["snap"])
        except Exception:
            return None

    def unpark(self, user: str) -> None:
        self.parked.pop(user, None)

    def _claim(self, user: str) -> tuple[float, str, bool] | None:
        """The parked table, brought onto the server: (when it was last played, its code, whether its player left)."""
        was = self.parked.get(user)
        if not was or was.get("taken") or time.time() - was["at"] > self.OFFER_MID_GAME:
            return None
        try:
            room = self.carry_back(was["snap"], was["token"], user)
        except (ValueError, RuntimeError) as exc:
            log.info("a parked table didn't come back: %s", exc)
            self.parked.pop(user, None)
            return None
        was["taken"] = room.code
        p = room.person(was["token"])[1]
        return was["at"], room.code, bool(p and p.away)

    def _new_code(self) -> str:
        for _ in range(100):
            code = "".join(secrets.choice(CODE_LETTERS) for _ in range(CODE_LENGTH))
            if code not in self.rooms and code not in self.closed and not self._saved(code):
                return code
        raise RuntimeError("could not allocate a room code")

    def get(self, code: str) -> Room | None:
        return self._pick(code.upper(), self._saved(code.upper()))

    async def aget(self, code: str) -> Room | None:
        """get(), with the storage read off the event loop, so other tables don't stall while it's in flight."""
        code = code.upper()
        return self._pick(code, await asyncio.to_thread(self._saved, code))

    def _pick(self, code: str, snap: dict | None) -> Room | None:
        room = self.rooms.get(code)
        # a newer copy than ours: saved by the other copy of the server while a deploy was switching over
        if snap and (room is None or (snap["rev"] > room.rev and not any(
                p.connections for p in [*room.players.values(), *room.watchers.values()]))):
            try:
                room = self._adopt(Room.restore(snap))
            except Exception:
                log.exception("could not bring back table %s", code)
                return room
        return room

    JUMP = 30 * 60  # opening the app on another phone this soon after playing goes straight back to the table
    OFFER = 2 * 3600  # after that, and after Leave, the lobby offers a way back this long after you last played
    OFFER_MID_GAME = 12 * 3600  # or this long when you left in the middle of a rubber

    async def table_for(self, user_id: str) -> dict | None:
        """The table this player was last seated at: {"room", "jump"}, or None. jump when they had it open in the last
        half hour and didn't tap Leave, so the app opened on another phone can go straight to their seat. The lobby
        offers it for 2 hours after they last played, or 12 if they left in the middle of a rubber."""
        # (not a deal played again: it's a side trip, not their table)
        found = [(p.last, code, p.away, r._mid_game(seat)) for code, r in self.rooms.items()
                 for seat, p in r.players.items() if p.user == user_id and not r.settings.replay]
        if not found and self.store:  # just after a deploy, tables wait in storage until someone comes back
            snaps = await asyncio.to_thread(self._all_saved)
            found = [(p.get("last", 0), snap["code"], p.get("away", False), _mid_game(snap, seat))
                     for snap in snaps for seat, p in snap["players"].items()
                     if p.get("user") == user_id and not snap["settings"].get("replay")]
        was = self.parked.get(user_id)
        if was and not was.get("taken") and (not found or was["at"] > max(found)[0]):
            claimed = self._claim(user_id)  # their bot table on their phone, newer than any here: it moves here
            if claimed:
                at, code, away = claimed
                return {"room": code, "jump": not away and time.time() - at < self.JUMP}
        if not found:
            return None
        last, code, away, mid_game = max(found)
        age = time.time() - last
        if age > (self.OFFER_MID_GAME if mid_game else self.OFFER):
            return None
        return {"room": code, "jump": not away and age < self.JUMP}

    async def tables_of(self, user_id: str) -> list[dict]:
        """Every table this player still has a seat at, newest first, for the home screen's Your tables (see brief):
        tables here, ones still in storage from before the last restart, and their bot table on their phone as of its
        last copy (parked: True; claim brings it here). A table drops off 2 days after they last played at it."""
        boot = await asyncio.to_thread(self._boot_saved)
        now = time.time()
        found: dict[str, dict] = {}
        for code, r in self.rooms.items():
            for seat, p in r.players.items():
                if p.user == user_id:
                    found[code] = brief(r.snapshot_brief(), seat, now)
        for snap in boot:  # not touched since the restart, so not in memory yet
            if snap["code"] in found or snap["code"] in self.rooms:
                continue
            for seat, p in snap["players"].items():
                if p.get("user") == user_id and not self.was_closed(snap["code"], p.get("token")):
                    found[snap["code"]] = brief(snap, seat, now)
        was = self.parked.get(user_id)
        if (was and not was.get("taken") and now - was["at"] <= self.OFFER_MID_GAME
                and not self.was_closed(str(was["snap"].get("code", "")), was["token"])):
            seat = next((s for s, p in was["snap"].get("players", {}).items() if p.get("token") == was["token"]), None)
            if seat:
                b = brief(was["snap"], seat, now)
                if b:
                    b["last"] = max(b["last"], was["at"])
                    found.setdefault(f"parked:{b['room']}", {**b, "parked": True})
        return sorted((b for b in found.values() if b and now - b["last"] <= self.KEEP), key=lambda b: -b["last"])

    def _boot_saved(self) -> list[dict]:
        """The tables in storage when the server started (read once): later ones are in memory, or were closed."""
        if self._boot is None:
            self._boot = self._all_saved() if self.store else []
        return self._boot

    def claim_parked(self, user_id: str) -> str | None:
        """Your tables' Play on the bot table on your other phone: it comes here, and that phone follows it."""
        claimed = self._claim(user_id)
        return claimed[1] if claimed else None

    async def quit_mine(self, user_id: str, code: str) -> bool:
        """Your tables' Quit table: as Leave, then Quit table, at that table (quit). Returns False if you aren't
        seated there. A parked table (your bot table on another phone) ends there too, by its seat."""
        was = self.parked.get(user_id)
        if code.startswith("parked:") and was and not was.get("taken"):
            self.parked.pop(user_id, None)
            self._mark_closed([f"seat:{was['token']}"])
            return True
        room = await self.aget(code)
        if room is None:
            return False
        token = next((p.token for p in room.players.values() if p.user == user_id), None)
        if not token:
            return False
        await self.quit(code, token)
        return True

    def copy_for(self, user_id: str, code: str) -> dict | None:
        """The whole table, for the app to carry on with if the internet drops: only a table where this player is
        the one person with the bots, as the table sends its seat over the socket (Room.carriable)."""
        room = self.rooms.get(code)
        if not room or not room.carriable() or not any(p.user == user_id for p in room.players.values()):
            return None
        return room.snapshot()

    def _all_saved(self) -> list[dict]:
        try:
            rows = self.store.query("rooms", "r")
        except Exception as exc:
            log.warning("could not list saved tables: %s", exc)
            return []
        return [snap for _, snap in rows if time.time() - snap.get("saved", 0) <= self.KEEP]

    def _saved(self, code: str) -> dict | None:
        if not self.store:
            return None
        try:
            snap = self.store.get("rooms", "r", code)
        except Exception as exc:
            log.warning("could not read table %s from storage: %s", code, exc)
            return None
        if snap and time.time() - snap.get("saved", 0) > self.KEEP:
            return None
        return snap

    # saving: at most a couple of times a second per table, off the event loop
    def _changed(self, room: Room) -> None:
        if not self.store and not (self.save_board and (room.finished or room.retracted)) and not (
                self.save_settings and room.chose) and not (self.save_puzzle and room.puzzle_marks):
            return
        self._dirty.add(room.code)
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        if self._saver is None or self._saver.done():
            self._saver = loop.create_task(self._save_soon())

    async def _save_soon(self) -> None:
        await asyncio.sleep(0.5)
        while self._dirty:
            codes, self._dirty = self._dirty, set()
            for code in codes:
                room = self.rooms.get(code)
                if room and self.drop_board:
                    while room.retracted:
                        user, rec = room.retracted.pop(0)
                        try:
                            await asyncio.to_thread(self.drop_board, user, rec)
                        except Exception as exc:
                            log.warning("could not remove an undone board from %s's history: %s", user, exc)
                if room and self.save_settings:
                    while room.chose:
                        user, chosen = room.chose.pop(0)
                        try:
                            await asyncio.to_thread(self.save_settings, user, chosen)
                        except Exception as exc:
                            log.warning("could not remember %s's table settings: %s", user, exc)
                if room and self.save_puzzle:
                    while room.puzzle_marks:
                        user, pid, right = room.puzzle_marks.pop(0)
                        try:
                            await asyncio.to_thread(self.save_puzzle, user, pid, right)
                        except Exception as exc:
                            log.warning("could not save %s's answer to a puzzle: %s", user, exc)
                if room and self.save_board:
                    while room.finished:
                        user, rec = room.finished.pop(0)
                        try:
                            await asyncio.to_thread(self.save_board, user, rec)
                        except Exception as exc:
                            log.warning("could not save a finished board to %s's history: %s", user, exc)
                if room and self.store:
                    try:
                        await asyncio.to_thread(self.store.put, "rooms", "r", code, room.snapshot())
                    except Exception as exc:  # the game goes on; it just won't survive a restart until a save works
                        log.warning("could not save table %s: %s", code, exc)

    def save_all(self) -> None:
        """At shutdown: everything, now."""
        for code, room in list(self.rooms.items()):
            try:
                self.store and self.store.put("rooms", "r", code, room.snapshot())
            except Exception as exc:
                log.warning("could not save table %s at shutdown: %s", code, exc)

    def _evict_old(self, max_age: float = 3 * 24 * 3600) -> None:
        now = time.time()
        for code, r in list(self.rooms.items()):
            idle = not any(p.connections for p in [*r.players.values(), *r.watchers.values()])
            if idle and now - r.created > max_age:
                del self.rooms[code]
