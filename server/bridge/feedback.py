"""Suggestions players send from the Feedback pull-down.

Each one is kept in the app's own storage. When BRIDGE_FEEDBACK_TOKEN and BRIDGE_FEEDBACK_REPO are set (a GitHub
token that may write issues, and the private repository they go in), a signed-in player's suggestion is also filed there as an issue labeled
"suggestion", where the owner reviews it and decides to build it, change it or leave it. Only signed-in players can
send one, so a stranger or a bot can't fill the list.
"""
from __future__ import annotations

import json
import logging
import os
import secrets
import threading
import time
import urllib.request

from . import site
from .store import Store

MAX_LEN = 2000
PER_HOUR = 10  # suggestions from one signed-in player in an hour, so a stuck button can't flood the list
STATUSES = ("new", "build", "maybe", "ignore", "done")

log = logging.getLogger(__name__)


def no_mentions(text: str) -> str:
    """Stop "@name" in a suggestion from notifying that GitHub user: a zero-width space after the @ keeps it as is
    on screen."""
    return text.replace("@", "@\u200b")


SEAT_NAME = {"N": "North", "E": "East", "S": "South", "W": "West"}
SYMBOL = {"S": "♠", "H": "♥", "D": "♦", "C": "♣", "N": "NT"}


def quoted(text: str) -> str:
    """The player's words for a GitHub issue, under a heading and as one quote block, so anyone reading the issue
    (a Claude thread too) sees where they start and end: every line quoted, blank ones included, so the quote can't be
    closed early, and "<" shown as itself, so no HTML hides anything (a <!-- comment --> is invisible on GitHub but
    not to an AI reading the issue)."""
    lines = text.replace("&", "&amp;").replace("<", "&lt;").splitlines() or [""]
    return "**Player's suggestion (as written):**\n\n" + "\n".join(f"> {line}".rstrip() for line in lines)


def call_text(call: str) -> str:
    return {"P": "Pass", "X": "Double", "XX": "Redouble"}.get(call) or call[0] + SYMBOL.get(call[1], call[1])


def card_text(card: str) -> str:
    return SYMBOL[card[0]] + ("10" if card[1] == "T" else card[1])


def odds_text(x: dict) -> str:
    """The review's verdict on a costly card, from its odds: Mistake (another card was the better bet) or Unlucky."""
    o = x.get("odds")
    if not o:
        return ""
    if o.get("better"):
        return f"; Mistake: it worked {o['played']}% of {o['samples']} layouts, {card_text(o['best'])} {o['best_pct']}%"
    return f"; Unlucky: it worked {o['played']}% of {o['samples']} layouts, as good a bet as any"


