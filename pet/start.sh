#!/bin/sh
# Starts the pet in the background on macOS. Uses the Python written to python.txt by the installer.
# Tk 9 draws see-through windows black on macOS, so that Python must carry Tk 8.6.
DIR="$(cd "$(dirname "$0")" && pwd)"
PY="$(head -n 1 "$DIR/python.txt" 2>/dev/null)"
[ -x "$PY" ] || PY="$(command -v python3)"
nohup "$PY" "$DIR/crab_pet.py" >/dev/null 2>&1 &
