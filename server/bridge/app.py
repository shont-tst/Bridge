"""FastAPI app: REST for rooms/conventions, a WebSocket per phone, and the
built web client as static files."""
from __future__ import annotations

import asyncio
import base64
import datetime as dt
import html
import json
import logging
import os
import re
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path
from zoneinfo import ZoneInfo
from urllib.parse import parse_qsl, unquote

from fastapi import Body, FastAPI, Header, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from .accounts import Accounts, AuthError, origin_for
from .bidding.conventions import BY_ID, convention_list, make_engine, requirements
from .bidding.lessons import LEADS, LEADS_PAGE, LESSONS, SIGNALS, SIGNALS_PAGE, examples_for, lesson_list
from .game.room import REMEMBERED, Room, Rooms, TableClosed, at as solver_at
from .game.speed import bench as speed_bench
from .game.second import fill_split
from .game.table import auction_shown
from .limits import Limiter, RateLimit, visitor
from . import solver
from .tutorial import card_tricks as tutorial_card_tricks
from .admin import CONFIRM, OLD_AFTER_DAYS, TABLE_LIMIT_MAX, Admin, live, table_view
from .backups import Backups, pacific_today
from .load import SAMPLE_EVERY, Load, machine, suggest_limit, timings as load_timings
from .push import Push
from .social import Social
from .stats import history_from_facts, stats_from_facts
from .feedback import Feedback
from .puzzles import KINDS, Puzzles
from . import backfill, offline, recheck, site
from .connector import Connector, OAuthError
from .store import open_store

store = open_store()
accounts = Accounts(store)
feedback = Feedback(store)
push = Push(accounts)
social = Social(accounts, push)
puzzles = Puzzles(store, accounts)
rooms = Rooms(store, save_board=accounts.save_board, drop_board=accounts.drop_board,
              save_settings=accounts.save_table_settings, save_puzzle=puzzles.mark)
Room.puzzle_loader = puzzles.spec  # Your mistakes: the next puzzle at a puzzle table
backups = Backups(store)
admin = Admin(store, accounts)
connector = Connector(store, accounts, rooms)
load = Load(store)
log = logging.getLogger("bridge.app")


def table_counts() -> tuple[int, int]:
    """Tables in use (someone has them open) and the people at them, for the table limit and the Load tab."""
    live_rooms = [r for r in rooms.rooms.values() if live(r)]
    people = sum(1 for r in live_rooms for p in [*r.players.values(), *r.watchers.values()] if p.connections)
    return len(live_rooms), people


@asynccontextmanager
async def lifespan(_app):
    try:  # addresses blocked on the Admin page
        limiter.blocked = (await asyncio.to_thread(store.get, "config", "cfg", "blocked") or {}).get("addresses", {})
    except Exception:
        pass
    task = asyncio.create_task(backups.run()) if store.durable else None  # weekly, of storage that lasts
    sampler = asyncio.create_task(load.run(table_counts))
    # the speed check after each start and daily, for the Load tab's history
    speeds = asyncio.create_task(speed_check.daily()) if os.environ.get("BRIDGE_SPEED_DAILY", "1") != "0" else None
    # saved boards from before the second table get one, once, in the background (backfill.py)
    second = asyncio.create_task(backfill.run(accounts)) if os.environ.get("BRIDGE_SECOND_BACKFILL", "1") != "0" else None
    # after a change of the bidding rules, saved boards' reviews are checked against them once (recheck.py)
    rules = asyncio.create_task(recheck.run(accounts)) if os.environ.get("BRIDGE_RULES_RECHECK", "1") != "0" else None
    yield
    sampler.cancel()
    if speeds:
        speeds.cancel()
    if second:
        second.cancel()
    if rules:
        rules.cancel()
    if task:
        task.cancel()
    rooms.save_all()  # a deploy stops this copy of the server: save every table so the next copy carries on
    solver.shutdown()


app = FastAPI(title=site.app_name(), lifespan=lifespan)
limiter = Limiter()
app.add_middleware(RateLimit, limiter=limiter)


# What the browser may load and run for this site: only its own scripts, plus the two Google fonts. If a name or a
# suggestion ever slipped some script into a page, the browser would refuse to run it, so the sign-in token kept on
# the phone stays out of reach. 'wasm-unsafe-eval' lets the offline engine (bridge/offline.py) compile WebAssembly, the
# site's own files only; it doesn't allow running text as script.
CSP = ("default-src 'self'; script-src 'self' 'wasm-unsafe-eval'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
       "font-src 'self' https://fonts.gstatic.com; img-src 'self' data: blob:; connect-src 'self' wss:; "
       "worker-src 'self'; manifest-src 'self'; object-src 'none'; base-uri 'self'; form-action 'self'; "
       "frame-ancestors 'none'")
SECURITY_HEADERS = {
    "X-Robots-Tag": "noindex, nofollow",  # private family app: ask search engines not to list or follow any page
    "Content-Security-Policy": CSP,
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "same-origin",
    "X-Frame-Options": "DENY",  # no other site may show the app inside its own page
    "Strict-Transport-Security": "max-age=31536000",  # always https from now on (ignored on a laptop's http)
}


@app.middleware("http")
async def security_headers(request, call_next):
    response = await call_next(request)
    response.headers.update(SECURITY_HEADERS)
    return response


@app.exception_handler(AuthError)
async def auth_error(_request, exc: AuthError):
    return JSONResponse({"detail": str(exc)}, status_code=400)

WEB_DIST = Path(os.environ.get("BRIDGE_WEB_DIST",
                               Path(__file__).resolve().parents[2] / "web" / "dist"))


def published_version() -> str | None:
    """The version of the web client this server is serving, from the version.json the build writes next to it."""
    try:
        return str(json.loads((WEB_DIST / "version.json").read_text())["version"])
    except (OSError, ValueError, KeyError, TypeError):
        return None


@app.get("/api/version")
def version():
    # a phone running an older client compares this with its own and offers Reload
    return JSONResponse({"version": published_version()}, headers={"Cache-Control": "no-store"})


