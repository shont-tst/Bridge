"""Weekly backups: every record the app keeps (accounts, passkeys, friends, saved boards,
tables in progress, suggestions, settings) as one gzipped JSON file, backup-YYYY-MM-DD.json.gz (Pacific day), in
the blob container "backups" of the app's own storage account. The newest KEEP are kept.

The server checks a few minutes after it starts and then every few hours, and makes one only when the newest is 7
days old or more. On Azure the app signs in to blob storage with its identity, which needs the role Storage Blob
Data Contributor on the storage account (docs/deploy-azure.md). Off Azure, backups go to the data folder.

To put a backup back: Backups -> Restore on the Admin page, or python -m scripts.restore_backup
backup-YYYY-MM-DD.json.gz (see that script).

A backup holds the app's secret settings too (the key sign-in tokens are signed with, the notification keys), so it
stays in the private storage account; download one from the Azure portal (Storage browser -> Blob containers ->
backups) only to restore it.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import gzip
import json
import logging
import os
import re
from pathlib import Path

from .load import timings
from .store import Store

CONTAINER = "backups"
KEEP = 12
EVERY_DAYS = 7
CHECK_EVERY = 6 * 3600  # seconds between checks while the server runs
NAME = re.compile(r"^backup-(\d{4}-\d{2}-\d{2})\.json\.gz$")
# made by the Admin page just before it puts a backup back, so the restore itself can be undone
BEFORE = re.compile(r"^before-restore-(\d{4}-\d{2}-\d{2}-\d{6})\.json\.gz$")
KEEP_BEFORE = 3

log = logging.getLogger("bridge.backups")


def pacific_today() -> dt.date:
    try:
        from zoneinfo import ZoneInfo
        return dt.datetime.now(ZoneInfo("America/Los_Angeles")).date()
    except Exception:  # no time zone data: UTC is near enough for naming a weekly file
        return dt.datetime.now(dt.timezone.utc).date()


class Folder:
    """Backups in a folder (a laptop, the tests)."""

    def __init__(self, path: Path):
        self.path = Path(path)

    def names(self) -> list[str]:
        return [p.name for p in self.path.glob("*.json.gz")] if self.path.exists() else []

    def sizes(self) -> dict[str, int]:
        return {p.name: p.stat().st_size for p in self.path.glob("*.json.gz")} if self.path.exists() else {}

    def get(self, name: str) -> bytes:
        return (self.path / name).read_bytes()

    def put(self, name: str, data: bytes) -> None:
        self.path.mkdir(parents=True, exist_ok=True)
        (self.path / name).write_bytes(data)

    def delete(self, name: str) -> None:
        (self.path / name).unlink(missing_ok=True)


class Blobs:
    """Backups in the blob container "backups" of the storage account the tables are in."""

    def __init__(self, tables_url: str):
        from azure.identity import DefaultAzureCredential
        from azure.storage.blob import BlobServiceClient
        service = BlobServiceClient(account_url=tables_url.replace(".table.", ".blob."),
                                    credential=DefaultAzureCredential())
        self.container = service.get_container_client(CONTAINER)
        self._made = False

    def _ready(self) -> None:
        if not self._made:
            from azure.core.exceptions import ResourceExistsError
            try:
                self.container.create_container()
            except ResourceExistsError:
                pass
            self._made = True

    def names(self) -> list[str]:
        return list(self.sizes())

    def sizes(self) -> dict[str, int]:
        self._ready()
        return {b.name: b.size for b in self.container.list_blobs()}

    def get(self, name: str) -> bytes:
        return self.container.download_blob(name).readall()

    def put(self, name: str, data: bytes) -> None:
        self._ready()
        self.container.upload_blob(name, data, overwrite=True)

    def delete(self, name: str) -> None:
        self.container.delete_blob(name)


def place():
    if os.environ.get("BRIDGE_TABLES_URL"):
        return Blobs(os.environ["BRIDGE_TABLES_URL"])
    from .game.room import data_dir
    return Folder(data_dir() / "backups")


class Backups:
    def __init__(self, store: Store, where=None):
        self.store = store
        self._where = where
        self.last: str | None = None  # the newest backup's day, once known (shown by /api/health)
        self.error: str | None = None

    @property
    def where(self):
        if self._where is None:
            self._where = place()
        return self._where

    def listing(self) -> list[str]:
        """Backup names, newest first."""
        return sorted((n for n in self.where.names() if NAME.match(n)), reverse=True)

    def _export(self) -> bytes:
        doc = {"exported_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
               "tables": self.store.dump()}
        return gzip.compress(json.dumps(doc, ensure_ascii=False, separators=(",", ":")).encode())

    def make(self, today: dt.date) -> str:
        name = f"backup-{today.isoformat()}.json.gz"
        with timings.working("Backup"):  # for the Admin page's Load tab
            self.where.put(name, self._export())
        for old in self.listing()[KEEP:]:
            self.where.delete(old)
        return name

    # --- for the Admin page ------------------------------------------------------------------
    def files(self) -> list[dict]:
        """Every backup, and the copies made before a restore, newest first: [{"name", "size", "before"}]."""
        sizes = self.where.sizes()
        weekly = [{"name": n, "size": sizes[n], "before": False} for n in sizes if NAME.match(n)]
        before = [{"name": n, "size": sizes[n], "before": True} for n in sizes if BEFORE.match(n)]
        return (sorted(weekly, key=lambda f: f["name"], reverse=True)
                + sorted(before, key=lambda f: f["name"], reverse=True))

    def read(self, name: str) -> bytes:
        if not (NAME.match(name) or BEFORE.match(name)):  # a name, never a path
            raise ValueError("no such backup")
        return self.where.get(name)

    def restore(self, name: str, now: dt.datetime | None = None) -> tuple[int, str]:
        """Puts a backup back (records made since it stay) -> (records written, the copy made just before)."""
        doc = json.loads(gzip.decompress(self.read(name)))
        stamp = (now or dt.datetime.now(dt.timezone.utc)).strftime("%Y-%m-%d-%H%M%S")
        before = f"before-restore-{stamp}.json.gz"
        self.where.put(before, self._export())
        for old in sorted((n for n in self.where.names() if BEFORE.match(n)), reverse=True)[KEEP_BEFORE:]:
            self.where.delete(old)
        return load(self.store, doc), before

    def weekly(self, today: dt.date | None = None) -> str | None:
        """Makes a backup when the newest is EVERY_DAYS old or more (or there's none) -> its name, or None."""
        today = today or pacific_today()
        have = self.listing()
        newest = NAME.match(have[0]).group(1) if have else None
        if newest and (today - dt.date.fromisoformat(newest)).days < EVERY_DAYS:
            self.last = newest
            return None
        name = self.make(today)
        self.last = today.isoformat()
        return name

    async def run(self, first_wait: float = 300) -> None:
        """While the server runs: check a few minutes after it starts, then every CHECK_EVERY seconds."""
        await asyncio.sleep(first_wait)
        while True:
            try:
                made = await asyncio.to_thread(self.weekly)
                self.error = None
                if made:
                    log.warning("made backup %s", made)  # warning, so it shows in the log stream
            except Exception as exc:
                self.error = type(exc).__name__
                log.warning("backup failed: %s", exc)
            await asyncio.sleep(CHECK_EVERY)


def load(store: Store, doc: dict) -> int:
    """Puts every record of a backup (as made by Backups.make) back into `store` -> how many."""
    n = 0
    for table, rows in doc["tables"].items():
        for row in rows:
            store.put(table, row["pk"], row["rk"], row["data"])
            n += 1
    return n
