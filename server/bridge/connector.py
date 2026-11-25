"""The AI connector: lets a player's own AI app (Claude first, ChatGPT and others later) read their finished boards and
the app's review of them, so they can talk a hand through with it, by text or by voice. Their AI subscription pays;
this server makes no AI calls of its own.

It is a standard MCP server (Streamable HTTP, JSON replies) at /mcp, with the small OAuth 2.1 sign-in that MCP asks
for: the AI app registers itself (/oauth/register), sends the player here to sign in with their passkey and tap Allow
(/oauth/authorize, then the ?connect= page in the web app), and swaps the code it gets back for tokens (/oauth/token).

Only AI apps whose sign-in return address is on the allowed list can connect (REDIRECTS, plus any in
BRIDGE_CONNECTOR_REDIRECTS, comma separated), so a look-alike site can't collect a player's boards. Each
connection is a "grant" kept with the account: the player can remove it in their account sheet, and Sign out other
phones ends every one. Everything is read only, apart from the player's own "working on" notes (coaching_notes).
"""
from __future__ import annotations

import asyncio
import base64
import datetime as dt
import hashlib
import hmac
import json
import os
import re
import secrets
import time
from urllib.parse import urlencode, urlsplit
from zoneinfo import ZoneInfo

from . import site
from .coach import board_sheet, contract_text, hint_sheet, instructions, table_sheet
from .puzzles import Puzzles
from .stats import own_play, stats_from_facts
from .trends import bidding_rows, filter_boards, in_range, mistakes, overview, when

# Where each AI app wants the player sent back after tapping Allow, and what to call it on the Allow page.
REDIRECTS = {
    "https://claude.ai/api/mcp/auth_callback": "Claude",
    "https://claude.com/api/mcp/auth_callback": "Claude",
    "https://chatgpt.com/connector_platform_oauth_redirect": "ChatGPT",
}
# ChatGPT now gives each app its own return address, https://chatgpt.com/connector/oauth/<id>; the old one above still
# works for apps added before the change.
PATTERNS = [(re.compile(r"https://chatgpt\.com/connector/oauth/[A-Za-z0-9_-]{1,128}"), "ChatGPT")]
REQUEST_LIFE = 15 * 60  # from the AI app sending the player here to tapping Allow
CODE_LIFE = 5 * 60
ACCESS_LIFE = 3600
GRANT_LIFE = 90 * 24 * 3600  # a connection not used for this long has to sign in again
MAX_PENDING = 1000
MAX_CLIENTS = 500
MAX_NOTES = 10  # "working on" notes an AI coach may keep with an account
CALLS_PER_HOUR = 200  # tool calls per player: plenty for a conversation, not for a script
PACIFIC = ZoneInfo("America/Los_Angeles")
PROTOCOLS = ("2025-11-25", "2025-06-18", "2025-03-26")  # MCP versions this server speaks, newest first


def slug(name: str) -> str:
    """The site's name as an MCP server name: "Card Club" -> "card-club"."""
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "bridge"


class OAuthError(Exception):
    def __init__(self, error: str, description: str = "", status: int = 400):
        super().__init__(description or error)
        self.error, self.description, self.status = error, description, status

    def body(self) -> dict:
        return {"error": self.error, **({"error_description": self.description} if self.description else {})}