class SpeedCheck:
    """The server's time on the speed check a phone also runs (game/speed.py), so the app can tell whether Play
    locally thinks slower than the server would. It runs live, in the same line for the solver as every table's bots,
    so a busy server answers with a slower time. One run at a time, and its answer is given for KEEP seconds.

    Every run is written down for the Admin page's Load tab (load.py), so the server's speed can be followed over
    time: `daily()` runs it a few minutes after each start and once a day at a quiet hour (QUIET, Pacific)."""
    KEEP = 600
    AFTER_START = 300  # seconds: let a start's own work (tables coming back, catching up on boards) get going first
    QUIET = 4  # 4 AM Pacific: the fewest tables

    def __init__(self):
        self._last: tuple[float, dict] | None = None
        self._running: asyncio.Future | None = None

    async def run(self, why: str = "phone") -> dict:
        if why == "phone" and self._last and time.monotonic() - self._last[0] < self.KEEP:
            return self._last[1]
        if self._running is None or self._running.done():
            self._running = asyncio.ensure_future(self._measure(why))
        return await asyncio.shield(self._running)

    async def _measure(self, why: str) -> dict:
        seconds = await asyncio.get_running_loop().run_in_executor(None, solver_at, solver.BOT, speed_bench)
        out = {"seconds": seconds, "version": published_version()}
        self._last = (time.monotonic(), out)
        try:
            await asyncio.to_thread(load.speed, seconds, why, table_counts()[0])
        except Exception:  # the history is a bonus; the phone still gets its answer
            log.exception("couldn't write down the speed check")
        return out

    @classmethod
    def until_quiet(cls, now: dt.datetime) -> float:
        """Seconds from `now` (aware) to the next QUIET o'clock, Pacific."""
        pacific = now.astimezone(ZoneInfo("America/Los_Angeles"))
        at = pacific.replace(hour=cls.QUIET, minute=0, second=0, microsecond=0)
        if at <= pacific:
            at = (pacific + dt.timedelta(days=1)).replace(hour=cls.QUIET, minute=0, second=0, microsecond=0)
        return (at - pacific).total_seconds()

    async def daily(self) -> None:
        await asyncio.sleep(self.AFTER_START)
        why = "start"
        while True:
            try:
                await self.run(why)
            except Exception:
                log.exception("the speed check failed")
            await asyncio.sleep(self.until_quiet(dt.datetime.now(dt.timezone.utc)))
            why = "daily"


speed_check = SpeedCheck()


@app.get("/api/speed")
async def speed():
    return JSONResponse(await speed_check.run(), headers={"Cache-Control": "no-store"})


class StorageCheck:
    """Whether storage answers, for /api/health. It is asked in the background at most once a minute and the last
    answer is given, so a slow storage can't make Azure's health probe time out (and restart a server that is fine).
    """
    EVERY = 60  # seconds

    def __init__(self):
        self.ok: bool | None = None  # None: not asked yet
        self.at = 0.0
        self.lock = threading.Lock()

    def status(self) -> str:
        """'ok', 'down', or 'checking' (just started); 'local' when the app isn't keeping lasting storage."""
        if not store.durable:
            return "local"
        with self.lock:
            due = time.time() - self.at >= self.EVERY
            if due:
                self.at = time.time()
        answer = "checking" if self.ok is None else "ok" if self.ok else "down"  # before a new ask can change it
        if due:
            threading.Thread(target=self._ask, daemon=True).start()
        return answer

    def _ask(self) -> None:
        try:
            store.get("config", "cfg", "health")  # any record will do; this one never exists
            self.ok = True
        except Exception as exc:
            if self.ok is not False:
                log.warning("storage can't be reached: %s", exc)
            self.ok = False


storage_check = StorageCheck()


def backup_days() -> int | None:
    """How many days old the newest backup is (None until the server has looked, a few minutes after it starts)."""
    try:
        return (pacific_today() - dt.date.fromisoformat(backups.last)).days if backups.last else None
    except ValueError:
        return None


@app.get("/api/health")
def health(request: Request):
    # Always 200 while the server runs: Azure restarts the app when this fails, and a restart can't mend storage.
    # The Uptime workflow reads "storage" and "backup_days" and emails the owner when either is wrong.
    # "you": the address this request is counted under for rate limits, so they can be checked from outside
    return {"ok": True, "rooms": len(rooms.rooms), "you": visitor(request.scope),
            "storage": storage_check.status(), "backup": backups.last, "backup_days": backup_days(),
            "backup_error": backups.error}


def alert_owner(text: str, url: str) -> None:
    """A phone notification to the site's owner only (if they have notifications on), at most once a day (Pacific).
    The day of the last one is kept in storage, so a deploy doesn't send another."""
    try:
        today = pacific_today().isoformat()
        if (store.get("config", "cfg", "limit_alert") or {}).get("day") == today:
            return
        store.put("config", "cfg", "limit_alert", {"day": today, "at": time.time()})
        owner = accounts.user(accounts.admin_id() or "")
        if owner:
            threading.Thread(target=push.send, args=(owner, site.app_name(), text, url), daemon=True).start()
    except Exception:  # an alert is a bonus; the player still gets their answer
        log.exception("couldn't alert the owner")


def _chosen_settings(body: dict, authorization: str | None) -> tuple[dict, dict | None]:
    """The table settings a new table of this player's starts with, and the player when signed in: kept with their
    account when signed in, otherwise sent from their phone (phones from before 1.55 send just the scoring)."""
    chosen = {**({"scoring": body["scoring"]} if body.get("scoring") else {}),
              **(body.get("settings") if isinstance(body.get("settings"), dict) else {})}
    user = None
    if authorization:
        try:
            user = accounts.user_for(authorization.removeprefix("Bearer ").strip())
            if user:
                chosen = {**chosen, **accounts.table_settings(user)}
        except Exception:  # storage can't be reached: the phone's choices will do
            pass
    return chosen, user


def _settings_preview(chosen: dict) -> dict:
    """The settings a new table would start with, without making one."""
    room = Room("PREVIEW")
    room.apply_remembered(chosen)
    return room.settings.to_dict()


@app.post("/api/table-defaults")
def table_defaults(body: dict | None = Body(None), authorization: str | None = Header(None)):
    """The home screen's menu: the settings your next new table starts with."""
    return _settings_preview(_chosen_settings(body or {}, authorization)[0])


@app.post("/api/me/table-settings")
def save_table_defaults(body: dict = Body(...), authorization: str | None = Header(None)):
    """Changed in the home screen's menu: kept with the account (only settings a table remembers, and only valid
    ones), like a change made at a table."""
    user = _signed_in(authorization)
    asked = body.get("settings") if isinstance(body.get("settings"), dict) else {}
    now = _settings_preview({**accounts.table_settings(user), **asked})
    chosen = {k: now[k] for k in REMEMBERED if k in asked}
    if chosen:
        accounts.save_table_settings(user["id"], chosen)
    return now


def _new_room(request: Request, chosen: dict, user: dict | None) -> Room:
    # the Admin page's table limit: past it the tables in play would slow down, so wait for one to finish. The owner
    # can always start one.
    limit = admin.table_limit()
    in_use = table_counts()[0]
    load_timings.tables(in_use)
    if in_use >= limit and not accounts.is_admin(user):
        load_timings.turned_away()
        alert_owner(f"Someone couldn't start a table: all {limit} are in use.", _origin(request).origin + "/")
        raise HTTPException(503, f"All {limit} tables are in use right now. Please try again in a few minutes.")
    try:
        room = rooms.create(chosen)
    except RuntimeError:  # full: a flood of rooms, or far more players than this app expects
        raise HTTPException(503, "The server is busy. Please try again in a few minutes.")
    return room


