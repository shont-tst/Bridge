"""What this copy of the app is called and where it lives, from settings (environment variables), so the code names no
particular site. Unset, the app is plain "Bridge" and files no feedback issues: each site sets its own (README, Settings).

- BRIDGE_APP_NAME: the name players see (page title, Home Screen, notifications, sign-in prompts, the AI connector).
- BRIDGE_ORIGIN: the site's address, e.g. https://bridge.example.com (passkeys, links, notifications).
- BRIDGE_FEEDBACK_REPO: the GitHub repository Feedback suggestions are filed in, e.g. owner/name (with
  BRIDGE_FEEDBACK_TOKEN). Best a private one: suggestions carry players' names and boards.
- BRIDGE_SOURCE_URL: where the app's open source code is, e.g. https://github.com/owner/name. What's new links to it.
"""
from __future__ import annotations

import os

DEFAULT_NAME = "Bridge"


def app_name() -> str:
    return os.environ.get("BRIDGE_APP_NAME", "").strip() or DEFAULT_NAME


def origin() -> str | None:
    o = os.environ.get("BRIDGE_ORIGIN", "").strip().rstrip("/")
    return o or None


def feedback_repo() -> str | None:
    return os.environ.get("BRIDGE_FEEDBACK_REPO", "").strip().strip("/") or None


def source_url() -> str | None:
    """The open source code's address, only if it is a web address (it goes into the page as a link)."""
    u = os.environ.get("BRIDGE_SOURCE_URL", "").strip()
    return u if u.startswith("https://") else None
