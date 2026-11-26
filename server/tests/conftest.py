"""Every test gets throwaway storage, with accounts switched on as they are on Azure."""
import os
import tempfile

os.environ.setdefault("BRIDGE_DATA_DIR", tempfile.mkdtemp(prefix="bridge-test-"))
os.environ.setdefault("BRIDGE_ACCOUNTS", "1")
os.environ.setdefault("BRIDGE_RATE_LIMITS", "0")  # every test client comes from one address; test_limits turns them on
os.environ.setdefault("BRIDGE_SECOND_BACKFILL", "0")  # tests that want it call backfill.run themselves
os.environ.setdefault("BRIDGE_RULES_RECHECK", "0")  # likewise recheck.run
os.environ.setdefault("BRIDGE_SPEED_DAILY", "0")  # the speed check after a start and daily (tests call it themselves)

import pytest


@pytest.fixture(autouse=True)
def _no_bot_claims(request, monkeypatch):
    """Bots claim only in the tests that ask for it (`@pytest.mark.bot_claims`): elsewhere a bot's claim would stop
    a test that plays a hand through, waiting for someone to accept it."""
    if not request.node.get_closest_marker("bot_claims"):
        from bridge.game.table import Table
        monkeypatch.setattr(Table, "bot_claims", False)