@app.post("/api/rooms")
def create_room(request: Request, body: dict | None = Body(None), authorization: str | None = Header(None)):
    body = body or {}
    chosen, user = _chosen_settings(body, authorization)
    room = _new_room(request, chosen, user)
    if body.get("replay"):  # Play on from here, or Play this deal again, from a review (game/replay.py)
        try:
            room.start_replay(body["replay"])
        except (TypeError, ValueError, KeyError) as e:
            rooms.rooms.pop(room.code, None)
            raise HTTPException(400, f"That deal can't be played again: {e}")
    if body.get("tutorial") is not None:  # Learn to play steps 6 and 7 play at a real table
        try:
            room.start_tutorial(int(body["tutorial"]))
        except (TypeError, ValueError) as e:
            raise HTTPException(400, str(e))
    if body.get("practice"):  # Learn & practice in the home screen's menu: a table already on that practice
        try:
            room.update_settings(practice=str(body["practice"]))
        except ValueError as e:
            rooms.rooms.pop(room.code, None)
            raise HTTPException(400, str(e))
    return {"code": room.code}


@app.post("/api/rooms/carry")
def carry_back(body: dict = Body(...), authorization: str | None = Header(None)):
    """A table the app played by itself while the server couldn't be reached comes back (bridge/local.py)."""
    snap, token = body.get("snap"), body.get("token")
    if not isinstance(snap, dict) or not isinstance(token, str):
        raise HTTPException(400, "snap and token, please")
    user = None
    if authorization:
        user = accounts.user_for(authorization.removeprefix("Bearer ").strip())
        if not user:
            raise HTTPException(401, "Please sign in again")
    try:
        room = rooms.carry_back(snap, token, user["id"] if user else None)
    except TableClosed as exc:  # the app lets its copy go
        raise HTTPException(410, str(exc))
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except RuntimeError:
        raise HTTPException(503, "The server is busy. Please try again in a few minutes.")
    if user:
        rooms.unpark(user["id"])
    rooms._changed(room)
    return {"code": room.code}


@app.post("/api/rooms/quit")
async def quit_table(body: dict = Body(...)):
    """Leave a table for good (the seat's token says whose): see Rooms.quit."""
    code, token = body.get("code"), body.get("token")
    if not isinstance(code, str) or not isinstance(token, str) or not token or len(code) > 12 or len(token) > 100:
        raise HTTPException(400, "code and token, please")
    await rooms.quit(code.upper(), token)
    return {"ok": True}


@app.get("/api/rooms/{code}/closed")
def room_closed(code: str, seat: str | None = None):
    """Whether the Admin page closed this table, so an app holding a copy of it lets it go. `seat`: the app's seat
    token, which finds a copy that has another code here."""
    return {"closed": rooms.was_closed(code.upper()[:12], seat[:100] if seat else None)}


@app.post("/api/me/parked")
def park_table(body: dict = Body(...), authorization: str | None = Header(None)):
    """A copy of the bot table you're playing on your phone, kept so your other devices can carry on with it.
    {"taken": code} once one has: the phone follows the table here."""
    user = _signed_in(authorization)
    snap, token = body.get("snap"), body.get("token")
    if not isinstance(snap, dict) or not isinstance(token, str) or len(json.dumps(snap)) > 300_000:
        raise HTTPException(400, "snap and token, please")
    try:
        device = body.get("device")
        taken = rooms.park(user["id"], snap, token, device if isinstance(device, str) else None)
    except TableClosed as exc:  # the app lets its copy go
        return {"closed": str(exc)}
    return {"taken": taken} if taken else {}


@app.post("/api/me/offline-boards")
def offline_boards(body: dict = Body(...), authorization: str | None = Header(None)):
    """Boards played on the app with no internet, for My stats and the review. `drop`: ones Undo took back."""
    user = _signed_in(authorization)
    saved = 0
    for key, fn in (("boards", accounts.save_board), ("drop", accounts.drop_board)):
        recs = body.get(key) or []
        if not isinstance(recs, list) or len(recs) > 20:
            raise HTTPException(400, f"{key}: a list of at most 20 boards")
        for rec in recs:
            if not (isinstance(rec, dict) and isinstance(rec.get("board"), int) and isinstance(rec.get("hands"), dict)
                    and isinstance(rec.get("finished_at"), (int, float))):
                raise HTTPException(400, "that isn't a board")
            with_ = rec.get("with")
            rec = {**rec, "offline": True,
                   "with": [w for w in with_ if isinstance(w, str)][:3] if isinstance(with_, list) else []}
            fn(user["id"], rec)
            saved += 1
    return {"saved": saved}


# --- accounts -----------------------------------------------------------------------------------
def _origin(request: Request):
    return origin_for(request.headers.get("host", "localhost"), request.url.scheme)


def _signed_in(authorization: str | None) -> dict:
    token = (authorization or "").removeprefix("Bearer ").strip()
    user = accounts.user_for(token)
    if not user:
        raise HTTPException(401, "Please sign in again")
    return user


@app.get("/api/config")
def config():
    out = {"accounts": accounts.enabled}
    if accounts.enabled:
        try:
            out["push_key"] = push.public_key()
        except Exception:  # the storage can't be reached: everyone plays as a guest meanwhile
            out = {"accounts": False}
    try:
        out["notice"] = admin.notice()  # the site owner's message for everyone, shown in the lobby
    except Exception:
        pass
    return out


@app.post("/api/feedback")
def send_feedback(body: dict = Body(...), authorization: str | None = Header(None)):
    user = _signed_in(authorization)  # signed-in players only
    try:
        about = None  # feedback from the table: the server adds the deal, auction and play itself
        b = body.get("bid") or body.get("card") or body.get("board")
        if isinstance(b, dict):
            room = rooms.get(str(b.get("room", ""))[:12])
            if room is None:
                raise ValueError("That table has ended")
            board = int(b.get("board", -1))
            about = (room.bid_report(board, int(b.get("index", -1))) if "bid" in body else
                     room.card_report(board, str(b.get("card", ""))[:2]) if "card" in body else room.board_report(board))
        feedback.add(str(body.get("text", "")), user["id"], name=user["name"], user_id=user["id"],
                     version=str(body.get("version") or "")[:10] or None, about=about)
    except (TypeError, ValueError) as e:
        raise HTTPException(400, str(e))
    return {"ok": True}


@app.get("/api/auth/signup")
def signup_status(invite: str | None = None):
    return accounts.signup_status(invite)


@app.post("/api/auth/register/options")
def register_options(request: Request, body: dict = Body(...)):
    return accounts.register_options(_origin(request), body.get("name", ""), body.get("invite"))


@app.post("/api/auth/register/verify")
def register_verify(request: Request, body: dict = Body(...)):
    return accounts.register_verify(_origin(request), body.get("challenge_id", ""), body.get("credential") or {})


