"""The app's offline engine: this server's own game code, as one zip the app downloads and keeps (see bridge/local.py).

It holds the `bridge` package as it is on this server, so the app plays offline exactly as the server plays, plus
`server/offline/` (the solver built for the browser, and the parts of endplay the game uses; see its README).
"""
from __future__ import annotations

import hashlib
import io
import zipfile
from functools import lru_cache
from pathlib import Path

SERVER = Path(__file__).resolve().parents[1]
PACKAGE = SERVER / "bridge"
EXTRA = SERVER / "offline"
# only the game: nothing that holds accounts, storage, admin or the AI connector goes onto phones
LEAVE_OUT = {"app.py", "accounts.py", "admin.py", "backups.py", "connector.py", "coach.py", "feedback.py", "push.py",
             "social.py", "limits.py", "stats.py", "trends.py", "patterns.py", "offline.py",
             "backfill.py"}


def _files() -> list[tuple[str, Path]]:
    out = []
    for f in sorted(PACKAGE.rglob("*")):
        rel = f.relative_to(PACKAGE)
        if f.is_file() and "__pycache__" not in rel.parts and f.suffix in (".py", ".json") \
                and not (len(rel.parts) == 1 and rel.name in LEAVE_OUT):
            out.append((f"bridge/{rel.as_posix()}", f))
    for f in sorted((EXTRA / "endplay").rglob("*")):
        rel = f.relative_to(EXTRA)
        if f.is_file() and "__pycache__" not in rel.parts and f.name != "LICENCE":
            out.append((rel.as_posix(), f))
    out.append(("more_itertools.py", EXTRA / "more_itertools.py"))
    return out


@lru_cache(maxsize=1)
def bundle() -> tuple[bytes, str]:
    """(the zip, a tag that changes whenever its contents do)."""
    buf = io.BytesIO()
    digest = hashlib.sha256()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for name, path in _files():
            data = path.read_bytes()
            digest.update(name.encode() + b"\0" + data)
            info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))  # the same bytes every time
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, data)
    return buf.getvalue(), digest.hexdigest()[:16]
