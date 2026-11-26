"""A throwaway server for the README screenshots: the demo account and boards in demo.json, a table at one saved
moment, and the clock stopped at the demo's own date, so every run shows the same screens. Run by shoot.js:
    python serve.py DEMO_JSON MOMENT PORT DATA_DIR
MOMENT is a key of demo.json's "tables" (the table as it was then), or "none". It prints one line, "TOKEN <token>",
the demo account's sign-in, once the server is ready."""
import os
import sys
import time

if __name__ == "__main__":
    demo_path, moment, port, data = sys.argv[1], sys.argv[2], int(sys.argv[3]), sys.argv[4]
    os.environ.update(BRIDGE_ACCOUNTS="1", BRIDGE_DATA_DIR=data, BRIDGE_RATE_LIMITS="0", BRIDGE_SECOND_BACKFILL="0", BRIDGE_RULES_RECHECK="0", BRIDGE_SPEED_DAILY="0",
                      BRIDGE_BOT_DELAY="0.05")
    os.environ.pop("BRIDGE_TABLES_URL", None)
    os.environ.pop("BRIDGE_ORIGIN", None)

import json  # noqa: E402

DEMO = None


def _stop_the_clock(now: float) -> None:
    """time.time() starts at the demo's date and moves on from there, in this process and the solver's."""
    real, start = time.time, time.time()
    time.time = lambda: now + (real() - start)


if __name__ != "__main__" and os.environ.get("BRIDGE_DEMO_NOW"):
    _stop_the_clock(float(os.environ["BRIDGE_DEMO_NOW"]))  # the solver's worker process, which imports this file


def main() -> None:
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
    with open(demo_path) as f:
        demo = json.load(f)
    now = demo["now"]
    os.environ["BRIDGE_DEMO_NOW"] = str(now)
    _stop_the_clock(now)
    from bridge.store import SqliteStore

    db = os.path.join(data, "bridge.db")
    if os.path.exists(db):
        os.remove(db)
    store = SqliteStore(db)
    for r in demo["rows"]:
        store.put(r["tbl"], r["pk"], r["rk"], r["data"])
    if moment != "none":
        snap = demo["tables"][moment]
        snap["saved"] = now
        for p in snap["players"].values():
            if p.get("user"):
                p.update(last=now, away=False)
        store.put("rooms", "r", snap["code"], snap)
    store.db.close()

    import uvicorn
    from bridge.app import accounts, app

    user = next(r for r in demo["rows"] if r["tbl"] == "users")
    print("TOKEN", accounts.token_for({"id": user["rk"], **user["data"]}), flush=True)
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()