@app.post("/api/auth/login/options")
def login_options(request: Request):
    return accounts.login_options(_origin(request))


@app.post("/api/auth/login/verify")
def login_verify(request: Request, body: dict = Body(...)):
    return accounts.login_verify(_origin(request), body.get("challenge_id", ""), body.get("credential") or {})


@app.get("/api/me")
def me(authorization: str | None = Header(None)):
    out = accounts.me((authorization or "").removeprefix("Bearer ").strip())
    if not out:
        raise HTTPException(401, "Please sign in again")
    return out


@app.post("/api/me/invite")
def make_invite(request: Request, authorization: str | None = Header(None)):
    code = accounts.make_invite(_signed_in(authorization))
    return {"code": code, "url": f"{_origin(request).origin}/?invite={code}"}


@app.post("/api/me/invite/sent")
def invite_sent(body: dict = Body(...), authorization: str | None = Header(None)):
    """The invite link was shared or copied: the next Invite makes a new one."""
    accounts.invite_sent(_signed_in(authorization), str(body.get("code", "")))
    return {}


@app.get("/api/me/table")
async def my_table(authorization: str | None = Header(None)):
    """The table you're seated at, so opening the app on another phone can go straight back to it."""
    user = await asyncio.to_thread(_signed_in, authorization)
    found = await rooms.table_for(user["id"]) or {}
    snap = rooms.copy_for(user["id"], found.get("room", ""))
    if snap:  # a bot table of theirs: a copy comes along, so this device can carry on with it with no internet
        found["snap"] = snap
    return found


@app.get("/api/me/tables")
async def my_tables(authorization: str | None = Header(None)):
    """The tables you still have a seat at, for the home screen's Your tables (Rooms.tables_of)."""
    user = await asyncio.to_thread(_signed_in, authorization)
    return {"tables": await rooms.tables_of(user["id"])}


@app.post("/api/me/tables/claim")
async def claim_my_table(authorization: str | None = Header(None)):
    """Your tables' Play on your bot table on another phone: it comes to the server, for this device to sit at."""
    user = await asyncio.to_thread(_signed_in, authorization)
    code = rooms.claim_parked(user["id"])
    if not code:
        raise HTTPException(404, "That table has ended")
    return {"room": code}


@app.post("/api/me/tables/quit")
async def quit_my_table(body: dict = Body(...), authorization: str | None = Header(None)):
    """Your tables' Quit table (Rooms.quit_mine)."""
    user = await asyncio.to_thread(_signed_in, authorization)
    code = body.get("room")
    if not isinstance(code, str) or not code or len(code) > 40:
        raise HTTPException(400, "room, please")
    if not await rooms.quit_mine(user["id"], code if code.startswith("parked:") else code.upper()):
        raise HTTPException(404, "That table has ended")
    return {"ok": True}


@app.post("/api/me/device-link")
def device_link(authorization: str | None = Header(None)):
    return {"code": accounts.make_device_link(_signed_in(authorization))}


@app.post("/api/me/sign-out-others")
def sign_out_others(authorization: str | None = Header(None)):
    """Every other phone signed in to this account is signed out (a lost or sold phone); this one stays in."""
    user = _signed_in(authorization)
    return {"token": accounts.sign_out_others(user), "user": accounts.public(user)}


@app.post("/api/me/notify")
def set_notify(body: dict = Body(...), authorization: str | None = Header(None)):
    user = _signed_in(authorization)
    accounts.set_notify(user, bool(body.get("on")))
    return accounts.public(user)


@app.post("/api/me/push")
def add_push(body: dict = Body(...), authorization: str | None = Header(None)):
    user = _signed_in(authorization)
    accounts.add_push(user, body.get("subscription"))
    return accounts.public(user)


@app.get("/api/me/tutorial")
def tutorial(authorization: str | None = Header(None)):
    """Learn to play progress, so it follows the player to their other devices."""
    return accounts.tutorial(_signed_in(authorization))


@app.post("/api/me/tutorial")
def save_tutorial(body: dict = Body(...), authorization: str | None = Header(None)):
    """Finished steps are only ever added; `games` replaces the list when it's sent."""
    return accounts.save_tutorial(_signed_in(authorization), body.get("games"), body.get("done"))


@app.post("/api/tutorial/hint")
async def tutorial_hint(body: dict = Body(...)):
    """Learn to play's Hint on a full deal: the tricks each card takes with all hands known. Guests can use it too."""
    try:
        return {"tricks": await asyncio.to_thread(tutorial_card_tricks, body)}
    except (ValueError, TypeError) as e:
        raise HTTPException(400, str(e))


@app.get("/api/me/stats")
def stats(days: int = 30, hints: bool = False, undo: bool = False, coach: bool = False,
          authorization: str | None = Header(None)):
    """My stats; hints, undo and coach leave out the help the player ticked (stats.leave_out)."""
    user = _signed_in(authorization)
    return stats_from_facts(accounts.facts(user["id"]), days or None, hints, undo, coach)


@app.get("/api/me/puzzles")
def my_puzzles(authorization: str | None = Header(None)):
    """Your mistakes on the home screen: how many puzzles are waiting (puzzles.py)."""
    return puzzles.summary(_signed_in(authorization)["id"])


@app.post("/api/puzzles/start")
def start_puzzles(request: Request, body: dict | None = Body(None), authorization: str | None = Header(None)):
    """A table for Your mistakes, at the first puzzle waiting: the app joins it like any table. `kind` in the body
    (puzzles.KINDS) practices only that kind; left out, every kind."""
    user = _signed_in(authorization)
    chosen, _ = _chosen_settings({}, authorization)
    kind = (body or {}).get("kind") if isinstance(body, dict) else None
    queue = puzzles.queue(user["id"], kinds={kind} if kind in KINDS else None)
    for pos, pid in enumerate(queue):
        spec = puzzles.spec(user["id"], pid)
        if spec:
            break
    else:
        raise HTTPException(404, "No mistakes waiting right now.")
    room = _new_room(request, chosen, user)
    try:
        room.start_replay(spec, queue, pos, user["id"])
    except (TypeError, ValueError, KeyError) as e:
        rooms.rooms.pop(room.code, None)
        raise HTTPException(400, f"That puzzle can't be set up: {e}")
    return {"code": room.code}


@app.get("/api/me/boards")
def boards(role: str | None = None, limit: int = 200, authorization: str | None = Header(None)):
    """Hand history, newest first: the latest `limit` boards (at most 1,000), optionally only one role's."""
    user = _signed_in(authorization)
    return history_from_facts(accounts.facts(user["id"]), role if role in ("declarer", "defender") else None,
                              max(1, min(limit, 1000)))


