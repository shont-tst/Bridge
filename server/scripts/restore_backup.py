"""Put a weekly backup back into storage (bridge/backups.py makes them).

Download the backup from the Azure portal (the storage account -> Storage browser -> Blob containers ->
backups), then from server/, signed in with `az login` as someone with Storage Table Data Contributor:

    BRIDGE_TABLES_URL=https://<account>.table.core.windows.net python -m scripts.restore_backup FILE [--yes]

Every record in the file is written back, replacing the one with the same key; records made since the backup are left
as they are. Without --yes it only says what it would do.
"""
from __future__ import annotations

import gzip
import json
import sys

from bridge.backups import load
from bridge.store import open_store


def main(argv: list[str]) -> None:
    if not argv:
        sys.exit(__doc__)
    doc = json.loads(gzip.decompress(open(argv[0], "rb").read()))
    counts = {t: len(rows) for t, rows in doc["tables"].items()}
    print(f"Backup from {doc['exported_at']}: " + ", ".join(f"{t} {n}" for t, n in sorted(counts.items())))
    if "--yes" not in argv:
        print("Nothing written. Run again with --yes to put these records back.")
        return
    print(f"Wrote {load(open_store(), doc)} records.")


if __name__ == "__main__":
    main(sys.argv[1:])
