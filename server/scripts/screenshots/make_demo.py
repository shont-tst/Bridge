"""Makes demo.json from a local server's data folder: the one account in it, its saved boards, and two saved tables
(rooms rows copied while that account sat at them). Only needed to change what the screenshots show:
    python make_demo.py DATA_DIR BID_TABLE.json PLAY_TABLE.json REVIEW_BOARD OUT.json
The account must be a made-up demo one (the screenshots go in the public README), never a real player's."""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from bridge.store import SqliteStore  # noqa: E402


def main() -> None:
    data, bid, play, review, out = sys.argv[1:6]
    store = SqliteStore(Path(data) / "bridge.db")
    users = store.query("users", "u")
    if len(users) != 1:
        sys.exit("expected exactly one (demo) account")
    uid, user = users[0]
    user = {k: v for k, v in user.items() if k in ("name", "friend_code", "created", "notify")}
    rows = [{"tbl": "users", "pk": "u", "rk": uid, "data": user},
            {"tbl": "codes", "pk": "code", "rk": user["friend_code"].replace("-", ""), "data": {"user": uid}}]
    boards = store.query("boards", uid)
    rows += [{"tbl": "boards", "pk": uid, "rk": rk, "data": rec} for rk, rec in boards]
    tables = {}
    for name, f in (("bid", bid), ("play", play)):
        snap = json.loads(Path(f).read_text())
        for p in snap["players"].values():
            p.update(device=None, device_name="")
        tables[name] = snap
    now = max(rec["finished_at"] for _, rec in boards) + 600
    Path(out).write_text(json.dumps({"made": time.strftime("%Y-%m-%d"), "now": now, "review": {"board": review, "open": ["Cards that cost", "Second table"]}, "rows": rows,
                                     "tables": tables}, separators=(",", ":")))
    print(f"{out}: {len(boards)} boards")


if __name__ == "__main__":
    main()