@app.get("/api/me/boards/{key}")
def board(key: str, authorization: str | None = Header(None)):
    user = _signed_in(authorization)
    rec = accounts.board(user["id"], key)
    if not rec:
        raise HTTPException(404, "no such board")
    fill_split(rec)  # second tables played before the bidding and play shares were kept
    # the auction with each call's meaning, as at the table, for the review's Auction pull-down
    if rec.get("calls") and rec.get("dealer"):
        try:
            engine = make_engine(set(rec["conventions"]) if rec.get("conventions") is not None
                                 else {c.id for c in BY_ID.values() if c.default_on})
            rec = {**rec, "auction": auction_shown(engine, rec["dealer"], rec["calls"])}
        except Exception as exc:  # an old board the engine can't read: the review shows without it
            log.warning("could not show the auction of board %s: %s", key, exc)
    return rec


@app.post("/api/friends/request")
async def friend_request(body: dict = Body(...), authorization: str | None = Header(None)):
    user = await asyncio.to_thread(_signed_in, authorization)
    other = await asyncio.to_thread(accounts.request_friend, user, str(body.get("who", "")))
    await social.refresh(user["id"])
    await social.refresh(other["id"])
    return {"name": other["name"]}


@app.post("/api/friends/invite")
async def friend_invite(body: dict = Body(...), authorization: str | None = Header(None)):
    """A signed-in player opened a friend's invite link."""
    user = await asyncio.to_thread(_signed_in, authorization)
    other = await asyncio.to_thread(accounts.use_invite, user, str(body.get("code", "")))
    await social.refresh(user["id"])
    await social.refresh(other["id"])
    return {"name": other["name"]}


@app.post("/api/friends/answer")
async def friend_answer(body: dict = Body(...), authorization: str | None = Header(None)):
    user = await asyncio.to_thread(_signed_in, authorization)
    other = str(body.get("id", ""))
    await asyncio.to_thread(accounts.answer_friend, user, other, bool(body.get("accept")))
    await social.refresh(user["id"])
    await social.refresh(other)
    return {"ok": True}


@app.post("/api/friends/remove")
async def friend_remove(body: dict = Body(...), authorization: str | None = Header(None)):
    user = await asyncio.to_thread(_signed_in, authorization)
    other = str(body.get("id", ""))
    await asyncio.to_thread(accounts.unfriend, user["id"], other)
    await social.refresh(user["id"])
    await social.refresh(other)
    return {"ok": True}


@app.post("/api/play/invite")
async def play_invite(request: Request, body: dict = Body(...), authorization: str | None = Header(None)):
    user = await asyncio.to_thread(_signed_in, authorization)
    room = await rooms.aget(str(body.get("room", "")))
    if not room:
        raise HTTPException(404, "no such room")
    try:
        return await social.invite(user, str(body.get("friend", "")), room.code, _origin(request).origin)
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@app.post("/api/play/answer")
async def play_answer(body: dict = Body(...), authorization: str | None = Header(None)):
    user = await asyncio.to_thread(_signed_in, authorization)
    await social.answer_invite(user, str(body.get("from", "")), str(body.get("room", "")), bool(body.get("accept")))
    return {"ok": True}


# --- the Admin page (bridge/admin.py) ----------------------------------------------------------------------
def _admin(authorization: str | None, confirmed: bool = False) -> dict:
    """The admin, or 404 for everyone else. `confirmed`: Face ID must have been given again in the last few minutes."""
    user = accounts.user_for((authorization or "").removeprefix("Bearer ").strip())
    if not accounts.is_admin(user):
        raise HTTPException(404, "not found")
    if confirmed and not admin.is_confirmed(user):
        raise HTTPException(403, CONFIRM)
    return user


@app.post("/api/admin/confirm/options")
def admin_confirm_options(request: Request, authorization: str | None = Header(None)):
    return admin.confirm_options(_admin(authorization), _origin(request))


@app.post("/api/admin/confirm/verify")
def admin_confirm_verify(request: Request, body: dict = Body(...), authorization: str | None = Header(None)):
    admin.confirm_verify(_admin(authorization), _origin(request), body.get("challenge_id", ""),
                         body.get("credential") or {})
    return {"ok": True}


@app.get("/api/admin/players")
def admin_players(authorization: str | None = Header(None)):
    _admin(authorization)
    return {"players": admin.players(), "old": [p["id"] for p in admin.old_players()],
            "old_after_days": OLD_AFTER_DAYS}


@app.get("/api/admin/friends")
def admin_friends(authorization: str | None = Header(None)):
    _admin(authorization)
    return admin.friends()


@app.post("/api/admin/players/remove")
async def admin_remove_player(body: dict = Body(...), authorization: str | None = Header(None)):
    user = await asyncio.to_thread(_admin, authorization, True)
    try:
        gone = await asyncio.to_thread(admin.remove_player, str(body.get("id", "")))
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    await asyncio.to_thread(admin.log, user, "Removed a player", gone["name"])
    for other in list(social.sockets):  # their friends' lists drop them
        await social.refresh(other)
    return {"ok": True}


@app.post("/api/admin/players/clear-old")
async def admin_clear_old(authorization: str | None = Header(None)):
    user = await asyncio.to_thread(_admin, authorization, True)
    old = await asyncio.to_thread(admin.old_players)
    for p in old:
        await asyncio.to_thread(admin.remove_player, p["id"])
    await asyncio.to_thread(admin.log, user, f"Cleared {len(old)} old account{'s' * (len(old) != 1)}",
                            ", ".join(p["name"] for p in old))
    for other in list(social.sockets):
        await social.refresh(other)
    return {"removed": len(old)}


@app.get("/api/admin/tables")
def admin_tables(authorization: str | None = Header(None)):
    _admin(authorization)
    online = [{"name": u["name"], "id": uid} for uid in social.sockets if social.sockets[uid]
              for u in [accounts.user(uid)] if u]
    return {"tables": sorted((table_view(r) for r in rooms.rooms.values()), key=lambda t: -t["active"]),
            "online": online, "invites": admin.invites(), "limit": admin.table_limit(),
            "suggest": suggest_limit(machine(), load.speeds(), most=TABLE_LIMIT_MAX)}


@app.get("/api/admin/load")
def admin_load(days: int = 7, authorization: str | None = Header(None)):
    _admin(authorization)
    live_now, people = table_counts()
    return {"rows": load.rows(max(1, min(days, 30))), "limit": admin.table_limit(), "every": SAMPLE_EVERY,
            "now": {"tables": live_now, "people": people}, "machine": machine(), "speed": load.speeds()}


@app.post("/api/admin/tables/limit")
def admin_table_limit(body: dict = Body(...), authorization: str | None = Header(None)):
    user = _admin(authorization)
    try:
        n = admin.set_table_limit(body.get("tables"))
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    admin.log(user, "Set the table limit", str(n))
    return {"limit": n}


