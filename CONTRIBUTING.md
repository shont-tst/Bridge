# Contributing

Thanks for wanting to help.

- **Ideas and bugs:** open an issue. Say what you did, what you expected and what happened; for a bridge question,
  include the deal and the auction.
- **Pull requests:** keep each one to a single change. Run the tests (`cd server && python -m pytest -q`) and the web
  build (`cd web && npm ci && npm run build`) first, and add a test for a fix or a new rule.
- **The look:** the app is used on phones and tablets, so check a change at phone and tablet sizes. Suits are always
  colored symbols (♠ ♥ ♦ ♣), never letters, and the wording is short and plain.
- **The game code also runs in the browser** (Play locally, through Pyodide): code under `server/bridge/core`,
  `bidding`, `bots`, `game` and `solver.py` must not import a new third-party package or rely on threads.
- **Site details are settings:** never write a site's name, address or account names into the code (see `site.py`).

Changes from this repository are folded into the running app by hand, after review, so a merged change here may take a
while to appear anywhere. By sending a pull request you agree that it's licensed under this repository's MIT license.