def _hash(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def allowed_redirects() -> dict[str, str]:
    extra = {u.strip(): urlsplit(u.strip()).hostname or "an AI app"
             for u in os.environ.get("BRIDGE_CONNECTOR_REDIRECTS", "").split(",") if u.strip()}
    return {**REDIRECTS, **extra}


def redirect_app(uri: str) -> str | None:
    """The AI app a sign-in return address belongs to, or None if it isn't one we connect to."""
    if (app := allowed_redirects().get(uri)):
        return app
    return next((app for pat, app in PATTERNS if pat.fullmatch(uri)), None)

# What each field a tool returns means, where the name alone doesn't say (tests/test_connector_fields.py checks that
# every field a tool returns is described here or plain from its name). They go at the end of the tool's description,
# so the AI reads the numbers the way the app means them.
SECOND_TABLE = ("The second table is the same deal played again, as at a team match, with a level 10 bot in the "
                "player's seat and the other three seats as at their table (a bot at the table's level stands in for "
                "any other person). Both results are scored at duplicate and the difference turned into IMPs on the "
                "standard 0-24 scale; plus means the player did better than the level 10 bot.")
STATS_FIELDS = {
    "days": "the days looked back",
    "now": "the figures for those days",
    "before": "the same figures for the stretch of days just before, to compare (null if none)",
    "boards": "boards finished",
    "all_boards": "boards finished before any were left out",
    "second_imps": "IMPs per board against the second table, averaged (null until a board has one)",
    "second_boards": "boards that have a second table result",
    "second_bidding": "the bidding's share of second_imps per board: both contracts scored as if played with every "
                      "card seen, so the card play doesn't count",
    "second_declaring": "the play's share (second_imps minus the bidding's share) per board, on boards the "
                        "player's side declared (including when their partner declared)",
    "second_defending": "the play's share per board on boards the other side declared; partner's defense and the "
                        "other table's bots count too",
    "vs_par": "average score against double-dummy par per board (plus beats par)",
    "at_or_above_par": "percent of boards scoring at or above par",
    "declared": "hands the player declared",
    "makeable": "of those, contracts that make with every card seen",
    "made": "of the makeable ones, how many the player made",
    "declarer_lost": "tricks lost per hand against double dummy as declarer (dummy's cards too)",
    "defended": "hands the player defended",
    "defender_lost": "tricks given away per hand against double dummy on defense",
    "leads": "opening leads the player made",
    "costly_leads": "opening leads that let declarer take one more trick double dummy",
    "off_system_per_10": "calls off the system per 10 boards",
    "off_system_by": "the bidding areas with most calls off the system, as [area, count]",
    "off_system_points": "points per off-system call that decided the contract (nobody bid after), against the "
                         "contract the system's call would have reached, both double dummy (plus: leaving the system "
                         "helped)",
    "off_system_helped": "off-system calls that scored better than the system's call",
    "off_system_cost": "off-system calls that scored worse",
    "off_system_same": "off-system calls that made no difference",
    "hints_per_board": "hints used per board (counted over all boards)",
    "undos_per_board": "undos per board (all boards)",
    "coach_per_board": "AI coach questions on the player's turn per board (all boards)",
    "trend": "score against par per day, oldest first",
    "day": "the day, YYYY-MM-DD",
    "level": "the player's level on the bots' 1 to 10 scale, from their most recent hands as declarer or defender "
             "(level.level overall, level.low and level.high the 95% range, level.declaring and level.defending "
             "each role; null until level.hands reaches level.needed)",
    "low": "the bottom of the level's 95% range",
    "high": "the top of the level's 95% range",
    "declaring": "the level as declarer (1 to 10)",
    "defending": "the level on defense (1 to 10)",
    "hands": "hands the level is worked out from",
    "needed": "hands needed before a level is shown",
    "bots": "the bot level at the player's latest table",
    "left_out": "help that removed boards from the figures (always empty here)",
}
BOARD_SECOND_FIELDS = {
    "second_table": "the same deal at the second table (missing until it has been played, a few minutes after the "
                    "board)",
    "bot_level_in_your_seat": "always 10",
    "other_bots_level": "the level of the bots in the other seats",
    "their_auction": "the second table's auction, with what each call meant",
    "their_contract": "the contract the second table reached",
    "their_result": "how many tricks it made",
    "their_score_for_you": "its duplicate score for the player's side",
    "your_score_at_duplicate": "the player's own result scored the same way",
    "imps_for_you": "your_score_at_duplicate against their_score_for_you in IMPs (plus: the player did better)",
    "bidding_imps": "the bidding's share of imps_for_you: both contracts scored as if played with every card seen",
    "play_imps": "the rest of imps_for_you: the card play at both tables",
    "second_table_imps": "IMPs against the second table (null until it has been played)",
}
# In the example boards that coaching_overview and mistake_patterns quote
EXAMPLE_FIELDS = {
    "better": "the cards that would have lost nothing, double dummy",
    "after": "the help the player asked for right before choosing (a hint or an AI coach question)",
    "led": "the opening lead",
    "best": "the opening leads that would have lost nothing, double dummy",
    "holding": "the player's cards in the suit they led from",
    "against": "notrump or a suit contract",
}
BOARD_FIELDS = {k: v for k, v in BOARD_SECOND_FIELDS.items() if k != "second_table_imps"}
# coaching_overview's your_mistakes (puzzles.py)
PUZZLE_FIELDS = {
    "your_mistakes": "the app's Your mistakes puzzles: the player's own past cards marked mistake and calls that cost "
                     "on average, set up again at that spot for them to answer (all time, whatever stretch is asked; "
                     "kept out of my_stats)",
    "waiting": "puzzles ready to try now",
    "kinds": "the waiting puzzles by kind, as the player can pick them to practice: bidding (calls), suit and notrump "
             "(declarer play in that kind of contract), leads (opening leads) and defense (the rest of defense, in any "
             "contract)",
    "tried": "puzzles answered at least once",
    "right": "right answers so far (a card is right unless clearly worse on the odds than the best one; a call is "
             "right when it's the system's)",
    "wrong": "wrong answers so far (each brings that puzzle back in 3 days)",
    "done": "puzzles answered right twice, which then stop coming back",
    "removed": "puzzles the player removed after a wrong answer because they disagree it was a mistake; they never "
               "come back (worth asking about: the player may have a point, or may be missing the idea)",
}


def fields_text(fields: dict[str, str]) -> str:
    """A field guide for the end of a tool's description."""
    return " Fields: " + "; ".join(f"{k}: {v}" for k, v in fields.items()) + "."


TOOLS = [
    {"name": "last_board_review",
     "title": "Review my last board",
     "description": "The board the player finished most recently: all four hands, the auction with what each call "
                    "meant in the app's system, the play trick by trick, the result, double-dummy par, and the "
                    "app's review (calls that differed from the system, cards that cost tricks, each marked "
                    "mistake or unlucky with its odds), and the same deal at the second table. Use this first when "
                    "the player asks about 'that hand' or 'the last board'. " + SECOND_TABLE
                    + fields_text(BOARD_FIELDS),
     "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
     "annotations": {"readOnlyHint": True, "openWorldHint": False}},
    {"name": "recent_boards",
     "title": "My boards",
     "description": "The player's finished boards, newest first, a page at a time: when, contract, result, score, "
                    "par, IMPs against the second table, and a key to pass to board_review or board_reviews. Covers "
                    "every saved board; filter by dates, role, contract and calls off the system, and pass "
                    "next_cursor to get the next page. " + SECOND_TABLE
                    + fields_text({"second_table_imps": BOARD_SECOND_FIELDS["second_table_imps"]}),
     "inputSchema": {"type": "object", "properties": {
         "limit": {"type": "integer", "minimum": 1, "maximum": 50, "description": "Boards per page (default 10)"},
         "cursor": {"type": "string", "description": "next_cursor from the previous page"},
         "role": {"type": "string", "enum": ["declarer", "dummy", "defender"], "description": "Only boards in this role"},
         "since": {"type": "string", "description": "First day, YYYY-MM-DD (Pacific time)"},
         "until": {"type": "string", "description": "Last day, YYYY-MM-DD (Pacific time)"},
         "min_level": {"type": "integer", "minimum": 1, "maximum": 7, "description": "Lowest contract level"},
         "max_level": {"type": "integer", "minimum": 1, "maximum": 7, "description": "Highest contract level"},
         "strain": {"type": "string", "enum": ["S", "H", "D", "C", "N"], "description": "Only contracts in this strain"},
         "off_system": {"type": "boolean", "description": "true: only boards where the player left the system; "
                                                         "false: only boards where they didn't"},
         "partner": {"type": "string", "enum": ["bot", "person"], "description": "Only boards with this partner"}},
         "additionalProperties": False},
     "annotations": {"readOnlyHint": True, "openWorldHint": False}},
    {"name": "board_review",
     "title": "Review a board",
     "description": "The full review of one of the player's finished boards, by the key from recent_boards. Same "
                    "contents as last_board_review." + fields_text(BOARD_FIELDS),
     "inputSchema": {"type": "object", "properties": {"key": {"type": "string"}}, "required": ["key"],
                     "additionalProperties": False},
     "annotations": {"readOnlyHint": True, "openWorldHint": False}},
    {"name": "board_reviews",
     "title": "Review several boards",
     "description": "Full reviews of up to 10 boards in one call, by their keys from recent_boards or the examples "
                    "in coaching_overview and mistake_patterns. Same contents as last_board_review."
                    + fields_text(BOARD_FIELDS),
     "inputSchema": {"type": "object", "properties": {
         "keys": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 10}},
         "required": ["keys"], "additionalProperties": False},
     "annotations": {"readOnlyHint": True, "openWorldHint": False}},
    {"name": "coaching_overview",
     "title": "Coaching overview",
     "description": "Start here to look for patterns. Rates over any stretch of boards (all of them by default): "
                    "tricks lost per hand as declarer and defender next to the app's bots at each level, makeable "
                    "contracts made (notrump vs suit, part score vs game vs slam), opening leads by what they were "
                    "led from and how often they cost, costly cards by kind, bidding areas where the player leaves "
                    "the system with how those boards scored against par, hints, undos and the first choices they "
                    "took back, their level, their 'working on' notes, and how they do at Your mistakes. Each group "
                    "quotes example boards."
                    + fields_text({**EXAMPLE_FIELDS, **PUZZLE_FIELDS}),
     "inputSchema": {"type": "object", "properties": {
         "since": {"type": "string", "description": "First day, YYYY-MM-DD (Pacific time)"},
         "until": {"type": "string", "description": "Last day, YYYY-MM-DD (Pacific time)"},
         "days": {"type": "integer", "minimum": 1, "maximum": 3650, "description": "Or: the last this many days"},
         "own_play_only": {"type": "boolean", "description": "Leave out calls and cards made right after a hint or "
                                                            "an AI coach question (marked from version 1.88 on)"}},
         "additionalProperties": False},
     "annotations": {"readOnlyHint": True, "openWorldHint": False}},
    {"name": "mistake_patterns",
     "title": "Mistake patterns",
     "description": "Cards that cost tricks double dummy, grouped across boards: by role (declarer, defender), by "
                    "kind (opening lead, later lead, follow, ruff, discard), those involving trumps, and counting "
                    "checks (led a trump when the opponents had none, discarded a sure winner, ruffed partner's "
                    "winning trick). Rates are costly cards out of all cards of that kind the player chose; each "
                    "card is marked mistake or unlucky where the odds are known. Examples carry board keys."
                    + fields_text(EXAMPLE_FIELDS),
     "inputSchema": {"type": "object", "properties": {
         "since": {"type": "string", "description": "First day, YYYY-MM-DD (Pacific time)"},
         "until": {"type": "string", "description": "Last day, YYYY-MM-DD (Pacific time)"},
         "days": {"type": "integer", "minimum": 1, "maximum": 3650, "description": "Or: the last this many days"},
         "whose": {"type": "string", "enum": ["you", "bot partner"], "description": "The player's cards (default) or "
                                                                                 "their bot partner's on defense"},
         "own_play_only": {"type": "boolean", "description": "Leave out cards played right after a hint or an AI "
                                                            "coach question"},
         "examples": {"type": "integer", "minimum": 0, "maximum": 10, "description": "Example boards per group (default 3)"}},
         "additionalProperties": False},
     "annotations": {"readOnlyHint": True, "openWorldHint": False}},
    {"name": "bidding_history",
     "title": "My bidding",
     "description": "The player's calls across boards, a page of boards at a time: for each, their hand, the "
                    "auction before the call, what it meant, the system's call and meaning when it differed, "
                    "whether they asked for help first, and how the board ended (contract, tricks, double-dummy "
                    "tricks, score and par). By default only calls that left the system; set all_calls for every call.",
     "inputSchema": {"type": "object", "properties": {
         "since": {"type": "string", "description": "First day, YYYY-MM-DD (Pacific time)"},
         "until": {"type": "string", "description": "Last day, YYYY-MM-DD (Pacific time)"},
         "all_calls": {"type": "boolean", "description": "Every call, not only those off the system"},
         "include_small_differences": {"type": "boolean", "description": "Also calls the system allows but wouldn't "
                                                                        "pick first (left out by default)"},
         "boards": {"type": "integer", "minimum": 1, "maximum": 40, "description": "Boards per page (default 20)"},
         "cursor": {"type": "string", "description": "next_cursor from the previous page"}},
         "additionalProperties": False},
     "annotations": {"readOnlyHint": True, "openWorldHint": False}},
    {"name": "coaching_notes",
     "title": "My 'working on' notes",
     "description": "Short notes on what the player is working on (for example 'count trumps before drawing the "
                    "last one'), kept with their account so a later conversation can check whether that area got "
                    "better. list shows them; add saves one (agree the wording with the player first); remove "
                    "deletes one by its id. At most 10 notes.",
     "inputSchema": {"type": "object", "properties": {
         "action": {"type": "string", "enum": ["list", "add", "remove"]},
         "text": {"type": "string", "maxLength": 300, "description": "For add: the note"},
         "id": {"type": "string", "description": "For remove: the note's id"}},
         "required": ["action"], "additionalProperties": False},
     "annotations": {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False,
                     "openWorldHint": False}},
    {"name": "current_board",
     "title": "My current board",
     "description": "The board the player is playing right now, exactly as their seat sees it: their hand, dummy "
                    "once it's down, the auction with meanings, the tricks so far, and the calls or cards they may "
                    "choose from. Only works when their table allows AI coaching during play. Asking while it's "
                    "their turn is counted as AI coach help in their review.",
     "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
     "annotations": {"readOnlyHint": True, "openWorldHint": False}},
    {"name": "app_hint",
     "title": "Ask the app's hint",
     "description": "The app's own Hint for the player's turn on the current board: the system's call, or the "
                    "strongest bot's card with how often it makes or beats the contract, judged only on what the "
                    "player can see. Counts as a hint, as if they had tapped Hint. Needs AI coaching during play "
                    "and hints both allowed at the table.",
     "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
     "annotations": {"readOnlyHint": True, "openWorldHint": False}},
    {"name": "my_stats",
     "title": "My stats",
     "description": "The player's results over recent days, as on the app's My stats: boards played, contracts "
                    "made, tricks lost against double dummy, opening-lead costs, calls off the system, hints and "
                    "undos used, their level on the bots' 1 to 10 scale, and IMPs per board against the second "
                    "table, split into bidding, declaring and defending. Score against par scores each board the "
                    "same way as par: game and part-score bonuses on the board, and at rubber the part score "
                    "already below the line counts towards game. " + SECOND_TABLE + " A single board says more "
                    "about the cards than the player; the averages over many boards are the measure."
                    + fields_text(STATS_FIELDS),
     "inputSchema": {"type": "object", "properties": {
         "days": {"type": "integer", "minimum": 1, "maximum": 365, "description": "Days to look back (default 30)"},
         "own_play_only": {"type": "boolean", "description": "Leave out calls and cards made right after a hint or "
                                                            "an AI coach question (marked from version 1.88 on)"}},
         "additionalProperties": False},
     "annotations": {"readOnlyHint": True, "openWorldHint": False}},
]