@app.post("/api/admin/tables/close")
async def admin_close_table(body: dict = Body(...), authorization: str | None = Header(None)):
    user = await asyncio.to_thread(_admin, authorization)
    code = str(body.get("code", "")).upper()
    room = await asyncio.to_thread(rooms.close, code)
    if room:
        for p in [*room.players.values(), *room.watchers.values()]:
            for send in list(p.connections):
                try:
                    await send({"type": "error", "message": f"Table {code} was closed", "fatal": True})
                except Exception:
                    pass
    await asyncio.to_thread(admin.log, user, "Closed a table", code)
    return {"ok": True}


@app.post("/api/admin/invites/cancel")
def admin_cancel_invite(body: dict = Body(...), authorization: str | None = Header(None)):
    user = _admin(authorization)
    try:
        admin.cancel_invite(str(body.get("code", "")))
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    admin.log(user, "Cancelled an invite", str(body.get("code", "")))
    return {"ok": True}


@app.get("/api/admin/feedback")
def admin_feedback(authorization: str | None = Header(None)):
    _admin(authorization)
    return {"items": list(reversed(feedback.all()))}


@app.post("/api/admin/feedback/mark")
def admin_mark_feedback(body: dict = Body(...), authorization: str | None = Header(None)):
    user = _admin(authorization)
    try:
        rec = feedback.mark(str(body.get("key", "")), str(body.get("status", "")))
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    admin.log(user, f"Marked a suggestion {rec['status']}", rec["text"][:80])
    return rec


@app.post("/api/admin/feedback/delete")
def admin_delete_feedback(body: dict = Body(...), authorization: str | None = Header(None)):
    user = _admin(authorization)
    feedback.delete(str(body.get("key", "")))
    admin.log(user, "Deleted a suggestion", str(body.get("key", "")))
    return {"ok": True}


@app.get("/api/admin/backups")
def admin_backups(authorization: str | None = Header(None)):
    _admin(authorization)
    try:
        files = backups.files()
    except Exception as exc:
        return {"files": [], "error": f"Couldn't reach the backups ({type(exc).__name__})", "last": backups.last}
    return {"files": files, "error": backups.error, "last": backups.last}


@app.post("/api/admin/backups/run")
async def admin_run_backup(authorization: str | None = Header(None)):
    user = await asyncio.to_thread(_admin, authorization)
    try:
        name = await asyncio.to_thread(backups.make, pacific_today())
    except Exception as exc:
        raise HTTPException(500, f"The backup didn't work ({type(exc).__name__})")
    backups.last = pacific_today().isoformat()
    await asyncio.to_thread(admin.log, user, "Made a backup", name)
    return {"name": name}


@app.get("/api/admin/backups/file")
def admin_download_backup(name: str, authorization: str | None = Header(None)):
    user = _admin(authorization, True)
    try:
        data = backups.read(name)
    except Exception:
        raise HTTPException(404, "no such backup")
    admin.log(user, "Downloaded a backup", name)
    return Response(data, media_type="application/gzip",
                    headers={"Content-Disposition": f'attachment; filename="{name}"', "Cache-Control": "no-store"})


@app.post("/api/admin/backups/restore")
async def admin_restore_backup(body: dict = Body(...), authorization: str | None = Header(None)):
    user = await asyncio.to_thread(_admin, authorization, True)
    name = str(body.get("name", ""))
    try:
        n, before = await asyncio.to_thread(backups.restore, name)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except Exception as exc:
        raise HTTPException(500, f"The restore didn't work ({type(exc).__name__})")
    admin.forget()
    push._keys = None
    limiter.blocked = (await asyncio.to_thread(store.get, "config", "cfg", "blocked") or {}).get("addresses", {})
    await asyncio.to_thread(admin.log, user, "Restored a backup", f"{name}: {n} records (copy first: {before})")
    return {"records": n, "before": before}


@app.get("/api/admin/safety")
def admin_safety(request: Request, authorization: str | None = Header(None)):
    _admin(authorization)
    return {**limiter.report(), "you": visitor(request.scope)}


def _save_blocked() -> None:
    store.put("config", "cfg", "blocked", {"addresses": limiter.blocked})


@app.post("/api/admin/safety/block")
def admin_block(request: Request, body: dict = Body(...), authorization: str | None = Header(None)):
    user = _admin(authorization)
    address = str(body.get("address", "")).strip()[:64]
    if not address:
        raise HTTPException(400, "Enter an address")
    if address == visitor(request.scope):
        raise HTTPException(400, "That's your own address right now")
    limiter.blocked[address] = {"at": time.time(), "note": str(body.get("note", ""))[:100]}
    _save_blocked()
    admin.log(user, "Blocked an address", address)
    return {"ok": True}


@app.post("/api/admin/safety/unblock")
def admin_unblock(body: dict = Body(...), authorization: str | None = Header(None)):
    user = _admin(authorization)
    address = str(body.get("address", ""))
    limiter.blocked.pop(address, None)
    limiter.misses.pop(address, None)  # also lifts a block for too many wrong table codes
    _save_blocked()
    admin.log(user, "Unblocked an address", address)
    return {"ok": True}


@app.get("/api/admin/notice")
def admin_notice_now(authorization: str | None = Header(None)):
    """The notice showing in everyone's lobby now (None if there isn't one), for the Admin page's Notice tab."""
    _admin(authorization)
    return {"notice": admin.notice()}


@app.post("/api/admin/notice")
async def admin_notice(request: Request, body: dict = Body(...), authorization: str | None = Header(None)):
    """Set (or, with no text, take down) the notice shown in everyone's lobby; optionally a phone notification too."""
    user = await asyncio.to_thread(_admin, authorization)
    try:
        notice = await asyncio.to_thread(admin.set_notice, str(body.get("text") or ""))
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    sent = 0
    if notice and body.get("push"):
        url = _origin(request).origin + "/"
        for u in await asyncio.to_thread(accounts.all_users):
            sent += bool(await asyncio.to_thread(push.send, u, site.app_name(), notice["text"], url))
    await asyncio.to_thread(admin.log, user, "Posted a notice" if notice else "Took down the notice",
                            (notice["text"] if notice else "") + (f" (notified {sent})" if sent else ""))
    return {"notice": notice, "notified": sent}


@app.get("/api/admin/log")
def admin_log(authorization: str | None = Header(None)):
    _admin(authorization)
    return {"rows": admin.log_rows()}


HELLO_WAIT = 10  # seconds a new socket has to say who it is; a phone does at once, an idle connection is let go


async def first_message(ws: WebSocket) -> dict | None:
    """A socket's first message, or None (the socket is then closed) if it doesn't come in time or isn't an object."""
    try:
        msg = await asyncio.wait_for(ws.receive_json(), HELLO_WAIT)
    except (asyncio.TimeoutError, ValueError):
        msg = None
    if not isinstance(msg, dict):
        await ws.close(code=1008)
        return None
    return msg


