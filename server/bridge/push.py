"""Phone notifications (Web Push) for invites to play, for friends who don't have the app open.

The keys that identify this server to Apple's and Google's push services are made once and kept in storage.
A player turns notifications on or off in Settings; when off, nothing is sent and their phone's address is forgotten.
"""
from __future__ import annotations

import base64
import json
import logging

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from . import site
from .accounts import Accounts

log = logging.getLogger("bridge.push")


def contact() -> str:
    """Who runs this server, for the push services: the site's address (BRIDGE_ORIGIN)."""
    return site.origin() or "https://localhost"


class Push:
    def __init__(self, accounts: Accounts):
        self.accounts = accounts
        self._keys: dict | None = None

    def keys(self) -> dict:
        if self._keys is None:
            store = self.accounts.store
            k = store.get("config", "cfg", "vapid")
            if not k:
                key = ec.generate_private_key(ec.SECP256R1())
                pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                        serialization.NoEncryption()).decode()
                raw = key.public_key().public_bytes(serialization.Encoding.X962,
                                                    serialization.PublicFormat.UncompressedPoint)
                k = {"private": pem, "public": base64.urlsafe_b64encode(raw).rstrip(b"=").decode()}
                store.put("config", "cfg", "vapid", k)
            self._keys = k
        return self._keys

    def public_key(self) -> str:
        return self.keys()["public"]

    def send(self, user: dict, title: str, body: str, url: str) -> int:
        """Notify every phone the player turned notifications on for. Returns how many took it."""
        if not user.get("notify", True) or not user.get("push"):
            return 0
        from pywebpush import WebPushException, webpush
        from py_vapid import Vapid
        vapid = Vapid.from_pem(self.keys()["private"].encode())
        sent = 0
        for sub in list(user["push"]):
            try:
                webpush(subscription_info=sub, data=json.dumps({"title": title, "body": body, "url": url}),
                        vapid_private_key=vapid, vapid_claims={"sub": contact()}, ttl=300, timeout=10)
                sent += 1
            except WebPushException as exc:
                status = getattr(exc.response, "status_code", None)
                if status in (404, 410):  # the phone turned them off, or the app was removed
                    self.accounts.drop_push(user["id"], sub["endpoint"])
                else:
                    log.warning("push to %s failed: %s", user["id"], exc)
            except Exception as exc:  # a notification is a bonus; never break an invite over it
                log.warning("push to %s failed: %s", user["id"], exc)
        return sent