def about_details(b: dict) -> str:
    """The board behind feedback sent from the table, for its GitHub issue: enough to replay it. A report on one
    call (Room.bid_report) also names the call and its rule, and marks it in the auction."""
    hands = "\n".join(f"{SEAT_NAME[s]:<6} " + "  ".join(f"{SYMBOL[x]} {h or '—'}" for x, h in zip("SHDC", b["hands"][s].split(".")))
                       for s in "NESW")
    start = "WNES".index(b["dealer"])
    grid = ["West   North  East   South", " " * 7 * start]
    for i, c in enumerate(b["calls"]):
        label = call_text(c) + ("*" if i == b.get("index") else "")
        grid[-1] += f"{label:<7}"
        if (start + i) % 4 == 3:
            grid.append("")
    out = ""
    if "card" in b:
        how = b.get("how") or {}
        alts = ", ".join(f"{card_text(a['card'])} {a['made']}/{how.get('samples')} ({a['tricks']} tricks)" for a in how.get("alts") or [])
        out = (f"**Card:** {SEAT_NAME[b['seat']]} played {card_text(b['card'])}\n"
               f"**How the bot picked it:** {how.get('kind', 'not recorded')}, level {how.get('level', '?')}, "
               f"{how.get('samples', 0)} layouts; reached its goal in {how.get('made', '?')} "
               f"({how.get('tricks', '?')} tricks)" + (f"; next best {alts}" if alts else "") + "\n")
    elif "call" in b:
        who = ("bot " if b.get("bot") else "") + SEAT_NAME[b["seat"]]
        rule = f"{b['rule']} ({b['convention']})" if b.get("rule") else "none found"
        out = (f"**Call:** {who} bid {call_text(b['call'])} (call {b['index'] + 1} of the auction)\n"
               f"**Meaning:** {b['meaning']}\n**Rule:** {rule}\n")
    res = b.get("result")
    if res:
        c = res.get("contract")
        out += ("**Result:** " + (f"{call_text(str(c['level']) + c['strain'])}{'X' * c.get('doubled', 0) if isinstance(c.get('doubled'), int) else ''} "
                                  f"by {SEAT_NAME.get(c['declarer'], c['declarer'])}, {res['declarer_tricks']} tricks"
                                  if isinstance(c, dict) and c.get("level") else "passed out")
                + f", {res.get('score_ns'):+} for N-S" + (" (claimed)" if res.get("claimed") else "") + "\n")
        rv = b.get("review") or {}
        for x in rv.get("calls") or []:
            out += (f"**Review, call {x['index'] + 1}:** {SEAT_NAME[x['seat']]} bid {call_text(x['call'])}, the system "
                    f"bids {call_text(x['system_call'])}" + (" (a sensible alternative)" if x.get("minor") else "") + "\n")
        for x in rv.get("cards") or []:
            better = ", ".join(card_text(c) for c in x.get("best") or [])
            out += (f"**Review, trick {x['trick']}:** {SEAT_NAME[x['seat']]} played {card_text(x['card'])}, cost "
                    f"{x['lost']} trick{'s' if x['lost'] > 1 else ''} with all cards seen" + (f" (better {better})" if better else "")
                    + odds_text(x) + (f"; {x['back']} given straight back" if x.get("back") else "") + "\n")
    play = b.get("play") or []
    tricks = [" ".join(f"{s}:{card_text(c)}" for s, c in play[i:i + 4]) for i in range(0, len(play), 4)]
    return (out + f"**Board:** {b['board']} · dealer {SEAT_NAME[b['dealer']]} · vulnerable {b['vulnerability']} · "
            f"table {b['room']} · bots {''.join(b.get('bots') or []) or 'none'}\n"
            f"**Conventions:** {', '.join(b['conventions'])} · bot level {b['difficulty']}\n\n"
            f"```\n{hands}\n\n" + "\n".join(r.rstrip() for r in grid if r.strip())
            + ("\n\n" + "\n".join(f"Trick {i + 1}: {t}" for i, t in enumerate(tricks)) if tricks else "")
            + "\n```" + ("\n(* the reported call)" if "call" in b else ""))