@app.websocket("/ws/presence")
async def presence_ws(ws: WebSocket):
    """One per signed-in phone while the app is open: keeps the friends list live and brings invites."""
    await ws.accept()

    async def send(msg: dict) -> None:
        await ws.send_json(msg)

    user = None
    try:
        hello = await first_message(ws)
        if hello is None:
            return
        user = await asyncio.to_thread(accounts.user_for, hello.get("token"))
        if not user:
            await send({"type": "error", "message": "Please sign in again", "fatal": True})
            await ws.close()
            return
        await social.connect(user["id"], send)
        await send(await asyncio.to_thread(social.friends_view, user["id"]))
        while True:
            msg = await ws.receive_json()
            if msg.get("type") == "ping":
                await send({"type": "pong"})
    except WebSocketDisconnect:
        pass
    finally:
        if user:
            await social.disconnect(user["id"], send)


@app.get("/api/conventions")
def conventions():
    return convention_list()


@app.get("/api/lessons")
def lessons():
    return lesson_list()


@app.get("/api/conventions/{conv_id}")
def convention_page(conv_id: str):
    """A convention's page, or a lesson on part of the base system (same shape, so the app shows both alike)."""
    if conv_id == SIGNALS:
        return SIGNALS_PAGE
    if conv_id == LEADS:
        return LEADS_PAGE
    conv = BY_ID.get(conv_id)
    lesson = LESSONS.get(conv_id)
    if not conv and not lesson:
        raise HTTPException(404, "no such convention")
    out = ({**conv.summary(), "lesson": lesson is not None} if conv else
           {"id": lesson.id, "title": lesson.title, "description": lesson.description, "default_on": True,
            "core": True, "lesson": True})
    if lesson:
        engine = make_engine({c.id for c in BY_ID.values() if c.default_on}
                             | (requirements(conv_id) if conv else set()))
        out["explainer"] = lesson.explainer
        out["examples"] = examples_for(engine, lesson)
        out["student"] = lesson.student
    return out


async def send_hint(room, seat: str, send) -> None:
    try:
        started = time.monotonic()
        hint = await room.hint(seat, later=send)  # a close call's firmer answer follows on its own
        if hint.get("phase") == "playing":  # a bidding hint is instant; the time is to the first answer
            load_timings.record("hint", time.monotonic() - started)
        await send(hint)
    except ValueError as exc:  # e.g. the turn moved on before the hint was asked for
        await send({"type": "error", "message": str(exc)})
    except Exception:  # the phone may have gone; nothing to tell it
        pass


@app.websocket("/ws/{code}")
async def play_ws(ws: WebSocket, code: str):
    await ws.accept()
    who = visitor(ws.scope)
    if limiter.too_many_misses(who):
        await ws.send_json({"type": "error", "fatal": True,
                            "message": "Too many wrong table codes. Please wait an hour and try again."})
        await ws.close()
        return
    room = await rooms.aget(code)
    if room is None:
        limiter.missed_code(who)
        # rooms live in memory, so a restart (each deploy) ends them: tell the phone to stop retrying
        await ws.send_json({"type": "error", "message": f"Room {code.upper()} has ended", "fatal": True})
        await ws.close()
        return

    async def send(msg: dict) -> None:
        await ws.send_json(msg)

    async def close() -> None:
        try:
            await ws.close()
        except Exception:
            pass

    send.close = close
    seat = user = token = None
    try:
        hello = await first_message(ws)
        if hello is None:
            return
        if hello.get("type") != "join":
            await send({"type": "error", "message": "first message must be join"})
            await ws.close()
            return
        user = await asyncio.to_thread(accounts.user_for, hello.get("auth")) if hello.get("auth") else None
        try:
            seat, token = room.join(user["name"] if user else str(hello.get("name", ""))[:24], hello.get("token"),
                                    hello.get("seat"), user["id"] if user else None)
        except ValueError as exc:
            await send({"type": "error", "message": str(exc), "fatal": True})
            await ws.close()
            return
        if hello.get("solo") and seat == "S" and len(room.players) == 1:
            room.update_settings(solo=True)
        if hello.get("watch") and seat is None:
            room.watch(token)
        device = str(hello.get("device") or "")[:40] or None
        device_name = str(hello.get("device_name") or "")[:24]
        elsewhere = room.hold(token, device, device_name, bool(hello.get("takeover")))
        if elsewhere:  # the game moved to another of their phones while this one slept: say so, don't take it back
            await send({"type": "moved", "to": elsewhere})
            await ws.close()
            return
        me = room.person(token)[1]
        for other in list(me.connections):  # the phone they were playing on shows "Playing on your iPad now"
            if device and getattr(other, "device", None) not in (None, device):
                me.connections.discard(other)
                try:
                    await other({"type": "moved", "to": device_name or "another device"})
                except Exception:
                    pass
        send.device = device
        send.carry = bool(hello.get("carry"))  # the app keeps the table to carry on offline (Room.carriable)
        me.connections.add(send)
        if user:
            await social.sit(user["id"], send, room.code)
        await send({"type": "joined", "room": room.code, "seat": seat, "token": token})
        if room.table is None and room.can_start():
            room.new_board()
        await room.broadcast()
        room.kick_bots()
        hinting: asyncio.Task | None = None
        while True:
            msg = await ws.receive_json()
            if msg.get("type") == "ping":  # the app checking the connection is still alive
                await send({"type": "pong", "rev": room.rev})  # and whether it has seen the latest update
                continue
            seat, me = room.person(token)  # sitting down, standing up or changing seats moves you
            if device and me and me.device != device:  # moved to another phone: this one can't play for them now
                await send({"type": "moved", "to": me.device_name or "another device"})
                break
            if msg.get("type") == "sync":  # the phone missed an update (see the pong): send the table as it is now
                if me:
                    me.connections.add(send)
                await send(room.state_for(seat, me))
                continue
            if me and msg.get("type") != "away":  # Leave doesn't count as playing, so it doesn't restart the clock
                me.last = time.time()
            if msg.get("type") == "away":  # tapped Leave: the app opened elsewhere shows the lobby, not this table
                if me:
                    me.away = True
                    room.on_change and room.on_change(room)
                    await room.recheck_ready()  # the others needn't wait for them to tap Next board
                continue
            try:
                if msg.get("type") == "hint":
                    if seat is None:
                        raise ValueError("take a seat to play")
                    # worked out on the side, so a card played while it thinks is still read straight away
                    if hinting is None or hinting.done():
                        hinting = asyncio.create_task(send_hint(room, seat, send))
                    continue
                await room.handle(seat, msg, token)
                if msg.get("id"):  # a call or card the app keeps sending until it hears back (Room._fresh)
                    await send({"type": "ack", "id": msg["id"]})
            except ValueError as exc:
                await send({"type": "error", "message": str(exc), **({"id": msg["id"]} if msg.get("id") else {})})
    except WebSocketDisconnect:
        pass
    finally:
        if user:
            await social.stand(user["id"], send)
        p = room.person(token)[1] if token else None
        if p:
            p.connections.discard(send)
            p.last = time.time()
            if not p.connections and room.person(token)[0]:  # gone from a seat: the others hear in 3 minutes
                asyncio.create_task(room.broadcast_when_away())
            try:
                await room.recheck_ready()  # the others needn't wait for someone who closed the app
            except Exception:
                pass


