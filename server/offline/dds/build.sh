#!/bin/bash
# Rebuilds server/offline/endplay (the solver and card types the app's offline engine uses) from endplay's source
# release. Needs the Emscripten SDK at the version the Pyodide in web/package.json was built with (Pyodide 0.29.5:
# Emscripten 4.0.9), on the PATH (source emsdk_env.sh). Run from anywhere:
#   server/offline/dds/build.sh 0.5.12
# The endplay version must match server/requirements.txt, so the app and the server solve alike.
set -euo pipefail
VERSION=${1:?endplay version, as in server/requirements.txt}
HERE=$(cd "$(dirname "$0")" && pwd)
OUT=$HERE/../endplay
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
cd "$WORK"
URL=$(curl -sS "https://pypi.org/pypi/endplay/$VERSION/json" |
  python3 -c "import json,sys;print([u['url'] for u in json.load(sys.stdin)['urls'] if u['packagetype']=='sdist'][0])")
curl -sSL "$URL" | tar xz
SRC=$WORK/endplay-$VERSION
DDS=$SRC/libs/dds
patch -d "$DDS/src" -p0 < "$HERE/System.cpp.patch"

# the Python side: only what the game uses, endplay's own __init__ trimmed to match, and the ctypes wrappers that
# pass structs by value pointed at byref.cpp (Pyodide's ctypes can't pass a struct by value)
KEEP_INIT=$(cat "$OUT/__init__.py")

pip download -q --no-deps --only-binary :all: --python-version 3.13 --platform manylinux2014_x86_64 \
  "endplay==$VERSION" -d wheel
python3 -m zipfile -e wheel/*.whl wheel/x
rm -rf "$OUT"
mkdir -p "$OUT/_dds"
cp -r "$SRC/src/endplay/"{config.py,dds,types,utils} "$OUT/"
printf '%s\n' "$KEEP_INIT" > "$OUT/__init__.py"
cp wheel/x/endplay/_dds/__init__.py "$OUT/_dds/__init__.py"
python3 "$HERE/patch_endplay.py" "$OUT/_dds/__init__.py"
cp "$SRC/LICENCE" "$OUT/LICENCE"
cp "$DDS/LICENSE" "$HERE/DDS-LICENSE"

SRCS=$(sed -n 's/^[ \t]*\([A-Za-z]*\.cpp\).*/\1/p' "$DDS/src/Makefiles/sources.txt" | sort -u | sed "s|^|$DDS/src/|")
em++ -O3 -std=c++17 -fPIC -sSIDE_MODULE=1 -include cstdio -include cstring -w -I"$DDS/include" \
  $SRCS "$HERE/byref.cpp" -o "$OUT/_dds/libdds.so"
find "$OUT" -name __pycache__ -prune -exec rm -rf {} +
echo "built $OUT"