class Feedback:
    def __init__(self, store: Store):
        self.store = store
        self.recent: dict[str, list[float]] = {}

    def add(self, text: str, sender: str, name: str | None = None, user_id: str | None = None,
            version: str | None = None, now: float | None = None, about: dict | None = None) -> dict:
        """`about`: feedback sent from the table carries the board it's about (Room.board_report), or one call on it
        (Room.bid_report)."""
        if not user_id:
            raise ValueError("Please sign in to send a suggestion")
        text = (text or "").strip() or (("This bid looks wrong" if "call" in about else "This card looks wrong") if about and ("call" in about or "card" in about) else "")
        if not text:
            raise ValueError("Write a suggestion first")
        if len(text) > MAX_LEN:
            raise ValueError(f"Please keep it under {MAX_LEN} characters")
        now = now or time.time()
        times = [t for t in self.recent.get(sender, []) if now - t < 3600]
        if len(times) >= PER_HOUR:
            raise ValueError("Thanks! That's plenty for now. Try again in a while")
        self.recent[sender] = times + [now]
        rec = {"text": text, "name": name, "user": user_id, "version": version,
               "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now))}
        if about:
            rec["about"] = about
        key = f"{rec['at']}-{secrets.token_hex(3)}"
        self.store.put("feedback", "f", key, rec)
        token, repo = os.environ.get("BRIDGE_FEEDBACK_TOKEN"), site.feedback_repo()
        if token and repo:
            threading.Thread(target=self._file_issue, args=(token, repo, key, rec), daemon=True).start()
        return rec

    def all(self) -> list[dict]:
        return [{"key": k, **r} for k, r in self.store.query("feedback", "f")]

    # --- the owner's review, from the Admin page ----------------------------------------------
    def mark(self, key: str, status: str) -> dict:
        """Build, maybe, ignore or done (or back to new). Its GitHub issue follows: ignore and done close it, the rest
        leave it open."""
        if status not in STATUSES:
            raise ValueError("unknown status")
        rec = self.store.get("feedback", "f", key)
        if not rec:
            raise ValueError("no such suggestion")
        rec["status"] = status
        self.store.put("feedback", "f", key, rec)
        self._sync_issue(rec, status)
        return {"key": key, **rec}

    def delete(self, key: str) -> None:
        """Spam, or a duplicate: gone from the list, and its issue closed as not planned."""
        rec = self.store.get("feedback", "f", key)
        if rec:
            self.store.delete("feedback", "f", key)
            self._sync_issue(rec, "ignore")

    def _sync_issue(self, rec: dict, status: str) -> None:
        token = os.environ.get("BRIDGE_FEEDBACK_TOKEN")
        repo = rec.get("repo") or site.feedback_repo()  # the repository it was filed in (older ones: the setting's)
        if token and repo and rec.get("issue"):
            threading.Thread(target=self._set_issue_state, args=(token, repo, rec["issue"], status),
                             daemon=True).start()

    def _set_issue_state(self, token: str, repo: str, number: int, status: str) -> None:
        state = ({"state": "closed", "state_reason": "not_planned"} if status == "ignore" else
                 {"state": "closed", "state_reason": "completed"} if status == "done" else {"state": "open"})
        req = urllib.request.Request(
            f"https://api.github.com/repos/{repo}/issues/{int(number)}", method="PATCH", data=json.dumps(state).encode(),
            headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                     "X-GitHub-Api-Version": "2022-11-28"})
        try:
            urllib.request.urlopen(req, timeout=15).close()
        except Exception as exc:
            log.warning("could not update issue %s: %s", number, exc)

    def _file_issue(self, token: str, repo: str, key: str, rec: dict) -> None:
        text = no_mentions(rec["text"])
        first = text.splitlines()[0]
        b = rec.get("about")
        if b and "call" in b:
            first = f"{SEAT_NAME[b['seat']]}'s {call_text(b['call'])} on board {b['board']}: {first}"
        elif b and "card" in b:
            first = f"{SEAT_NAME[b['seat']]}'s {card_text(b['card'])} on board {b['board']}: {first}"
        elif b:
            first = f"Board {b['board']}: {first}"
        title = first if len(first) <= 70 else first[:67] + "…"
        body = quoted(text)
        if b:
            body += "\n\n" + about_details(b)
        body = (f"{body}\n\n---\nFrom {no_mentions(rec['name'] or 'a guest')} · version {rec['version'] or '?'} · "
                f"{rec['at']}\n\n_Sent from the app's Feedback pull-down._")
        req = urllib.request.Request(
            f"https://api.github.com/repos/{repo}/issues", method="POST",
            data=json.dumps({"title": title, "body": body, "labels": ["suggestion"]}).encode(),
            headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                     "X-GitHub-Api-Version": "2022-11-28"})
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                issue = json.loads(r.read())
            self.store.put("feedback", "f", key, {**rec, "issue": issue.get("number"), "repo": repo})
        except Exception as exc:  # it's still kept in storage; the owner can see it there
            log.warning("could not file suggestion %s as an issue: %s", key, exc)