def named_page(text: str) -> str:
    """The web app's index.html with this site's name (BRIDGE_APP_NAME) as its title and Home Screen name, which the
    app's own text then reads from the page, and where its open source code is (BRIDGE_SOURCE_URL), for What's new."""
    name = html.escape(site.app_name())
    source = html.escape(site.source_url() or "")
    text = re.sub(r"<title>[^<]*</title>", f"<title>{name}</title>", text, count=1)
    text = re.sub(r'(<meta name="source-url" content=")[^"]*(")', lambda m: m[1] + source + m[2], text, count=1)
    return re.sub(r'(<meta name="apple-mobile-web-app-title" content=")[^"]*(")', lambda m: m[1] + name + m[2], text,
                  count=1)


def named_manifest(text: str) -> str:
    """manifest.webmanifest with this site's name, which Android and the Home Screen show."""
    data = json.loads(text)
    data["name"] = data["short_name"] = site.app_name()
    return json.dumps(data, ensure_ascii=False, indent=2)


def web_response(path: str) -> Response:
    """A file of the built web app; the page itself (with this site's name) for any other address."""
    if path == "manifest.webmanifest":
        return Response(named_manifest((WEB_DIST / path).read_text()), media_type="application/manifest+json",
                        headers={"Cache-Control": "no-cache"})
    f = web_file(WEB_DIST, path) if path != "index.html" else None
    if f:
        return FileResponse(f)
    # always check for a newer page, so a Home Screen app picks up a new version when it is reopened
    return Response(named_page((WEB_DIST / "index.html").read_text()), media_type="text/html",
                    headers={"Cache-Control": "no-cache"})


def web_file(root: Path, path: str) -> Path | None:
    """The file at `path` inside the web folder, or None. Never anything outside it: "../" (or %2f-encoded slashes)
    must not reach the rest of the server."""
    f = (root / path).resolve()
    return f if path and f.is_relative_to(root.resolve()) and f.is_file() else None


# --- the AI connector (connector.py): a player's own Claude or ChatGPT reads their finished boards ---------------
@app.exception_handler(OAuthError)
async def oauth_error(_request, exc: OAuthError):
    return JSONResponse(exc.body(), status_code=exc.status, headers={"Cache-Control": "no-store"})


@app.get("/.well-known/oauth-protected-resource")
@app.get("/.well-known/oauth-protected-resource/mcp")
def oauth_resource(request: Request):
    return connector.resource_metadata(_origin(request).origin)


@app.get("/.well-known/oauth-authorization-server")
def oauth_server(request: Request):
    return connector.server_metadata(_origin(request).origin)


@app.post("/oauth/register", status_code=201)
def oauth_register(body: dict = Body(...)):
    return connector.register(body)


@app.get("/oauth/authorize")
def oauth_authorize(request: Request):
    try:
        rid = connector.authorize(dict(request.query_params))
    except OAuthError as exc:  # never sent back to the AI app: its return address may be the problem
        return Response(f"{site.app_name()} can't connect: {exc.description}", status_code=exc.status,
                        media_type="text/plain")
    return Response(status_code=302, headers={"Location": f"/?connect={rid}", "Cache-Control": "no-store"})


@app.post("/oauth/token")
async def oauth_token(request: Request):
    raw = (await request.body()).decode("utf-8", "replace")
    form = json.loads(raw) if raw.startswith("{") else dict(parse_qsl(raw))
    basic = None
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("basic "):
        try:
            who, _, secret = base64.b64decode(auth[6:]).decode().partition(":")
            basic = (unquote(who), unquote(secret))
        except ValueError:
            raise OAuthError("invalid_client", "Bad client credentials", 401)
    out = await asyncio.to_thread(connector.token, {k: str(v) for k, v in form.items()}, basic)
    return JSONResponse(out, headers={"Cache-Control": "no-store"})


@app.get("/api/connect/{rid}")
def connect_request(rid: str):
    return connector.request_info(rid)


@app.post("/api/connect/approve")
def connect_approve(body: dict = Body(...), authorization: str | None = Header(None)):
    user = _signed_in(authorization)
    return {"redirect": connector.approve(user, str(body.get("request", "")), bool(body.get("allow")))}


@app.get("/api/me/ai")
def ai_connections(authorization: str | None = Header(None)):
    return connector.connections(_signed_in(authorization))


@app.post("/api/me/ai/remove")
def ai_disconnect(body: dict = Body(...), authorization: str | None = Header(None)):
    user = _signed_in(authorization)
    connector.disconnect(user, str(body.get("id", "")))
    return connector.connections(user)


@app.post("/mcp")
async def mcp(request: Request, authorization: str | None = Header(None)):
    token = (authorization or "").removeprefix("Bearer ").strip()
    user = await asyncio.to_thread(connector.user_for, token) if token else None
    if not user:
        meta = f"{_origin(request).origin}/.well-known/oauth-protected-resource/mcp"
        return JSONResponse({"error": "invalid_token"}, status_code=401, headers={
            "WWW-Authenticate": f'Bearer resource_metadata="{meta}", scope="bridge"'})
    try:
        msg = json.loads(await request.body())
    except ValueError:
        return JSONResponse({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}},
                            status_code=400)
    reply = await connector.handle(user, msg, published_version(), connector.grant_of(token))
    return JSONResponse(reply) if reply else Response(status_code=202)


@app.get("/mcp")
@app.delete("/mcp")
def mcp_other():
    return Response(status_code=405, headers={"Allow": "POST"})


@app.get("/offline/engine.zip")
def offline_engine(request: Request):
    """The game for the app's offline engine (bridge/offline.py). The app asks for it with its own version in the
    address, and keeps it until a newer version comes."""
    data, tag = offline.bundle()
    etag = f'"{tag}"'
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers={"ETag": etag})
    return Response(data, media_type="application/zip", headers={"ETag": etag, "Cache-Control": "no-cache"})


if WEB_DIST.exists():
    app.mount("/assets", StaticFiles(directory=WEB_DIST / "assets"), name="assets")

    @app.get("/{path:path}")
    def spa(path: str):
        if path == "api" or path.startswith("api/"):  # an API address that doesn't exist is not a page
            raise HTTPException(404, "not found")
        return web_response(path)
else:
    @app.get("/")
    def no_client():
        return JSONResponse({"message": "web client not built: cd web && npm install && "
                                        "npm run build"})
