"""Weekly backups: made when due, old ones dropped, and they put everything back."""
import datetime as dt
import gzip
import json

from bridge.backups import EVERY_DAYS, KEEP, Backups, Folder, load
from bridge.store import SqliteStore


def _store(tmp_path, name="s.db"):
    s = SqliteStore(tmp_path / name, durable=True)
    s.put("users", "u", "abc", {"name": "Avery"})
    s.put("boards", "abc", "k1", {"score_ns": 420})
    return s


def test_weekly_backup_is_made_when_due_and_old_ones_go(tmp_path):
    b = Backups(_store(tmp_path), Folder(tmp_path / "backups"))
    day = dt.date(2026, 10, 28)
    assert b.weekly(day) == "backup-2026-10-28.json.gz"
    assert b.weekly(day + dt.timedelta(days=EVERY_DAYS - 1)) is None  # not due yet
    assert b.last == "2026-10-28"
    for week in range(1, KEEP + 3):
        b.weekly(day + dt.timedelta(days=EVERY_DAYS * week))
    names = b.listing()
    assert len(names) == KEEP and names[0] == f"backup-{(day + dt.timedelta(days=EVERY_DAYS * (KEEP + 2))).isoformat()}.json.gz"


def test_a_backup_puts_everything_back(tmp_path):
    b = Backups(_store(tmp_path), Folder(tmp_path / "backups"))
    name = b.make(dt.date(2026, 10, 28))
    doc = json.loads(gzip.decompress((tmp_path / "backups" / name).read_bytes()))
    fresh = SqliteStore(tmp_path / "fresh.db", durable=True)
    assert load(fresh, doc) == 2
    assert fresh.get("users", "u", "abc") == {"name": "Avery"}
    assert fresh.get("boards", "abc", "k1") == {"score_ns": 420}