class Connector:
    def __init__(self, store, accounts, rooms):
        self.store = store
        self.accounts = accounts
        self.rooms = rooms
        self.pending: dict[str, dict] = {}  # sign-ins waiting for the player to tap Allow
        self.codes: dict[str, dict] = {}  # one-use codes the AI app swaps for tokens
        self.calls: dict[str, list[float]] = {}  # tool calls per player in the last hour

    # --- discovery: how an AI app finds out where to sign in ---------------------------------------
    @staticmethod
    def resource_metadata(origin: str) -> dict:
        return {"resource": f"{origin}/mcp", "authorization_servers": [origin], "scopes_supported": ["bridge"],
                "bearer_methods_supported": ["header"], "resource_name": site.app_name()}

    @staticmethod
    def server_metadata(origin: str) -> dict:
        return {"issuer": origin,
                "authorization_endpoint": f"{origin}/oauth/authorize",
                "token_endpoint": f"{origin}/oauth/token",
                "registration_endpoint": f"{origin}/oauth/register",
                "response_types_supported": ["code"],
                "grant_types_supported": ["authorization_code", "refresh_token"],
                "code_challenge_methods_supported": ["S256"],
                "token_endpoint_auth_methods_supported": ["none", "client_secret_post", "client_secret_basic"],
                "scopes_supported": ["bridge"]}

    # --- registration -------------------------------------------------------------------------------
    def register(self, body: dict) -> dict:
        uris = body.get("redirect_uris")
        if not isinstance(uris, list) or not uris or not all(isinstance(u, str) for u in uris):
            raise OAuthError("invalid_redirect_uri", "redirect_uris is required")
        apps = [redirect_app(u) for u in uris]
        if not all(apps):
            raise OAuthError("invalid_redirect_uri", f"This AI app isn't one {site.app_name()} connects to yet.")
        if len(self.store.query("aiclients", "c")) >= MAX_CLIENTS:
            raise OAuthError("temporarily_unavailable", "Too many apps registered. Please try again later.", 503)
        method = body.get("token_endpoint_auth_method") or "none"
        if method not in ("none", "client_secret_post", "client_secret_basic"):
            method = "none"
        client_id = secrets.token_urlsafe(16)
        row = {"redirect_uris": uris, "app": apps[0], "method": method, "created": time.time(),
               "name": str(body.get("client_name") or "")[:80]}
        out = {"client_id": client_id, "client_id_issued_at": int(row["created"]), "redirect_uris": uris,
               "grant_types": ["authorization_code", "refresh_token"], "response_types": ["code"],
               "token_endpoint_auth_method": method}
        if method != "none":
            secret = secrets.token_urlsafe(32)
            row["secret"] = _hash(secret)
            out["client_secret"] = secret
            out["client_secret_expires_at"] = 0
        if body.get("client_name"):
            out["client_name"] = row["name"]
        self.store.put("aiclients", "c", client_id, row)
        return out

    def _client(self, client_id: str) -> dict | None:
        return self.store.get("aiclients", "c", str(client_id)) if client_id else None

    # --- the player says yes ------------------------------------------------------------------------
    def authorize(self, q: dict) -> str:
        """Checks the AI app's sign-in request and keeps it until the player taps Allow; returns its id. Never sends
        the player back to an address that isn't the app's own registered one."""
        client = self._client(q.get("client_id", ""))
        if not client:
            raise OAuthError("invalid_client", "This AI app isn't registered. Remove the connector and add it again.")
        redirect = q.get("redirect_uri") or (client["redirect_uris"][0] if len(client["redirect_uris"]) == 1 else "")
        if redirect not in client["redirect_uris"] or not redirect_app(redirect):
            raise OAuthError("invalid_request", "That return address doesn't belong to this AI app.")
        if q.get("response_type") != "code":
            raise OAuthError("unsupported_response_type", "Only response_type=code is supported.")
        if q.get("code_challenge_method") != "S256" or not q.get("code_challenge"):
            raise OAuthError("invalid_request", "PKCE with S256 is required.")
        now = time.time()
        self.pending = {k: v for k, v in self.pending.items() if v["exp"] > now}
        if len(self.pending) >= MAX_PENDING:
            raise OAuthError("temporarily_unavailable", "Too many sign-ins at once. Please try again shortly.", 503)
        rid = secrets.token_urlsafe(16)
        self.pending[rid] = {"client": q["client_id"], "app": client["app"], "redirect": redirect,
                             "challenge": q["code_challenge"], "state": q.get("state"), "exp": now + REQUEST_LIFE}
        return rid

    def request_info(self, rid: str) -> dict:
        req = self.pending.get(rid)
        if not req or req["exp"] < time.time():
            raise OAuthError("invalid_request", "This sign-in has expired. Start again from your AI app.", 404)
        return {"app": req["app"]}

    def approve(self, user: dict, rid: str, allow: bool) -> str:
        """The address to send the player back to, with a code (Allow) or access_denied (Don't allow)."""
        req = self.pending.pop(rid, None)
        if not req or req["exp"] < time.time():
            raise OAuthError("invalid_request", "This sign-in has expired. Start again from your AI app.", 404)
        params = {"state": req["state"]} if req["state"] is not None else {}
        if allow:
            code = secrets.token_urlsafe(24)
            now = time.time()
            self.codes = {k: v for k, v in self.codes.items() if v["exp"] > now}
            self.codes[code] = {"user": user["id"], "client": req["client"], "app": req["app"],
                                "redirect": req["redirect"], "challenge": req["challenge"], "exp": now + CODE_LIFE}
            params = {"code": code, **params}
        else:
            params = {"error": "access_denied", **params}
        return req["redirect"] + ("&" if "?" in req["redirect"] else "?") + urlencode(params)

    # --- tokens -------------------------------------------------------------------------------------
    def _check_client(self, form: dict, basic: tuple[str, str] | None) -> tuple[str, dict]:
        client_id = (basic[0] if basic else None) or form.get("client_id", "")
        client = self._client(client_id)
        if not client:
            raise OAuthError("invalid_client", "Unknown client", 401)
        if client.get("secret"):
            given = (basic[1] if basic else None) or form.get("client_secret", "")
            if not hmac.compare_digest(_hash(given), client["secret"]):
                raise OAuthError("invalid_client", "Wrong client secret", 401)
        return client_id, client

    def token(self, form: dict, basic: tuple[str, str] | None = None) -> dict:
        client_id, client = self._check_client(form, basic)
        kind = form.get("grant_type")
        if kind == "authorization_code":
            got = self.codes.pop(form.get("code", ""), None)
            if not got or got["exp"] < time.time() or got["client"] != client_id:
                raise OAuthError("invalid_grant", "That code has expired or was already used.")
            if form.get("redirect_uri") and form["redirect_uri"] != got["redirect"]:
                raise OAuthError("invalid_grant", "Return address doesn't match.")
            verifier = form.get("code_verifier", "")
            check = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
            if not verifier or not hmac.compare_digest(check, got["challenge"]):
                raise OAuthError("invalid_grant", "PKCE check failed.")
            user = self.accounts.user(got["user"])
            if not user:
                raise OAuthError("invalid_grant", "This account no longer exists.")
            gid = secrets.token_urlsafe(12)
            grant = {"client": client_id, "app": got["app"], "gen": user.get("gen", 0), "created": time.time()}
            return self._issue(user["id"], gid, grant)
        if kind == "refresh_token":
            uid, gid, secret = (form.get("refresh_token", "").split(".") + ["", "", ""])[:3]
            grant = self.store.get("aigrants", uid, gid) if uid and gid else None
            user = self.accounts.user(uid) if grant else None
            if (not grant or not user or grant.get("client") != client_id or grant.get("gen", 0) != user.get("gen", 0)
                    or time.time() - grant.get("refreshed", grant["created"]) > GRANT_LIFE
                    or not hmac.compare_digest(_hash(secret), grant.get("refresh", ""))):
                raise OAuthError("invalid_grant", "Please connect again.")
            return self._issue(uid, gid, grant)
        raise OAuthError("unsupported_grant_type")

    def _issue(self, uid: str, gid: str, grant: dict) -> dict:
        refresh = secrets.token_urlsafe(32)
        now = time.time()
        self.store.put("aigrants", uid, gid, {**grant, "refresh": _hash(refresh), "refreshed": now})
        return {"access_token": self._access(uid, gid, now), "token_type": "Bearer", "expires_in": ACCESS_LIFE,
                "refresh_token": f"{uid}.{gid}.{refresh}", "scope": "bridge"}

    # Access tokens are signed like the app's own sign-in tokens, but start "ai1." and carry the grant, so neither kind
    # works in place of the other.
    def _access(self, uid: str, gid: str, issued: float) -> str:
        body = f"ai1.{uid}.{gid}.{int(issued)}"
        return f"{body}.{hmac.new(self.accounts.secret(), body.encode(), hashlib.sha256).hexdigest()[:32]}"

    def user_for(self, token: str | None) -> dict | None:
        try:
            prefix, uid, gid, issued, sig = str(token).split(".")
        except ValueError:
            return None
        body = f"{prefix}.{uid}.{gid}.{issued}"
        good = hmac.new(self.accounts.secret(), body.encode(), hashlib.sha256).hexdigest()[:32]
        if prefix != "ai1" or not hmac.compare_digest(sig, good) or not issued.isdigit() \
                or time.time() - int(issued) > ACCESS_LIFE:
            return None
        grant = self.store.get("aigrants", uid, gid)
        user = self.accounts.user(uid) if grant else None
        if not user or grant.get("gen", 0) != user.get("gen", 0):  # removed, or Sign out other phones
            return None
        return user

    # --- the player's connections, for their account sheet ------------------------------------------
    def connections(self, user: dict) -> list[dict]:
        rows = [{"id": gid, "app": g.get("app", "AI app"), "since": g.get("created"), "last": g.get("refreshed"),
                 "used": g.get("used")}  # the last call that pulled their data (note_use), not a token refresh
                for gid, g in self.store.query("aigrants", user["id"]) if g.get("gen", 0) == user.get("gen", 0)]
        return sorted(rows, key=lambda r: -(r["since"] or 0))

    def disconnect(self, user: dict, gid: str) -> None:
        self.store.delete("aigrants", user["id"], str(gid))

    def forget(self, user_id: str) -> None:
        for gid, _ in self.store.query("aigrants", user_id):
            self.store.delete("aigrants", user_id, gid)

    # --- MCP ----------------------------------------------------------------------------------------
    @staticmethod
    def grant_of(token: str | None) -> str | None:
        """The connection a (checked) access token belongs to."""
        parts = str(token or "").split(".")
        return parts[2] if len(parts) == 5 else None

    def note_use(self, user: dict, gid: str | None, tool: str) -> None:
        """A tool call that answered with the player's data: kept on the account (`ai_used`: when, which AI app,
        which tool) for the Admin page. Connecting, listing tools and token refreshes don't count. Saved at most once a
        minute per player, as one question often makes several calls."""
        grant = self.store.get("aigrants", user["id"], gid) if gid else None
        app = (grant or {}).get("app") or "AI app"
        now = time.time()
        if grant and now - (grant.get("used") or 0) >= 60:  # for the player's own list of connections
            self.store.put("aigrants", user["id"], gid, {**grant, "used": now})
        fresh = self.accounts.user(user["id"])
        if not fresh:
            return
        last = fresh.get("ai_used") or {}
        if last.get("app") == app and now - (last.get("at") or 0) < 60:
            return
        title = next((t["title"] for t in TOOLS if t["name"] == tool), tool)
        self.accounts.save_user({**fresh, "ai_used": {"at": now, "app": app, "tool": title}})

    async def handle(self, user: dict, msg, version: str | None, gid: str | None = None) -> dict | None:
        """One JSON-RPC message from the AI app; None for a notification (no reply)."""
        if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0" or not isinstance(msg.get("method"), str):
            return _error(None, -32600, "Invalid request")
        mid, method, params = msg.get("id"), msg["method"], msg.get("params") or {}
        if "id" not in msg:
            return None
        try:
            if method == "initialize":
                asked = params.get("protocolVersion")
                return _result(mid, {
                    "protocolVersion": asked if asked in PROTOCOLS else PROTOCOLS[0],
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": slug(site.app_name()), "title": site.app_name(), "version": version or "1"},
                    "instructions": instructions()})
            if method == "ping":
                return _result(mid, {})
            if method == "tools/list":
                return _result(mid, {"tools": TOOLS})
            if method == "tools/call":
                name = params.get("name")
                if name in ("current_board", "app_hint"):  # the live table: on the event loop, with the room's lock
                    out = await self._live(user, name)
                else:
                    out = await asyncio.to_thread(self._call, user, name, params.get("arguments") or {})
                if not out.get("isError"):
                    await asyncio.to_thread(self.note_use, user, gid, name)
                return _result(mid, out)
            return _error(mid, -32601, f"Unknown method {method}")
        except ValueError as exc:
            return _error(mid, -32602, str(exc))

    def _allowed(self, user: dict) -> bool:
        now = time.time()
        recent = [t for t in self.calls.get(user["id"], []) if now - t < 3600]
        if len(recent) >= CALLS_PER_HOUR:
            return False
        self.calls[user["id"]] = recent + [now]
        return True

    async def _live(self, user: dict, name: str) -> dict:
        if not self._allowed(user):
            return _text({"error": "That's a lot of questions for one hour. Please try again a little later."}, True)
        seats = [(p.last, room, seat) for room in list(self.rooms.rooms.values())
                 for seat, p in room.players.items() if p.user == user["id"]]
        phone = self.rooms.parked_room(user["id"])  # a bot table on their phone (bridge/local.py), as of its last copy
        if phone:
            seats += [(phone[0], phone[1], seat) for seat, p in phone[1].players.items() if p.user == user["id"]]
        if not seats:
            return _text({"error": "You're not seated at a table right now."}, True)
        _, room, seat = max(seats, key=lambda x: x[0])
        try:
            if name == "app_hint":
                if not room.settings.ai_coach:
                    raise ValueError("AI coaching during play is off at this table")
                t = room.table
                if not t or t.phase == "done" or t.controller_to_act() != seat:
                    raise ValueError("the app's hint is only for your turn on a board in progress")
                return _text(hint_sheet(await room.hint(seat)))
            async with room.lock:
                state = room.coach_view(seat)
            return _text(table_sheet(state))
        except ValueError as exc:
            msg = str(exc)
            if "AI coaching" in msg:
                msg += ". Anyone seated can switch on Allow AI coaching during play in the ☰ menu's table settings."
            elif "no board" in msg:
                msg += ". Use last_board_review for the board just finished."
            return _text({"error": msg[0].upper() + msg[1:]}, True)

    def _call(self, user: dict, name, args: dict) -> dict:
        if name not in {t["name"] for t in TOOLS}:
            raise ValueError(f"Unknown tool {name}")
        if not self._allowed(user):
            return _text({"error": "That's a lot of questions for one hour. Please try again a little later."}, True)
        uid = user["id"]
        if name == "last_board_review":
            rec = self._last_board(uid)
            return _text(board_sheet(rec) if rec else {"error": "You haven't finished a board while signed in yet."},
                         not rec)
        if name == "board_review":
            rec = self._board(uid, str(args.get("key", "")))
            return _text(board_sheet(rec) if rec else {"error": "No board with that key. Use recent_boards."},
                         not rec)
        if name == "board_reviews":
            out = []
            for key in [str(k) for k in (args.get("keys") or [])][:10]:
                rec = self._board(uid, key)
                out.append(board_sheet(rec) if rec else {"key": key, "error": "No board with that key."})
            return _text({"boards": out})
        if name == "recent_boards":
            return _text(self._boards(uid, args))
        if name == "coaching_overview":
            facts = self._range(uid, args)
            out = overview(facts, bool(args.get("own_play_only")))
            if facts:
                out["from"], out["to"] = when(min(f["at"] for f in facts)), when(max(f["at"] for f in facts))
            out["working_on"] = self._notes(uid)
            try:
                out["your_mistakes"] = Puzzles(self.store, self.accounts).summary(uid)
            except Exception:  # a bonus
                pass
            return _text(out)
        if name == "mistake_patterns":
            facts = self._range(uid, args)
            whose = "bot partner" if args.get("whose") == "bot partner" else "you"
            n = args.get("examples")
            return _text({"boards": len(facts), **mistakes(facts, whose, bool(args.get("own_play_only")),
                                                           3 if n is None else max(0, min(int(n), 10)))})
        if name == "bidding_history":
            return _text(self._bidding(uid, args))
        if name == "coaching_notes":
            return _text(self._edit_notes(uid, args))
        days = max(1, min(int(args.get("days") or 30), 365))
        facts = self.accounts.facts(uid)
        return _text(stats_from_facts(own_play(facts) if args.get("own_play_only") else facts, days))

    def _range(self, uid: str, args: dict) -> list[dict]:
        days = args.get("days")
        return in_range(self.accounts.facts(uid), args.get("since"), args.get("until"),
                        max(1, int(days)) if days else None)

    def _boards(self, uid: str, args: dict) -> dict:
        limit = max(1, min(int(args.get("limit") or 10), 50))
        start = _cursor(args.get("cursor"))
        lv = lambda k: max(1, min(int(args[k]), 7)) if args.get(k) is not None else None
        rows = filter_boards(self._range(uid, args), args.get("role"), lv("min_level"), lv("max_level"),
                             args.get("strain"), args.get("off_system"), args.get("partner"))
        page = rows[start:start + limit]
        out = {"total": len(rows), "boards": [{
            "key": f["key"], "finished": _when(f["at"]), "board": f["board"], "you": f["seat"], "role": f["role"],
            "contract": contract_text(f["contract"]), "declarer_tricks": f["tricks"] if f["contract"] else None,
            "your_score": f["score"],
            **({"your_score_for_par": f["score_for_par"]} if f.get("rubber") and f["contract"] else {}),
            "par_for_you": f["par"], "partner": f["partner"] or "a bot",
            "dd_tricks_lost_by_you": f["lost"], "calls_off_system": len(f["off_system"]),
            "second_table_imps": f.get("second_imps"),
            "hints": f["hints"], "undos": f["undos"]} for f in page]}
        if start + limit < len(rows):
            out["next_cursor"] = str(start + limit)
        return out

    def _bidding(self, uid: str, args: dict) -> dict:
        per = max(1, min(int(args.get("boards") or 20), 40))
        start = _cursor(args.get("cursor"))
        every = bool(args.get("all_calls"))
        small = bool(args.get("include_small_differences"))
        facts = sorted(self._range(uid, args), key=lambda f: -f["at"])
        if not every:  # boards with an off-system call (small differences aren't in the facts: read those boards too)
            facts = [f for f in facts if f["off_system"] or small]
        page = facts[start:start + per]
        boards = []
        for f in page:
            rec = self._board(uid, f["key"])
            if not rec:
                continue
            if not small:
                review = rec.get("review") or {}
                rec = {**rec, "review": {**review, "bidding": [b for b in review.get("bidding") or []
                                                              if not b.get("minor")]}}
            boards += bidding_rows({**rec, "key": f["key"]}, only_off_system=not every)
        out = {"boards_matching": len(facts), "boards": boards}
        if start + per < len(facts):
            out["next_cursor"] = str(start + per)
        return out

    def _notes(self, uid: str) -> list[dict]:
        user = self.accounts.user(uid) or {}
        return [{"id": n["id"], "note": n["text"], "added": _when(n["at"])} for n in user.get("coach_notes") or []]

    def _edit_notes(self, uid: str, args: dict) -> dict:
        action = args.get("action")
        if action in ("add", "remove"):
            user = self.accounts.user(uid)
            if not user:
                return {"error": "No account."}
            notes = list(user.get("coach_notes") or [])
            if action == "add":
                text = " ".join(str(args.get("text") or "").split())[:300]
                if not text:
                    return {"error": "The note is empty."}
                if len(notes) >= MAX_NOTES:
                    return {"error": f"There are already {MAX_NOTES} notes: remove one first.", "notes": self._notes(uid)}
                notes.append({"id": secrets.token_hex(3), "text": text, "at": time.time()})
            else:
                keep = [n for n in notes if n["id"] != str(args.get("id") or "")]
                if len(keep) == len(notes):
                    return {"error": "No note with that id.", "notes": self._notes(uid)}
                notes = keep
            user["coach_notes"] = notes
            self.accounts.save_user(user)
        return {"notes": self._notes(uid)}

    def _board(self, uid: str, key: str) -> dict | None:
        """A saved board, with the rubber's part score when it was dealt: boards from before 1.93 didn't keep it, so
        it comes from the facts, which rebuilt it by replaying the rubber (stats.rebuild_part_scores)."""
        rec = self.accounts.board(uid, key)
        if rec and rec.get("scoring") == "rubber" and rec.get("below_before") is None:
            f = next((f for f in self.accounts.facts(uid) if f["key"] == key), None)
            if f and f.get("below_before") is not None:
                rec = {**rec, "below_before": f["below_before"], "below_guessed": f.get("below_guessed", False)}
        return rec

    def _last_board(self, uid: str) -> dict | None:
        """The newest board this player finished: from a table still open on the server when there is one (its
        review's odds may have arrived after the board was saved), otherwise from their saved boards."""
        live = [{**rec, "seat": seat} for room in list(self.rooms.rooms.values()) for rec in room.history[-1:]
                for seat, p in room.players.items() if p.user == uid and seat not in (rec.get("bots") or [])]
        facts = self.accounts.facts(uid)
        saved = max(facts, key=lambda f: f["at"]) if facts else None
        best = max(live, key=lambda r: r.get("finished_at", 0)) if live else None
        if best and (not saved or best.get("finished_at", 0) >= saved["at"] - 1):
            return best
        return self._board(uid, saved["key"]) if saved else None


def _cursor(c) -> int:
    try:
        return max(0, int(str(c or "0")))
    except ValueError:
        return 0


def _when(at: float) -> str:
    """"October 29, 2026, 9:05 AM", in Pacific time like the rest of the app."""
    t = dt.datetime.fromtimestamp(at, PACIFIC)
    return f"{t:%B} {t.day}, {t.year}, {t.hour % 12 or 12}:{t:%M} {'AM' if t.hour < 12 else 'PM'}"


def _text(data: dict, error: bool = False) -> dict:
    return {"content": [{"type": "text", "text": json.dumps(data, ensure_ascii=False, separators=(",", ":"))}],
            "structuredContent": data, "isError": error}


def _result(mid, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": mid, "result": result}


def _error(mid, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": message}}
