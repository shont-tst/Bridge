#!/usr/bin/env sh
# Run the whole app locally (server + built web client) on port 8000.
# Phones on the same Wi-Fi can then open http://<this-computer's-IP>:8000
set -e
cd "$(dirname "$0")"

if [ ! -d .venv ]; then
  python3 -m venv .venv
fi
. .venv/bin/activate
pip install -q -r server/requirements-dev.txt

if [ ! -d web/dist ] || [ "${REBUILD:-0}" = "1" ]; then
  (cd web && npm install && npm run build)
fi

IP=$( (hostname -I 2>/dev/null || ipconfig getifaddr en0 2>/dev/null) | awk '{print $1}')
echo
echo "  Bridge running. On your phones open:  http://${IP:-localhost}:${PORT:-8000}"
echo
cd server
exec uvicorn bridge.app:app --host 0.0.0.0 --port "${PORT:-8000}"
